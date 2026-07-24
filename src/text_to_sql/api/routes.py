"""Versioned API routes (``/api/v1``).

Endpoints:

* ``POST /query``          — generate, validate, (optionally) execute, explain.
* ``POST /query/preview``  — generate & validate; never execute.
* ``POST /query/validate`` — validate caller-supplied SQL via the policy engine.
* ``GET  /schema``         — authorization-filtered schema summary.
* ``POST /schema/refresh`` — force schema re-introspection (admin only).

Handlers translate HTTP ↔ orchestrator and set semantic status codes (e.g. 409
when the question needs clarification) while returning the structured body.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from text_to_sql.api.dependencies import (
    get_auth_context,
    get_container,
    get_orchestrator,
    require_admin,
)
from text_to_sql.application.container import AppContainer
from text_to_sql.application.orchestrator import QueryOrchestrator
from text_to_sql.domain.context import AuthContext
from text_to_sql.domain.enums import ResponseStatus
from text_to_sql.domain.models import (
    QueryRequest,
    QueryResponse,
    SchemaSummaryResponse,
    ValidateSQLRequest,
    ValidationReport,
)

router = APIRouter(prefix="/api/v1", tags=["text-to-sql"])


def _apply_status_code(response: Response, result: QueryResponse) -> None:
    if result.status == ResponseStatus.CLARIFICATION_REQUIRED:
        response.status_code = status.HTTP_409_CONFLICT
    else:
        response.status_code = status.HTTP_200_OK


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Generate, validate, execute, and explain a query",
)
async def post_query(
    request: QueryRequest,
    response: Response,
    auth: AuthContext = Depends(get_auth_context),
    orchestrator: QueryOrchestrator = Depends(get_orchestrator),
) -> QueryResponse:
    result = await orchestrator.process(request, auth, execute=True)
    _apply_status_code(response, result)
    return result


@router.post(
    "/query/preview",
    response_model=QueryResponse,
    summary="Generate and validate SQL without executing it",
)
async def post_query_preview(
    request: QueryRequest,
    response: Response,
    auth: AuthContext = Depends(get_auth_context),
    orchestrator: QueryOrchestrator = Depends(get_orchestrator),
) -> QueryResponse:
    result = await orchestrator.process(request, auth, execute=False)
    _apply_status_code(response, result)
    return result


@router.post(
    "/query/validate",
    response_model=ValidationReport,
    summary="Validate caller-supplied SQL through the policy engine",
)
async def post_validate(
    request: ValidateSQLRequest,
    auth: AuthContext = Depends(get_auth_context),
    orchestrator: QueryOrchestrator = Depends(get_orchestrator),
) -> ValidationReport:
    return orchestrator.validate_sql(request, auth)


@router.get(
    "/schema",
    response_model=SchemaSummaryResponse,
    summary="Authorization-filtered schema summary",
)
async def get_schema(
    auth: AuthContext = Depends(get_auth_context),
    container: AppContainer = Depends(get_container),
) -> SchemaSummaryResponse:
    schema = container.catalog.get_schema()

    def visible(_table: str, _column: str, classification) -> bool:  # type: ignore[no-untyped-def]
        return container.column_policy.can_view(classification, auth.roles)

    return container.catalog.summary(schema, visible=visible)


@router.post(
    "/schema/refresh",
    response_model=SchemaSummaryResponse,
    summary="Refresh schema metadata (admin only)",
)
async def post_schema_refresh(
    auth: AuthContext = Depends(require_admin),
    container: AppContainer = Depends(get_container),
) -> SchemaSummaryResponse:
    schema = container.catalog.refresh()

    def visible(_table: str, _column: str, classification) -> bool:  # type: ignore[no-untyped-def]
        return container.column_policy.can_view(classification, auth.roles)

    return container.catalog.summary(schema, visible=visible)
