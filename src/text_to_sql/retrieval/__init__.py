"""Relevant-schema retrieval.

Sending an entire database schema to the LLM on every request is wasteful and
degrades accuracy. The retriever selects only the tables likely relevant to a
question — using lexical matching, glossary/metric matches, and foreign-key graph
expansion — and returns them with scores and human-readable reasons.

The default implementation is fully deterministic and requires no vector
database. The :class:`~text_to_sql.retrieval.retriever.SchemaRetriever` interface
is pluggable so an embedding-based ranker can be swapped in later without changing
the orchestrator.
"""

from __future__ import annotations

from text_to_sql.retrieval.retriever import (
    LexicalSchemaRetriever,
    RetrievalResult,
    SchemaRetriever,
)

__all__ = ["LexicalSchemaRetriever", "RetrievalResult", "SchemaRetriever"]
