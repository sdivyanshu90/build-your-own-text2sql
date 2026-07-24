"""Semantic-layer value objects and the :class:`SemanticLayer` container.

Everything here is a frozen Pydantic model so the semantic layer is an immutable,
serializable configuration object that can be validated at startup and unit-tested
in isolation.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from text_to_sql.domain.enums import DataClassification


class TermKind(str, Enum):
    """What a business term denotes."""

    METRIC = "metric"  # a measure, e.g. revenue
    DIMENSION = "dimension"  # a grouping attribute, e.g. region
    ENTITY = "entity"  # a table/concept, e.g. customer
    FILTER = "filter"  # a canned predicate, e.g. "active customers"


class BusinessTerm(BaseModel):
    """A single glossary term with synonyms and the schema it maps to."""

    model_config = ConfigDict(frozen=True)

    term: str
    kind: TermKind
    definition: str
    synonyms: tuple[str, ...] = ()
    related_tables: tuple[str, ...] = ()
    related_columns: tuple[str, ...] = ()

    @property
    def all_surface_forms(self) -> tuple[str, ...]:
        return (self.term, *self.synonyms)


class MetricDefinition(BaseModel):
    """An approved calculation for a business metric.

    ``sql_expression`` is an authoritative SQL fragment (e.g.
    ``SUM(order_items.quantity * order_items.unit_price)``). It is injected into
    the prompt as the *only* acceptable definition and is documented in the
    explanation. The engine never lets the LLM invent an alternative when an
    authoritative definition exists.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    sql_expression: str
    required_tables: tuple[str, ...] = ()
    default_filters: tuple[str, ...] = ()
    synonyms: tuple[str, ...] = ()

    @property
    def all_surface_forms(self) -> tuple[str, ...]:
        return (self.name, *self.synonyms)


class ColumnAnnotation(BaseModel):
    """Governance metadata for a single column, keyed by (table, column)."""

    model_config = ConfigDict(frozen=True)

    table: str
    column: str
    classification: DataClassification = DataClassification.INTERNAL
    comment: str | None = None
    # Representative NON-sensitive sample values allowed to reach the LLM.
    sample_values: tuple[str, ...] = ()


class TableAnnotation(BaseModel):
    """Governance metadata for a table."""

    model_config = ConfigDict(frozen=True)

    table: str
    comment: str | None = None
    tenant_column: str | None = None
    aliases: tuple[str, ...] = ()


class SemanticLayer(BaseModel):
    """Immutable container aggregating all semantic configuration."""

    model_config = ConfigDict(frozen=True)

    terms: tuple[BusinessTerm, ...] = ()
    metrics: tuple[MetricDefinition, ...] = ()
    column_annotations: tuple[ColumnAnnotation, ...] = ()
    table_annotations: tuple[TableAnnotation, ...] = ()
    # Human-readable calendar policy injected into prompts/explanations.
    date_policy: str = (
        "Relative dates use the Gregorian calendar in UTC. 'Last quarter' means "
        "the most recently completed calendar quarter; 'last month' the most "
        "recently completed calendar month; 'this year' the current calendar "
        "year to date."
    )
    # Default date field per table used to resolve relative-date filters.
    default_date_fields: tuple[tuple[str, str], ...] = ()

    # ------------------------------------------------------------------ #
    # Lookups (built lazily; the layer is small)
    # ------------------------------------------------------------------ #
    def _term_index(self) -> dict[str, BusinessTerm]:
        idx: dict[str, BusinessTerm] = {}
        for term in self.terms:
            for form in term.all_surface_forms:
                idx[form.lower()] = term
        return idx

    def _metric_index(self) -> dict[str, MetricDefinition]:
        idx: dict[str, MetricDefinition] = {}
        for metric in self.metrics:
            for form in metric.all_surface_forms:
                idx[form.lower()] = metric
        return idx

    def resolve_term(self, text: str) -> BusinessTerm | None:
        return self._term_index().get(text.strip().lower())

    def resolve_metric(self, text: str) -> MetricDefinition | None:
        return self._metric_index().get(text.strip().lower())

    def column_annotation(self, table: str, column: str) -> ColumnAnnotation | None:
        t, c = table.strip().lower(), column.strip().lower()
        for ann in self.column_annotations:
            if ann.table.lower() == t and ann.column.lower() == c:
                return ann
        return None

    def table_annotation(self, table: str) -> TableAnnotation | None:
        t = table.strip().lower()
        for ann in self.table_annotations:
            if ann.table.lower() == t:
                return ann
        return None

    def default_date_field(self, table: str) -> str | None:
        t = table.strip().lower()
        for name, field in self.default_date_fields:
            if name.lower() == t:
                return field
        return None

    def find_surface_forms(self, question: str) -> list[BusinessTerm]:
        """Return terms whose surface form appears (word-ish) in the question."""
        lowered = f" {question.lower()} "
        found: list[BusinessTerm] = []
        seen: set[str] = set()
        for term in self.terms:
            for form in term.all_surface_forms:
                needle = f" {form.lower()} "
                if needle in lowered and term.term not in seen:
                    found.append(term)
                    seen.add(term.term)
                    break
        return found

    def find_metrics(self, question: str) -> list[MetricDefinition]:
        lowered = f" {question.lower()} "
        found: list[MetricDefinition] = []
        seen: set[str] = set()
        for metric in self.metrics:
            for form in metric.all_surface_forms:
                if f" {form.lower()} " in lowered and metric.name not in seen:
                    found.append(metric)
                    seen.add(metric.name)
                    break
        return found
