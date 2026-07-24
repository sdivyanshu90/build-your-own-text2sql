"""Unit tests for relative-date resolution."""

from __future__ import annotations

from datetime import datetime

import pytest

from text_to_sql.semantic.dates import resolve_relative_date

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 24)  # a Friday in Q3 2026


def test_last_quarter_is_previous_completed_quarter() -> None:
    r = resolve_relative_date("revenue last quarter", NOW)
    assert r is not None
    assert r.start == datetime(2026, 4, 1)
    assert r.end == datetime(2026, 7, 1)


def test_last_month() -> None:
    r = resolve_relative_date("orders last month", NOW)
    assert r is not None
    assert r.start == datetime(2026, 6, 1)
    assert r.end == datetime(2026, 7, 1)


def test_this_year_to_date() -> None:
    r = resolve_relative_date("signups this year", NOW)
    assert r is not None
    assert r.start == datetime(2026, 1, 1)
    assert r.end == NOW


def test_last_year() -> None:
    r = resolve_relative_date("revenue last year", NOW)
    assert r is not None
    assert r.start == datetime(2025, 1, 1)
    assert r.end == datetime(2026, 1, 1)


def test_last_n_days() -> None:
    r = resolve_relative_date("customers in the past 90 days", NOW)
    assert r is not None
    assert (NOW - r.start).days == 90
    assert r.end == NOW


def test_no_relative_phrase_returns_none() -> None:
    assert resolve_relative_date("show all products", NOW) is None


def test_sql_predicate_is_half_open() -> None:
    r = resolve_relative_date("last month", NOW)
    assert r is not None
    pred = r.as_sql_predicate("orders.ordered_at")
    assert ">=" in pred and "<" in pred
    assert "2026-06-01" in pred


def test_quarter_boundary_january() -> None:
    # In Q1, "last quarter" is Q4 of the previous year.
    r = resolve_relative_date("last quarter", datetime(2026, 2, 15))
    assert r is not None
    assert r.start == datetime(2025, 10, 1)
    assert r.end == datetime(2026, 1, 1)
