"""Unit tests for the AST SQL validator — the primary safety gate."""

from __future__ import annotations

import pytest

from text_to_sql.common.errors import SQLParseError
from text_to_sql.domain.enums import SQLDialect
from text_to_sql.domain.schema_models import DatabaseSchema
from text_to_sql.sql.validator import SQLValidator

pytestmark = pytest.mark.unit

DIALECT = SQLDialect.SQLITE


@pytest.fixture
def validator() -> SQLValidator:
    return SQLValidator()


def codes(validator: SQLValidator, sql: str, schema: DatabaseSchema) -> set[str]:
    return {i.code for i in validator.validate(sql, DIALECT, schema).issues}


def test_valid_select_passes(validator: SQLValidator, schema: DatabaseSchema) -> None:
    out = validator.validate(
        "SELECT products.name FROM products WHERE products.active = 1 LIMIT 5",
        DIALECT,
        schema,
    )
    assert out.is_valid
    assert out.referenced_tables == ["products"]
    assert "products.name" in out.referenced_columns


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("DROP TABLE users", "forbidden_statement"),
        ("DELETE FROM orders", "forbidden_statement"),
        ("UPDATE users SET role='a'", "forbidden_statement"),
        ("INSERT INTO users(email) VALUES ('x')", "forbidden_statement"),
        ("TRUNCATE users", "forbidden_statement"),
        ("ALTER TABLE users ADD COLUMN x int", "forbidden_statement"),
        ("CREATE TABLE t (id int)", "forbidden_statement"),
        ("GRANT SELECT ON users TO bob", "forbidden_statement"),
    ],
)
def test_destructive_statements_rejected(
    validator: SQLValidator, schema: DatabaseSchema, sql: str, expected: str
) -> None:
    assert expected in codes(validator, sql, schema)


def test_multiple_statements_rejected(validator: SQLValidator, schema: DatabaseSchema) -> None:
    assert "multiple_statements" in codes(
        validator, "SELECT id FROM users; DROP TABLE users", schema
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM users -- drop everything",
        "SELECT id /* hidden */ FROM users",
    ],
)
def test_comments_rejected(validator: SQLValidator, schema: DatabaseSchema, sql: str) -> None:
    assert "comment_present" in codes(validator, sql, schema)


def test_select_star_rejected(validator: SQLValidator, schema: DatabaseSchema) -> None:
    assert "select_star_forbidden" in codes(validator, "SELECT * FROM users", schema)


def test_count_star_allowed(validator: SQLValidator, schema: DatabaseSchema) -> None:
    out = validator.validate("SELECT COUNT(*) AS c FROM users", DIALECT, schema)
    assert out.is_valid


def test_unknown_table_and_column(validator: SQLValidator, schema: DatabaseSchema) -> None:
    assert "unknown_table" in codes(validator, "SELECT id FROM ghosts", schema)
    assert "unknown_column" in codes(validator, "SELECT nope FROM users", schema)


@pytest.mark.parametrize(
    "sql",
    ["SELECT id, pg_sleep(5) FROM users", "SELECT load_extension('x')"],
)
def test_denied_functions(validator: SQLValidator, schema: DatabaseSchema, sql: str) -> None:
    assert "denied_function" in codes(validator, sql, schema)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT name FROM sqlite_master",
        "SELECT table_name FROM information_schema.tables",
    ],
)
def test_system_catalogs_rejected(
    validator: SQLValidator, schema: DatabaseSchema, sql: str
) -> None:
    assert "system_catalog_access" in codes(validator, sql, schema)


def test_alias_and_order_by_alias_allowed(validator: SQLValidator, schema: DatabaseSchema) -> None:
    sql = (
        "SELECT products.name AS product, "
        "SUM(order_items.quantity * order_items.unit_price) AS revenue "
        "FROM order_items JOIN products ON products.id = order_items.product_id "
        "GROUP BY products.name ORDER BY revenue DESC LIMIT 5"
    )
    out = validator.validate(sql, DIALECT, schema)
    assert out.is_valid, [i.code for i in out.issues]


def test_cte_is_read_only_and_valid(validator: SQLValidator, schema: DatabaseSchema) -> None:
    sql = "WITH t AS (SELECT id FROM orders) SELECT id FROM t LIMIT 5"
    out = validator.validate(sql, DIALECT, schema)
    assert out.is_valid


def test_parse_failure_raises(validator: SQLValidator, schema: DatabaseSchema) -> None:
    with pytest.raises(SQLParseError):
        validator.validate("SELECT FROM WHERE", DIALECT, schema)


def test_cte_hides_base_columns_but_inner_reference_resolved(
    validator: SQLValidator, schema: DatabaseSchema
) -> None:
    # Inner reference to users.email is resolved even though it's laundered via a CTE.
    sql = "WITH t AS (SELECT users.email FROM users) SELECT email FROM t LIMIT 5"
    out = validator.validate(sql, DIALECT, schema)
    assert "users.email" in out.referenced_columns
