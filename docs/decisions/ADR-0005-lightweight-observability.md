# ADR-0005: Dependency-light observability

- **Status:** Accepted
- **Context**

The requirements call for structured logging, Prometheus-compatible metrics, and
OpenTelemetry-compatible tracing. Pulling in `prometheus_client` and the full OTel
SDK adds weight and external assumptions for what, at its core, is "count things,
time things, and emit spans".

- **Decision**

Ship a **first-party**, dependency-free observability stack:

- JSON structured logging with correlation ids and built-in redaction
  (`observability/logging.py`);
- an in-process metrics registry that renders valid **Prometheus text exposition**
  at `/metrics` (`observability/metrics.py`);
- **OpenTelemetry-shaped** spans (name, attributes, status, timing, parent
  linkage) with a pluggable exporter (`observability/tracing.py`).

An optional `otel` extra can bridge spans to a real OTLP collector.

- **Consequences**

  - **Positive:** the whole system runs and is fully testable with **zero** external
    telemetry services (important for local dev and CI). Output is standard enough to
    be scraped by a real Prometheus.
  - **Positive:** redaction and correlation are baked in rather than bolted on.
  - **Negative:** the metric/span feature set is intentionally minimal (counters +
    histograms; no exemplars, no summaries). For richer needs, wire the `otel`
    extra / a real client — the call sites are already in place.

- **Alternatives considered**

  - *Require `prometheus_client` + OTel SDK* — rejected as the default: heavier and
    unnecessary for the core; offered as an opt-in extra instead.
