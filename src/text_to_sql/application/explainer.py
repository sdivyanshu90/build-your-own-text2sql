"""Grounded result explanation.

The natural-language answer is generated **deterministically from the actual
result set**, not by asking the LLM to narrate (which risks hallucinating facts
not in the data). This guarantees the requirement that explanations are "grounded
only in returned query results" and "must not invent facts."

The explanation explicitly separates:

* **database-derived facts** (row counts, concrete top values),
* **system assumptions** (e.g. how revenue / a date range was interpreted),
* **warnings and limitations** (truncation, low confidence, sensitive data).

Values are passed through the redactor as defense-in-depth even though policy
already prevents sensitive columns from being selected.
"""

from __future__ import annotations

from typing import Any

from text_to_sql.common.redaction import redact_text
from text_to_sql.execution.executor import ExecutionResult


class ResultExplainer:
    """Builds a factual, result-grounded explanation and warnings."""

    def explain(
        self,
        *,
        question: str,
        result: ExecutionResult,
        assumptions: list[str],
        confidence: float,
        truncated_note: bool,
    ) -> tuple[str, list[str]]:
        facts = self._facts(result)
        parts: list[str] = [facts]
        if assumptions:
            parts.append("Assumptions: " + "; ".join(assumptions) + ".")
        explanation = " ".join(parts)

        warnings: list[str] = []
        if truncated_note or result.truncated:
            warnings.append(
                f"Results were truncated to {result.row_count} rows; refine the "
                "question or add filters to see the full set."
            )
        if confidence < 0.5:
            warnings.append("Low generation confidence — verify the SQL matches your intent.")
        return explanation, warnings

    # ------------------------------------------------------------------ #
    def _facts(self, result: ExecutionResult) -> str:
        n = result.row_count
        if n == 0:
            return "The query returned no matching rows."

        # Single scalar (1 row, 1 column): report the value directly.
        if n == 1 and len(result.columns) == 1:
            value = _fmt(result.rows[0][0])
            return f"The result is {result.columns[0]} = {value}."

        # Two-column aggregate/ranking: surface the leading rows.
        if len(result.columns) == 2 and n <= 100:
            label_col, value_col = result.columns
            preview = ", ".join(f"{_fmt(row[0])}: {_fmt(row[1])}" for row in result.rows[:5])
            more = "" if n <= 5 else f" (and {n - 5} more)"
            return f"Returned {n} rows of {value_col} by {label_col}. Top: {preview}{more}."

        cols = ", ".join(result.columns)
        return f"Returned {n} rows with columns: {cols}."


def _fmt(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float):
        # Trim trailing zeros for readability.
        return f"{value:,.2f}".rstrip("0").rstrip(".") if value % 1 else f"{int(value):,}"
    if isinstance(value, int):
        return f"{value:,}"
    return redact_text(str(value))
