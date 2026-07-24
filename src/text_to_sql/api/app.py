"""FastAPI application factory.

``create_app`` builds the wired :class:`AppContainer`, installs correlation-ID
middleware, registers exception handlers, and mounts the routers. Tests can inject
a pre-built container (with an in-memory DB and the fake provider) to exercise the
full HTTP stack deterministically.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, Response

from text_to_sql.api.errors import register_exception_handlers
from text_to_sql.api.health import health_router, metrics_router
from text_to_sql.api.routes import router as v1_router
from text_to_sql.application.container import AppContainer
from text_to_sql.common.ids import sanitize_correlation_id
from text_to_sql.configuration import Settings, get_settings
from text_to_sql.observability.logging import bind_correlation_id, configure_logging, get_logger

_log = get_logger(__name__)

_CORRELATION_HEADER = "X-Correlation-Id"


def create_app(
    settings: Settings | None = None,
    *,
    container: AppContainer | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)

    owns_container = container is None
    container = container or AppContainer.create(settings)

    app = FastAPI(
        title="Text-to-SQL Engine",
        version="0.1.0",
        description=(
            "Convert natural-language questions into safe, validated, executable "
            "read-only SQL. Security is enforced deterministically after generation."
        ),
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
    )
    app.state.container = container
    app.state.settings = settings

    @app.middleware("http")
    async def _correlation_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        correlation_id = sanitize_correlation_id(request.headers.get(_CORRELATION_HEADER))
        bind_correlation_id(correlation_id)
        response: Response = await call_next(request)
        response.headers[_CORRELATION_HEADER] = correlation_id
        return response

    register_exception_handlers(app)
    app.include_router(v1_router)
    app.include_router(health_router)
    app.include_router(metrics_router)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        if owns_container:
            container.dispose()
        _log.info("application_shutdown")

    _log.info(
        "application_started",
        environment=settings.environment.value,
        provider=settings.llm_provider,
        dialect=settings.sql_dialect,
    )
    return app
