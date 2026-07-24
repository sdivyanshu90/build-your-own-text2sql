"""The schema catalog: introspection + semantic enrichment + caching.

``SchemaCatalog`` is the single entry point the rest of the engine uses to obtain
schema. It:

1. reflects structure via :class:`SchemaIntrospector`,
2. enriches columns/tables with governance metadata from the semantic layer
   (classification, curated comments, tenant columns, non-sensitive samples),
3. serves the result from a TTL cache with explicit invalidation,
4. detects and logs schema drift (version changes across refreshes),
5. produces authorization-filtered summaries for the API.
"""

from __future__ import annotations

from collections.abc import Callable

from text_to_sql.domain.enums import DataClassification
from text_to_sql.domain.models import (
    SchemaColumnSummary,
    SchemaSummaryResponse,
    SchemaTableSummary,
)
from text_to_sql.domain.schema_models import (
    ColumnInfo,
    DatabaseSchema,
    TableInfo,
)
from text_to_sql.observability.logging import get_logger
from text_to_sql.observability.metrics import MetricsRegistry
from text_to_sql.schema.cache import SchemaCache
from text_to_sql.schema.introspector import SchemaIntrospector
from text_to_sql.semantic.models import SemanticLayer

_log = get_logger(__name__)

# Predicate: given (table, column, classification) -> may the caller see it?
ColumnVisibility = Callable[[str, str, DataClassification], bool]


class SchemaCatalog:
    """Owns the enriched, cached schema and exposes read APIs."""

    def __init__(
        self,
        introspector: SchemaIntrospector,
        semantic_layer: SemanticLayer,
        cache: SchemaCache,
        metrics: MetricsRegistry,
    ) -> None:
        self._introspector = introspector
        self._semantic = semantic_layer
        self._cache = cache
        self._metrics = metrics

    # ------------------------------------------------------------------ #
    # Access
    # ------------------------------------------------------------------ #
    def get_schema(self, *, force_refresh: bool = False) -> DatabaseSchema:
        if not force_refresh:
            cached = self._cache.get()
            if cached is not None:
                self._metrics.inc("schema_cache_total", 1.0, result="hit")
                return cached
        self._metrics.inc("schema_cache_total", 1.0, result="miss")
        previous_version = self._cache.current_version
        raw = self._introspector.introspect()
        enriched = self._enrich(raw)
        self._cache.set(enriched)
        if previous_version is not None and previous_version != enriched.version:
            _log.warning(
                "schema_drift_detected",
                previous_version=previous_version,
                new_version=enriched.version,
            )
            self._metrics.inc("schema_drift_total", 1.0)
        return enriched

    def refresh(self) -> DatabaseSchema:
        """Force re-introspection (used by ``POST /schema/refresh``)."""
        self._cache.invalidate()
        return self.get_schema(force_refresh=True)

    # ------------------------------------------------------------------ #
    # Enrichment
    # ------------------------------------------------------------------ #
    def _enrich(self, raw: DatabaseSchema) -> DatabaseSchema:
        enriched_tables: list[TableInfo] = []
        for table in raw.tables:
            table_ann = self._semantic.table_annotation(table.name)
            tenant_column = None
            # Only assign a tenant column that actually exists on the table.
            if table_ann and table_ann.tenant_column and table.has_column(table_ann.tenant_column):
                tenant_column = table_ann.tenant_column

            new_columns: list[ColumnInfo] = []
            for col in table.columns:
                col_ann = self._semantic.column_annotation(table.name, col.name)
                if col_ann is None:
                    new_columns.append(col)
                    continue
                new_columns.append(
                    col.model_copy(
                        update={
                            "classification": col_ann.classification,
                            "comment": col_ann.comment or col.comment,
                            "sample_values": col_ann.sample_values,
                        }
                    )
                )

            comment = (table_ann.comment if table_ann else None) or table.comment
            enriched_tables.append(
                table.model_copy(
                    update={
                        "columns": tuple(new_columns),
                        "tenant_column": tenant_column,
                        "comment": comment,
                    }
                )
            )
        return raw.model_copy(update={"tables": tuple(enriched_tables)})

    # ------------------------------------------------------------------ #
    # Summaries
    # ------------------------------------------------------------------ #
    def summary(
        self,
        schema: DatabaseSchema,
        *,
        visible: ColumnVisibility | None = None,
    ) -> SchemaSummaryResponse:
        """Build an authorization-filtered schema summary.

        ``visible`` decides per-column visibility. When omitted, always-secret
        classes (auth secrets / highly-restricted) are hidden and everything else
        is shown.
        """
        if visible is None:
            visible = _default_visibility

        table_summaries: list[SchemaTableSummary] = []
        for table in schema.tables:
            cols: list[SchemaColumnSummary] = []
            for col in table.columns:
                if not visible(table.name, col.name, col.classification):
                    continue
                cols.append(
                    SchemaColumnSummary(
                        name=col.name,
                        data_type=col.data_type,
                        nullable=col.nullable,
                        is_primary_key=col.is_primary_key,
                        classification=col.classification.value,
                        sensitive=col.classification.is_sensitive,
                    )
                )
            table_summaries.append(
                SchemaTableSummary(
                    name=table.qualified_name,
                    kind=table.kind,
                    comment=table.comment,
                    columns=cols,
                )
            )
        return SchemaSummaryResponse(
            dialect=schema.dialect,
            version=schema.version,
            tables=table_summaries,
        )


def _default_visibility(_table: str, _column: str, classification: DataClassification) -> bool:
    return classification not in {
        DataClassification.AUTH_SECRET,
        DataClassification.HIGHLY_RESTRICTED,
    }
