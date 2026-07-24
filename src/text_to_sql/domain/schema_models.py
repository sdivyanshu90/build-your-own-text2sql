"""Normalized internal schema representation.

This is the engine's *own* model of a database — deliberately decoupled from
SQLAlchemy's reflection objects so the rest of the pipeline (retrieval, prompt
building, validation, policy) depends on a stable, serializable vocabulary
rather than on the database toolkit.

Key ideas
---------
* Identifiers are compared case-insensitively (SQL identifiers are typically
  case-insensitive unless quoted). Lookups normalize to lowercase.
* Columns carry a :class:`~text_to_sql.domain.enums.DataClassification` so the
  policy layer can reason about sensitivity without re-deriving it.
* :meth:`DatabaseSchema.serialize_for_prompt` produces a compact,
  injection-resistant textual rendering that fits a token budget — the LLM only
  ever sees *this*, never live rows or secrets.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator

from pydantic import BaseModel, ConfigDict

from text_to_sql.domain.enums import DataClassification, SQLDialect


def _norm(identifier: str) -> str:
    """Normalize an identifier for case-insensitive comparison."""
    return identifier.strip().strip('"').lower()


class ForeignKeyRef(BaseModel):
    """A foreign-key relationship from a table's column(s) to another table."""

    model_config = ConfigDict(frozen=True)

    columns: tuple[str, ...]
    referred_table: str
    referred_columns: tuple[str, ...]
    referred_schema: str | None = None


class ColumnInfo(BaseModel):
    """A single column in the normalized catalog."""

    model_config = ConfigDict(frozen=True)

    name: str
    data_type: str
    nullable: bool = True
    is_primary_key: bool = False
    comment: str | None = None
    classification: DataClassification = DataClassification.INTERNAL
    # Representative NON-sensitive sample values, only populated when explicitly
    # allowed by policy for a column. Never contains sensitive data.
    sample_values: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return _norm(self.name)


class TableInfo(BaseModel):
    """A table or view with its columns, keys, and metadata."""

    model_config = ConfigDict(frozen=True)

    name: str
    schema_name: str | None = None
    kind: str = "table"  # "table" | "view"
    comment: str | None = None
    columns: tuple[ColumnInfo, ...] = ()
    primary_key: tuple[str, ...] = ()
    foreign_keys: tuple[ForeignKeyRef, ...] = ()
    unique_constraints: tuple[tuple[str, ...], ...] = ()
    indexes: tuple[str, ...] = ()
    row_estimate: int | None = None
    # Name of the tenant-scoping column present on this table, if any. Used by
    # the query rewriter to inject mandatory tenant predicates.
    tenant_column: str | None = None

    @property
    def qualified_name(self) -> str:
        if self.schema_name:
            return f"{self.schema_name}.{self.name}"
        return self.name

    @property
    def key(self) -> str:
        return _norm(self.qualified_name)

    def column(self, name: str) -> ColumnInfo | None:
        target = _norm(name)
        for col in self.columns:
            if col.key == target:
                return col
        return None

    def has_column(self, name: str) -> bool:
        return self.column(name) is not None

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(col.name for col in self.columns)


