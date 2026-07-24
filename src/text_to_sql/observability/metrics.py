"""In-process metrics registry with Prometheus text exposition.

A minimal, thread-safe registry supporting counters and histograms — enough to
satisfy the observability requirements (request counts, stage latencies,
validation outcomes, repair attempts, token usage, cache hits) without pulling in
``prometheus_client``. The output of :meth:`MetricsRegistry.render` is valid
Prometheus text-exposition format, so a real Prometheus can scrape ``/metrics``.

Labels are supported via a tuple key. Histograms use fixed, latency-oriented
buckets (milliseconds) plus a ``+Inf`` bucket, and expose ``_count``/``_sum`` as
Prometheus expects.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Iterable

# Default histogram buckets in milliseconds — tuned for request/stage latencies.
_DEFAULT_BUCKETS_MS: tuple[float, ...] = (
    1,
    5,
    10,
    25,
    50,
    100,
    250,
    500,
    1000,
    2500,
    5000,
    10000,
)

_LabelKey = tuple[tuple[str, str], ...]


def _label_key(labels: dict[str, str] | None) -> _LabelKey:
    if not labels:
        return ()
    return tuple(sorted(labels.items()))


def _render_labels(key: _LabelKey, extra: tuple[tuple[str, str], ...] = ()) -> str:
    items = list(key) + list(extra)
    if not items:
        return ""
    inner = ",".join(f'{name}="{_escape(value)}"' for name, value in items)
    return "{" + inner + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


class _Counter:
    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help = help_text
        self._values: dict[_LabelKey, float] = defaultdict(float)

    def inc(self, amount: float, labels: dict[str, str] | None) -> None:
        self._values[_label_key(labels)] += amount

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        if not self._values:
            lines.append(f"{self.name} 0")
        for key, value in sorted(self._values.items()):
            lines.append(f"{self.name}{_render_labels(key)} {value}")
        return lines


class _Histogram:
    def __init__(self, name: str, help_text: str, buckets: tuple[float, ...]) -> None:
        self.name = name
        self.help = help_text
        self.buckets = buckets
        self._bucket_counts: dict[_LabelKey, list[int]] = defaultdict(
            lambda: [0] * (len(buckets) + 1)
        )
        self._sum: dict[_LabelKey, float] = defaultdict(float)
        self._count: dict[_LabelKey, int] = defaultdict(int)

    def observe(self, value: float, labels: dict[str, str] | None) -> None:
        key = _label_key(labels)
        counts = self._bucket_counts[key]
        placed = False
        for i, upper in enumerate(self.buckets):
            if value <= upper:
                counts[i] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1  # +Inf bucket
        self._sum[key] += value
        self._count[key] += 1

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        keys = set(self._count) or {()}
        for key in sorted(keys):
            counts = self._bucket_counts.get(key, [0] * (len(self.buckets) + 1))
            cumulative = 0
            for i, upper in enumerate(self.buckets):
                cumulative += counts[i]
                lines.append(
                    f"{self.name}_bucket{_render_labels(key, (('le', str(upper)),))} {cumulative}"
                )
            cumulative += counts[-1]
            lines.append(f"{self.name}_bucket{_render_labels(key, (('le', '+Inf'),))} {cumulative}")
            lines.append(f"{self.name}_sum{_render_labels(key)} {self._sum.get(key, 0.0)}")
            lines.append(f"{self.name}_count{_render_labels(key)} {self._count.get(key, 0)}")
        return lines


class MetricsRegistry:
    """Thread-safe registry of counters and histograms."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, _Counter] = {}
        self._histograms: dict[str, _Histogram] = {}

    def counter(self, name: str, help_text: str = "") -> _Counter:
        with self._lock:
            if name not in self._counters:
                self._counters[name] = _Counter(name, help_text or name)
            return self._counters[name]

    def histogram(
        self,
        name: str,
        help_text: str = "",
        buckets: tuple[float, ...] = _DEFAULT_BUCKETS_MS,
    ) -> _Histogram:
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = _Histogram(name, help_text or name, buckets)
            return self._histograms[name]

    # Convenience helpers used throughout the pipeline ------------------------
    def inc(self, name: str, amount: float = 1.0, **labels: str) -> None:
        self.counter(name).inc(amount, labels or None)

    def observe(self, name: str, value: float, **labels: str) -> None:
        self.histogram(name).observe(value, labels or None)

    def render(self) -> str:
        """Render all metrics in Prometheus text-exposition format."""
        with self._lock:
            lines: list[str] = []
            for counter in self._counters.values():
                lines.extend(counter.render())
            for hist in self._histograms.values():
                lines.extend(hist.render())
        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        """Clear all metrics (used by tests)."""
        with self._lock:
            self._counters.clear()
            self._histograms.clear()


_GLOBAL_REGISTRY = MetricsRegistry()


def get_metrics() -> MetricsRegistry:
    """Return the process-wide metrics registry."""
    return _GLOBAL_REGISTRY


def iter_metric_lines(registry: MetricsRegistry) -> Iterable[str]:
    return registry.render().splitlines()
