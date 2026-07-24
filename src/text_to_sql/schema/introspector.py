"""Structural schema introspection via SQLAlchemy reflection.

Produces a *raw* :class:`DatabaseSchema` (structure only: tables, columns, types,
keys, constraints, indexes, and — where the backend supports it — comments and
row estimates). Governance metadata (classification, tenant columns, curated
comments, sample values) is layered on later by the :class:`SchemaCatalog` from
the semantic layer.

Reflection deliberately never reads row data. The only value-like data that can
ever reach the LLM is the small set of curated, non-sensitive sample values
supplied by the semantic layer.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import Engine, inspect
from sqlalchemy.engine import make_url

from text_to_sql.domain.enums import DataClassification, SQLDialect
from text_to_sql.domain.schema_models import (
    ColumnInfo,
    DatabaseSchema,
    ForeignKeyRef,
    TableInfo,
)
from text_to_sql.observability.logging import get_logger

_log = get_logger(__name__)

_BACKEND_TO_DIALECT = {
    "sqlite": SQLDialect.SQLITE,
    "postgresql": SQLDialect.POSTGRES,
}


class SchemaIntrospector:
    """Reflects a database into a normalized structural schema."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        backend = make_url(str(engine.url)).get_backend_name()
        self._dialect = _BACKEND_TO_DIALECT.get(backend, SQLDialect.SQLITE)
        self._backend = backend

    @property
    def dialect(self) -> SQLDialect:
        return self._dialect

    def introspect(self) -> DatabaseSchema:
        inspector = inspect(self._engine)
        tables: list[TableInfo] = []

        table_names = sorted(inspector.get_table_names())
        view_names = sorted(inspector.get_view_names())

        for name in table_names:
            tables.append(self._reflect_table(inspector, name, kind="table"))
        for name in view_names:
            tables.append(self._reflect_table(inspector, name, kind="view"))

        version = self._compute_version(tables)
        _log.info(
            "schema_introspected",
            table_count=len(table_names),
            view_count=len(view_names),
            dialect=self._dialect.value,
            version=version,
        )
        return DatabaseSchema(dialect=self._dialect, tables=tuple(tables), version=version)

    # ------------------------------------------------------------------ #
    def _reflect_table(self, inspector, name: str, *, kind: str) -> TableInfo:  # type: ignore[no-untyped-def]
        pk = inspector.get_pk_constraint(name).get("constrained_columns") or []
        pk_set = {c.lower() for c in pk}

        columns: list[ColumnInfo] = []
        for col in inspector.get_columns(name):
            columns.append(
                ColumnInfo(
                    name=col["name"],
                    data_type=self._type_name(col["type"]),
                    nullable=bool(col.get("nullable", True)),
                    is_primary_key=col["name"].lower() in pk_set,
                    comment=col.get("comment"),
                    classification=DataClassification.INTERNAL,
                )
            )

        foreign_keys: list[ForeignKeyRef] = []
        for fk in inspector.get_foreign_keys(name):
            referred = fk.get("referred_table")
            if not referred:
                continue
            foreign_keys.append(
                ForeignKeyRef(
                    columns=tuple(fk.get("constrained_columns", ())),
                    referred_table=referred,
                    referred_columns=tuple(fk.get("referred_columns", ())),
                    referred_schema=fk.get("referred_schema"),
                )
            )

        unique: list[tuple[str, ...]] = []
        for uc in inspector.get_unique_constraints(name):
            cols = tuple(uc.get("column_names", ()) or ())
            if cols:
                unique.append(cols)

        indexes = tuple(idx["name"] for idx in inspector.get_indexes(name) if idx.get("name"))

        comment = None
        try:
            comment = (inspector.get_table_comment(name) or {}).get("text")
        except Exception:
            comment = None

        return TableInfo(
            name=name,
            kind=kind,
            comment=comment,
            columns=tuple(columns),
            primary_key=tuple(pk),
            foreign_keys=tuple(foreign_keys),
            unique_constraints=tuple(unique),
            indexes=indexes,
        )

    @staticmethod
    def _type_name(sa_type: object) -> str:
        """Render a SQLAlchemy type to a stable, dialect-neutral string."""
        try:
            return str(sa_type).upper()
        except Exception:
            return "UNKNOWN"

    @staticmethod
    def _compute_version(tables: list[TableInfo]) -> str:
        """Hash the structural shape so drift/invalidation can be detected."""
        shape = [
            {
                "t": t.qualified_name,
                "k": t.kind,
                "c": [(c.name, c.data_type, c.nullable, c.is_primary_key) for c in t.columns],
                "fk": [
                    (fk.columns, fk.referred_table, fk.referred_columns) for fk in t.foreign_keys
                ],
            }
            for t in tables
        ]
        digest = hashlib.sha256(json.dumps(shape, default=str, sort_keys=True).encode()).hexdigest()
        return digest[:16]
