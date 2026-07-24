"""Database engine construction and read-only connection helpers.

We use *synchronous* SQLAlchemy 2.x engines. Read-only query execution is
CPU-light but I/O-bound, and the orchestrator invokes it via ``asyncio.to_thread``
so the event loop is never blocked. Synchronous engines keep the executor simple
and avoid the ``greenlet``/async-driver surface area for what is fundamentally a
"run one SELECT and read rows" operation.

Two engines are provided:

* ``engine`` — the primary engine (migrations, introspection, admin).
* ``readonly_engine`` — used by the query executor. In production this points at a
  URL backed by a read-only database role. Even when it is the same URL (e.g.
  local SQLite), the executor still applies session-level read-only enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import make_url

from text_to_sql.configuration import Settings
from text_to_sql.observability.logging import get_logger

_log = get_logger(__name__)


def _is_sqlite(url: str) -> bool:
    return make_url(url).get_backend_name() == "sqlite"


def build_engine(url: str, settings: Settings, *, readonly: bool = False) -> Engine:
    """Construct a SQLAlchemy engine with pool and dialect-appropriate options."""
    parsed = make_url(url)
    backend = parsed.get_backend_name()
    kwargs: dict[str, object] = {"future": True, "pool_pre_ping": True}

    if backend == "sqlite":
        # check_same_thread=False is required because the executor runs queries in
        # a worker thread (asyncio.to_thread) distinct from the creating thread.
        kwargs["connect_args"] = {"check_same_thread": False}
        # Ensure the parent directory exists for a file-backed SQLite database.
        if parsed.database and parsed.database != ":memory:":
            Path(parsed.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    else:
        kwargs.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout_seconds,
        )

    engine = create_engine(url, **kwargs)

    if backend == "sqlite" and readonly:
        # Enforce read-only at the connection level for SQLite. PostgreSQL uses
        # a read-only transaction + read-only role instead (see the executor).
        @event.listens_for(engine, "connect")
        def _set_sqlite_query_only(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("PRAGMA query_only = ON")
            finally:
                cursor.close()

    return engine


@dataclass
class Database:
    """Bundle of primary and read-only engines plus dialect metadata."""

    settings: Settings
    engine: Engine
    readonly_engine: Engine

    @property
    def backend(self) -> str:
        return make_url(self.settings.database_url).get_backend_name()

    def check_connection(self) -> bool:
        """Cheap readiness probe: run ``SELECT 1`` on the read-only engine."""
        try:
            with self.readonly_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as exc:
            _log.error("db_readiness_failed", exc_info=False, error=str(exc))
            return False

    def dispose(self) -> None:
        self.engine.dispose()
        if self.readonly_engine is not self.engine:
            self.readonly_engine.dispose()


def make_database(settings: Settings) -> Database:
    """Build a :class:`Database` from settings.

    When the read-only URL equals the primary URL and the backend is SQLite, we
    still build a *separate* engine so we can attach the ``query_only`` PRAGMA
    without affecting migrations/seeding on the primary engine.
    """
    engine = build_engine(settings.database_url, settings, readonly=False)
    ro_url = settings.effective_readonly_url
    readonly_engine = build_engine(ro_url, settings, readonly=True)
    return Database(settings=settings, engine=engine, readonly_engine=readonly_engine)
