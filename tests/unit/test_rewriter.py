"""Unit tests for tenant-predicate AST rewriting."""

from __future__ import annotations

import pytest

from text_to_sql.domain.enums import SQLDialect
from text_to_sql.domain.schema_models import DatabaseSchema
from text_to_sql.security.rewriter import TenantRewriter
from text_to_sql.sql.normalizer import normalize_sql
from text_to_sql.sql.parser import parse_statements

pytestmark = pytest.mark.unit
D = SQLDialect.SQLITE


def _rewrite(sql: str, schema: DatabaseSchema, tenant: str = "1") -> tuple[str, list[str]]:
    expr = parse_statements(sql, D)[0]
    new_expr, applied = TenantRewriter().rewrite(expr, schema, tenant)
    return normalize_sql(new_expr, D, pretty=False), applied


def test_single_table_gets_predicate(schema: DatabaseSchema) -> None:
    sql, applied = _rewrite("SELECT id FROM orders", schema)
    assert "orders.organization_id = 1" in sql
    assert applied == ["orders.organization_id = 1"]


def test_join_scopes_every_tenant_table(schema: DatabaseSchema) -> None:
    sql, applied = _rewrite(
        "SELECT o.id FROM orders o JOIN customers c ON c.id = o.customer_id", schema
    )
    assert "o.organization_id = 1" in sql
    assert "c.organization_id = 1" in sql
    assert len(applied) == 2


def test_subquery_scope_is_isolated(schema: DatabaseSchema) -> None:
    sql, _ = _rewrite(
        "SELECT c.id FROM customers c WHERE NOT EXISTS "
        "(SELECT 1 FROM orders o WHERE o.customer_id = c.id)",
        schema,
    )
    # Both the outer customers and the inner orders are scoped in their own scope.
    assert "c.organization_id = 1" in sql
    assert "o.organization_id = 1" in sql


def test_non_tenant_table_not_scoped(schema: DatabaseSchema) -> None:
    sql, applied = _rewrite("SELECT name FROM regions", schema)
    assert "organization_id" not in sql
    assert applied == []


def test_string_tenant_uses_string_literal(schema: DatabaseSchema) -> None:
    sql, _ = _rewrite("SELECT id FROM orders", schema, tenant="acme")
    assert "orders.organization_id = 'acme'" in sql


def test_rewrite_does_not_mutate_original(schema: DatabaseSchema) -> None:
    expr = parse_statements("SELECT id FROM orders", D)[0]
    TenantRewriter().rewrite(expr, schema, "1")
    assert "organization_id" not in normalize_sql(expr, D, pretty=False)