class DatabaseSchema(BaseModel):
    """The full normalized catalog for one data source."""

    model_config = ConfigDict(frozen=True)

    dialect: SQLDialect
    tables: tuple[TableInfo, ...] = ()
    # Monotonic version/hash used for cache invalidation and drift detection.
    version: str = "0"

    # ------------------------------------------------------------------ #
    # Lookups
    # ------------------------------------------------------------------ #
    def _index(self) -> dict[str, TableInfo]:
        # Built on demand; the model is frozen so we cannot cache on the instance
        # without extra machinery — schemas are small, so this is cheap.
        idx: dict[str, TableInfo] = {}
        for table in self.tables:
            idx[table.key] = table
            # Also index by bare name for unqualified lookups.
            idx.setdefault(_norm(table.name), table)
        return idx

    def table(self, name: str) -> TableInfo | None:
        """Look up a table by qualified or bare name (case-insensitive)."""
        return self._index().get(_norm(name))

    def has_table(self, name: str) -> bool:
        return self.table(name) is not None

    def iter_columns(self) -> Iterator[tuple[TableInfo, ColumnInfo]]:
        for table in self.tables:
            for column in table.columns:
                yield table, column

    @property
    def table_names(self) -> tuple[str, ...]:
        return tuple(t.qualified_name for t in self.tables)

    # ------------------------------------------------------------------ #
    # Join graph
    # ------------------------------------------------------------------ #
    def join_graph(self) -> dict[str, set[str]]:
        """Adjacency map of table-key -> set of directly join-related table-keys.

        Built from declared foreign keys (in both directions). Used by retrieval
        to expand a seed set of tables along join paths so required bridge tables
        are not omitted.
        """
        graph: dict[str, set[str]] = defaultdict(set)
        index = self._index()
        for table in self.tables:
            for fk in table.foreign_keys:
                referred = index.get(_norm(fk.referred_table))
                if referred is None:
                    continue
                graph[table.key].add(referred.key)
                graph[referred.key].add(table.key)
        return graph

    def neighbors(self, table_key: str, *, hops: int = 1) -> set[str]:
        """Return table keys reachable from ``table_key`` within ``hops`` joins."""
        graph = self.join_graph()
        frontier = {_norm(table_key)}
        seen = set(frontier)
        for _ in range(max(0, hops)):
            nxt: set[str] = set()
            for node in frontier:
                nxt |= graph.get(node, set())
            nxt -= seen
            seen |= nxt
            frontier = nxt
            if not frontier:
                break
        seen.discard(_norm(table_key))
        return seen

    # ------------------------------------------------------------------ #
    # Prompt serialization (token-budget aware, injection resistant)
    # ------------------------------------------------------------------ #
    def subset(self, table_names: Iterable[str]) -> DatabaseSchema:
        """Return a new schema containing only the named tables."""
        wanted = {_norm(name) for name in table_names}
        kept = tuple(t for t in self.tables if t.key in wanted or _norm(t.name) in wanted)
        return DatabaseSchema(dialect=self.dialect, tables=kept, version=self.version)

    def serialize_for_prompt(self, *, max_chars: int = 8000) -> str:
        """Render a compact DDL-like description for the LLM prompt.

        The rendering deliberately:

        * omits live data and sensitive columns' sample values,
        * neutralizes comment text (comments are untrusted metadata and are
          rendered on a single line, prefixed, so an injected instruction cannot
          masquerade as a real prompt directive),
        * truncates to ``max_chars`` to respect the token budget, emitting an
          explicit truncation marker so the model knows context is partial.
        """
        lines: list[str] = []
        for table in self.tables:
            header = f"TABLE {table.qualified_name}"
            if table.kind == "view":
                header = f"VIEW {table.qualified_name}"
            if table.comment:
                header += f"  -- {_flatten_comment(table.comment)}"
            lines.append(header)
            for col in table.columns:
                flags: list[str] = [col.data_type]
                if col.is_primary_key:
                    flags.append("PK")
                if not col.nullable:
                    flags.append("NOT NULL")
                if col.classification.is_sensitive:
                    flags.append(f"[{col.classification.value.upper()}]")
                col_line = f"  - {col.name} ({', '.join(flags)})"
                if col.comment:
                    col_line += f"  -- {_flatten_comment(col.comment)}"
                lines.append(col_line)
            for fk in table.foreign_keys:
                lines.append(
                    f"  FK ({', '.join(fk.columns)}) -> "
                    f"{fk.referred_table} ({', '.join(fk.referred_columns)})"
                )
            lines.append("")
        text = "\n".join(lines).rstrip()
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "\n-- [schema truncated to fit token budget]"
        return text


_MAX_COMMENT_LEN = 200


def _flatten_comment(comment: str) -> str:
    """Collapse a comment to a single, length-bounded line.

    Comments come from the database and are *untrusted*. Collapsing newlines and
    bounding length prevents a multi-line "comment" from injecting fake prompt
    sections. Deeper prompt-injection scrubbing happens in the prompt builder.
    """
    flat = " ".join(comment.split())
    if len(flat) > _MAX_COMMENT_LEN:
        flat = flat[:_MAX_COMMENT_LEN] + "…"
    return flat
