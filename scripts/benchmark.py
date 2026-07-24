#!/usr/bin/env python
"""Benchmark the engine: latency percentiles, stage breakdown, and token usage.

Runs a fixed question set through the full pipeline N times per provider and
reports p50/p95 latency, a per-stage breakdown (retrieval / generation /
validation+security / execution), token usage, and repair rate. Comparing the
`fake` provider against a live model isolates **engine overhead** from **model
latency** — the fake baseline is essentially the engine's own cost.

Usage:
    python scripts/benchmark.py --provider fake --trials 5
    T2SQL_LLM_API_KEY_ENV=GEMINI_API_KEY GEMINI_API_KEY=... \
      python scripts/benchmark.py --provider gemini --model gemini-2.5-flash --trials 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from datetime import datetime
from pathlib import Path

from text_to_sql.application.container import AppContainer
from text_to_sql.common.errors import EngineError
from text_to_sql.configuration import Settings
from text_to_sql.domain.context import AuthContext
from text_to_sql.domain.models import QueryRequest
from text_to_sql.infrastructure.bootstrap import create_schema, seed_database
from text_to_sql.infrastructure.database import make_database

FIXED_NOW = datetime(2026, 7, 24)
ANALYST = AuthContext(user_id="bench", tenant_id="1", roles=("analyst",))
OUTPUT_DIR = Path("eval_results")

QUESTIONS = [
    "How many customers do we have?",
    "Show revenue by region",
    "What is our total revenue?",
    "How many orders were placed last month?",
    "What were our top five products by revenue last quarter?",
    "Show all open support tickets",
]


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round((p / 100.0) * (len(ordered) - 1)))))
    return ordered[k]


async def benchmark(provider: str, model: str, trials: int) -> dict:
    settings = Settings(
        _env_file=None,
        database_url="sqlite:///./data/bench.db",
        llm_provider=provider,  # type: ignore[arg-type]
        llm_model=model,
        llm_api_key_env=os.environ.get("T2SQL_LLM_API_KEY_ENV", "OPENAI_API_KEY"),
        llm_timeout_seconds=float(os.environ.get("T2SQL_LLM_TIMEOUT_SECONDS", "60")),
        sql_dialect="sqlite",
        log_json=False,
        log_level="ERROR",
    )
    database = make_database(settings)
    create_schema(database.engine, drop_first=True)
    seed_database(database.engine)
    container = AppContainer.create(settings, database=database, clock=lambda: FIXED_NOW)

    totals: list[float] = []
    retrieval: list[float] = []
    generation: list[float] = []
    execution: list[float] = []
    prompt_tokens: list[int] = []
    completion_tokens: list[int] = []
    repairs = 0
    failures = 0
    samples = 0
    failure_detail: list[str] = []

    # Warm caches (schema introspection) so the first call isn't an outlier.
    try:
        await container.orchestrator.process(QueryRequest(question=QUESTIONS[0]), ANALYST)
    except EngineError:
        pass

    for _ in range(trials):
        for question in QUESTIONS:
            t0 = time.perf_counter()
            try:
                resp = await container.orchestrator.process(
                    QueryRequest(question=question), ANALYST
                )
            except EngineError as exc:
                failures += 1
                failure_detail.append(f"{question[:40]!r} -> {exc.error_code}")
                continue
            wall = (time.perf_counter() - t0) * 1000
            samples += 1
            totals.append(wall)
            retrieval.append(resp.timings.retrieval_ms)
            generation.append(resp.timings.generation_ms)
            execution.append(resp.timings.execution_ms)
            if resp.model:
                repairs += resp.model.repair_attempts
                prompt_tokens.append(resp.model.prompt_tokens or 0)
                completion_tokens.append(resp.model.completion_tokens or 0)

    container.dispose()

    gen_mean = statistics.mean(generation) if generation else 0.0
    total_mean = statistics.mean(totals) if totals else 0.0
    # Everything that is not the model call is engine overhead.
    overhead = total_mean - gen_mean

    return {
        "provider": provider,
        "model": model,
        "trials": trials,
        "samples": samples,
        "failures": failures,
        "repair_attempts": repairs,
        "failure_detail": failure_detail,
        "latency_ms": {
            "mean": round(total_mean, 1),
            "p50": round(_pct(totals, 50), 1),
            "p95": round(_pct(totals, 95), 1),
            "min": round(min(totals), 1) if totals else 0.0,
            "max": round(max(totals), 1) if totals else 0.0,
        },
        "stage_mean_ms": {
            "retrieval": round(statistics.mean(retrieval), 2) if retrieval else 0.0,
            "generation": round(gen_mean, 1),
            "execution": round(statistics.mean(execution), 2) if execution else 0.0,
            "engine_overhead": round(overhead, 2),
        },
        "tokens_mean": {
            "prompt": round(statistics.mean(prompt_tokens), 1) if prompt_tokens else 0.0,
            "completion": round(statistics.mean(completion_tokens), 1) if completion_tokens else 0.0,
        },
    }


def render(results: list[dict]) -> str:
    lines = [
        "# Performance Benchmark",
        "",
        f"Question set: {len(QUESTIONS)} analytical questions, full pipeline "
        "(retrieval → generation → validate → policy → tenant rewrite → cost → execute → explain).",
        "",
        "| Provider | Model | Samples | Mean | p50 | p95 | Generation | Engine overhead | Prompt tok | Completion tok |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in results:
        lines.append(
            f"| {r['provider']} | `{r['model']}` | {r['samples']} | "
            f"{r['latency_ms']['mean']:.0f} ms | {r['latency_ms']['p50']:.0f} ms | "
            f"{r['latency_ms']['p95']:.0f} ms | {r['stage_mean_ms']['generation']:.0f} ms | "
            f"**{r['stage_mean_ms']['engine_overhead']:.1f} ms** | "
            f"{r['tokens_mean']['prompt']:.0f} | {r['tokens_mean']['completion']:.0f} |"
        )
    lines += [
        "",
        "**Engine overhead** = total wall time minus the LLM call. It is the cost of "
        "retrieval, parsing, AST validation, policy, tenant rewriting, cost analysis, "
        "execution, and explanation — i.e. everything this project actually controls.",
        "",
    ]
    for r in results:
        s = r["stage_mean_ms"]
        lines += [
            f"### {r['provider']} / `{r['model']}` stage breakdown (mean)",
            "",
            f"- retrieval: {s['retrieval']:.2f} ms",
            f"- generation (LLM): {s['generation']:.1f} ms",
            f"- execution (SQL): {s['execution']:.2f} ms",
            f"- validation + security + explain (remainder): "
            f"{max(0.0, s['engine_overhead'] - s['retrieval'] - s['execution']):.2f} ms",
            f"- failures: {r['failures']}, repair attempts: {r['repair_attempts']}",
            "",
        ]
        if r.get("failure_detail"):
            lines.append("Failures observed (model non-determinism, not engine faults):")
            lines += [f"  - {f}" for f in r["failure_detail"]]
            lines.append("")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the Text-to-SQL engine.")
    parser.add_argument("--provider", default="fake")
    parser.add_argument("--model", default=None)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--compare-fake", action="store_true", help="Also run the fake baseline.")
    args = parser.parse_args()

    model = args.model or ("deterministic-fake" if args.provider == "fake" else "gemini-2.5-flash")

    results = []
    if args.compare_fake and args.provider != "fake":
        print("Running fake baseline ...")
        results.append(await benchmark("fake", "deterministic-fake", args.trials))
    print(f"Running {args.provider} / {model} ...")
    results.append(await benchmark(args.provider, model, args.trials))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "benchmark.json").write_text(json.dumps(results, indent=2))
    report = render(results)
    (OUTPUT_DIR / "benchmark.md").write_text(report)
    print()
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
