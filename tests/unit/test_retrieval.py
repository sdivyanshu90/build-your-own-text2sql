"""Unit tests for schema retrieval."""

from __future__ import annotations

import pytest

from text_to_sql.domain.schema_models import DatabaseSchema
from text_to_sql.retrieval.retriever import LexicalSchemaRetriever
from text_to_sql.semantic.models import SemanticLayer

pytestmark = pytest.mark.unit


@pytest.fixture
def retriever(semantic: SemanticLayer) -> LexicalSchemaRetriever:
    return LexicalSchemaRetriever(semantic, top_k=12)


def _names(retriever: LexicalSchemaRetriever, q: str, schema: DatabaseSchema) -> set[str]:
    return {o.table for o in retriever.retrieve(q, schema).selected}


def test_includes_required_join_path_for_revenue_by_region(
    retriever: LexicalSchemaRetriever, schema: DatabaseSchema
) -> None:
    names = _names(retriever, "Show revenue by region", schema)
    # The full join path must be present so the query can be generated.
    for required in {"order_items", "orders", "customers", "regions"}:
        assert required in names, f"missing {required}"


def test_excludes_irrelevant_tables(
    retriever: LexicalSchemaRetriever, schema: DatabaseSchema
) -> None:
    names = _names(retriever, "list all products", schema)
    assert "products" in names
    assert "support_tickets" not in names
    assert "payments" not in names


def test_scores_and_reasons_present(
    retriever: LexicalSchemaRetriever, schema: DatabaseSchema
) -> None:
    result = retriever.retrieve("top products by revenue", schema)
    assert result.selected
    assert all(o.reason for o in result.selected)
    assert result.selected == sorted(result.selected, key=lambda o: (-o.score, o.table))


def test_subset_is_valid_schema(retriever: LexicalSchemaRetriever, schema: DatabaseSchema) -> None:
    subset = retriever.retrieve("revenue by region", schema).schema_subset
    assert isinstance(subset, DatabaseSchema)
    assert subset.dialect == schema.dialect
    assert len(subset.tables) <= len(schema.tables)


def test_fallback_when_no_signal(retriever: LexicalSchemaRetriever, schema: DatabaseSchema) -> None:
    result = retriever.retrieve("zzz qqq wubbalubba", schema)
    assert result.selected  # deterministic fallback, never empty
