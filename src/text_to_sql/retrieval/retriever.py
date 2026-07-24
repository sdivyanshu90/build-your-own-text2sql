"""Deterministic lexical + graph-based schema retriever.

Algorithm
---------
1. **Score** every table from several deterministic signals:
   * lexical overlap between question tokens and the table's name/columns/comment,
   * glossary term matches whose ``related_tables`` include the table,
   * metric matches whose ``required_tables`` include the table.
2. Choose the top-scoring tables as **seeds** (bounded by ``top_k``).
3. **Bridge**: add every table that lies on a shortest foreign-key path between
   any two seeds, so required join tables are never dropped.
4. If nothing scored (unusual), fall back to a deterministic default set.

The result is a subset schema plus per-object scores and reasons. This is the
only schema the LLM ever sees.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from typing import Protocol

from text_to_sql.domain.models import RetrievedObject
from text_to_sql.domain.schema_models import DatabaseSchema
from text_to_sql.semantic.models import SemanticLayer

# Scoring weights (documented so ranking behaviour is transparent and tunable).
_W_TABLE_NAME = 5.0
_W_COLUMN_NAME = 2.0
_W_COMMENT = 1.0
_W_GLOSSARY = 4.0
_W_METRIC = 4.0
_BRIDGE_SCORE = 0.5

_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "by",
        "for",
        "to",
        "in",
        "on",
        "and",
        "or",
        "with",
        "show",
        "list",
        "get",
        "give",
        "me",
        "our",
        "what",
        "which",
        "how",
        "many",
        "much",
        "was",
        "were",
        "is",
        "are",
        "that",
        "this",
        "over",
        "per",
        "each",
        "all",
        "top",
        "last",
        "past",
        "year",
        "month",
        "quarter",
        "week",
        "day",
        "days",
        "compare",
        "between",
        "from",
        "have",
        "has",
        "not",
        "who",
        "their",
        "them",
        "did",
        "do",
        "does",
        "count",
        "number",
    }
)


def _tokenize(text: str) -> set[str]:
    raw = re.split(r"[^a-z0-9]+", text.lower())
    tokens: set[str] = set()
    for tok in raw:
        if not tok or tok in _STOPWORDS or len(tok) < 3:
            continue
        tokens.add(tok)
        # naive singularization so "products" matches "product"
        if tok.endswith("s") and len(tok) > 3:
            tokens.add(tok[:-1])
    return tokens


@dataclass
class RetrievalResult:
    """The retriever's output."""

    selected: list[RetrievedObject]
    schema_subset: DatabaseSchema

    @property
    def table_names(self) -> list[str]:
        return [obj.table for obj in self.selected]


class SchemaRetriever(Protocol):
    """Pluggable retrieval interface (lexical default; embeddings later)."""

    def retrieve(self, question: str, schema: DatabaseSchema) -> RetrievalResult: ...


class LexicalSchemaRetriever:
    """Deterministic retriever combining lexical, glossary, and graph signals."""

    def __init__(self, semantic_layer: SemanticLayer, *, top_k: int = 12) -> None:
        self._semantic = semantic_layer
        self._top_k = top_k

    def retrieve(self, question: str, schema: DatabaseSchema) -> RetrievalResult:
        tokens = _tokenize(question)
        scores: dict[str, float] = {}
        reasons: dict[str, list[str]] = {}

        def add(table_key: str, amount: float, reason: str) -> None:
            scores[table_key] = scores.get(table_key, 0.0) + amount
            reasons.setdefault(table_key, []).append(reason)

        # 1. Lexical signals ------------------------------------------------
        for table in schema.tables:
            name_tokens = _tokenize(table.name)
            if tokens & name_tokens:
                overlap = ", ".join(sorted(tokens & name_tokens))
                add(table.key, _W_TABLE_NAME, f"table name matches '{overlap}'")
            col_hits = {col.name for col in table.columns if _tokenize(col.name) & tokens}
            if col_hits:
                add(
                    table.key,
                    _W_COLUMN_NAME * min(len(col_hits), 3),
                    f"columns match: {', '.join(sorted(col_hits))}",
                )
            if table.comment and (_tokenize(table.comment) & tokens):
                add(table.key, _W_COMMENT, "description matches question terms")

        # 2. Glossary terms -------------------------------------------------
        for term in self._semantic.find_surface_forms(question):
            for related in term.related_tables:
                t = schema.table(related)
                if t is not None:
                    add(t.key, _W_GLOSSARY, f"glossary term '{term.term}'")

        # 3. Metrics --------------------------------------------------------
        for metric in self._semantic.find_metrics(question):
            for required in metric.required_tables:
                t = schema.table(required)
                if t is not None:
                    add(t.key, _W_METRIC, f"metric '{metric.name}' requires this table")

        # 4. Seeds ----------------------------------------------------------
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        seeds = [key for key, _ in ranked[: self._top_k]]

        if not seeds:
            # Deterministic fallback: keep behaviour predictable when a question
            # has no lexical/semantic overlap at all.
            fallback = sorted(t.key for t in schema.tables)[: self._top_k]
            for key in fallback:
                add(key, 0.1, "fallback: no strong signal, included by default")
            seeds = fallback

        # 5. Bridge along shortest FK paths between seeds -------------------
        bridged = self._add_bridges(schema, seeds)
        for key in bridged:
            if key not in scores:
                add(key, _BRIDGE_SCORE, "join bridge required to connect selected tables")

        selected_keys = list(dict.fromkeys(seeds + list(bridged)))

        selected = [
            RetrievedObject(
                table=self._qualified(schema, key),
                score=round(scores.get(key, _BRIDGE_SCORE), 3),
                reason="; ".join(reasons.get(key, ["included"])),
            )
            for key in selected_keys
        ]
        selected.sort(key=lambda o: (-o.score, o.table))

        subset = schema.subset([self._qualified(schema, k) for k in selected_keys])
        return RetrievalResult(selected=selected, schema_subset=subset)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _qualified(schema: DatabaseSchema, key: str) -> str:
        table = schema.table(key)
        return table.qualified_name if table else key

    def _add_bridges(self, schema: DatabaseSchema, seeds: list[str]) -> set[str]:
        graph = schema.join_graph()
        bridge_nodes: set[str] = set(seeds)
        for i, src in enumerate(seeds):
            for dst in seeds[i + 1 :]:
                path = _shortest_path(graph, src, dst)
                if path:
                    bridge_nodes.update(path)
        return bridge_nodes - set(seeds)


def _shortest_path(graph: dict[str, set[str]], src: str, dst: str) -> list[str]:
    """BFS shortest path (inclusive of endpoints); empty if unreachable."""
    if src == dst:
        return [src]
    prev: dict[str, str] = {src: src}
    queue: deque[str] = deque([src])
    while queue:
        node = queue.popleft()
        for nbr in sorted(graph.get(node, set())):
            if nbr in prev:
                continue
            prev[nbr] = node
            if nbr == dst:
                # reconstruct
                path = [dst]
                cur = dst
                while cur != src:
                    cur = prev[cur]
                    path.append(cur)
                return list(reversed(path))
            queue.append(nbr)
    return []
