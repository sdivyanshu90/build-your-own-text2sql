"""Unit tests for the parser and normalizer."""

from __future__ import annotations

import pytest

from text_to_sql.common.errors import SQLParseError
from text_to_sql.domain.enums import SQLDialect, StatementType
from text_to_sql.sql.normalizer import enforce_limit, normalize_sql, transpile_sql
from text_to_sql.sql.parser import classify_statement, parse_statements

pytestmark = pytest.mark.unit
D = SQLDialect.SQLITE


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("SELECT 1", StatementType.SELECT),
        ("SELECT a FROM t UNION SELECT b FROM u", StatementType.UNION),
        ("DELETE FROM t", StatementType.DELETE),
        ("UPDATE t SET a=1", StatementType.UPDATE),
        ("INSERT INTO t VALUES (1)", StatementType.INSERT),
        ("DROP TABLE t", StatementType.DROP),
        ("TRUNCATE t", StatementType.TRUNCATE),
        ("GRANT SELECT ON t TO u", StatementType.GRANT),
    ],
)
def test_classify_statement(sql: str, expected: StatementType) -> None:
    stmt = parse_statements(sql, D)[0]
    assert classify_statement(stmt) == expected


def test_parse_multiple_statements() -> None:
    stmts = parse_statements("SELECT 1; SELECT 2", D)
    assert len(stmts) == 2


def test_parse_empty_raises() -> None:
    with pytest.raises(SQLParseError):
        parse_statements(";", D)


def test_read_only_property() -> None:
    assert StatementType.SELECT.is_read_only
    assert not StatementType.DELETE.is_read_only


def test_enforce_limit_adds_when_missing() -> None:
    expr = parse_statements("SELECT id FROM orders", D)[0]
    outcome = enforce_limit(expr, 100)
    assert outcome.applied
    assert "LIMIT 100" in normalize_sql(outcome.expression, D, pretty=False)


def test_enforce_limit_caps_when_too_large() -> None:
    expr = parse_statements("SELECT id FROM orders LIMIT 100000", D)[0]
    outcome = enforce_limit(expr, 1000)
    assert outcome.capped
    assert outcome.effective_limit == 1000


def test_enforce_limit_keeps_smaller_existing() -> None:
    expr = parse_statements("SELECT id FROM orders LIMIT 10", D)[0]
    outcome = enforce_limit(expr, 1000)
    assert not outcome.applied and not outcome.capped
    assert outcome.effective_limit == 10


def test_enforce_limit_does_not_mutate_input() -> None:
    expr = parse_statements("SELECT id FROM orders", D)[0]
    _ = enforce_limit(expr, 50)
    assert expr.args.get("limit") is None  # original untouched


def test_transpile_between_dialects() -> None:
    out = transpile_sql(
        "SELECT strftime('%Y', ordered_at) FROM orders",
        SQLDialect.SQLITE,
        SQLDialect.POSTGRES,
    )
    assert isinstance(out, str) and "orders" in out


def test_transpile_invalid_raises() -> None:
    with pytest.raises(SQLParseError):
        transpile_sql("SELECT FROM", SQLDialect.SQLITE, SQLDialect.POSTGRES)
