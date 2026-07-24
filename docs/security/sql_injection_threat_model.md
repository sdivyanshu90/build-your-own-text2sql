# SQL-Injection & Unsafe-Query Threat Model

"SQL injection" in a text-to-SQL system has two distinct flavours, both addressed
here.

## Flavour 1 — the LLM *is* the injection vector

Unlike a classic web app where user input is concatenated into a query, here the
model **writes the whole query**. So "injection" means the model emitting hostile
SQL (destructive statements, unauthorized tables/columns, exfiltration `UNION`s,
system-catalog reads, multi-statements, comment payloads).

**Control [Deterministic]:** the AST validator + policy engine + tenant rewriter +
cost analyzer. See [SQL parsing & AST validation](../concepts/sql_validation.md)
and the [threat model](threat_model.md) T1–T3, T5, T10. The model's output is a
*proposal*, never trusted.

## Flavour 2 — untrusted *values* concatenated into SQL by our code

The classic risk: a value (from data, from a client identifier, from a tenant id)
concatenated into SQL text and breaking out of its context.

**Where could this happen?** Only where the engine itself builds SQL:

| Site | How it's made safe |
| --- | --- |
| Tenant predicate injection | Built from **typed `sqlglot` literal nodes** (`exp.Literal.number/string`) and AST composition — never string concatenation. See [`security/rewriter.py`](../../src/text_to_sql/security/rewriter.py). |
| Relative-date bounds | Engine-derived ISO constants from `resolve_relative_date`, injected as guidance and then **re-validated** against the schema by the AST validator. Not user text. |
| Execution | `ReadOnlyExecutor` runs the **validated, normalized AST output** via SQLAlchemy `text()`; the SQL has already passed every gate. |
| Client correlation id | Sanitized to a conservative allowlist (`sanitize_correlation_id`) before it can touch a log line. |
| Fake provider SQL building | The fake provider *simulates an LLM*; its output goes through the same gate as any provider. |

**Why not parameterized queries for the generated SQL?** The generated query's
*structure* (which columns, joins, filters) is the answer — it cannot be a bound
parameter. Safety therefore comes from **validating the structure** (AST) rather
than from parameter binding. Where the engine adds *values* (tenant id), those are
typed AST literals, which is the AST equivalent of parameter binding.

## Bandit note

Bandit flags `B608` ("possible SQL injection through string-based query
construction") on the fake provider's SQL templates and the `EXPLAIN` wrapper.
This is a **false positive for our architecture**: the constructed SQL is always
parsed and AST-validated before execution, which Bandit's string heuristic does not
model. `B608` is therefore skipped with this rationale in `pyproject.toml`; the AST
validator is the real control, exercised by the security and property test suites.

## Unsafe-query controls beyond injection

- **Unbounded results** → `LIMIT` always enforced (`enforce_limit`).
- **Runaway cost** → `CostAnalyzer` + statement timeout (see [query cost](query_cost.md)).
- **Non-read-only** → validator + read-only role.

## Tests

`tests/security/test_deterministic_rejection.py`,
`tests/security/test_tenant_isolation.py`,
`tests/property/test_invariants.py`,
`tests/unit/test_rewriter.py`.
