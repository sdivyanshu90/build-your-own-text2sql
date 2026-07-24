"""OpenTelemetry-shaped tracing with a dependency-free default.

We model spans the way OTel does — name, attributes, events, status, start/end
timestamps, parent linkage — but the default tracer records spans in-process and
emits a structured debug log per span instead of requiring the OTel SDK. This
keeps traces available everywhere (tests, CI, local) while staying compatible
with a real exporter: the optional ``otel`` extra can wrap :class:`Tracer` to
forward spans to an OTLP collector.

Span attributes are redaction-friendly: callers must only attach non-sensitive
values (ids, counts, durations, statement types), never raw SQL text or PII.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from text_to_sql.common.ids import new_correlation_id
from text_to_sql.observability.logging import get_correlation_id

SpanExporter = Callable[["Span"], None]

_current_span: ContextVar[Span | None] = ContextVar("current_span", default=None)


@dataclass
class Span:
    """A single unit of traced work."""

    name: str
    span_id: str
    parent_id: str | None
    correlation_id: str
    start_perf: float
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    status: str = "unset"  # unset | ok | error
    duration_ms: float | None = None

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def set_attributes(self, **values: Any) -> None:
        self.attributes.update(values)

    def add_event(self, name: str, **attrs: Any) -> None:
        self.events.append({"name": name, **attrs})

    def set_status(self, status: str) -> None:
        self.status = status

    def record_exception(self, exc: BaseException) -> None:
        # Only the exception type/message — never the traceback in span data.
        self.status = "error"
        self.attributes["error_type"] = type(exc).__name__


class Tracer:
    """Creates spans and forwards completed ones to an exporter."""

    def __init__(self, exporter: SpanExporter | None = None) -> None:
        self._exporter = exporter
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"span_{self._counter:06d}"

    @contextmanager
    def start_span(self, name: str, **attributes: Any) -> Iterator[Span]:
        parent = _current_span.get()
        span = Span(
            name=name,
            span_id=self._next_id(),
            parent_id=parent.span_id if parent else None,
            correlation_id=get_correlation_id() or new_correlation_id(),
            start_perf=time.perf_counter(),
            attributes=dict(attributes),
        )
        token = _current_span.set(span)
        try:
            yield span
            if span.status == "unset":
                span.status = "ok"
        except BaseException as exc:
            span.record_exception(exc)
            raise
        finally:
            span.duration_ms = (time.perf_counter() - span.start_perf) * 1000.0
            _current_span.reset(token)
            if self._exporter is not None:
                self._exporter(span)


def _default_exporter(span: Span) -> None:
    """Emit a structured debug log for each completed span."""
    # Imported lazily to avoid a circular import at module load.
    from text_to_sql.observability.logging import get_logger

    get_logger("trace").debug(
        "span",
        span_name=span.name,
        span_id=span.span_id,
        parent_id=span.parent_id,
        status=span.status,
        duration_ms=round(span.duration_ms or 0.0, 3),
        **{f"attr_{k}": v for k, v in span.attributes.items()},
    )


_GLOBAL_TRACER = Tracer(exporter=_default_exporter)


def get_tracer() -> Tracer:
    return _GLOBAL_TRACER
