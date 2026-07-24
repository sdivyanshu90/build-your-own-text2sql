"""Unit tests for the deterministic fake provider."""

from __future__ import annotations

import pytest

from text_to_sql.domain.enums import SQLDialect
from text_to_sql.domain.schema_models import DatabaseSchema
from text_to_sql.llm.base import GenerationRequest, RepairContext, ResolvedDate
from text_to_sql.llm.fake import DeterministicFakeProvider
from text_to_sql.llm.prompt import PromptBuilder, PromptContext
from text_to_sql.semantic.models import SemanticLayer

pytestmark = pytest.mark.unit
D = SQLDialect.SQLITE


def _request(
    question: str,
    schema: DatabaseSchema,
    semantic: SemanticLayer,
    *,
    repair: RepairContext | None = None,
    resolved: ResolvedDate | None = None,
) -> GenerationRequest:
    payload = PromptBuilder().build(
        PromptContext(
            question=question,
            dialect=D,
            schema_text=schema.serialize_for_prompt(),
            semantic_text="",
            max_rows=1000,
        )
    )
    return GenerationRequest(
        question=question,
        dialect=D,
        schema_subset=schema,
        semantic_layer=semantic,
        prompt=payload,
        max_rows=1000,
        repair=repair,
        resolved_date=resolved,
    )


async def test_heuristic_count(schema: DatabaseSchema, semantic: SemanticLayer) -> None:
    provider = DeterministicFakeProvider()
    resp = await provider.generate(_request("how many customers do we have", schema, semantic))
    assert "count(*)" in resp.sql.lower()
    assert "customers" in resp.sql.lower()
    assert resp.provider == "fake"
    assert resp.usage.total_tokens > 0


async def test_heuristic_is_deterministic(schema: DatabaseSchema, semantic: SemanticLayer) -> None:
    provider = DeterministicFakeProvider()
    q = "Show revenue by region"
    a = await provider.generate(_request(q, schema, semantic))
    b = await provider.generate(_request(q, schema, semantic))
    assert a.sql == b.sql


async def test_scripted_response(schema: DatabaseSchema, semantic: SemanticLayer) -> None:
    provider = DeterministicFakeProvider(scripts={"magic q": ["SELECT 1 AS one"]})
    resp = await provider.generate(_request("magic q", schema, semantic))
    assert resp.sql == "SELECT 1 AS one"


async def test_scripted_repair_sequence(schema: DatabaseSchema, semantic: SemanticLayer) -> None:
    provider = DeterministicFakeProvider(
        scripts={"q": ["SELECT bad FROM users", "SELECT id FROM users"]}
    )
    first = await provider.generate(_request("q", schema, semantic))
    assert first.sql == "SELECT bad FROM users"
    repaired = await provider.generate(
        _request(
            "q",
            schema,
            semantic,
            repair=RepairContext(attempt=1, previous_sql=first.sql, errors=("unknown_column",)),
        )
    )
    assert repaired.sql == "SELECT id FROM users"


async def test_fallback_avoids_sensitive_columns(
    schema: DatabaseSchema, semantic: SemanticLayer
) -> None:
    provider = DeterministicFakeProvider()
    resp = await provider.generate(_request("list all users", schema, semantic))
    assert "password_hash" not in resp.sql
    assert "email" not in resp.sql.lower()
