"""Structured JSON logging with correlation IDs and redaction.

All log records are emitted as one-line JSON objects so they can be shipped to
any log aggregator. A :class:`contextvars.ContextVar` carries the current
correlation ID so every line for a request is stitched together without threading
the ID through every call.

Redaction is applied to the free-text ``event`` message and to structured fields
by default, so a caller cannot accidentally log a secret or PII value. Callers
that have *already* redacted (or that log known-safe data) can opt out per call.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

from text_to_sql.common.redaction import redact_text

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")

_CONFIGURED = False


def bind_correlation_id(correlation_id: str) -> None:
    """Bind the correlation ID for the current async/sync context."""
    _correlation_id.set(correlation_id)


def get_correlation_id() -> str:
    return _correlation_id.get()


class _JsonFormatter(logging.Formatter):
    """Render log records as compact JSON, merging structured fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", _correlation_id.get()),
        }
        structured = getattr(record, "structured", None)
        if isinstance(structured, dict):
            # Structured fields never overwrite the reserved keys above.
            for key, value in structured.items():
                if key not in payload:
                    payload[key] = value
        if record.exc_info:
            # We include only the exception *type* and message, never the traceback,
            # to avoid leaking internal detail into shipped logs. Full tracebacks
            # are available via the console handler in development only.
            exc_type, exc_value, _ = record.exc_info
            payload["error_type"] = getattr(exc_type, "__name__", str(exc_type))
            payload["error_message"] = redact_text(str(exc_value))
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(*, level: str = "INFO", json_output: bool = True) -> None:
    """Configure the root logger. Idempotent across repeated calls."""
    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(level.upper())
    # Remove existing handlers so re-configuration (e.g. in tests) is clean.
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(stream=sys.stdout)
    if json_output:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s"))
    root.addHandler(handler)
    _CONFIGURED = True


class StructuredLogger:
    """A thin wrapper over :mod:`logging` that emits structured, redacted events.

    Example
    -------
    >>> log = get_logger(__name__)
    >>> log.info("sql_validated", statement_type="select", table_count=3)
    """

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def _emit(
        self,
        level: int,
        event: str,
        *,
        redact: bool = True,
        exc_info: bool = False,
        **fields: Any,
    ) -> None:
        if not self._logger.isEnabledFor(level):
            return
        message = redact_text(event) if redact else event
        structured = {
            key: (redact_text(value) if redact and isinstance(value, str) else value)
            for key, value in fields.items()
        }
        self._logger.log(
            level,
            message,
            extra={"structured": structured, "correlation_id": _correlation_id.get()},
            exc_info=exc_info,
        )

    def debug(self, event: str, **fields: Any) -> None:
        self._emit(logging.DEBUG, event, **fields)

    def info(self, event: str, **fields: Any) -> None:
        self._emit(logging.INFO, event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._emit(logging.WARNING, event, **fields)

    def error(self, event: str, *, exc_info: bool = False, **fields: Any) -> None:
        self._emit(logging.ERROR, event, exc_info=exc_info, **fields)


def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(name)
