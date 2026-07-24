"""SQL normalization, LIMIT enforcement, and dialect transpilation.

* :func:`normalize_sql` renders an AST back to canonical, pretty SQL.
* :func:`enforce_limit` guarantees a bounded result set by injecting or capping a
  top-level ``LIMIT`` — the deterministic defense against unbounded queries.
* :func:`transpile_sql` converts SQL between dialects (dialect-confusion defense
  and cross-dialect support).
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from text_to_sql.common.errors import SQLParseError
from text_to_sql.domain.enums import SQLDialect


def normalize_sql(expression: exp.Expression, dialect: SQLDialect, *, pretty: bool = True) -> str:
    """Render an expression to canonical SQL for the given dialect."""
    return expression.sql(dialect=dialect.sqlglot_name, pretty=pretty)


@dataclass
class LimitOutcome:
    expression: exp.Expression
    applied: bool  # a LIMIT was added where none existed
    capped: bool  # an existing LIMIT exceeded max and was reduced
    effective_limit: int


def enforce_limit(expression: exp.Expression, max_rows: int) -> LimitOutcome:
    """Ensure the top-level query has a ``LIMIT`` no greater than ``max_rows``.

    Works on a copy so the caller's expression is untouched until it chooses to
    adopt the result (which is then re-validated).
    """
    expr = expression.copy()

    if not isinstance(expr, (exp.Select, exp.Union, exp.Subquery, exp.Intersect, exp.Except)):
        # Non-query expressions never reach here in practice (validator blocks
        # them first); return unchanged.
        return LimitOutcome(expr, applied=False, capped=False, effective_limit=max_rows)

    existing = expr.args.get("limit")
    current_value = _limit_value(existing)

    if current_value is None:
        limited = expr.limit(max_rows)
        return LimitOutcome(limited, applied=True, capped=False, effective_limit=max_rows)

    if current_value > max_rows:
        limited = expr.limit(max_rows)
        return LimitOutcome(limited, applied=False, capped=True, effective_limit=max_rows)

    return LimitOutcome(expr, applied=False, capped=False, effective_limit=current_value)


def _limit_value(limit_node: exp.Expression | None) -> int | None:
    """Extract an integer literal limit value, or ``None`` if absent/dynamic."""
    if limit_node is None:
        return None
    inner = limit_node.expression if isinstance(limit_node, exp.Limit) else limit_node
    if isinstance(inner, exp.Literal) and inner.is_int:
        return int(inner.name)
    # Non-literal (parameter/expression) limit: treat as "unknown", force cap.
    return None if inner is None else 10**12


def transpile_sql(sql: str, read: SQLDialect, write: SQLDialect) -> str:
    """Transpile SQL from one dialect to another."""
    try:
        out = sqlglot.transpile(sql, read=read.sqlglot_name, write=write.sqlglot_name)
    except ParseError as exc:
        raise SQLParseError(
            "SQL could not be transpiled between dialects.",
            details={"reason": str(exc).splitlines()[0][:200]},
        ) from exc
    return out[0] if out else sql
