"""Mandatory tenant-predicate injection via AST rewriting.

Tenant isolation must never depend on the LLM (or the user) including the right
filter. This rewriter walks the *parsed* query and, for every base table that has
a tenant column, ANDs a predicate ``<alias>.<tenant_column> = <tenant_id>`` into
the ``WHERE`` of the exact SELECT scope that owns that table.

Two properties make this safe:

1. **AST, not strings.** The predicate is built from ``sqlglot`` expression nodes
   and the literal is a typed literal node — there is no string concatenation of
   user/tenant input into SQL text, so it cannot be broken out of.
2. **Per-scope.** Because scoping is anchored to each table's enclosing SELECT,
   subqueries and CTEs that read base tables are scoped too. A join, a correlated
   ``NOT EXISTS``, or a CTE cannot smuggle another tenant's rows.

After rewriting, the orchestrator re-runs full validation on the rewritten AST.
"""

from __future__ import annotations

from sqlglot import exp

from text_to_sql.domain.schema_models import DatabaseSchema


class TenantRewriter:
    """Injects mandatory tenant predicates into a parsed query."""

    def __init__(self, tenant_column_default: str = "organization_id") -> None:
        self._default_column = tenant_column_default

    def rewrite(
        self,
        expression: exp.Expression,
        schema: DatabaseSchema,
        tenant_id: str,
    ) -> tuple[exp.Expression, list[str]]:
        """Return a tenant-scoped copy of ``expression`` and the rewrites applied."""
        expr = expression.copy()
        applied: list[str] = []

        # Collect (select_scope, table, column) first, then mutate, so we never
        # modify the tree while walking it.
        targets: list[tuple[exp.Select, exp.Table, str]] = []
        for table in expr.find_all(exp.Table):
            info = schema.table(table.name)
            if info is None or not info.tenant_column:
                continue
            scope = table.find_ancestor(exp.Select)
            if scope is None:
                continue
            targets.append((scope, table, info.tenant_column))

        for scope, table, tenant_column in targets:
            qualifier = table.alias or table.name
            predicate = self._build_predicate(qualifier, tenant_column, tenant_id)
            scope.where(predicate, append=True, copy=False)
            applied.append(f"{qualifier}.{tenant_column} = {tenant_id}")

        return expr, applied

    @staticmethod
    def _build_predicate(qualifier: str, column: str, tenant_id: str) -> exp.Expression:
        col = exp.column(column, table=qualifier)
        # Typed literal node — not string concatenation into SQL text.
        if tenant_id.isdigit():
            literal: exp.Expression = exp.Literal.number(tenant_id)
        else:
            literal = exp.Literal.string(tenant_id)
        return exp.EQ(this=col, expression=literal)
