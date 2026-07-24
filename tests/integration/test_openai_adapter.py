"""Integration tests for the OpenAI-compatible adapter against a mock server.

No real credentials or network are used: an ``httpx.MockTransport`` plays the role
of the provider so we can exercise success, malformed output, rate-limiting,
timeouts, and retry behaviour deterministically.
"""

from __future__ import annotations

import json

import httpx
import pytest

from text_to_sql.common.errors import (
    ConfigurationError,
    ProviderError,
    ProviderOutputError,
    ProviderTimeoutError,
)
from text_to_sql.domain.enums import SQLDialect
from text_to_sql.llm.base import GenerationRequest
from text_to_sql.llm.openai_adapter import OpenAICompatibleProvider
from text_to_sql.llm.prompt import PromptBuilder, PromptContext

pytestmark = pytest.mark.integration


def _request(schema, semantic):  # type: ignore[no-untyped-def]
    payload = PromptBuilder().build(
        PromptContext(
            question="revenue by region",
            dialect=SQLDialect.SQLITE,
            schema_text="TABLE orders",
            semantic_text="",
            max_rows=1000,
        )
    )
    return GenerationRequest(
        question="revenue by region",
        dialect=SQLDialect.SQLITE,
        schema_subset=schema,
        semantic_layer=semantic,
        prompt=payload,
        max_rows=1000,
    )


def _provider(handler, **kw):  # type: ignore[no-untyped-def]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleProvider(api_key="test-key", model="gpt-x", client=client, **kw)


def _chat_response(content: str, usage: dict | None = None) -> httpx.Response:
    body = {
        "choices": [{"message": {"content": content}}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5},
    }
    return httpx.Response(200, json=body)


async def test_requires_api_key() -> None:
    with pytest.raises(ConfigurationError):
        OpenAICompatibleProvider(api_key=None, model="x")


async def test_successful_generation(schema, semantic) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["response_format"]["type"] == "json_object"
        return _chat_response(
            json.dumps(
                {
                    "sql": "SELECT 1 AS one",
                    "dialect": "sqlite",
                    "explanation": "ok",
                    "referenced_tables": ["orders"],
                    "confidence": 0.9,
                }
            )
        )

    provider = _provider(handler)
    resp = await provider.generate(_request(schema, semantic))
    assert resp.sql == "SELECT 1 AS one"
    assert resp.provider == "openai"
    assert resp.usage.prompt_tokens == 10
    assert resp.confidence == 0.9


async def test_malformed_json_content_raises_output_error(schema, semantic) -> None:
    provider = _provider(lambda req: _chat_response("not json at all"))
    with pytest.raises(ProviderOutputError):
        await provider.generate(_request(schema, semantic))


async def test_missing_sql_field_raises_output_error(schema, semantic) -> None:
    provider = _provider(lambda req: _chat_response(json.dumps({"dialect": "sqlite"})))
    with pytest.raises(ProviderOutputError):
        await provider.generate(_request(schema, semantic))


async def test_rate_limit_is_retryable_error(schema, semantic) -> None:
    provider = _provider(lambda req: httpx.Response(429, json={}), max_retries=0)
    with pytest.raises(ProviderError) as exc:
        await provider.generate(_request(schema, semantic))
    assert exc.value.retryable is True


async def test_timeout_maps_to_provider_timeout(schema, semantic) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    provider = _provider(handler, max_retries=1)
    with pytest.raises(ProviderTimeoutError):
        await provider.generate(_request(schema, semantic))


async def test_retry_then_success(schema, semantic) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={})
        return _chat_response(
            json.dumps({"sql": "SELECT 1", "dialect": "sqlite", "confidence": 0.5})
        )

    provider = _provider(handler, max_retries=2)
    resp = await provider.generate(_request(schema, semantic))
    assert resp.sql == "SELECT 1"
    assert calls["n"] == 2
