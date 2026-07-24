"""Unit tests for Gemini provider wiring.

Gemini speaks the OpenAI chat-completions protocol, so it reuses
``OpenAICompatibleProvider``. These tests lock in the two things that make that
work: the auto-defaulted base URL and a truthful reported provider name.
"""

from __future__ import annotations

import json

import httpx
import pytest

from text_to_sql.application.container import build_provider
from text_to_sql.common.errors import ConfigurationError
from text_to_sql.configuration.settings import GEMINI_BASE_URL, Settings
from text_to_sql.domain.enums import SQLDialect
from text_to_sql.llm.base import GenerationRequest
from text_to_sql.llm.openai_adapter import OpenAICompatibleProvider
from text_to_sql.llm.prompt import PromptBuilder, PromptContext

pytestmark = pytest.mark.unit


def _settings(**kw: object) -> Settings:
    base: dict[str, object] = {"_env_file": None}
    base.update(kw)
    return Settings(**base)  # type: ignore[arg-type]


def test_gemini_defaults_to_google_openai_endpoint() -> None:
    s = _settings(llm_provider="gemini")
    assert s.effective_llm_base_url == GEMINI_BASE_URL


def test_explicit_base_url_overrides_gemini_default() -> None:
    s = _settings(llm_provider="gemini", llm_base_url="https://proxy.internal/v1")
    assert s.effective_llm_base_url == "https://proxy.internal/v1"


def test_openai_provider_keeps_its_own_base_url() -> None:
    s = _settings(llm_provider="openai")
    assert s.effective_llm_base_url == "https://api.openai.com/v1"


def test_build_provider_gemini_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    s = _settings(llm_provider="gemini", llm_api_key_env="GEMINI_API_KEY")
    with pytest.raises(ConfigurationError):
        build_provider(s)


def test_build_provider_gemini_reports_provider_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    s = _settings(
        llm_provider="gemini", llm_api_key_env="GEMINI_API_KEY", llm_model="gemini-2.5-flash"
    )
    provider = build_provider(s)
    assert provider.name == "gemini"
    assert provider.model == "gemini-2.5-flash"


async def test_response_metadata_reports_gemini(schema, semantic) -> None:
    """A generation through the shared adapter is attributed to 'gemini'."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(GEMINI_BASE_URL)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"sql": "SELECT 1 AS one", "confidence": 0.8})
                        }
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            },
        )

    provider = OpenAICompatibleProvider(
        api_key="k",
        model="gemini-2.5-flash",
        base_url=GEMINI_BASE_URL,
        provider_name="gemini",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    payload = PromptBuilder().build(
        PromptContext(
            question="q",
            dialect=SQLDialect.SQLITE,
            schema_text="",
            semantic_text="",
            max_rows=1000,
        )
    )
    resp = await provider.generate(
        GenerationRequest(
            question="q",
            dialect=SQLDialect.SQLITE,
            schema_subset=schema,
            semantic_layer=semantic,
            prompt=payload,
            max_rows=1000,
        )
    )
    assert resp.provider == "gemini"
    assert resp.model == "gemini-2.5-flash"
    assert resp.sql == "SELECT 1 AS one"
