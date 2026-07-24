# Text-to-SQL Engine — Documentation

This documentation explains *what* the engine does, *why* it is built the way it
is, *how* each part works, and *how it is tested*. Every conceptual document
references the concrete modules and classes that implement it.

## Reading order

1. **[Architecture overview](architecture/overview.md)** — system context, the
   request lifecycle, and trust boundaries.
2. **[Component design](architecture/components.md)** — each pipeline stage, the
   interface it exposes, and the module that implements it.
3. **[Text-to-SQL concepts](concepts/text_to_sql.md)** — schema introspection,
   the semantic layer, retrieval, prompting, generation, ambiguity, and repair.
4. **[SQL parsing & AST validation](concepts/sql_validation.md)** — the primary
   deterministic safety gate.
5. **Security**
   - [Threat model](security/threat_model.md) — the master document.
   - [Authorization & tenant isolation](security/authorization.md)
   - [Prompt-injection threat model](security/prompt_injection_threat_model.md)
   - [SQL-injection & unsafe-query threat model](security/sql_injection_threat_model.md)
   - [Sensitive-data handling](security/sensitive_data.md)
   - [Query-cost controls](security/query_cost.md)
6. **Operations**
   - [Configuration reference](operations/configuration.md)
   - [Local development](operations/local_development.md)
   - [Docker deployment](operations/docker.md)
   - [Production deployment](operations/production.md)
   - [Observability & alerting](operations/observability.md)
   - [Troubleshooting](operations/troubleshooting.md)
7. **[API reference](api/reference.md)**
8. **[Testing strategy & evaluation methodology](testing/strategy.md)**
9. **[Example scenarios](scenarios.md)** — the 17 required scenarios end-to-end.
10. **[Known limitations & future work](limitations.md)** · **[Glossary](glossary.md)**
11. **[Architecture Decision Records](decisions/)**

## The one-paragraph summary

A request enters the [orchestrator](../src/text_to_sql/application/orchestrator.py),
which checks for **ambiguity** (returning a clarification if the answer would
materially depend on interpretation), **retrieves** only the relevant slice of the
schema, resolves **relative dates** under a documented calendar policy, builds a
**versioned prompt**, and asks a pluggable **LLM provider** for structured SQL.
The generated SQL is then run through a purely deterministic gauntlet: **parse →
AST validate → policy → tenant rewrite → re-validate → cost analysis**. Only a
query that survives all of it is executed via a **read-only** connection with a
**LIMIT** and a statement timeout. The natural-language answer is generated
**from the actual result rows**, not by asking the model to narrate. If a
*correctness* check fails, a bounded **repair loop** feeds sanitized errors back
to the model and tries again; *security* failures are hard rejections that never
retry.
