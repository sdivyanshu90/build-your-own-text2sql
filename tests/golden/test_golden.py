"""Golden suite as pytest: every case passes and aggregate metrics meet gates."""

from __future__ import annotations

import pytest

from tests.golden.dataset import GOLDEN_CASES
from tests.golden.evaluator import compute_metrics, evaluate_case, scripted_provider
from text_to_sql.application.container import AppContainer

pytestmark = pytest.mark.golden


@pytest.fixture
def golden_container(make_container) -> AppContainer:  # type: ignore[no-untyped-def]
    return make_container(provider=scripted_provider(GOLDEN_CASES))


async def _run_all(container: AppContainer):  # type: ignore[no-untyped-def]
    return [await evaluate_case(container.orchestrator, case) for case in GOLDEN_CASES]


async def test_every_golden_case_passes(golden_container: AppContainer) -> None:
    results = await _run_all(golden_container)
    failures = {r.id: r.failures for r in results if not r.passed}
    assert not failures, f"golden failures: {failures}"


async def test_golden_metrics_meet_thresholds(golden_container: AppContainer) -> None:
    results = await _run_all(golden_container)
    metrics = compute_metrics(results)
    # Deterministic fake baseline must be perfect on validity/safety/clarification.
    assert metrics["valid_sql_rate"] == 1.0
    assert metrics["clarification_accuracy"] == 1.0
    assert metrics["unsafe_query_rejection_rate"] == 1.0
    assert metrics["schema_linking_recall"] >= 0.9
    assert metrics["overall_pass_rate"] == 1.0
