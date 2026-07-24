# Troubleshooting

Use the `correlation_id` (response body and `X-Correlation-Id` header) to find all
log lines and spans for a request.

## Error codes

Every non-2xx response is an [`ErrorResponse`](../../src/text_to_sql/domain/models.py)
with a stable `error.code`:

| Code | HTTP | Meaning / action |
| --- | --- | --- |
| `invalid_request` | 422 | Malformed body. Check the `details.errors`. |
| `clarification_required` | 409 | Not an error — refine the question per the `clarification`. |
| `authorization_denied` | 403 | Missing auth headers, tenant mismatch, or a denied table/column. |
| `sql_validation_failed` | 422 | The model produced unsafe SQL (rejected). |
| `query_cost_rejected` | 422 | Too expensive/complex; add filters or narrow the question. |
| `repair_exhausted` | 422 | Couldn't produce valid SQL in the allowed attempts. |
| `provider_timeout` | 504 | LLM slow/unreachable; retryable. |
| `provider_error` | 502 | Upstream provider problem; often retryable. |
| `execution_failed` | 500 | DB error/timeout during execution. |
| `dependency_unavailable` | 503 | DB/provider unavailable (see readiness). |

## Common symptoms

**`/health/ready` returns 503.**
The DB is unreachable or the schema can't be introspected. Check
`T2SQL_DATABASE_URL`, that migrations ran, and DB connectivity. `checks.database`
/ `checks.schema` in the body pinpoint which.

**Every query returns `clarification_required`.**
The question likely triggers an ambiguity rule (e.g. contains "sales" or a ranking
without a measure, or an undefined term like "churn"). Provide the measure/entity,
or extend the semantic layer with an authoritative definition.

**A revenue query returns 403 (`column_denied`).**
The caller's role lacks access to a `financial` column (e.g. `payments.amount`).
Net revenue via `order_items` works for any analyst; raw money columns require
`analyst`/`finance_read`. Check `X-Roles`.

**Valid-looking SQL is rejected as `sql_validation_failed`.**
Look at `validation.issues`. Common causes: `SELECT *` (list columns explicitly),
a function on the denylist, or a system-catalog reference.

**`repair_exhausted` on a reasonable question.**
The model kept producing invalid SQL (e.g. hallucinated columns). Inspect logs for
the rejected candidates' `rejected_codes`. Consider a better model, a clearer
prompt version, or adding the concept to the semantic layer.

**Results look wrong (right shape, wrong numbers).**
This is a *correctness* issue, not a safety one. Verify the metric definition in
the semantic layer and the assumptions in the response. Add a golden case to lock
in the expected behaviour.

**Startup fails with a configuration error.**
`Settings` validation failed (e.g. `cost_rows_medium_threshold ≥ high`, bad log
level). The message names the offending field.

**Provider requests fail with `configuration_error`.**
`T2SQL_LLM_PROVIDER=openai` but no key resolved. Set the env var named by
`T2SQL_LLM_API_KEY_ENV`.

## Debugging tips

- Set `T2SQL_LOG_LEVEL=DEBUG` to see per-span timing lines.
- `python scripts/run_examples.py` reproduces the canonical scenarios locally.
- `python -m tests.golden.run_eval` produces `eval_results/golden_report.md` with
  per-case pass/fail and metrics.
