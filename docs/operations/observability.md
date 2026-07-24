# Observability & Alerting

The engine ships a dependency-light observability stack
([`observability/*`](../../src/text_to_sql/observability)) that runs everywhere with
no external services, while remaining compatible with real backends.

## Structured logging

- One-line JSON per event, with `level`, `logger`, `event`, and `correlation_id`.
- A `contextvars`-based correlation id stitches every line of a request together.
- **Redaction** is applied to messages and string fields by default, so secrets/PII
  cannot be logged accidentally. Tracebacks are never shipped (only exception
  type + redacted message).

Correlation id flows: client `X-Correlation-Id` → middleware binds it → every log
line and the response body/header carry it.

## Metrics (`/metrics`, Prometheus text format)

Emitted by `MetricsRegistry`
([`observability/metrics.py`](../../src/text_to_sql/observability/metrics.py)):

| Metric | Type | Meaning |
| --- | --- | --- |
| `t2sql_requests_total{mode}` | counter | requests by execute/preview |
| `t2sql_requests_success_total{mode}` | counter | successful requests |
| `t2sql_requests_rejected_total` | counter | deterministic rejections |
| `t2sql_clarifications_total{category}` | counter | clarifications by category |
| `t2sql_repair_attempts_total` | counter | repair attempts |
| `t2sql_injection_markers_total{surface}` | counter | injection phrasing detected |
| `schema_cache_total{result}` | counter | schema cache hit/miss |
| `schema_drift_total` | counter | schema version changes |
| `t2sql_generation_ms` / `t2sql_execution_ms` / `t2sql_total_ms` | histogram | stage latencies (ms) |

## Tracing (OpenTelemetry-shaped)

`Tracer`/`Span` ([`observability/tracing.py`](../../src/text_to_sql/observability/tracing.py))
model spans (name, attributes, status, timing, parent linkage) with a
dependency-free default exporter that logs one debug line per span. Spans exist for
`query.process`, `retrieval`, `generation`, `validate_and_secure`, and `execution`.
The optional `otel` extra can bridge these to an OTLP collector. Span attributes are
non-sensitive by construction (ids, counts, durations, statement types).

## Recommended alerts

| Alert | Condition (suggested) |
| --- | --- |
| Elevated rejections | `rate(t2sql_requests_rejected_total[5m])` spikes (possible attack/misuse) |
| Provider degradation | p95 of `t2sql_generation_ms` high, or `provider_*` errors rising |
| Slow queries | p95 of `t2sql_execution_ms` above SLO |
| Readiness failing | `/api/v1/health/ready` returning 503 |
| Schema drift | any increase in `schema_drift_total` (migration happened) |
| Injection probing | sustained `t2sql_injection_markers_total` |

## Recommended dashboard panels

- Request rate & success/rejection/clarification split.
- Stage-latency histograms (generation vs execution vs total).
- Repair-attempt rate (a proxy for model quality).
- Cache hit ratio.
- Token usage (from response `model` metadata, if you export it).

## Caching (and its risks)

- **Schema cache** — TTL-bounded, explicitly invalidatable, version-aware,
  **tenant-independent** (identical shape for all tenants), so it cannot leak data.
- **Result cache** — **off by default** (`T2SQL_ENABLE_RESULT_CACHE=false`). Any
  result cache MUST be keyed by tenant id + auth/role context + schema version, and
  must never be shared across tenants or incompatible authorization contexts.
  Sensitive results should not be cached at all.
