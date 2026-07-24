"""Ambiguity detection and clarification.

Runs *before* generation. It asks: could a reasonable reading of this question
materially change the result? If so, return a structured
:class:`~text_to_sql.domain.models.Clarification` instead of guessing. It does
**not** clarify things that a documented default resolves safely (e.g. relative
dates → calendar policy) — per the requirement to avoid trivial clarifications.

Detection is deterministic and glossary-aware. The rules, in priority order:

1. **Unknown term** — the question uses a recognized-but-undefined analytics term
   (churn, LTV, CAC, ARR, retention, NPS) that has no authoritative definition.
2. **Ambiguous metric** — "sales" with no qualifier (net vs gross vs order count).
3. **Unspecified measure** — "top/best/most <entity>" with no measure.
4. **Entity reference** — a commerce measure attached to "users" (customers vs
   application users).
"""

from __future__ import annotations

import re

from text_to_sql.domain.enums import AmbiguityCategory
from text_to_sql.domain.models import Clarification, ClarificationInterpretation
from text_to_sql.semantic.models import SemanticLayer

# Analytics terms people say but that require an authoritative definition here.
_UNDEFINED_TERMS = {
    "churn": "customer churn rate",
    "ltv": "customer lifetime value",
    "cac": "customer acquisition cost",
    "arr": "annual recurring revenue",
    "retention": "a retention metric",
    "nps": "net promoter score",
    "conversion rate": "a conversion-rate metric",
}

_MEASURE_WORDS = {
    "revenue",
    "sales",
    "orders",
    "order",
    "count",
    "margin",
    "profit",
    "quantity",
    "spend",
    "amount",
    "mrr",
    "tickets",
    "value",
    "number",
}

_RANK_WORDS = {"top", "best", "highest", "largest", "most", "biggest", "leading"}
_ENTITY_WORDS = {
    "customer",
    "customers",
    "product",
    "products",
    "region",
    "regions",
    "account",
    "accounts",
    "user",
    "users",
}


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


class AmbiguityDetector:
    """Detects material ambiguity and proposes a clarification."""

    def __init__(self, semantic: SemanticLayer) -> None:
        self._semantic = semantic

    def detect(self, question: str) -> Clarification | None:
        q = question.lower()

        clarification = (
            self._unknown_term(q)
            or self._ambiguous_metric(q)
            or self._unspecified_measure(q)
            or self._entity_reference(q)
        )
        return clarification

    # ------------------------------------------------------------------ #
    def _unknown_term(self, q: str) -> Clarification | None:
        for term, label in _UNDEFINED_TERMS.items():
            if _has_word(q, term):
                # Only ambiguous if we truly have no authoritative definition.
                if self._semantic.resolve_metric(term) or self._semantic.resolve_term(term):
                    continue
                return Clarification(
                    category=AmbiguityCategory.UNKNOWN_TERM,
                    explanation=(
                        f"The term '{term}' ({label}) has no authoritative definition "
                        "in the semantic layer, so it cannot be computed safely."
                    ),
                    interpretations=[
                        ClarificationInterpretation(
                            label="Provide a definition",
                            description=f"Define how '{term}' should be calculated.",
                        )
                    ],
                    suggested_question=(
                        f"How should '{term}' be defined (which tables/columns and formula)?"
                    ),
                    confidence=0.8,
                )
        return None

    def _ambiguous_metric(self, q: str) -> Clarification | None:
        if not _has_word(q, "sales"):
            return None
        # If the user qualified it, it's not ambiguous.
        if any(_has_word(q, w) for w in ("revenue", "gross", "net", "count", "number")):
            return None
        return Clarification(
            category=AmbiguityCategory.METRIC_DEFINITION,
            explanation="'Sales' can mean net revenue, gross revenue, or the number of orders.",
            interpretations=[
                ClarificationInterpretation(
                    label="Net revenue", description="Line-item revenue minus approved refunds."
                ),
                ClarificationInterpretation(
                    label="Gross revenue", description="Line-item revenue before refunds."
                ),
                ClarificationInterpretation(
                    label="Order count", description="The number of orders placed."
                ),
            ],
            suggested_question="By 'sales' do you mean net revenue, gross revenue, or order count?",
            confidence=0.75,
        )

    def _unspecified_measure(self, q: str) -> Clarification | None:
        if not any(_has_word(q, w) for w in _RANK_WORDS):
            return None
        if not any(_has_word(q, w) for w in _ENTITY_WORDS):
            return None
        # If a measure is present ("by revenue", "by orders"), it's specified.
        if any(_has_word(q, w) for w in _MEASURE_WORDS):
            return None
        return Clarification(
            category=AmbiguityCategory.MEASURE_UNSPECIFIED,
            explanation="A ranking was requested but the measure to rank by is unspecified.",
            interpretations=[
                ClarificationInterpretation(label="By revenue", description="Rank by net revenue."),
                ClarificationInterpretation(
                    label="By order count", description="Rank by number of orders."
                ),
                ClarificationInterpretation(
                    label="By MRR", description="Rank by monthly recurring revenue."
                ),
            ],
            suggested_question=(
                "Which measure should the ranking use — revenue, order count, or MRR?"
            ),
            confidence=0.7,
        )

    def _entity_reference(self, q: str) -> Clarification | None:
        commerce = any(
            _has_word(q, w) for w in ("revenue", "orders", "order", "sales", "spend", "mrr")
        )
        if commerce and (_has_word(q, "user") or _has_word(q, "users")):
            return Clarification(
                category=AmbiguityCategory.ENTITY_REFERENCE,
                explanation=(
                    "Commerce measures attach to customer accounts, but the question "
                    "mentions 'users' (application logins). These are different entities."
                ),
                interpretations=[
                    ClarificationInterpretation(
                        label="Customers", description="Customer accounts that place orders."
                    ),
                    ClarificationInterpretation(
                        label="Application users", description="Login users of the application."
                    ),
                ],
                suggested_question="Do you mean customer accounts or application users?",
                confidence=0.65,
            )
        return None
