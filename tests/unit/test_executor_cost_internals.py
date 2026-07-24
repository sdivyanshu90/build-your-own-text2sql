"""Unit tests for executor value coercion, error mapping, and cost internals."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

from text_to_sql.domain.enums import SQLDialect
from text_to_sql.execution.executor import _classify_db_error, _to_jsonable
from text_to_sql.security.config import SecurityPolicyConfig
from text_to_sql.security.cost import (
    CostAnalyzer,
    _has_cartesian_product,
    _max_select_depth,
    _projected_column_count,
)
from text_to_sql.sql.parser import parse_statements

pytestmark = pytest.mark.unit
D = SQLDialect.SQLITE


# --- Executor helpers ----------------------------------------------------- #
@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (True, True),
        (5, 5),
        ("x", "x"),
        (Decimal("12.50"), 12.5),
    ],
)
def test_to_jsonable_primitives(value: object, expected: object) -> None:
    assert _to_jsonable(value) == expected


def test_to_jsonable_datetime_and_bytes() -> None:
    assert _to_jsonable(dt.datetime(2026, 1, 2, 3, 4)) == "2026-01-02T03:04:00"
    assert _to_jsonable(dt.date(2026, 1, 2)) == "2026-01-02"
    assert _to_jsonable(b"\x00\x01") == "«binary»"


def test_classify_db_error() -> None:
    assert (
        _classify_db_error(
            OperationalError("s", {}, Exception("canceling statement due to timeout"))
        )
        == "statement_timeout"
    )
    assert (
        _classify_db_error(
            OperationalError("s", {}, Exception("attempt to write a readonly database"))
        )
        == "read_only_violation"
    )
    assert (
        _classify_db_error(OperationalError("s", {}, Exception("near syntax error")))
        == "syntax_error"
    )
    assert _classify_db_error(OperationalError("s", {}, Exception("boom"))) == "database_error"


# --- Cost internals ------------------------------------------------------- #
def _e(sql: str):  # type: ignore[no-untyped-def]
    return parse_statements(sql, D)[0]


def test_max_select_depth() -> None:
    assert _max_select_depth(_e("SELECT id FROM orders")) == 1
    nested = _e("SELECT id FROM orders WHERE customer_id IN (SELECT id FROM customers)")
    assert _max_select_depth(nested) == 2


def test_projected_column_count() -> None:
    assert _projected_column_count(_e("SELECT a, b, c FROM orders")) == 3


def test_has_cartesian_product() -> None:
    assert _has_cartesian_product(_e("SELECT a.id FROM orders a CROSS JOIN customers b"))
    assert not _has_cartesian_product(
        _e("SELECT a.id FROM orders a JOIN customers b ON b.id = a.customer_id")
    )


def test_cost_medium_risk_from_join_heuristic() -> None:
    cfg = SecurityPolicyConfig(max_joins=3)
    sql = (
        "SELECT o.id FROM orders o "
        "JOIN customers c ON c.id = o.customer_id "
        "JOIN regions r ON r.id = c.region_id"
    )
    report = CostAnalyzer(cfg).analyze(_e(sql), sql, D)
    assert report.allowed
    assert report.risk_level.value == "medium"  # near the join limit
