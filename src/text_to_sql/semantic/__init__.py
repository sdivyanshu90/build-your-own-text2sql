"""Semantic layer: business glossary, metric definitions, and annotations.

The semantic layer is the *authoritative* source of business meaning. It answers
questions the raw schema cannot:

* What does "revenue" mean? (a specific SUM minus approved refunds)
* Is a "customer" an account or an application user?
* How is "last quarter" defined? (calendar policy)
* Which columns are sensitive, and what is each table/column *for*?

By resolving these deterministically *before* prompting, we stop the LLM from
inventing inconsistent definitions and we feed the catalog its governance
metadata (classification, comments, tenant columns).
"""

from __future__ import annotations

from text_to_sql.semantic.models import (
    BusinessTerm,
    ColumnAnnotation,
    MetricDefinition,
    SemanticLayer,
    TableAnnotation,
    TermKind,
)
from text_to_sql.semantic.reference import build_reference_semantic_layer

__all__ = [
    "BusinessTerm",
    "ColumnAnnotation",
    "MetricDefinition",
    "SemanticLayer",
    "TableAnnotation",
    "TermKind",
    "build_reference_semantic_layer",
]
