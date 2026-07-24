"""Query cost & complexity controls.

Two layers of defense against expensive/denial-of-service queries:

1. **AST heuristics** (dialect-independent, always available): join count,
   subquery-nesting depth, projected-column count, and Cartesian-product / cross-
   join detection. Exceeding a configured threshold is a hard rejection.
2. **Planner estimate** (optional, PostgreSQL): a safe ``EXPLAIN`` (never
   ``EXPLAIN ANALYZE`` — the query is *not executed*) yields estimated rows and
   total cost, which classify risk and can reject very large scans.

Limitations (documented in ``docs/security/query_cost.md``): planner estimates are
approximate and can be wrong for skewed data or missing statistics; SQLite does
not expose comparable estimates, so there we rely on the AST heuristics alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Engine, text
from sqlglot import exp

from text_to_sql.domain.enums import RiskLevel, SQLDialect
from text_to_sql.domain.models import ValidationIssue
from text_to_sql.observability.logging import get_logger
from text_to_sql.security.config import SecurityPolicyConfig

_log = get_logger(__name__)


@dataclass
class CostReport:
    """Result of cost analysis."""

    allowed: bool
    risk_level: RiskLevel
    join_count: int
    subquery_depth: int
    selected_columns: int
    estimated_rows: float | None = None
    estimated_cost: float | None = None
    issues: list[ValidationIssue] = field(default_factory=list)

    def _reject(self, code: str, message: str) -> None:
        self.allowed = False
        self.risk_level = RiskLevel.HIGH
        self.issues.append(ValidationIssue(code=code, message=message))


class CostAnalyzer:
    """Estimates query cost/complexity and classifies risk."""

    def __init__(self, config: SecurityPolicyConfig) -> None:
        self._config = config

    def analyze(
        self,
        expression: exp.Expression,
        sql_text: str,
        dialect: SQLDialect,
        engine: Engine | None = None,
    ) -> CostReport:
        join_count = len(list(expression.find_all(exp.Join)))
        depth = _max_select_depth(expression)
        selected = _projected_column_count(expression)

        report = CostReport(
            allowed=True,
            risk_level=RiskLevel.LOW,
            join_count=join_count,
            subquery_depth=depth,
            selected_columns=selected,
        )

        # --- AST hard limits ---------------------------------------------
        if join_count > self._config.max_joins:
            report._reject(
                "too_many_joins",
                f"Query has {join_count} joins; limit is {self._config.max_joins}.",
            )
        if depth > self._config.max_subquery_depth:
            report._reject(
                "subquery_too_deep",
                f"Subquery nesting depth {depth} exceeds limit {self._config.max_subquery_depth}.",
            )
        if selected > self._config.max_selected_columns:
            report._reject(
                "too_many_columns",
                f"Query projects {selected} columns; limit is {self._config.max_selected_columns}.",
            )
        if _has_cartesian_product(expression):
            report._reject(
                "cartesian_product",
                "Query contains a cross join / Cartesian product without a join condition.",
            )

        # --- Planner estimate (Postgres only, safe EXPLAIN) --------------
        if engine is not None and dialect == SQLDialect.POSTGRES:
            self._estimate_with_explain(sql_text, engine, report)

        # --- Final risk classification -----------------------------------
        if report.allowed:
            report.risk_level = self._classify_risk(report)
            if (
                report.estimated_rows is not None
                and report.estimated_rows >= self._config.cost_rows_high_threshold
            ):
                report._reject(
                    "estimated_cost_too_high",
                    f"Estimated result size (~{int(report.estimated_rows)} rows) "
                    f"exceeds the configured maximum.",
                )
        return report

    # ------------------------------------------------------------------ #
    def _estimate_with_explain(self, sql: str, engine: Engine, report: CostReport) -> None:
        # EXPLAIN (no ANALYZE) does not execute the query.
        explain_sql = f"EXPLAIN (FORMAT JSON) {sql}"
        try:
            with engine.connect() as conn:
                row = conn.execute(text(explain_sql)).scalar()
        except Exception as exc:
            _log.warning("explain_failed", error=str(exc)[:200])
            return
        if row is None:
            return
        try:
            plan = row[0]["Plan"] if isinstance(row, list) else row["Plan"]
            report.estimated_rows = float(plan.get("Plan Rows", 0))
            report.estimated_cost = float(plan.get("Total Cost", 0))
        except (KeyError, IndexError, TypeError):
            _log.warning("explain_parse_failed")

    def _classify_risk(self, report: CostReport) -> RiskLevel:
        rows = report.estimated_rows
        if rows is not None:
            if rows >= self._config.cost_rows_high_threshold:
                return RiskLevel.HIGH
            if rows >= self._config.cost_rows_medium_threshold:
                return RiskLevel.MEDIUM
            return RiskLevel.LOW
        # No estimate: fall back to structural heuristics.
        if report.join_count >= max(1, self._config.max_joins - 1) or report.subquery_depth >= max(
            1, self._config.max_subquery_depth - 1
        ):
            return RiskLevel.MEDIUM
        return RiskLevel.LOW


def _max_select_depth(expression: exp.Expression) -> int:
    """Maximum SELECT nesting depth in the tree."""
    max_depth = 0
    for node in expression.find_all(exp.Select):
        depth = 1
        ancestor = node.parent
        while ancestor is not None:
            if isinstance(ancestor, exp.Select):
                depth += 1
            ancestor = ancestor.parent
        max_depth = max(max_depth, depth)
    return max_depth or 1


def _projected_column_count(expression: exp.Expression) -> int:
    """Number of projected expressions in the outermost SELECT."""
    select = expression if isinstance(expression, exp.Select) else expression.find(exp.Select)
    if select is None:
        return 0
    return len(select.expressions)


def _has_cartesian_product(expression: exp.Expression) -> bool:
    """Detect cross joins / comma joins lacking a join condition."""
    for join in expression.find_all(exp.Join):
        kind = (join.kind or "").upper()
        side = (join.side or "").upper()
        if kind == "CROSS":
            return True
        # A join with neither ON nor USING and not an explicit CROSS is implicit
        # Cartesian (except NATURAL joins, which carry their own condition).
        has_condition = join.args.get("on") is not None or join.args.get("using") is not None
        is_natural = "NATURAL" in kind or "NATURAL" in side
        if not has_condition and not is_natural:
            return True
    return False
