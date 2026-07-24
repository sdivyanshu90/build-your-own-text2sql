"""Extra coverage for the fake provider's heuristic branches."""

from __future__ import annotations

import pytest

from text_to_sql.domain.enums import SQLDialect
from text_to_sql.domain.schema_models import DatabaseSchema
from text_to_sql.llm.base import GenerationRequest, ResolvedDate
from text_to_sql.llm.fake import DeterministicFakeProvider
from text_to_sql.llm.prompt import PromptBuilder, PromptContext
from text_to_sql.semantic.models import SemanticLayer

pytestmark = pytest.mark.unit
D = SQLDialect.SQLITE


def _req(
    question: str, schema: DatabaseSchema, semantic: SemanticLayer, *, resolved=None
) -> GenerationRequest:
    payload = PromptBuilder().build(
        PromptContext(question=question, dialect=D, schema_text="", semantic_text="", max_rows=1000)
    )
    return GenerationRequest(
        question=question,
        dialect=D,
        schema_subset=schema,
        semantic_layer=semantic,
        prompt=payload,
        max_rows=1000,
        resolved_date=resolved,
    )


DATE = ResolvedDate(
    description="the last completed calendar quarter",
    matched_phrase="last quarter",
    start_iso="2026-04-01 00:00:00",
    end_iso="2026-07-01 00:00:00",
)


@pytest.mark.parametrize(
    "question,expect",
    [
        ("revenue by customer", "customers.name"),
        ("revenue by category", "products.category"),
        ("revenue by month", "strftime"),
        ("revenue by product", "products.name"),
        ("what is our total revenue", "SUM(order_items.quantity"),
        ("show revenue by region", "regions.name"),
    ],
)
async def test_revenue_variants(
    schema: DatabaseSchema, semantic: SemanticLayer, question: str, expect: str
) -> None:
    resp = await DeterministicFakeProvider().generate(_req(question, schema, semantic))
    assert expect in resp.sql


async def test_top_products_uses_limit(schema: DatabaseSchema, semantic: SemanticLayer) -> None:
    resp = await DeterministicFakeProvider().generate(
        _req("top 3 products by revenue last quarter", schema, semantic, resolved=DATE)
    )
    assert "LIMIT 3" in resp.sql
    assert "2026-04-01" in resp.sql


async def test_status_listing(schema: DatabaseSchema, semantic: SemanticLayer) -> None:
    resp = await DeterministicFakeProvider().generate(_req("show paid orders", schema, semantic))
    assert "status = 'paid'" in resp.sql


async def test_fallback_low_confidence(schema: DatabaseSchema, semantic: SemanticLayer) -> None:
    resp = await DeterministicFakeProvider().generate(
        _req("wibble wobble flimflam", schema, semantic)
    )
    assert resp.confidence <= 0.5


async def test_count_with_date(schema: DatabaseSchema, semantic: SemanticLayer) -> None:
    resp = await DeterministicFakeProvider().generate(
        _req("how many orders last quarter", schema, semantic, resolved=DATE)
    )
    assert "COUNT(*)" in resp.sql
    assert "2026-04-01" in resp.sql
