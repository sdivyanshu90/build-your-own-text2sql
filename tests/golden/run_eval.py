"""Golden evaluation harness (runnable outside pytest).

    python -m tests.golden.run_eval

Builds a self-contained engine (SQLite + deterministic fake provider), runs the
golden dataset, and writes machine-readable JSON plus a human-readable Markdown
report to ``eval_results/``. This is the deterministic *baseline*; the same
evaluator can be pointed at a live provider (set ``T2SQL_LLM_PROVIDER=openai``)
to measure a real model against the same cases.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from tests.golden.dataset import DATASET_VERSION, GOLDEN_CASES
from tests.golden.evaluator import (
    CaseResult,
    compute_metrics,
    evaluate_case,
    result_to_dict,
    scripted_provider,
)
from text_to_sql.application.container import AppContainer
from text_to_sql.configuration import Settings
from text_to_sql.infrastructure.bootstrap import create_schema, seed_database
from text_to_sql.infrastructure.database import make_database

FIXED_NOW = datetime(2026, 7, 24)
OUTPUT_DIR = Path("eval_results")


async def run() -> tuple[list[CaseResult], dict[str, float]]:
    # Provider is chosen from the environment: "fake" (default) gives the
    # deterministic baseline; setting T2SQL_LLM_PROVIDER=openai measures a real
    # model against the SAME dataset (see .github/workflows/live-eval.yml).
    provider_name = os.environ.get("T2SQL_LLM_PROVIDER", "fake")
    settings = Settings(
        _env_file=None,
        database_url="sqlite:///./data/eval.db",
        llm_provider=provider_name,  # type: ignore[arg-type]
        llm_model=os.environ.get("T2SQL_LLM_MODEL", "deterministic-fake"),
        sql_dialect="sqlite",
        log_json=False,
    )
    database = make_database(settings)
    create_schema(database.engine, drop_first=True)
    seed_database(database.engine)

    # The fake baseline uses scripting to force the security cases' hostile SQL;
    # a real provider is built by the container from settings.
    provider = scripted_provider(GOLDEN_CASES) if provider_name == "fake" else None
    container = AppContainer.create(
        settings,
        database=database,
        provider=provider,
        clock=lambda: FIXED_NOW,
    )
    try:
        results = [await evaluate_case(container.orchestrator, case) for case in GOLDEN_CASES]
    finally:
        container.dispose()

    metrics = compute_metrics(results)
    return results, metrics


def write_reports(results: list[CaseResult], metrics: dict[str, float]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset_version": DATASET_VERSION,
        "provider": "fake",
        "metrics": metrics,
        "cases": [result_to_dict(r) for r in results],
    }
    (OUTPUT_DIR / "golden_results.json").write_text(json.dumps(payload, indent=2))
    (OUTPUT_DIR / "golden_report.md").write_text(_markdown(results, metrics))


def _markdown(results: list[CaseResult], metrics: dict[str, float]) -> str:
    lines = [
        f"# Golden Evaluation Report — dataset {DATASET_VERSION}",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    for key, value in metrics.items():
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "## Cases",
        "",
        "| id | tier | status | expected | pass | latency (ms) | notes |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        notes = "; ".join(r.failures) if r.failures else (r.error_code or "ok")
        mark = "✅" if r.passed else "❌"
        lines.append(
            f"| {r.id} | {r.difficulty} | {r.actual_status} | {r.expected_status} | "
            f"{mark} | {r.latency_ms} | {notes} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    results, metrics = asyncio.run(run())
    write_reports(results, metrics)
    passed = sum(1 for r in results if r.passed)
    print(f"Golden evaluation: {passed}/{len(results)} cases passed")
    for key, value in metrics.items():
        print(f"  {key}: {value}")
    print(f"Reports written to {OUTPUT_DIR}/")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
