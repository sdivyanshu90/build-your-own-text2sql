"""Shared pytest fixtures.

The suite runs entirely on a file-backed SQLite database (so the primary and
read-only engines see the same data) seeded once per session with the
deterministic reference data. All LLM calls use the deterministic fake provider,
so nothing needs credentials or network access. A fixed clock (2026-07-24) makes
relative-date resolution reproducible.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime

import httpx
import pytest

from text_to_sql.application.container import AppContainer
from text_to_sql.configuration import Settings
from text_to_sql.domain.context import AuthContext
from text_to_sql.domain.schema_models import DatabaseSchema
from text_to_sql.infrastructure.bootstrap import create_schema, seed_database
from text_to_sql.infrastructure.database import make_database
from text_to_sql.llm.base import LLMProvider
from text_to_sql.semantic.models import SemanticLayer
from text_to_sql.semantic.reference import build_reference_semantic_layer

FIXED_NOW = datetime(2026, 7, 24)


@pytest.fixture(scope="session")
def database_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = tmp_path_factory.mktemp("db") / "reference.db"
    return f"sqlite:///{path}"


@pytest.fixture(scope="session", autouse=True)
def _seed_once(database_url: str) -> Iterator[None]:
    settings = _make_settings(database_url)
    database = make_database(settings)
    create_schema(database.engine, drop_first=True)
    seed_database(database.engine)
    database.dispose()
    yield


def _make_settings(database_url: str, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "database_url": database_url,
        "llm_provider": "fake",
        "sql_dialect": "sqlite",
        "log_json": False,
        "environment": "test",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def settings(database_url: str) -> Settings:
    return _make_settings(database_url)


@pytest.fixture
def make_settings(database_url: str) -> Callable[..., Settings]:
    def _factory(**overrides: object) -> Settings:
        return _make_settings(database_url, **overrides)

    return _factory


@pytest.fixture
def make_container(settings: Settings) -> Iterator[Callable[..., AppContainer]]:
    created: list[AppContainer] = []

    def _make(provider: LLMProvider | None = None, **kwargs: object) -> AppContainer:
        container = AppContainer.create(
            settings,
            provider=provider,
            clock=lambda: FIXED_NOW,
            **kwargs,  # type: ignore[arg-type]
        )
        created.append(container)
        return container

    yield _make
    for container in created:
        container.dispose()


@pytest.fixture
def container(make_container: Callable[..., AppContainer]) -> AppContainer:
    return make_container()


@pytest.fixture
def orchestrator(container: AppContainer):  # type: ignore[no-untyped-def]
    return container.orchestrator


@pytest.fixture
def app(settings: Settings, container: AppContainer):  # type: ignore[no-untyped-def]
    from text_to_sql.api.app import create_app

    return create_app(settings, container=container)


@pytest.fixture
async def client(app) -> Iterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


@pytest.fixture
def schema(container: AppContainer) -> DatabaseSchema:
    return container.catalog.get_schema()


@pytest.fixture
def semantic() -> SemanticLayer:
    return build_reference_semantic_layer()


# --- Auth contexts / headers --------------------------------------------- #
@pytest.fixture
def analyst_auth() -> AuthContext:
    return AuthContext(user_id="analyst-1", tenant_id="1", roles=("analyst",))


@pytest.fixture
def viewer_auth() -> AuthContext:
    return AuthContext(user_id="viewer-1", tenant_id="1", roles=("viewer",))


@pytest.fixture
def admin_auth() -> AuthContext:
    return AuthContext(user_id="admin-1", tenant_id="1", roles=("admin", "pii_read"))


@pytest.fixture
def other_tenant_auth() -> AuthContext:
    return AuthContext(user_id="analyst-2", tenant_id="2", roles=("analyst",))


def analyst_headers(tenant_id: str = "1", roles: str = "analyst") -> dict[str, str]:
    return {"X-User-Id": "u", "X-Tenant-Id": tenant_id, "X-Roles": roles}


@pytest.fixture
def headers() -> dict[str, str]:
    return analyst_headers()
