# Architecture Decision Records

ADRs capture significant, hard-to-reverse decisions and *why* they were made.

| ADR | Title | Status |
| --- | --- | --- |
| [0001](ADR-0001-deterministic-security.md) | Deterministic security enforced after generation | Accepted |
| [0002](ADR-0002-dependencies.md) | Technology stack & dependency choices | Accepted |
| [0003](ADR-0003-sync-execution.md) | Synchronous SQLAlchemy execution via `asyncio.to_thread` | Accepted |
| [0004](ADR-0004-reject-select-star.md) | Reject bare `SELECT *` instead of expanding it | Accepted |
| [0005](ADR-0005-lightweight-observability.md) | Dependency-light observability (first-party metrics/tracing) | Accepted |
| [0006](ADR-0006-grounded-explanations.md) | Grounded, deterministic explanations (not LLM narration) | Accepted |
| [0007](ADR-0007-python-version.md) | Target Python 3.10+ with 3.12 recommended | Accepted |
