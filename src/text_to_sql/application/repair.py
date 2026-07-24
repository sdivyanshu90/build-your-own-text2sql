"""Bounded SQL repair planning.

The orchestrator runs the repair *loop*; this module decides two things safely:

* **Is a failure repairable by re-prompting?** Correctness failures (parse errors,
  unknown table/column, ``SELECT *``, a denied function the model can swap) are
  worth another attempt. *Security* failures (destructive/forbidden statements,
  multiple statements, comment smuggling, policy denials, cost rejections) are
  NOT — re-prompting a model that emitted ``DROP TABLE`` is pointless and could
  loop, so those are hard rejections.
* **What sanitized feedback goes back to the model?** Only stable, non-sensitive
  issue messages — never raw driver output or internal detail.

This keeps the loop bounded, prevents infinite retries, and never lets a repair
bypass a deterministic security decision.
"""

from __future__ import annotations

from text_to_sql.domain.models import ValidationIssue

# Issue codes worth another generation attempt (correctness, not security).
REPAIRABLE_CODES = frozenset(
    {
        "sql_parse_failed",
        "unknown_table",
        "unknown_column",
        "select_star_forbidden",
        "denied_function",
    }
)

# Codes that are deterministic security/policy decisions — never repaired.
NON_REPAIRABLE_CODES = frozenset(
    {
        "non_read_only_statement",
        "forbidden_statement",
        "multiple_statements",
        "comment_present",
        "system_catalog_access",
        "cross_database_access",
        "schema_not_allowed",
        "column_denied",
        "table_denied",
        "table_not_allowed",
        "cartesian_product",
        "too_many_joins",
        "subquery_too_deep",
        "too_many_columns",
        "estimated_cost_too_high",
    }
)


class RepairPlanner:
    """Decides repairability and builds sanitized repair feedback."""

    def is_repairable(self, issues: list[ValidationIssue]) -> bool:
        if not issues:
            return False
        # Repairable only if every issue is a correctness issue (no security issue
        # is present). One security issue makes the whole attempt a hard rejection.
        codes = {issue.code for issue in issues}
        if codes & NON_REPAIRABLE_CODES:
            return False
        return bool(codes & REPAIRABLE_CODES)

    def sanitized_feedback(self, issues: list[ValidationIssue]) -> tuple[str, ...]:
        """Stable, non-sensitive one-line hints for the next attempt."""
        feedback: list[str] = []
        for issue in issues:
            if issue.code in REPAIRABLE_CODES:
                feedback.append(f"{issue.code}: {issue.message}")
        return tuple(dict.fromkeys(feedback))  # dedupe, preserve order
