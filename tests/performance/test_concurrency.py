"""Performance / reliability smoke tests.

These are deterministic and fast (no external services). They verify the pipeline
handles concurrency, benefits from schema caching, and degrades gracefully when
the provider fails — not throughput benchmarks (see ``tests/performance/locustfile.py``
and ``docs/testing/performance.md`` for load testing).
"""

from __future__ import annotations

import asyncio
import time

import pytest

from text_to_sql.application.container import AppContainer
from text_to_sql.common.errors import ProviderTimeoutError
from text_to_sql.domain.context import AuthContext
from text_to_sql.domain.models import QueryRequest
from text_to_sql.llm.base import GenerationRequest, GenerationResponse

pytestmark = pytest.mark.performance

ANALYST = AuthContext(user_id="u", tenant_id="1", roles=("analyst",))


async def test_concurrent_requests_all_succeed(container: AppContainer) -> None:
    async def one() -> str:
        resp = await container.orchestrator.process(
            QueryRequest(question="Show revenue by region"), ANALYST
        )
        return resp.status.value

    results = await asyncio.gather(*[one() for _ in range(25)])
    assert all(r == "success" for r in results)


async def test_schema_cache_hit_is_fast(container: AppContainer) -> None:
    container.catalog.get_schema()  # warm
    start = time.perf_counter()
    for _ in range(200):
        container.catalog.get_schema()
    elapsed = time.perf_counter() - start
    # 200 cache hits should be well under a second (no re-introspection).
    assert elapsed < 1.0


async def test_provider_failure_is_handled(container: AppContainer, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def boom(_request: GenerationRequest) -> GenerationResponse:
        raise ProviderTimeoutError("upstream timed out")

    monkeypatch.setattr(container.provider, "generate", boom)
    with pytest.raises(ProviderTimeoutError):
        await container.orchestrator.process(QueryRequest(question="revenue"), ANALYST)
