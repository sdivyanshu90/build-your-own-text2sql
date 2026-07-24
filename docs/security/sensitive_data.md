# Sensitive-Data Handling

## Classification model

Every column carries a `DataClassification`
([`domain/enums.py`](../../src/text_to_sql/domain/enums.py)):

`public` → `internal` → `confidential` → `pii` → `financial` → `auth_secret` →
`highly_restricted`.

Classifications are assigned in the semantic layer
([`semantic/reference.py`](../../src/text_to_sql/semantic/reference.py)), not
guessed. In the reference schema:

| Column | Classification |
| --- | --- |
| `users.password_hash`, `payments.payment_token` | `auth_secret` |
| `users.email`, `users.full_name`, `customers.contact_email`, `customers.contact_phone`, `payments.card_last4` | `pii` |
| `payments.amount`, `refunds.amount`, `subscriptions.mrr` | `financial` |
| everything else | `internal` / `public` |

`order_items.unit_price` / `products.unit_price` are deliberately `internal` (not
`financial`) so that the *revenue* metric is computable by any authenticated
analyst, while raw money fields (`payments.amount`, …) remain gated.

## Two independent protections

1. **Selection control [Deterministic].** The policy engine denies selection of a
   column the caller's roles may not view (see
   [authorization](authorization.md)). `auth_secret` / `highly_restricted` are
   never selectable by anyone. This *prevents* sensitive values from being
   returned at all.
2. **Redaction (defense in depth) [Deterministic].** If a sensitive value ever
   reached a string bound for a log, trace, error, prompt, explanation, or test
   snapshot, `Redactor` / `redact_text`
   ([`common/redaction.py`](../../src/text_to_sql/common/redaction.py)) scrub
   well-known shapes (emails, phones, card-like numbers, bearer tokens, API keys,
   and credentials embedded in connection strings — preserving scheme+host for
   diagnostics).

`DataClassification.is_sensitive` (PII / financial / auth-secret /
highly-restricted) is what marks a value for redaction and flags it in the
prompt-facing schema rendering.

## Where redaction is applied

- **Logs:** the structured logger redacts the event message and string fields by
  default ([`observability/logging.py`](../../src/text_to_sql/observability/logging.py)).
- **Traces:** spans carry only ids/counts/durations — never SQL text or values.
- **Errors:** the API returns a typed envelope with no stack trace, raw SQL, or
  driver text ([`api/errors.py`](../../src/text_to_sql/api/errors.py)).
- **Prompts:** only structural schema + curated non-sensitive sample values reach
  the model; live rows never do.
- **Explanations:** the explainer passes formatted values through `redact_text`.
- **Schema summary API:** `GET /schema` hides columns the caller may not view.

## What the LLM can see

Only: table/column **names and types**, curated **comments**, and a small set of
**explicitly whitelisted, non-sensitive sample values** (e.g. the enum values of
`orders.status`). No live data, no sensitive samples.

## Tests

`tests/security/test_injection_and_leakage.py` (no PII in logs / no stack traces),
`tests/unit/test_redaction.py`, `tests/unit/test_policy_cost.py` (classification
access), `tests/end_to_end/test_query_flow.py::test_schema_endpoint_filtered`.
