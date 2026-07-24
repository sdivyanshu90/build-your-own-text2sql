"""Extra coverage for date phrases and logging/tracing."""

from __future__ import annotations

from datetime import datetime

import pytest

from text_to_sql.observability.logging import (
    StructuredLogger,
    bind_correlation_id,
    configure_logging,
    get_correlation_id,
)
from text_to_sql.observability.tracing import Tracer
from text_to_sql.semantic.dates import days_in_month, resolve_relative_date

pytestmark = pytest.mark.unit
NOW = datetime(2026, 7, 24)


@pytest.mark.parametrize(
    "phrase,start,end",
    [
        ("this month", datetime(2026, 7, 1), NOW),
        ("this quarter", datetime(2026, 7, 1), NOW),
        ("yesterday", datetime(2026, 7, 23), datetime(2026, 7, 24)),
        ("today", datetime(2026, 7, 24), datetime(2026, 7, 25)),
    ],
)
def test_more_date_phrases(phrase: str, start: datetime, end: datetime) -> None:
    r = resolve_relative_date(f"data {phrase}", NOW)
    assert r is not None
    assert r.start == start
    assert r.end == end


def test_last_week() -> None:
    r = resolve_relative_date("orders last week", NOW)  # NOW is a Friday
    assert r is not None
    assert (r.end - r.start).days == 7


def test_days_in_month() -> None:
    assert days_in_month(2026, 2) == 28
    assert days_in_month(2024, 2) == 29


# --- Logging / tracing ---------------------------------------------------- #
def test_json_logging_redacts(capsys: pytest.CaptureFixture[str]) -> None:
    import json

    configure_logging(level="INFO", json_output=True)
    bind_correlation_id("corr_log_test")
    StructuredLogger("test.logger").info("user_event", email="alice@example.com", count=3)
    out = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(out)  # JsonFormatter produced valid JSON
    assert payload["event"] == "user_event"
    assert payload["correlation_id"] == "corr_log_test"
    assert "alice@example.com" not in json.dumps(payload)
    assert payload["count"] == 3
    # Reset to plain logging so later tests' caplog keeps working cleanly.
    configure_logging(level="INFO", json_output=False)


def test_structured_logger_below_level_is_noop() -> None:
    configure_logging(level="ERROR", json_output=False)
    StructuredLogger("q").debug("skipped_event", secret="x")  # must not raise
    configure_logging(level="INFO", json_output=False)


def test_correlation_id_binding() -> None:
    bind_correlation_id("corr_abc")
    assert get_correlation_id() == "corr_abc"


def test_tracer_records_span_status() -> None:
    captured: list = []
    tracer = Tracer(exporter=captured.append)
    with tracer.start_span("work", key="v") as span:
        span.set_attribute("rows", 5)
        span.add_event("checkpoint")
    assert captured[0].status == "ok"
    assert captured[0].attributes["rows"] == 5
    assert captured[0].duration_ms is not None


def test_tracer_records_exception() -> None:
    captured: list = []
    tracer = Tracer(exporter=captured.append)
    with pytest.raises(ValueError), tracer.start_span("boom"):
        raise ValueError("x")
    assert captured[0].status == "error"
    assert captured[0].attributes["error_type"] == "ValueError"
