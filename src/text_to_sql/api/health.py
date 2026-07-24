"""Health, readiness, and metrics endpoints.

* ``/api/v1/health/live``  — process liveness (always 200 if serving).
* ``/api/v1/health/ready`` — readiness: safely probes critical dependencies
  (database connectivity, schema availability). Returns 503 if not ready.
* ``/metrics``             — Prometheus text exposition (when enabled).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import PlainTextResponse

from text_to_sql.api.dependencies import get_container
from text_to_sql.application.container import AppContainer
from text_to_sql.domain.models import HealthResponse

health_router = APIRouter(prefix="/api/v1/health", tags=["health"])
metrics_router = APIRouter(tags=["observability"])


@health_router.get("/live", response_model=HealthResponse, summary="Liveness probe")
async def live() -> HealthResponse:
    return HealthResponse(status="ok", checks={"process": "ok"})


@health_router.get("/ready", response_model=HealthResponse, summary="Readiness probe")
async def ready(
    response: Response,
    container: AppContainer = Depends(get_container),
) -> HealthResponse:
    checks: dict[str, str] = {}

    db_ok = container.database.check_connection()
    checks["database"] = "ok" if db_ok else "unavailable"

    schema_ok = True
    try:
        container.catalog.get_schema()
    except Exception:
        schema_ok = False
    checks["schema"] = "ok" if schema_ok else "unavailable"

    ready_now = db_ok and schema_ok
    if not ready_now:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="ok" if ready_now else "not_ready", checks=checks)


@metrics_router.get("/metrics", summary="Prometheus metrics", include_in_schema=False)
async def metrics(container: AppContainer = Depends(get_container)) -> Response:
    if not container.settings.metrics_enabled:
        return PlainTextResponse("metrics disabled\n", status_code=status.HTTP_404_NOT_FOUND)
    return PlainTextResponse(
        container.metrics.render(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
