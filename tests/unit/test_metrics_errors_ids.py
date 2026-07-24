"""Unit tests for metrics, error hierarchy, and id helpers."""

from __future__ import annotations

import pytest

from text_to_sql.common.errors import (
    AuthorizationError,
    EngineError,
    ErrorCategory,
    ProviderTimeoutError,
    SQLValidationError,
)
from text_to_sql.common.ids import (
    new_correlation_id,
    new_request_id,
    sanitize_correlation_id,
)
from text_to_sql.observability.metrics import MetricsRegistry

pytestmark = pytest.mark.unit


# --- Metrics -------------------------------------------------------------- #
def test_counter_render() -> None:
    reg = MetricsRegistry()
    reg.inc("requests_total", 1.0, stage="gen")
    reg.inc("requests_total", 2.0, stage="gen")
    text = reg.render()
    assert 'requests_total{stage="gen"} 3.0' in text
    assert "# TYPE requests_total counter" in text


def test_histogram_render_buckets() -> None:
    reg = MetricsRegistry()
    for v in (2, 40, 900):
        reg.observe("latency_ms", v)
    text = reg.render()
    assert "latency_ms_bucket" in text
    assert "latency_ms_count" in text
    assert 'le="+Inf"' in text


def test_metrics_reset() -> None:
    reg = MetricsRegistry()
    reg.inc("x", 1.0)
    reg.reset()
    assert "x " not in reg.render()


# --- Errors --------------------------------------------------------------- #
def test_error_public_dict_is_safe() -> None:
    err = SQLValidationError("bad", details={"issues": []}, remediation="fix it")
    d = err.to_public_dict()
    assert d["code"] == "sql_validation_failed"
    assert d["category"] == ErrorCategory.VALIDATION.value
    assert d["retryable"] is False
    assert d["remediation"] == "fix it"


def test_error_status_and_retryability() -> None:
    assert AuthorizationError("x").http_status == 403
    assert ProviderTimeoutError("x").retryable is True
    assert EngineError("x").http_status == 500


# --- IDs ------------------------------------------------------------------ #
def test_new_ids_are_unique_and_prefixed() -> None:
    assert new_request_id().startswith("req_")
    assert new_correlation_id().startswith("corr_")
    assert new_request_id() != new_request_id()


def test_sanitize_correlation_id_strips_bad_chars() -> None:
    out = sanitize_correlation_id("abc\n123 evil;rm -rf")
    assert "\n" not in out and " " not in out and ";" not in out


def test_sanitize_correlation_id_generates_when_empty() -> None:
    assert sanitize_correlation_id(None).startswith("corr_")
    assert sanitize_correlation_id("").startswith("corr_")
    assert sanitize_correlation_id("!!!").startswith("corr_")  # all stripped => new
