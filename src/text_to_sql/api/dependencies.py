"""FastAPI dependency-injection helpers.

* :func:`get_container` / :func:`get_orchestrator` expose the wired object graph
  built at startup (stored on ``app.state``).
* :func:`get_auth_context` derives the *trusted* :class:`AuthContext` from request
  headers. This is a reference stand-in: in production the identity would come
  from a verified JWT / session established by an auth gateway. The engine treats
  the resulting context as authoritative for all authorization decisions, so it
  must never be derived from request *body* content or the LLM.
"""

from __future__ import annotations

from fastapi import Depends, Header, Request

from text_to_sql.application.container import AppContainer
from text_to_sql.application.orchestrator import QueryOrchestrator
from text_to_sql.common.errors import AuthorizationError
from text_to_sql.domain.context import AuthContext


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


def get_orchestrator(
    container: AppContainer = Depends(get_container),
) -> QueryOrchestrator:
    return container.orchestrator


def get_auth_context(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    x_roles: str | None = Header(default=None, alias="X-Roles"),
) -> AuthContext:
    """Build the authenticated caller context from headers.

    Requires ``X-User-Id`` and ``X-Tenant-Id``. Roles are a comma-separated list
    in ``X-Roles`` (e.g. ``analyst`` or ``admin,pii_read``).
    """
    if not x_user_id or not x_tenant_id:
        raise AuthorizationError(
            "Authentication context is required (X-User-Id and X-Tenant-Id headers).",
            details={"code": "missing_identity"},
        )
    roles = tuple(r.strip() for r in (x_roles or "").split(",") if r.strip())
    return AuthContext(user_id=x_user_id, tenant_id=x_tenant_id, roles=roles)


def require_admin(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
    """Dependency enforcing the ``admin`` role (schema refresh, etc.)."""
    if not auth.is_admin:
        raise AuthorizationError(
            "This operation requires the 'admin' role.",
            details={"code": "admin_required"},
        )
    return auth
