"""Unit tests for the policy engine, classification, and cost analyzer."""

from __future__ import annotations

import pytest

from text_to_sql.domain.context import AuthContext
from text_to_sql.domain.enums import DataClassification, RiskLevel, SQLDialect
from text_to_sql.domain.schema_models import DatabaseSchema
from text_to_sql.security.classification import ColumnAccessPolicy
from text_to_sql.security.config import SecurityPolicyConfig
from text_to_sql.security.cost import CostAnalyzer
from text_to_sql.security.policy import PolicyEngine
from text_to_sql.sql.parser import parse_statements
from text_to_sql.sql.validator import SQLValidator

pytestmark = pytest.mark.unit
D = SQLDialect.SQLITE


# --- Classification ------------------------------------------------------- #
@pytest.mark.parametrize(
    "classification,roles,expected",
    [
        (DataClassification.PUBLIC, ("viewer",), True),
        (DataClassification.INTERNAL, ("viewer",), True),
        (DataClassification.FINANCIAL, ("viewer",), False),
        (DataClassification.FINANCIAL, ("analyst",), True),
        (DataClassification.FINANCIAL, ("viewer", "finance_read"), True),
        (DataClassification.PII, ("analyst",), False),
        (DataClassification.PII, ("admin",), True),
        (DataClassification.PII, ("viewer", "pii_read"), True),
        (DataClassification.AUTH_SECRET, ("admin",), False),
        (DataClassification.HIGHLY_RESTRICTED, ("admin",), False),
    ],
)
def test_column_access(
    classification: DataClassification, roles: tuple[str, ...], expected: bool
) -> None:
    assert ColumnAccessPolicy().can_view(classification, roles) is expected


# --- Policy engine -------------------------------------------------------- #
def _refs(sql: str, schema: DatabaseSchema) -> tuple[list[str], list[str]]:
    out = SQLValidator().validate(sql, D, schema)
    return out.referenced_tables, out.referenced_columns


def test_policy_denies_secret_for_everyone(schema: DatabaseSchema) -> None:
    engine = PolicyEngine(SecurityPolicyConfig())
    tables, cols = _refs("SELECT users.password_hash FROM users", schema)
    admin = AuthContext(user_id="a", tenant_id="1", roles=("admin", "pii_read"))
    decision = engine.enforce(tables, cols, schema, admin)
    assert not decision.allowed
    assert any(i.code == "column_denied" for i in decision.issues)


def test_policy_allows_internal_columns(schema: DatabaseSchema) -> None:
    engine = PolicyEngine(SecurityPolicyConfig())
    tables, cols = _refs("SELECT products.name FROM products", schema)
    viewer = AuthContext(user_id="v", tenant_id="1", roles=("viewer",))
    assert engine.enforce(tables, cols, schema, viewer).allowed


def test_policy_denied_table(schema: DatabaseSchema) -> None:
    cfg = SecurityPolicyConfig(denied_tables=frozenset({"payments"}))
    engine = PolicyEngine(cfg)
    tables, cols = _refs("SELECT payments.id FROM payments", schema)
    analyst = AuthContext(user_id="a", tenant_id="1", roles=("analyst",))
    decision = engine.enforce(tables, cols, schema, analyst)
    assert not decision.allowed
    assert any(i.code == "table_denied" for i in decision.issues)


# --- Cost analyzer -------------------------------------------------------- #
def _cost(sql: str, cfg: SecurityPolicyConfig | None = None):  # type: ignore[no-untyped-def]
    expr = parse_statements(sql, D)[0]
    return CostAnalyzer(cfg or SecurityPolicyConfig()).analyze(expr, sql, D)


def test_cost_cartesian_rejected() -> None:
    report = _cost("SELECT a.id FROM orders a CROSS JOIN customers b")
    assert not report.allowed
    assert report.risk_level is RiskLevel.HIGH


def test_cost_too_many_joins_rejected() -> None:
    cfg = SecurityPolicyConfig(max_joins=1)
    report = _cost(
        "SELECT o.id FROM orders o "
        "JOIN customers c ON c.id = o.customer_id "
        "JOIN regions r ON r.id = c.region_id",
        cfg,
    )
    assert not report.allowed
    assert any(i.code == "too_many_joins" for i in report.issues)


def test_cost_subquery_depth_rejected() -> None:
    cfg = SecurityPolicyConfig(max_subquery_depth=1)
    report = _cost(
        "SELECT id FROM orders WHERE customer_id IN "
        "(SELECT id FROM customers WHERE region_id IN (SELECT id FROM regions))",
        cfg,
    )
    assert not report.allowed


def test_cost_simple_query_low_risk() -> None:
    report = _cost("SELECT id FROM orders LIMIT 10")
    assert report.allowed
    assert report.risk_level is RiskLevel.LOW
