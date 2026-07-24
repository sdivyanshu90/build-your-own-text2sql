# Live Benchmarks (Google Gemini)

How the engine behaves against a **real** LLM rather than the deterministic fake.
Everything here was produced by scripts in this repository; nothing is estimated.

## Reproduce

```bash
export T2SQL_LLM_PROVIDER=gemini
export T2SQL_LLM_MODEL=gemini-2.5-flash
export T2SQL_LLM_API_KEY_ENV=GEMINI_API_KEY
export GEMINI_API_KEY=...            # your key

python scripts/run_edge_cases.py                 # edge-case matrix (22 cases)
python -m tests.golden.run_eval                  # golden accuracy metrics
python scripts/benchmark.py --provider gemini \
       --model gemini-2.5-flash --trials 4 --compare-fake
```

## Methodology

- **Database:** the reference multi-tenant commerce schema (11 tables) with the
  deterministic seed data, on SQLite.
- **Clock:** pinned to `2026-07-24` so relative-date questions are reproducible.
- **Edge-case matrix** (`scripts/run_edge_cases.py`): 22 cases. Cases 1–11 are
  *prose* questions where the **live model** writes the SQL. Cases 12–22 are
  marked `[forced]` — hostile SQL is scripted directly into the model's mouth so
  the test measures the **deterministic gate**, not the model's willingness to
  refuse. That distinction is the whole point: a security control you can only
  demonstrate by asking the model nicely is not a control.
- **Benchmark** (`scripts/benchmark.py`): 6 analytical questions × N trials
  through the full pipeline, reporting p50/p95 and a stage breakdown. Comparing
  against the `fake` provider isolates **engine overhead** from **model latency**.

## Results

Measured on 2026-07-24, SQLite + reference seed data, `gemini-2.5-flash`.

### Edge-case matrix (22 cases)

3 consecutive runs: **22/22, 22/22, 22/22**. Screenshot of a run:
[`docs/assets/edge-cases-gemini.png`](../assets/edge-cases-gemini.png).

The 11 `[forced]` security cases complete in **1–6 ms** — they are rejected by
parsing, validation, policy, or cost analysis and never reach the model.

### Golden evaluation (14 cases)

| Metric | Live Gemini | Fake baseline |
| --- | --- | --- |
| overall pass rate | 1.0 | 1.0 |
| valid SQL rate | 1.0 | 1.0 |
| execution accuracy | 1.0 | 1.0 |
| schema-linking recall | 1.0 | 1.0 |
| clarification accuracy | 1.0 | 1.0 |
| unsafe-query rejection rate | 1.0 | 1.0 |
| avg latency | 4 625 ms | 6 ms |

### Latency (6 questions × 4 trials)

| Provider | Model | Samples | Mean | p50 | p95 | LLM call | Engine overhead | Failures | Repairs |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fake | `deterministic-fake` | 24 | 6 ms | 5 ms | 10 ms | 0 ms | **5.8 ms** | 0 | 0 |
| gemini | `gemini-2.5-flash` | 24 | 8 713 ms | 8 316 ms | 21 732 ms | 8 704 ms | **8.8 ms** | 0 | 0 |

Mean stage breakdown on Gemini: retrieval 0.46 ms, generation 8 704 ms, SQL
execution 1.05 ms, validation + security + explanation 7.26 ms. Mean token usage
per request: 1 162 prompt / 358 completion.

## What "engine overhead" means

Total wall time minus the LLM call: retrieval, parsing, AST validation, policy,
tenant rewriting, cost analysis, execution, and explanation — everything this
project actually controls. It is the number to optimise; model latency is the
vendor's.

## Interpreting the numbers

- **Latency is dominated by the model.** Engine overhead is single-digit
  milliseconds; the LLM call is seconds. Optimising the engine further would be
  premature — caching or a faster model is where the wins are.
- **p95 ≫ p50.** Gemini's tail latency is long (multi-second spread on identical
  inputs). Budget timeouts against p95, not the mean.
- **Security guarantees are latency-independent.** The `[forced]` cases execute in
  1–5 ms because they never reach the model — they are rejected by parsing,
  validation, policy, or cost analysis.

## Deterministic vs probabilistic, measured

The runs make the project's central claim concrete:

| Property | Guarantee | Observed |
| --- | --- | --- |
| Destructive SQL rejected | Deterministic | 100% of runs |
| Tenant isolation enforced | Deterministic | 100% of runs |
| Sensitive columns protected | Deterministic | 100% of runs |
| Cost limits enforced | Deterministic | 100% of runs |
| Model produces *correct* SQL | **Probabilistic** | see reliability below |

The security rows are 100% because they do not depend on the model. The last row
does, which is exactly why the engine never delegates security to it.

## A real bug this exercise found

Running against a live model surfaced a genuine validator defect the fake provider
never triggered. Gemini emitted a multi-CTE query using `refunds AS r` inside a CTE
and `regions AS r` in the outer query — both legal, since an alias is only unique
*within* a scope. The validator kept a single global alias→table map, so `r`
resolved to whichever table was parsed last and valid SQL was rejected with
`unknown_column`, then burned the repair budget and failed the request.

Fixed in [`sql/validator.py`](../../src/text_to_sql/sql/validator.py): an alias now
maps to the **set** of tables it may denote, a column is valid if **any** candidate
defines it, and **every** matching candidate is recorded so the policy engine still
sees the strictest possible set of base columns (over-reporting is safe;
under-reporting would not be). Locked in by
`tests/unit/test_validator_alias_scopes.py`, including a test proving the change
does not weaken column authorization.

This is the argument for evaluating against real models: the deterministic fake is
perfect for testing *the pipeline*, but only a real model generates the messy,
valid-but-unusual SQL that finds bugs like this.
