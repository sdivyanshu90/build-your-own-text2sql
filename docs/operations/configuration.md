# Configuration Reference

All configuration is loaded once at startup into an immutable, validated
`Settings` object ([`configuration/settings.py`](../../src/text_to_sql/configuration/settings.py))
from environment variables prefixed `T2SQL_` (and an optional `.env`). Invalid
configuration fails fast with an actionable error. No module reads `os.environ`
directly. See [`.env.example`](../../.env.example) for a copy-paste starting point.

## Runtime

| Variable | Default | Notes |
| --- | --- | --- |
| `T2SQL_ENVIRONMENT` | `development` | `development`/`staging`/`production`/`test` |
| `T2SQL_LOG_LEVEL` | `INFO` | validated; uppercased |
| `T2SQL_LOG_JSON` | `true` | structured JSON logs (keep `true` in prod) |
| `T2SQL_API_HOST` | `0.0.0.0` | bind address |
| `T2SQL_API_PORT` | `8000` | 1–65535 |

## Database

| Variable | Default | Notes |
| --- | --- | --- |
| `T2SQL_DATABASE_URL` | `sqlite:///./data/text_to_sql.db` | primary engine (migrations, introspection) |
| `T2SQL_READONLY_DATABASE_URL` | *(falls back to primary)* | point at a **read-only role** in prod |
| `T2SQL_DB_POOL_SIZE` | `5` | PostgreSQL pool |
| `T2SQL_DB_MAX_OVERFLOW` | `5` | |
| `T2SQL_DB_POOL_TIMEOUT_SECONDS` | `10` | |

## SQL dialect & safety limits

| Variable | Default | Notes |
| --- | --- | --- |
| `T2SQL_SQL_DIALECT` | `sqlite` | `sqlite` or `postgres` |
| `T2SQL_MAX_ROWS` | `1000` | hard `LIMIT` cap |
| `T2SQL_STATEMENT_TIMEOUT_MS` | `5000` | PostgreSQL statement timeout |
| `T2SQL_MAX_JOINS` | `6` | cost limit |
| `T2SQL_MAX_SUBQUERY_DEPTH` | `4` | cost limit |
| `T2SQL_MAX_SELECTED_COLUMNS` | `60` | cost limit |
| `T2SQL_COST_ROWS_MEDIUM_THRESHOLD` | `100000` | must be `<` high |
| `T2SQL_COST_ROWS_HIGH_THRESHOLD` | `1000000` | reject threshold |

## LLM provider

| Variable | Default | Notes |
| --- | --- | --- |
| `T2SQL_LLM_PROVIDER` | `fake` | `fake` (no creds) or `openai` |
| `T2SQL_LLM_MODEL` | `deterministic-fake` | model id |
| `T2SQL_LLM_BASE_URL` | `https://api.openai.com/v1` | any OpenAI-compatible endpoint |
| `T2SQL_LLM_API_KEY_ENV` | `OPENAI_API_KEY` | **name** of the env var holding the key |
| `T2SQL_LLM_TIMEOUT_SECONDS` | `30` | |
| `T2SQL_LLM_MAX_RETRIES` | `2` | |
| `T2SQL_LLM_TEMPERATURE` | `0.0` | deterministic where supported |

> The API key itself is **never** a config field. `T2SQL_LLM_API_KEY_ENV` names
> *another* variable; the key is resolved at call time and never logged.

## Pipeline behaviour

| Variable | Default | Notes |
| --- | --- | --- |
| `T2SQL_MAX_REPAIR_ATTEMPTS` | `2` | bounded repair loop |
| `T2SQL_SCHEMA_CACHE_TTL_SECONDS` | `300` | `0` disables TTL expiry |
| `T2SQL_ENABLE_RESULT_CACHE` | `false` | off by default (see caching risks) |
| `T2SQL_RETRIEVAL_TOP_K` | `12` | seed tables before bridging |
| `T2SQL_DISCLOSE_MODEL_METADATA` | `true` | include provider/model in responses |

## Observability & tenancy

| Variable | Default | Notes |
| --- | --- | --- |
| `T2SQL_METRICS_ENABLED` | `true` | serves `/metrics` |
| `T2SQL_TRACING_ENABLED` | `true` | OTel-shaped spans |
| `T2SQL_ALLOWED_SCHEMAS` | *(empty)* | comma-separated allowlist |
| `T2SQL_TENANT_COLUMN` | `organization_id` | column used for tenant predicates |

## Secret management

- Never commit a real `.env`. `.gitignore` excludes it.
- Provide `OPENAI_API_KEY` (or whatever `T2SQL_LLM_API_KEY_ENV` names) via your
  platform's secret store (Kubernetes Secret, AWS Secrets Manager, Vault, …),
  injected as an environment variable at runtime.
- Use a **dedicated read-only database role** for `T2SQL_READONLY_DATABASE_URL` in
  production.
