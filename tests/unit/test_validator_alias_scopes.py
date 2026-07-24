"""Regression tests: table aliases reused across scopes.

Found by running the engine against a live model. Gemini produced a multi-CTE
query that used ``refunds AS r`` inside a CTE and ``regions AS r`` in the outer
query — both legal, because an alias is only unique *within* a scope. The
validator kept one global alias→table map, so ``r`` resolved to whichever table
was seen last and ``r.name`` was reported as an unknown column, failing valid SQL.

The fix maps an alias to the SET of tables it may denote and accepts a column if
ANY candidate defines it, while recording EVERY matching candidate so the policy
engine still sees the strictest set of base columns.
"""

from __future__ import annotations

import pytest

from text_to_sql.domain.context import AuthContext
from text_to_sql.domain.enums import SQLDialect
from text_to_sql.domain.schema_models import DatabaseSchema
from text_to_sql.security.config import SecurityPolicyConfig
from text_to_sql.security.policy import PolicyEngine
from text_to_sql.sql.validator import SQLValidator

pytestmark = pytest.mark.unit
D = SQLDialect.SQLITE

# Shape of the real query that exposed the bug.
REUSED_ALIAS_SQL = """
WITH OrderRefunds AS (
    SELECT r.order_id, SUM(r.amount) AS refund_amount
    FROM refunds AS r
    GROUP BY r.order_id
)
SELECT r.name AS region,
       SUM(oi.quantity * oi.unit_price) - COALESCE(SUM(orf.refund_amount), 0) AS revenue
FROM order_items AS oi
JOIN orders AS o ON o.id = oi.order_id
JOIN customers AS c ON c.id = o.customer_id
JOIN regions AS r ON r.id = c.region_id
LEFT JOIN OrderRefunds AS orf ON orf.order_id = o.id
GROUP BY r.name
"""


def test_alias_reused_across_scopes_is_valid(schema: DatabaseSchema) -> None:
    outcome = SQLValidator().validate(REUSED_ALIAS_SQL, D, schema)
    assert outcome.is_valid, [(i.code, i.message) for i in outcome.issues]


def test_alias_reuse_records_both_base_columns(schema: DatabaseSchema) -> None:
    """`r.order_id` exists on refunds; `r.name` on regions — both are recorded."""
    outcome = SQLValidator().validate(REUSED_ALIAS_SQL, D, schema)
    assert "regions.name" in outcome.referenced_columns
    assert "refunds.order_id" in outcome.referenced_columns


def test_genuinely_unknown_column_still_rejected(schema: DatabaseSchema) -> None:
    sql = "SELECT r.definitely_not_a_column FROM regions AS r"
    outcome = SQLValidator().validate(sql, D, schema)
    assert not outcome.is_valid
    assert any(i.code == "unknown_column" for i in outcome.issues)


def test_alias_reuse_does_not_weaken_column_policy(schema: DatabaseSchema) -> None:
    """Over-reporting candidates must make policy stricter, never laxer.

    `u.email` with `u` bound to both `users` (PII) and `regions` must still be
    denied for a role without PII access.
    """
    sql = (
        "WITH ru AS (SELECT u.id FROM regions AS u) "
        "SELECT u.email FROM users AS u JOIN ru ON ru.id = u.id"
    )
    outcome = SQLValidator().validate(sql, D, schema)
    assert "users.email" in outcome.referenced_columns
    decision = PolicyEngine(SecurityPolicyConfig()).enforce(
        outcome.referenced_tables,
        outcome.referenced_columns,
        schema,
        AuthContext(user_id="a", tenant_id="1", roles=("analyst",)),
    )
    assert not decision.allowed
    assert any(i.code == "column_denied" for i in decision.issues)
