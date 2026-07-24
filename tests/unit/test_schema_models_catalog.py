"""Unit tests for schema models and the catalog."""

from __future__ import annotations

import pytest

from text_to_sql.domain.enums import DataClassification, SQLDialect
from text_to_sql.domain.schema_models import (
    ColumnInfo,
    DatabaseSchema,
    ForeignKeyRef,
    TableInfo,
)

pytestmark = pytest.mark.unit


def _schema() -> DatabaseSchema:
    a = TableInfo(
        name="a",
        columns=(ColumnInfo(name="id", data_type="INT", is_primary_key=True),),
    )
    b = TableInfo(
        name="b",
        columns=(
            ColumnInfo(name="id", data_type="INT"),
            ColumnInfo(name="a_id", data_type="INT"),
            ColumnInfo(name="secret", data_type="TEXT", classification=DataClassification.PII),
        ),
        foreign_keys=(
            ForeignKeyRef(columns=("a_id",), referred_table="a", referred_columns=("id",)),
        ),
    )
    c = TableInfo(
        name="c",
        columns=(ColumnInfo(name="id", data_type="INT"), ColumnInfo(name="b_id", data_type="INT")),
        foreign_keys=(
            ForeignKeyRef(columns=("b_id",), referred_table="b", referred_columns=("id",)),
        ),
    )
    return DatabaseSchema(dialect=SQLDialect.SQLITE, tables=(a, b, c), version="v1")


def test_case_insensitive_lookup() -> None:
    schema = _schema()
    assert schema.table("A") is not None
    assert schema.table("a").column("ID") is not None  # type: ignore[union-attr]


def test_join_graph_is_bidirectional() -> None:
    graph = _schema().join_graph()
    assert "a" in graph["b"] and "b" in graph["a"]
    assert "c" in graph["b"]


def test_neighbors_within_hops() -> None:
    schema = _schema()
    assert schema.neighbors("a", hops=1) == {"b"}
    assert schema.neighbors("a", hops=2) == {"b", "c"}


def test_subset_keeps_named_tables() -> None:
    subset = _schema().subset(["a", "b"])
    assert {t.name for t in subset.tables} == {"a", "b"}


def test_serialize_marks_sensitive_and_flattens_comments() -> None:
    schema = _schema()
    text = schema.serialize_for_prompt()
    assert "[PII]" in text  # sensitive columns flagged
    assert "FK" in text


def test_serialize_truncates_to_budget() -> None:
    text = _schema().serialize_for_prompt(max_chars=50)
    assert "truncated" in text


# --- Catalog (uses seeded DB via fixtures) -------------------------------- #
def test_catalog_enriches_classification_and_tenant(container) -> None:  # type: ignore[no-untyped-def]
    schema = container.catalog.get_schema()
    users = schema.table("users")
    assert users is not None
    assert users.column("password_hash").classification is DataClassification.AUTH_SECRET  # type: ignore[union-attr]
    assert users.tenant_column == "organization_id"
    regions = schema.table("regions")
    assert regions.tenant_column is None  # type: ignore[union-attr]


def test_catalog_cache_hit_and_refresh(container) -> None:  # type: ignore[no-untyped-def]
    first = container.catalog.get_schema()
    second = container.catalog.get_schema()  # cache hit
    assert first.version == second.version
    refreshed = container.catalog.refresh()
    assert refreshed.version == first.version  # structure unchanged => same version


def test_catalog_summary_hides_secrets_for_analyst(container) -> None:  # type: ignore[no-untyped-def]
    schema = container.catalog.get_schema()

    def visible(_t: str, _c: str, classification: DataClassification) -> bool:
        return container.column_policy.can_view(classification, ("analyst",))

    summary = container.catalog.summary(schema, visible=visible)
    users = next(t for t in summary.tables if t.name == "users")
    cols = {c.name for c in users.columns}
    assert "password_hash" not in cols
    assert "email" not in cols  # PII hidden from analyst
    assert "role" in cols
