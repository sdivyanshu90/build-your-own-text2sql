# Known Limitations & Future Improvements

Being explicit about limits is part of the security posture: it separates what is
*guaranteed* from what is *best-effort*.

## Known limitations

### Correctness is probabilistic
The engine guarantees generated SQL is **safe** and **references real schema** — not
that it perfectly captures intent. A model can produce a *valid but semantically
wrong* query (e.g. wrong join grain, wrong date column). Mitigations: semantic
layer, retrieval, repair, confidence, grounded explanations, and the golden suite.
This is a correctness risk, not a security one.

### Retriever is lexical
The default retriever ([`retrieval/retriever.py`](../src/text_to_sql/retrieval/retriever.py))
matches on tokens + glossary + FK graph. It can miss purely semantic paraphrases
with no lexical overlap. It is a `Protocol`, so an embedding ranker can be added.

### Planner cost estimates are approximate
`EXPLAIN`-based estimates (PostgreSQL only) can be wrong under skew/stale stats.
SQLite has no comparable estimate. The hard runtime bounds (`LIMIT`, statement
timeout, row-cap fetch) are the real guardrails. See
[query cost](security/query_cost.md).

### `SELECT *` is rejected, not expanded
To let the policy engine reason about concrete columns, bare `SELECT *` is
rejected rather than expanded. The prompt and fake provider avoid it and repair
can fix it, but a user pasting `SELECT *` into `/validate` gets a rejection.

### Single data source
The build targets one configured database. `data_source` in the request model is
reserved for future multi-source routing but not yet wired.

### Statement timeout is PostgreSQL-only
SQLite has no server-side statement timeout; there, bounding relies on `LIMIT` and
the row-cap fetch. Use PostgreSQL in production.

### Reference auth is header-based
The reference build derives identity from headers for demonstration. Production
must place a real auth gateway (JWT/session verification) in front and strip
client-supplied identity headers.

### Column resolution is conservative
Unqualified columns are accepted if they exist on *any* referenced table (no full
scope resolution). This favours availability; it will not flag an ambiguous column
that happens to exist on two joined tables.

### Dialects
Validated for SQLite and PostgreSQL. Other dialects need dialect-specific tests
before enabling.

## Future improvements

- **Embedding-based retrieval** behind the existing `SchemaRetriever` protocol,
  with the lexical retriever as a deterministic fallback.
- **Multi-source routing** (resolve `data_source` → a per-source catalog/engine).
- **Result caching** keyed by tenant + auth context + schema version (design in
  [observability](operations/observability.md)); off until then.
- **Richer semantic layer** (dimensions, hierarchies, more metrics; load from dbt
  metrics / a metrics store).
- **Column-level lineage** to detect ambiguous unqualified columns precisely.
- **Adaptive prompt versions** with A/B evaluation via the golden harness.
- **Native OTLP export** wired through the `otel` extra.
- **Per-tenant cost budgets** and rate limiting.
