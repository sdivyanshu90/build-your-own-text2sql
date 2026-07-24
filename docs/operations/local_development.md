# Local Development

## Prerequisites

- Python 3.10+ (3.12 recommended). No database or LLM credentials are required for
  the default configuration (SQLite + deterministic fake provider).

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
make install                 # pip install -e ".[dev]"
cp .env.example .env         # optional; defaults are fine
python scripts/init_db.py --drop --seed
```

## Everyday commands

```bash
make run          # dev server with autoreload → http://localhost:8000/api/v1/docs
make demo         # run scripts/run_examples.py (all 17 scenarios)
make test         # full suite with coverage
make test-fast    # unit + security only
make lint         # ruff check
make format       # ruff format
make typecheck    # mypy
make check        # lint + mypy + bandit + tests (the local "CI")
make eval         # golden evaluation → eval_results/
```

## Running a subset of tests

```bash
pytest -m unit
pytest -m "security or property"
pytest tests/end_to_end -q
pytest -k tenant           # by keyword
```

## Trying a real provider locally

```bash
export T2SQL_LLM_PROVIDER=openai
export T2SQL_LLM_MODEL=gpt-4o-mini
export OPENAI_API_KEY=sk-...      # resolved via T2SQL_LLM_API_KEY_ENV
make run
```

If you need to run an interactive login or shell command whose output you want in
this session, prefix it with `!` in the Claude Code prompt.

## Project conventions

- Business logic lives in `application/` and the layers it composes — **never** in
  route handlers.
- No direct provider calls or raw SQL execution outside their designated modules.
- Add a test at the appropriate level for every change; keep the 90% coverage gate
  green (`make test`).
- Run `make format` before committing.
