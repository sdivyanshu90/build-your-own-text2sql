"""Read-only query execution with hard bounds.

The executor is the *only* place raw SQL touches the database, and it does so
under multiple guarantees:

* a dedicated read-only engine/role (see
  :func:`~text_to_sql.infrastructure.database.make_database`),
* an explicit read-only transaction (PostgreSQL ``SET TRANSACTION READ ONLY``;
  SQLite ``PRAGMA query_only`` set on connect),
* a statement timeout (PostgreSQL ``SET LOCAL statement_timeout``),
* a row cap enforced by fetching at most ``max_rows + 1`` and reporting truncation,
* JSON-safe value coercion (Decimal/datetime/bytes),
* mapping of every driver error onto a sanitized :class:`ExecutionError` so raw
  driver messages never reach clients.

It is synchronous; the orchestrator invokes it via ``asyncio.to_thread`` so the
event loop is never blocked.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from text_to_sql.common.errors import ExecutionError
from text_to_sql.domain.enums import SQLDialect
from text_to_sql.observability.logging import get_logger

_log = get_logger(__name__)


@dataclass
class ExecutionResult:
    """The outcome of executing a validated query."""

    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    duration_ms: float


class ReadOnlyExecutor:
    """Executes validated, tenant-scoped SQL against a read-only engine."""

    def __init__(
        self,
        engine: Engine,
        dialect: SQLDialect,
        *,
        statement_timeout_ms: int = 5000,
    ) -> None:
        self._engine = engine
        self._dialect = dialect
        self._timeout_ms = statement_timeout_ms

    def execute(self, sql: str, *, max_rows: int) -> ExecutionResult:
        start = time.perf_counter()
        try:
            with self._engine.connect() as conn:
                self._apply_session_guards(conn)
                result = conn.execute(text(sql))
                columns = list(result.keys())
                fetched = result.fetchmany(max_rows + 1)
                # Read-only: no commit needed; context manager rolls back.
        except SQLAlchemyError as exc:
            # Never surface raw driver text; log it server-side, return a safe error.
            _log.error("query_execution_failed", error=str(exc)[:300])
            raise ExecutionError(
                "The query could not be executed.",
                details={"reason": _classify_db_error(exc)},
            ) from exc

        truncated = len(fetched) > max_rows
        rows = [[_to_jsonable(value) for value in row] for row in fetched[:max_rows]]
        duration_ms = (time.perf_counter() - start) * 1000.0
        return ExecutionResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            duration_ms=duration_ms,
        )

    def _apply_session_guards(self, conn) -> None:  # type: ignore[no-untyped-def]
        if self._dialect == SQLDialect.POSTGRES:
            # These run inside the connection's implicit transaction.
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = {int(self._timeout_ms)}"))
        # SQLite read-only is enforced via PRAGMA query_only on connect; it has no
        # server-side statement timeout, so bounding is via LIMIT + row cap.


def _to_jsonable(value: Any) -> Any:
    """Coerce DB values into JSON-serializable primitives."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        # Floats are fine for API transport; documented precision trade-off.
        return float(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "«binary»"
    return str(value)


def _classify_db_error(exc: SQLAlchemyError) -> str:
    """Map a driver error to a coarse, non-sensitive reason string."""
    text_lower = str(exc).lower()
    if "timeout" in text_lower or "canceling statement" in text_lower:
        return "statement_timeout"
    if "permission" in text_lower or "read-only" in text_lower or "readonly" in text_lower:
        return "read_only_violation"
    if "syntax" in text_lower:
        return "syntax_error"
    return "database_error"
