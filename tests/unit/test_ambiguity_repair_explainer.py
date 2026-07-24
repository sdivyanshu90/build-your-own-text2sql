"""Unit tests for ambiguity detection, repair planning, and explanation."""

from __future__ import annotations

import pytest

from text_to_sql.application.ambiguity import AmbiguityDetector
from text_to_sql.application.explainer import ResultExplainer
from text_to_sql.application.repair import RepairPlanner
from text_to_sql.domain.enums import AmbiguityCategory
from text_to_sql.domain.models import ValidationIssue
from text_to_sql.execution.executor import ExecutionResult
from text_to_sql.semantic.models import SemanticLayer

pytestmark = pytest.mark.unit


# --- Ambiguity ------------------------------------------------------------ #
@pytest.fixture
def detector(semantic: SemanticLayer) -> AmbiguityDetector:
    return AmbiguityDetector(semantic)


@pytest.mark.parametrize(
    "question,category",
    [
        ("Who are our top customers?", AmbiguityCategory.MEASURE_UNSPECIFIED),
        ("Show me churn", AmbiguityCategory.UNKNOWN_TERM),
        ("Show sales", AmbiguityCategory.METRIC_DEFINITION),
        ("What is revenue by users?", AmbiguityCategory.ENTITY_REFERENCE),
    ],
)
def test_detects_ambiguity(
    detector: AmbiguityDetector, question: str, category: AmbiguityCategory
) -> None:
    clar = detector.detect(question)
    assert clar is not None
    assert clar.category == category
    assert clar.suggested_question
    assert clar.interpretations


@pytest.mark.parametrize(
    "question",
    [
        "What were our top five products by revenue last quarter?",
        "Show revenue by region",
        "How many orders were placed last month?",
        "list all products",
    ],
)
def test_no_false_positive_ambiguity(detector: AmbiguityDetector, question: str) -> None:
    assert detector.detect(question) is None


# --- Repair planner ------------------------------------------------------- #
def _issue(code: str) -> ValidationIssue:
    return ValidationIssue(code=code, message=code)


def test_repairable_correctness_issue() -> None:
    planner = RepairPlanner()
    assert planner.is_repairable([_issue("unknown_column")])
    assert planner.is_repairable([_issue("select_star_forbidden")])


def test_security_issue_not_repairable() -> None:
    planner = RepairPlanner()
    assert not planner.is_repairable([_issue("forbidden_statement")])
    assert not planner.is_repairable([_issue("column_denied")])
    # A single security issue poisons the whole set even with a repairable one.
    assert not planner.is_repairable([_issue("unknown_column"), _issue("forbidden_statement")])


def test_no_issues_not_repairable() -> None:
    assert not RepairPlanner().is_repairable([])


def test_sanitized_feedback_dedupes_and_filters() -> None:
    planner = RepairPlanner()
    feedback = planner.sanitized_feedback([_issue("unknown_column"), _issue("unknown_column")])
    assert len(feedback) == 1


# --- Explainer ------------------------------------------------------------ #
def test_explain_scalar() -> None:
    result = ExecutionResult(
        columns=["revenue"], rows=[[1234.5]], row_count=1, truncated=False, duration_ms=1
    )
    text, warnings = ResultExplainer().explain(
        question="revenue",
        result=result,
        assumptions=["Revenue=..."],
        confidence=0.9,
        truncated_note=False,
    )
    assert "revenue" in text
    assert "1,234" in text
    assert warnings == []


def test_explain_zero_rows() -> None:
    result = ExecutionResult(columns=["id"], rows=[], row_count=0, truncated=False, duration_ms=1)
    text, _ = ResultExplainer().explain(
        question="q", result=result, assumptions=[], confidence=0.9, truncated_note=False
    )
    assert "no matching rows" in text.lower()


def test_explain_warns_on_truncation_and_low_confidence() -> None:
    result = ExecutionResult(
        columns=["a", "b"], rows=[["x", 1]], row_count=1, truncated=True, duration_ms=1
    )
    _, warnings = ResultExplainer().explain(
        question="q", result=result, assumptions=[], confidence=0.2, truncated_note=True
    )
    assert any("truncated" in w.lower() for w in warnings)
    assert any("confidence" in w.lower() for w in warnings)
