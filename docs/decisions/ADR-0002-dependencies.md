# ADR-0002: Technology stack & dependency choices

- **Status:** Accepted
- **Context**

The engine needs an HTTP framework, validation, a DB toolkit, a SQL parser, an
HTTP client, migrations, and a test/quality toolchain — without coupling the core
to any single LLM vendor, vector DB, or dialect.

- **Decision & justification (each major dependency)**

| Dependency | Why | Coupling note |
| --- | --- | --- |
| **FastAPI** | Async, typed, OpenAPI out of the box | Only `api/` imports it; business logic is framework-free |
| **Pydantic v2** | Typed, validated, immutable value objects | Domain models are pure Pydantic |
| **pydantic-settings** | Env-driven, validated config | Single `Settings` object |
| **SQLAlchemy 2** | Reflection + safe execution + dialect abstraction | Wrapped by `infrastructure/`, `schema/`, `execution/` |
| **SQLGlot** | Dialect-aware parse/AST/transpile — the basis of all validation | The security core; chosen over regex on principle |
| **httpx** | Async HTTP client with a testable `MockTransport` | Only the OpenAI adapter uses it |
| **Alembic** | Migrations derived from the single-source metadata | — |
| **uvicorn** | ASGI server | Runtime only |
| **pytest / pytest-asyncio / pytest-cov** | Test runner, async, coverage | Dev only |
| **Hypothesis** | Property-based invariants | Dev only |
| **Ruff / mypy / Bandit** | Lint, types, security scan | Dev only |
| **psycopg (optional)** | PostgreSQL driver | `postgres` extra |

- **Deliberately *not* required**

  - **`prometheus_client` / OpenTelemetry SDK** — replaced by a dependency-light,
    first-party equivalent (see [ADR-0005](ADR-0005-lightweight-observability.md));
    the `otel` extra can bridge to a real collector.
  - **A vector database / embeddings** — the default retriever is deterministic and
    needs none; the `SchemaRetriever` protocol allows adding one later.
  - **An ORM model layer** — Core + reflection suffice; the engine reads schema, it
    does not map objects.

- **Consequences**

  - Small default footprint; runs and tests with SQLite + fake provider and no
    external services. Vendor/dialect independence preserved via protocols and the
    dialect enum. Adding a provider/retriever/dialect is a localized change.
