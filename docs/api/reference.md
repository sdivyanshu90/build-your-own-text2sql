# API Reference

Base path: `/api/v1`. Interactive docs (OpenAPI/Swagger) are served at
`/api/v1/docs`; the raw spec at `/api/v1/openapi.json`. All models are defined in
[`domain/models.py`](../../src/text_to_sql/domain/models.py).

## Versioning

The API is versioned in the path (`/api/v1`). Breaking changes ship under a new
prefix; additive changes stay within `v1`. The prompt version and dataset version
are separate and reported in responses / evaluation output.

## Authentication

Every endpoint (except health/metrics) requires the caller's identity via headers:

| Header | Required | Example |
| --- | --- | --- |
| `X-User-Id` | yes | `u_123` |
| `X-Tenant-Id` | yes | `1` |
| `X-Roles` | no | `analyst` or `admin,pii_read` |
| `X-Correlation-Id` | no | echoed back; generated if absent |

In production these are set by an auth gateway that verifies a JWT/session (see
[authorization](../security/authorization.md)).

## `POST /api/v1/query`

Generate → validate → (optionally) execute → explain.

Request ([`QueryRequest`]): `question` (required), and optional `dialect`,
`tenant_id` (advisory; must match auth), `conversation`, `glossary_overrides`,
`max_rows`, `dry_run`, `sql_only`, `explain`, `correlation_id`.

```bash
curl -s http://localhost:8000/api/v1/query \
  -H 'Content-Type: application/json' \
  -H 'X-User-Id: u1' -H 'X-Tenant-Id: 1' -H 'X-Roles: analyst' \
  -d '{"question": "What were our top five products by revenue last quarter?"}'
```

Status codes: `200` success/preview · `409` clarification required · `403`
authorization denied · `422` validation/cost/repair failure or invalid body ·
`502/504` provider · `503` dependency unavailable.

Response: [`QueryResponse`] — `status`, `correlation_id`, `sql`, `columns`,
`rows`, `row_count`, `truncated`, `explanation`, `assumptions`, `warnings`,
`confidence`, `validation`, `clarification`, `retrieval`, `timings`, `execution`,
`model`.

## `POST /api/v1/query/preview`

Same as `/query` but **never executes**. `status` is `preview`; `rows` empty;
`execution` null. Useful for showing/approving SQL before running it.

## `POST /api/v1/query/validate`

Validate caller-supplied SQL through the same deterministic engine. Never
executes. Always returns `200` with a [`ValidationReport`] (does not raise for
invalid SQL) so clients can inspect `is_valid` and `issues`.

```bash
curl -s http://localhost:8000/api/v1/query/validate \
  -H 'Content-Type: application/json' \
  -H 'X-User-Id: u1' -H 'X-Tenant-Id: 1' -H 'X-Roles: analyst' \
  -d '{"sql": "DROP TABLE users"}'
# → {"is_valid": false, "issues": [{"code": "forbidden_statement", ...}], ...}
```

## `GET /api/v1/schema`

Returns an **authorization-filtered** [`SchemaSummaryResponse`]: tables, columns,
types, classification, and a `sensitive` flag — with columns the caller may not
view **omitted**. (An analyst will not see `users.email` or `password_hash`.)

## `POST /api/v1/schema/refresh`

Force schema re-introspection (cache invalidation). **Admin only** (`403`
otherwise). Returns the refreshed filtered summary.

## `GET /api/v1/health/live`

Liveness. Always `200` while the process serves.

## `GET /api/v1/health/ready`

Readiness. Safely probes DB connectivity and schema availability; `200` when
ready, `503` otherwise, with a `checks` map.

## `GET /metrics`

Prometheus text exposition (when `T2SQL_METRICS_ENABLED=true`). Not
authentication-gated by default — restrict at the network/proxy layer.

## Error envelope

All non-2xx responses share one shape ([`ErrorResponse`]):

```json
{
  "error": {
    "code": "authorization_denied",
    "message": "The query accesses data you are not permitted to read.",
    "category": "authorization",
    "retryable": false,
    "details": { "issues": [ ... ] }
  },
  "correlation_id": "corr_..."
}
```

Stack traces, raw SQL, and driver messages are never included.

[`QueryRequest`]: ../../src/text_to_sql/domain/models.py
[`QueryResponse`]: ../../src/text_to_sql/domain/models.py
[`ValidationReport`]: ../../src/text_to_sql/domain/models.py
[`SchemaSummaryResponse`]: ../../src/text_to_sql/domain/models.py
[`ErrorResponse`]: ../../src/text_to_sql/domain/models.py
