"""OpenAI-compatible provider adapter.

Targets any endpoint that speaks the OpenAI Chat Completions API (OpenAI, Azure
OpenAI, many self-hosted gateways). It requests **structured JSON output** so we
parse a well-defined object instead of scraping free text, and it maps transport
failures onto the engine's typed provider errors (timeout → retryable, etc.).

The API key is never taken from source or settings inline — it is resolved from a
named environment variable at call time (see
:meth:`~text_to_sql.configuration.settings.Settings.resolve_llm_api_key`).

This adapter is exercised in tests against a controlled fake HTTP server (see
``tests/integration/test_openai_adapter.py``); CI never needs real credentials.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from text_to_sql.common.errors import (
    ConfigurationError,
    ProviderError,
    ProviderOutputError,
    ProviderTimeoutError,
)
from text_to_sql.domain.enums import SQLDialect
from text_to_sql.llm.base import GenerationRequest, GenerationResponse, TokenUsage
from text_to_sql.observability.logging import get_logger

_log = get_logger(__name__)


class OpenAICompatibleProvider:
    """Provider backed by an OpenAI-compatible ``/chat/completions`` endpoint."""

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        temperature: float = 0.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ConfigurationError(
                "OpenAI-compatible provider selected but no API key is configured.",
                remediation="Set the environment variable named by T2SQL_LLM_API_KEY_ENV.",
            )
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._temperature = temperature
        self._client = client  # injectable for tests

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        payload = {
            "model": self._model,
            "temperature": self._temperature,
            "messages": [
                {"role": "system", "content": request.prompt.system},
                {"role": "user", "content": request.prompt.user},
            ],
            # Ask for a JSON object; adapters that support json_schema can tighten
            # this further. We still validate the parsed object ourselves.
            "response_format": {"type": "json_object"},
        }
        data = await self._post_with_retries(payload, request.timeout_seconds)
        return self._parse_response(data, request)

    # ------------------------------------------------------------------ #
    async def _post_with_retries(self, payload: dict, timeout: float) -> dict:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return await self._post(payload, timeout)
            except ProviderTimeoutError as exc:
                last_exc = exc
                _log.warning("provider_timeout", attempt=attempt)
            except ProviderError as exc:
                last_exc = exc
                if not exc.retryable:
                    raise
                _log.warning("provider_error_retrying", attempt=attempt, code=exc.error_code)
            if attempt < self._max_retries:
                # Deterministic linear backoff; avoids randomness for reproducibility.
                await asyncio.sleep(0.05 * (attempt + 1))
        assert last_exc is not None
        raise last_exc

    async def _post(self, payload: dict, timeout: float) -> dict:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/chat/completions"
        client = self._client or httpx.AsyncClient(timeout=timeout)
        owns_client = self._client is None
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("The LLM provider timed out.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("The LLM provider request failed.") from exc
        finally:
            if owns_client:
                await client.aclose()

        if resp.status_code == 429:
            raise ProviderError("The LLM provider rate-limited the request.", retryable=True)
        if resp.status_code >= 500:
            raise ProviderError(
                f"The LLM provider returned status {resp.status_code}.", retryable=True
            )
        if resp.status_code >= 400:
            raise ProviderError(
                f"The LLM provider rejected the request (status {resp.status_code}).",
                retryable=False,
            )
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise ProviderOutputError("The provider returned non-JSON output.") from exc

    def _parse_response(self, data: dict, request: GenerationRequest) -> GenerationResponse:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderOutputError("Provider response missing message content.") from exc
        try:
            obj = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderOutputError("Provider message content was not valid JSON.") from exc
        if not isinstance(obj, dict) or "sql" not in obj or not isinstance(obj["sql"], str):
            raise ProviderOutputError("Provider JSON did not include a 'sql' string.")

        usage_obj = data.get("usage") or {}
        usage = TokenUsage(
            prompt_tokens=int(usage_obj.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage_obj.get("completion_tokens", 0) or 0),
        )
        return GenerationResponse(
            sql=obj["sql"].strip(),
            dialect=_coerce_dialect(obj.get("dialect"), request.dialect),
            explanation=str(obj.get("explanation", "")),
            referenced_tables=tuple(str(t) for t in obj.get("referenced_tables", []) or []),
            referenced_columns=tuple(str(c) for c in obj.get("referenced_columns", []) or []),
            assumptions=tuple(str(a) for a in obj.get("assumptions", []) or []),
            confidence=_coerce_confidence(obj.get("confidence")),
            needs_clarification=bool(obj.get("needs_clarification", False)),
            prompt_version=request.prompt.version,
            provider="openai",
            model=self._model,
            usage=usage,
        )


def _coerce_dialect(value: object, default: SQLDialect) -> SQLDialect:
    if isinstance(value, str):
        try:
            return SQLDialect(value.lower())
        except ValueError:
            return default
    return default


def _coerce_confidence(value: object) -> float:
    try:
        conf = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, conf))
