# Text-to-SQL Engine

A production-oriented **natural-language → SQL** engine that turns questions like
*"What were our top five products by revenue last quarter?"* into safe, validated,
executable read-only SQL — and returns the SQL, the results, and a **grounded**
natural-language explanation.

The defining principle: **security is enforced deterministically, after
generation.** The LLM is treated as an untrusted component. Every query it
produces is parsed into an AST, validated against the schema, checked by a policy
engine, rewritten to inject mandatory tenant filters, cost-analysed, and only then
executed through a read-only connection. Prompt-level instructions are *defense in
depth*, never the security boundary.

```mermaid
flowchart LR
    Q["Natural-language question"] --> O[Orchestrator]
    O --> AMB{Ambiguous?}
    AMB -- yes --> CLAR[Clarification]
    AMB -- no --> RET[Schema retrieval]
    RET --> GEN[LLM provider]
    GEN --> VAL[Parse + AST validate]
    VAL --> POL[Policy engine]
    POL --> REW[Tenant rewrite]
    REW --> COST[Cost analysis]
    COST --> EXEC[Read-only execute]
    EXEC --> EXP[Grounded explanation]
    EXP --> R["Structured response"]
    VAL -. invalid & repairable .-> GEN
```

---

## Why this design

Text-to-SQL systems fail in two ways: they generate **wrong** SQL, and they
generate **dangerous** SQL. This project separates those concerns:

| Concern | Guarantee | Mechanism |
| --- | --- | --- |
| No data modification | **Deterministic** | AST validator rejects any non-`SELECT` node ([`sql/validator.py`](src/text_to_sql/sql/validator.py)) |
| No cross-tenant reads | **Deterministic** | AST tenant-predicate rewriter ([`security/rewriter.py`](src/text_to_sql/security/rewriter.py)) |
| No sensitive-column exposure | **Deterministic** | Classification policy ([`security/policy.py`](src/text_to_sql/security/policy.py)) |
| No unbounded / runaway queries | **Deterministic** | `LIMIT` injection + cost analyzer ([`security/cost.py`](src/text_to_sql/security/cost.py)) |
| Correct interpretation of the question | **Probabilistic** | LLM + semantic layer + retrieval + repair loop |

The deterministic guarantees hold *even if the model is fully compromised or
prompt-injected*. See [`docs/security/threat_model.md`](docs/security/threat_model.md).

---

## Quickstart (no credentials)

The default configuration uses SQLite and a **deterministic fake LLM provider**,
so it runs with zero external dependencies and no API keys.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Create the reference database and load deterministic seed data
python scripts/init_db.py --drop --seed

# See the whole pipeline (happy paths + adversarial scenarios)
python scripts/run_examples.py

# Run the API
uvicorn text_to_sql.main:app --reload
# → docs at http://localhost:8000/api/v1/docs
```

Ask a question:

```bash
curl -s http://localhost:8000/api/v1/query \
  -H 'Content-Type: application/json' \
  -H 'X-User-Id: u1' -H 'X-Tenant-Id: 1' -H 'X-Roles: analyst' \
  -d '{"question": "Show revenue by region, excluding refunded orders"}' | jq
```

### Or with Docker (PostgreSQL + API, one command)

```bash
docker compose up --build      # API on :8000, migrates + seeds automatically
```

---

## What you get back

`POST /api/v1/query` returns a structured [`QueryResponse`](src/text_to_sql/domain/models.py):

```jsonc
{
  "status": "success",
  "correlation_id": "corr_…",
  "sql": "SELECT regions.name AS region, SUM(...) AS revenue FROM order_items ... WHERE (order_items.organization_id = 1 AND ...) GROUP BY regions.name ORDER BY revenue DESC LIMIT 1000",
  "columns": ["region", "revenue"],
  "rows": [["North America", 7972.5], ["EMEA", 5732.5]],
  "row_count": 3,
  "explanation": "Returned 3 rows of revenue by region. Top: North America: 7,972.5 …",
  "assumptions": ["Revenue = SUM(quantity * unit_price) …", "Excluded orders with status 'refunded'."],
  "validation": { "is_valid": true, "referenced_tables": ["order_items","orders","customers","regions"], "applied_rewrites": ["order_items.organization_id = 1", "..."], "risk_level": "low" },
  "timings": { "retrieval_ms": 0.4, "generation_ms": 0.2, "execution_ms": 1.1, "total_ms": 3.0 },
  "model": { "provider": "fake", "model": "deterministic-fake", "prompt_version": "v1", "repair_attempts": 0 }
}
```

Ambiguous questions return HTTP `409` with a structured clarification instead of
guessing. Unsafe or unauthorized queries return a typed error envelope.

---

## Repository layout

```text
src/text_to_sql/
├── api/            FastAPI routes, DI, error envelope, health, metrics
├── application/    Orchestrator, ambiguity, repair, explainer, composition root
├── domain/         Pure Pydantic models & enums (no framework deps)
├── configuration/  Typed settings (env-driven)
├── common/         Errors, redaction, correlation ids
├── observability/  Structured logging, metrics, tracing
├── infrastructure/ DB engines, reference schema, seed data
├── schema/         Introspection, enriched catalog, cache
├── semantic/       Business glossary, metrics, classifications, date policy
├── retrieval/      Deterministic relevant-schema retriever
├── llm/            Provider protocol, fake + OpenAI adapters, prompt builder
├── sql/            SQLGlot parser, AST validator, normalizer
├── security/       Policy engine, tenant rewriter, classification, cost
└── execution/      Read-only executor
tests/              unit · integration · end_to_end · security · property · contract · performance · golden
docs/               architecture · concepts · security · operations · api · testing · decisions
```

## Documentation

Start at **[`docs/index.md`](docs/index.md)**. Highlights:

- [Architecture overview](docs/architecture/overview.md) · [Component design](docs/architecture/components.md)
- [Text-to-SQL concepts](docs/concepts/text_to_sql.md) · [SQL parsing & AST validation](docs/concepts/sql_validation.md)
- [Threat model](docs/security/threat_model.md) · [Authorization & tenancy](docs/security/authorization.md) · [Prompt-injection model](docs/security/prompt_injection_threat_model.md) · [SQL-injection model](docs/security/sql_injection_threat_model.md) · [Sensitive data](docs/security/sensitive_data.md) · [Query cost](docs/security/query_cost.md)
- [Configuration reference](docs/operations/configuration.md) · [API reference](docs/api/reference.md)
- [Local dev](docs/operations/local_development.md) · [Docker](docs/operations/docker.md) · [Production](docs/operations/production.md) · [Observability](docs/operations/observability.md) · [Troubleshooting](docs/operations/troubleshooting.md)
- [Testing strategy & evaluation](docs/testing/strategy.md) · [Known limitations](docs/limitations.md) · [Glossary](docs/glossary.md) · [ADRs](docs/decisions/)

## Development

```bash
make install        # editable install with dev extras
make check          # ruff + mypy + bandit + tests (with 90% coverage gate)
make test           # full test suite with coverage
make eval           # golden evaluation harness → eval_results/
make run            # dev server
```

## Technology

Python 3.12+ (runs on 3.10+) · FastAPI · Pydantic v2 · SQLAlchemy 2 · SQLGlot ·
httpx · Alembic · pytest/Hypothesis · Ruff/mypy/Bandit · Docker. Every dependency
is justified in [`docs/decisions/ADR-0002-dependencies.md`](docs/decisions/ADR-0002-dependencies.md).

## License

MIT.
