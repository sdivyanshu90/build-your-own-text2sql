"""Observability: structured logging, metrics, and tracing.

The engine ships a *dependency-light* observability stack:

* **Logging** — JSON structured logs with correlation IDs and built-in redaction.
* **Metrics** — an in-process registry exposed in Prometheus text format at
  ``/metrics`` (no ``prometheus_client`` dependency required).
* **Tracing** — OpenTelemetry-*shaped* spans (name, attributes, status, timing)
  with a no-op default and a pluggable exporter. The optional ``otel`` extra can
  bridge these to a real OTLP collector.

Keeping these first-party means the whole system runs and is testable with zero
external telemetry services, while remaining compatible with real backends.
"""

from __future__ import annotations

from text_to_sql.observability.logging import (
    StructuredLogger,
    bind_correlation_id,
    configure_logging,
    get_correlation_id,
    get_logger,
)
from text_to_sql.observability.metrics import MetricsRegistry, get_metrics
from text_to_sql.observability.tracing import Span, Tracer, get_tracer

__all__ = [
    "MetricsRegistry",
    "Span",
    "StructuredLogger",
    "Tracer",
    "bind_correlation_id",
    "configure_logging",
    "get_correlation_id",
    "get_logger",
    "get_metrics",
    "get_tracer",
]
