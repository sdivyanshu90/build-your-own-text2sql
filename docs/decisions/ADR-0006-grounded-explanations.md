# ADR-0006: Grounded, deterministic explanations

- **Status:** Accepted
- **Context**

The response includes a natural-language answer. The obvious approach is to ask the
LLM to summarize the results. But an LLM asked to narrate will confidently state
facts that are not in the data (hallucination), which is unacceptable for an
analytics tool people will trust to make decisions.

- **Decision**

Generate the answer **deterministically from the actual result rows**
(`application/explainer.py`): report the row count, scalar/top-N values, and the
engine's own assumptions (metric formula, resolved date range), and separate
database-derived facts from assumptions and warnings. Values pass through
redaction. The model's own free-text explanation is retained only as metadata/for
preview, never as the grounded answer.

- **Consequences**

  - **Positive:** the answer can never invent facts absent from the result set —
    a guarantee, not a hope. Clear separation of "what the data says" vs "what we
    assumed" vs "caveats".
  - **Positive:** deterministic and unit-testable
    (`test_ambiguity_repair_explainer.py`).
  - **Negative:** the phrasing is templated and less fluent than an LLM summary.
    For richer prose, a *constrained* summarization step could be added that is only
    allowed to reference provided values — future work.

- **Alternatives considered**

  - *LLM-narrated summary* — rejected as the primary answer: hallucination risk.
  - *No natural-language answer* — rejected: the requirements ask for a grounded
    explanation distinguishing facts, assumptions, and interpretation.
