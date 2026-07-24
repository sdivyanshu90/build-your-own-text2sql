# ADR-0003: Synchronous SQLAlchemy execution via `asyncio.to_thread`

- **Status:** Accepted
- **Context**

The orchestrator is async (it awaits the LLM provider over HTTP). Query execution,
by contrast, is "run one validated `SELECT` and read bounded rows". We must not
block the event loop, but we also want the executor to be simple and robust.

- **Decision**

Use **synchronous** SQLAlchemy engines and run execution in a worker thread via
`asyncio.to_thread` from the orchestrator. The read-only engine uses
`check_same_thread=False` (SQLite) precisely because execution happens on a
different thread than engine creation.

- **Consequences**

  - **Positive:** avoids the async-driver/`greenlet` surface area for what is a
    small, bounded operation; the executor is a straightforward, well-tested class
    (`execution/executor.py`). Read-only session guards
    (`SET TRANSACTION READ ONLY`, `PRAGMA query_only`, statement timeout) are easy
    to apply synchronously.
  - **Negative:** each execution consumes a thread-pool slot; for very high
    concurrency the pool size and DB connection pool must be tuned together. This is
    acceptable given queries are short and `LIMIT`-bounded.

- **Alternatives considered**

  - *Async SQLAlchemy (`asyncpg`/`aiosqlite`)* — more moving parts and driver
    quirks for marginal benefit on short read-only queries; rejected for v1.
