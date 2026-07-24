# ADR-0001: Deterministic security enforced after generation

- **Status:** Accepted
- **Context**

An LLM that writes SQL is, by definition, an untrusted code generator. It can be
wrong, and it can be manipulated (directly or via injected metadata). Two common
approaches are (a) trust the prompt to keep the model in line, and (b) validate the
output. Approach (a) offers no guarantee: one successful injection or regression
crosses a security boundary.

- **Decision**

Treat all model output as an untrusted *proposal*. Enforce every security property
in deterministic code that runs **after** generation and operates on the parsed
AST and the authenticated context: parse → AST validate → policy → tenant rewrite →
re-validate → cost analysis → read-only execution. Prompt hardening is retained
only as defense in depth, never as a control.

- **Consequences**

  - **Positive:** tenant isolation, read-only enforcement, sensitive-column
    protection, and cost limits hold even if the model is fully compromised. These
    become *testable invariants* (see the security and property suites).
  - **Positive:** the security core is pure functions over an AST + context, so it
    is unit-testable without a server, database, or real LLM.
  - **Negative:** some valid-but-exotic SQL may be rejected (safe failure). The
    engine cannot execute what it cannot prove safe.
  - **Negative:** duplication of intent (the prompt *and* the validator both say
    "read-only"); accepted because the prompt is advisory and the validator is the
    guarantee.

- **Alternatives considered**

  - *Prompt-only guardrails* — rejected: not a guarantee.
  - *Fine-tuned "safe" model* — rejected as a primary control: still probabilistic.
  - *Sandbox and let it run, then filter results* — rejected: destructive
    statements and cross-tenant reads must be prevented, not observed.
