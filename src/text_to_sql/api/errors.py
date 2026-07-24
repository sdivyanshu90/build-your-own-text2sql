"""Exception handlers producing the uniform error envelope.

Every failure surfaced to a client is an
:class:`~text_to_sql.domain.models.ErrorResponse` with a stable code, safe
message, category, retryability, correlation id, and optional safe details.
Internal specifics (stack traces, raw SQL, driver text) are never included — they
live only in server-side structured logs.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from text_to_sql.common.errors import EngineError, InvalidRequestError
from text_to_sql.domain.models import ErrorDetail, ErrorResponse
from text_to_sql.observability.logging import get_correlation_id, get_logger

_log = get_logger(__name__)


def _envelope(error: EngineError, correlation_id: str) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(
            code=error.error_code,
            message=error.message,
            category=error.category.value,
            retryable=error.retryable,
            details=error.details or None,
            remediation=error.remediation,
        ),
        correlation_id=correlation_id,
    )
    return JSONResponse(status_code=error.http_status, content=body.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(EngineError)
    async def _engine_error(_request: Request, exc: EngineError) -> JSONResponse:
        cid = get_correlation_id()
        # Client/ambiguity errors are expected; log at info. Others at error.
        if exc.http_status < 500:
            _log.info("request_rejected", code=exc.error_code, status=exc.http_status)
        else:
            _log.error("request_failed", code=exc.error_code, status=exc.http_status)
        return _envelope(exc, cid)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        cid = get_correlation_id()
        err = InvalidRequestError(
            "The request body failed validation.",
            details={"errors": _safe_validation_errors(exc)},
        )
        _log.info("request_validation_error")
        return _envelope(err, cid)

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        cid = get_correlation_id()
        # Never leak the exception detail to the client.
        _log.error("unhandled_exception", exc_info=True, error_type=type(exc).__name__)
        err = EngineError("An unexpected internal error occurred.")
        return _envelope(err, cid)


def _safe_validation_errors(exc: RequestValidationError) -> list[dict]:
    """Reduce Pydantic errors to safe (location, message) pairs."""
    out: list[dict] = []
    for e in exc.errors()[:20]:
        loc = ".".join(str(p) for p in e.get("loc", []))
        out.append({"location": loc, "message": e.get("msg", "invalid")})
    return out
