# Glossary

**Ambiguity detection** — Deciding, before generation, whether a reasonable
alternative reading would materially change the answer, and if so returning a
clarification. Implemented in `application/ambiguity.py`.

**AST (abstract syntax tree)** — The parsed, structural representation of SQL.
Safety decisions are made on the AST (via SQLGlot), not on text.

**AuthContext** — The trusted `{user_id, tenant_id, roles}` established by the
transport; the anchor for all authorization. `domain/context.py`.

**Classification** — A column's sensitivity level (`public`…`highly_restricted`)
that drives selection policy and redaction. `domain/enums.py`.

**Composition root** — The single place concrete implementations are wired:
`application/container.py`.

**Correlation id** — An identifier tying every log line, span, and response for
one request together.

**Cost analysis** — Complexity/EXPLAIN-based estimation that classifies risk and
rejects expensive queries. `security/cost.py`.

**Deterministic guarantee** — A property enforced by code that cannot be talked
out of its decision (vs. probabilistic, which depends on model behaviour).

**Golden suite** — A versioned evaluation dataset with semantic checks and metric
gates. `tests/golden/`.

**Grounding** — Generating the natural-language answer from the actual result rows
rather than model narration. `application/explainer.py`.

**Join graph** — Tables as nodes and foreign keys as edges; used by retrieval to
include bridge tables. `DatabaseSchema.join_graph()`.

**LLM provider** — A pluggable backend implementing the `generate` protocol
(`DeterministicFakeProvider`, `OpenAICompatibleProvider`). `llm/`.

**Orchestrator** — The single entry point that sequences the whole pipeline.
`application/orchestrator.py`.

**Policy engine** — Deterministic table/column authorization run after generation.
`security/policy.py`.

**Prompt injection** — Untrusted text attempting to manipulate the model. Contained
(not trusted to be prevented) because output is re-validated.

**Repair loop** — Bounded re-prompting to fix *correctness* errors; never repairs
*security* failures. `application/repair.py`.

**Retrieval** — Selecting the relevant slice of the schema for a question.
`retrieval/retriever.py`.

**Semantic layer** — Authoritative business meaning (metrics, terms,
classifications, date policy). `semantic/`.

**Schema catalog** — The enriched, cached, normalized schema. `schema/catalog.py`.

**Schema drift** — A change in the structural schema version across refreshes.

**Tenant rewriter** — AST rewriter that injects mandatory
`organization_id = <tenant>` predicates into every SELECT scope.
`security/rewriter.py`.

**Validator** — The AST safety gate (read-only, single statement, schema-valid,
no comments/`SELECT *`/denied functions/system catalogs). `sql/validator.py`.
