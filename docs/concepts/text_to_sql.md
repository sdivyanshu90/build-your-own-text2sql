# Text-to-SQL Concepts

This document explains the core ideas the engine is built on and where each lives
in the code. For every concept we cover: *what it is, why it is needed, how it
works, how it is implemented, alternatives, trade-offs, failure modes, and how it
is tested.*

## Relational concepts we rely on

- **Schema / tables / columns / data types** — the structure the query targets.
- **Primary keys & foreign keys** — FKs define the *join graph*, which retrieval
  uses to include bridge tables and which the LLM uses to write joins.
- **Join graph** — tables as nodes, foreign keys as edges. See
  `DatabaseSchema.join_graph()` in
  [`domain/schema_models.py`](../../src/text_to_sql/domain/schema_models.py).
- **Aggregation / GROUP BY / window functions** — the shape of most analytical
  answers (revenue by region, top-N, running totals).
- **NULL semantics & outer joins** — why "customers with no orders" needs
  `NOT EXISTS`/`LEFT JOIN … IS NULL`, and why NULLs appear in results.

## Schema introspection

**What.** Reading the live database's structure (tables, columns, types, keys,
constraints, indexes, comments) into a normalized internal model.

**Why.** The LLM must be told the schema; but the *live* DB object is not a good
prompt input (it's verbose, dialect-specific, and mixes in sensitive detail).

**How / implementation.** `SchemaIntrospector`
([`schema/introspector.py`](../../src/text_to_sql/schema/introspector.py)) uses
SQLAlchemy reflection to build a `DatabaseSchema` of frozen Pydantic models. It
computes a structural **version hash** for cache invalidation and **schema-drift**
detection. `SchemaCatalog`
([`schema/catalog.py`](../../src/text_to_sql/schema/catalog.py)) then *enriches*
the raw structure with governance metadata from the semantic layer
(classification, curated comments, tenant columns, safe sample values) and serves
it from a TTL cache with explicit invalidation.

**Token-budget & serialization.** `DatabaseSchema.serialize_for_prompt(max_chars)`
renders a compact DDL-like description, flags sensitive columns, **flattens
untrusted comments to a single line**, and truncates to a budget.

**Trade-offs / failure modes.** Reflection is comparatively slow → we cache.
Cached schema can go stale after a migration → TTL + `POST /schema/refresh`.
SQLite exposes no column comments → governance comments come from the semantic
layer instead. **Tested** in `tests/integration/test_introspection_execution.py`
and `tests/unit/test_schema_models_catalog.py`.

## Semantic layer & business glossary

**What.** The authoritative source of *business meaning*: metric formulas,
synonyms, entity definitions, classifications, default filters, date policy.

**Why.** "Revenue" is not in the schema — it's a *definition*
(`SUM(quantity*unit_price)` minus approved refunds). Letting the LLM invent it
per-request produces inconsistent, unauditable numbers.

**How.** `SemanticLayer`
([`semantic/models.py`](../../src/text_to_sql/semantic/models.py)) holds
`MetricDefinition`s, `BusinessTerm`s, `ColumnAnnotation`s (classification), and a
`date_policy`. The reference instance is
[`semantic/reference.py`](../../src/text_to_sql/semantic/reference.py). Metric
formulas are injected verbatim into the prompt as the *only* acceptable
definition and echoed in the response's `assumptions`.

**Alternatives.** A full metrics layer (dbt metrics, Cube, LookML). This is a
lightweight, in-process version with the same intent. **Tested** in
`tests/unit/test_semantic_prompt.py`.

## Relevant-schema retrieval

**What.** Selecting only the tables likely relevant to a question.

**Why.** Sending the whole schema wastes tokens and *reduces* accuracy (more
irrelevant tables → more chances to link the wrong one). It also does not scale to
large databases.

**How.** `LexicalSchemaRetriever`
([`retrieval/retriever.py`](../../src/text_to_sql/retrieval/retriever.py)) scores
tables by lexical overlap (name/column/comment tokens), glossary-term matches, and
metric matches; takes the top-k as *seeds*; then adds every table on a **shortest
foreign-key path between seeds** so required join/bridge tables are never dropped.
It returns per-object **scores and reasons**. A deterministic fallback keeps the
result non-empty when nothing matches.

**Alternatives / trade-offs.** Embedding-based retrieval improves recall on
paraphrases but needs a vector store and is non-deterministic; the interface is a
`Protocol`, so it can be swapped in. The lexical retriever favours **recall**
(don't drop needed tables) over precision, on the reasoning that a few extra
tables cost tokens but a missing table costs correctness. **Tested** in
`tests/unit/test_retrieval.py`, which asserts required join-path tables are
included and irrelevant tables excluded.

## Prompt engineering

**What.** Assembling a versioned prompt from clearly separated sections: system
instructions + security policy, schema context, semantic definitions, resolved
dates, conversation summary, and the user question, plus the output schema.

**Why.** Structure improves reliability and makes injection *containment*
possible: untrusted content is fenced and labelled so an embedded "ignore
previous instructions" cannot masquerade as a real section.

**How.** `PromptBuilder`
([`llm/prompt.py`](../../src/text_to_sql/llm/prompt.py)) emits a `PromptPayload`
carrying `PROMPT_VERSION` (recorded on every response for reproducibility) and a
JSON output schema. Untrusted text is passed through `sanitize_untrusted`
(strips control chars, neutralizes role markers and code fences, optionally
collapses the question to one line). **Prompting is not a security control** — see
the [prompt-injection model](../security/prompt_injection_threat_model.md).
**Tested** in `tests/unit/test_semantic_prompt.py`.

## LLM provider abstraction

**What.** A vendor-independent `LLMProvider` protocol returning a *structured*
`GenerationResponse` (SQL, dialect, explanation, referenced tables/columns,
assumptions, confidence).

**Why.** Avoid vendor lock-in; enable deterministic testing; require structured
output instead of scraping free text.

**How.** `DeterministicFakeProvider`
([`llm/fake.py`](../../src/text_to_sql/llm/fake.py)) powers tests/CI with zero
credentials and supports *scripting* (force any SQL to exercise the gate).
`OpenAICompatibleProvider`
([`llm/openai_adapter.py`](../../src/text_to_sql/llm/openai_adapter.py)) targets
any OpenAI-compatible endpoint with JSON output, timeout, retries, and typed error
mapping. **Tested** in `tests/unit/test_fake_provider.py` and
`tests/integration/test_openai_adapter.py` (against a mock HTTP server).

## Ambiguity detection

**What.** Deciding *before* generation whether a reasonable alternative reading
would materially change the answer, and if so returning a structured
clarification.

**Why.** Guessing on "top customers" (by revenue? orders? MRR?) produces a
confident but possibly wrong answer. Asking is cheaper than being wrong. But we do
**not** clarify anything a documented default resolves safely (e.g. relative
dates → calendar policy).

**How.** `AmbiguityDetector`
([`application/ambiguity.py`](../../src/text_to_sql/application/ambiguity.py))
applies glossary-aware rules: unknown term, ambiguous metric ("sales"),
unspecified ranking measure, and entity confusion ("users" vs "customers"). The
API returns HTTP `409` with category, interpretations, and a suggested question.
**Tested** in `tests/unit/test_ambiguity_repair_explainer.py` (positive and
false-positive cases).

## Bounded SQL repair

**What.** When a *correctness* check fails (parse error, unknown column,
`SELECT *`, disallowed function), feed sanitized errors back to the model and try
again, up to a strict limit.

**Why.** LLMs make fixable mistakes; a single retry with the specific error often
succeeds without a human. But repair must never loop forever or bypass security.

**How.** `RepairPlanner`
([`application/repair.py`](../../src/text_to_sql/application/repair.py)) classifies
issues: correctness issues are repairable; *any* security/policy/cost issue makes
the whole attempt a hard rejection (re-prompting a model that emitted `DROP TABLE`
is pointless). The loop lives in `QueryOrchestrator._generate_with_repair`; each
attempt re-runs the *entire* deterministic gate. **Tested** in
`tests/end_to_end/test_repair_conversation.py`.

## Result explanation (grounding)

**What.** A natural-language answer generated **from the returned rows**, not by
asking the model to narrate.

**Why.** Model-narrated answers hallucinate facts absent from the data. Grounding
guarantees the answer reflects what the query actually returned.

**How.** `ResultExplainer`
([`application/explainer.py`](../../src/text_to_sql/application/explainer.py))
templates the row count, scalar/top-N values, and assumptions, and separates
database-derived facts from system assumptions and warnings. **Tested** in
`tests/unit/test_ambiguity_repair_explainer.py`.

## Conversation context

Follow-ups ("now group that by region") are supported via **structured**
conversation state (`ConversationState` in
[`domain/context.py`](../../src/text_to_sql/domain/context.py)) — prior intent,
metrics, filters, dimensions — *not* raw chat history (a token sink and an
injection vector). Every follow-up is re-validated as a brand-new request under
the *current* security policy; old messages can never relax it. **Tested** in
`tests/end_to_end/test_repair_conversation.py`.
