"""Deterministic fake LLM provider.

Two responsibilities:

1. **Scripted mode** — tests register exact SQL strings for a question (and,
   optionally, a *sequence* of strings to model a repair loop). This lets the
   suite force ANY output — destructive SQL, unknown columns, injected payloads —
   to prove the deterministic downstream layers reject or repair them. The LLM is
   never trusted, so being able to make it "misbehave" on demand is essential.

2. **Heuristic mode** — for the reference commerce schema, a small rules engine
   produces correct SQL for common analytical questions (counts, listings,
   revenue rankings, revenue-by-dimension, cohort-style "not ordered recently").
   This powers the runnable examples, the golden suite's easy/medium tiers, and
   local demos with zero credentials.

Determinism is the whole point: identical inputs always yield identical SQL, so
tests and the evaluation baseline are stable.
"""

from __future__ import annotations

import re

from text_to_sql.domain.enums import SQLDialect
from text_to_sql.domain.schema_models import DatabaseSchema
from text_to_sql.llm.base import (
    GenerationRequest,
    GenerationResponse,
    TokenUsage,
)
from text_to_sql.semantic.models import SemanticLayer

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twenty": 20,
}


def _normalize_question(question: str) -> str:
    return " ".join(question.lower().split())


def _extract_limit(text: str, default: int) -> int:
    m = re.search(r"\btop\s+(\d+)\b", text)
    if m:
        return int(m.group(1))
    for word, value in _NUMBER_WORDS.items():
        if re.search(rf"\btop\s+{word}\b", text):
            return value
    return default


class DeterministicFakeProvider:
    """A credential-free provider for tests, CI, and local demos."""

    def __init__(
        self,
        *,
        model: str = "deterministic-fake",
        scripts: dict[str, list[str]] | None = None,
    ) -> None:
        self._model = model
        # Normalized question -> ordered SQL candidates (index by repair attempt).
        self._scripts: dict[str, list[str]] = {
            _normalize_question(k): v for k, v in (scripts or {}).items()
        }

    # -- Test helpers ---------------------------------------------------------
    def script(self, question: str, sql_candidates: list[str]) -> None:
        """Register scripted SQL candidate(s) for a question."""
        self._scripts[_normalize_question(question)] = list(sql_candidates)

    # -- Provider protocol ----------------------------------------------------
    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return self._model

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        attempt_index = request.repair.attempt if request.repair else 0
        normalized = _normalize_question(request.question)

        scripted = self._scripts.get(normalized)
        if scripted is not None:
            sql = scripted[min(attempt_index, len(scripted) - 1)]
            return self._response(
                request,
                sql=sql,
                explanation="Scripted deterministic response.",
                confidence=0.9,
                assumptions=(),
            )

        generated = _HeuristicGenerator(
            request.schema_subset, request.semantic_layer, request.dialect
        ).generate(request)
        return self._response(
            request,
            sql=generated.sql,
            explanation=generated.explanation,
            confidence=generated.confidence,
            assumptions=generated.assumptions,
            referenced_tables=generated.tables,
        )

    def _response(
        self,
        request: GenerationRequest,
        *,
        sql: str,
        explanation: str,
        confidence: float,
        assumptions: tuple[str, ...] = (),
        referenced_tables: tuple[str, ...] = (),
    ) -> GenerationResponse:
        # Token accounting is approximated (chars/4) so cost metrics have signal.
        prompt_len = len(request.prompt.system) + len(request.prompt.user)
        return GenerationResponse(
            sql=sql,
            dialect=request.dialect,
            explanation=explanation,
            referenced_tables=referenced_tables,
            assumptions=assumptions,
            confidence=confidence,
            prompt_version=request.prompt.version,
            provider="fake",
            model=self._model,
            usage=TokenUsage(prompt_tokens=prompt_len // 4, completion_tokens=len(sql) // 4),
        )


class _Generated:
    def __init__(
        self,
        sql: str,
        explanation: str,
        confidence: float,
        assumptions: tuple[str, ...],
        tables: tuple[str, ...],
    ) -> None:
        self.sql = sql
        self.explanation = explanation
        self.confidence = confidence
        self.assumptions = assumptions
        self.tables = tables


# Entity keyword -> reference table name.
_ENTITY_TABLES = {
    "product": "products",
    "customer": "customers",
    "account": "customers",
    "order": "orders",
    "user": "users",
    "region": "regions",
    "payment": "payments",
    "refund": "refunds",
    "subscription": "subscriptions",
    "ticket": "support_tickets",
    "organization": "organizations",
}

_STATUS_VALUES = {
    "open",
    "pending",
    "closed",
    "paid",
    "shipped",
    "refunded",
    "cancelled",
    "active",
    "canceled",
    "past_due",
    "succeeded",
    "failed",
}


class _HeuristicGenerator:
    """Rule-based NL->SQL for the reference schema (deterministic)."""

    def __init__(
        self,
        schema: DatabaseSchema,
        semantic: SemanticLayer,
        dialect: SQLDialect,
    ) -> None:
        self._schema = schema
        self._semantic = semantic
        self._dialect = dialect

    def generate(self, request: GenerationRequest) -> _Generated:
        q = _normalize_question(request.question)
        date = request.resolved_date
        limit = request.max_rows

        # 1. Top-N products by revenue ------------------------------------
        if ("top" in q or "best" in q or "highest" in q) and "revenue" in q and "product" in q:
            return self._top_products_by_revenue(q, date)

        # 2. Revenue by dimension -----------------------------------------
        if "revenue" in q and " by " in q:
            return self._revenue_by_dimension(q, date)

        # 3. Customers with no recent orders ------------------------------
        if (
            ("not" in q or "haven't" in q or "have not" in q or "without" in q)
            and "order" in q
            and date
        ):
            return self._customers_without_orders(date)

        # 4. MRR ----------------------------------------------------------
        if "mrr" in q or "recurring revenue" in q:
            return _Generated(
                "SELECT SUM(subscriptions.mrr) AS mrr FROM subscriptions "
                "WHERE subscriptions.status = 'active'",
                "Monthly recurring revenue from active subscriptions.",
                0.9,
                ("MRR is the sum of mrr over active subscriptions.",),
                ("subscriptions",),
            )

        # 5. Scalar revenue ----------------------------------------------
        if "revenue" in q or "gross sales" in q:
            return self._scalar_revenue(q, date)

        # 6. Counts -------------------------------------------------------
        if "how many" in q or "number of" in q or q.startswith("count"):
            return self._count(q, date)

        # 7. Status-filtered listing -------------------------------------
        status = self._detect_status(q)
        entity_table = self._detect_entity_table(q)
        if status and entity_table:
            return self._status_listing(entity_table, status, limit)

        # 8. Generic listing ---------------------------------------------
        if entity_table and ("list" in q or "show" in q or "all" in q or q.startswith("what")):
            return self._listing(entity_table, limit, date)

        # 9. Fallback -----------------------------------------------------
        return self._fallback(entity_table, limit)

    # ------------------------------------------------------------------ #
    def _date_clause(self, column: str, date) -> str:  # type: ignore[no-untyped-def]
        return f"{column} >= '{date.start_iso}' AND {column} < '{date.end_iso}'"

    def _month_expr(self, column: str) -> str:
        if self._dialect == SQLDialect.POSTGRES:
            return f"to_char({column}, 'YYYY-MM')"
        return f"strftime('%Y-%m', {column})"

    def _top_products_by_revenue(self, q: str, date) -> _Generated:  # type: ignore[no-untyped-def]
        k = _extract_limit(q, 5)
        where = f"\nWHERE {self._date_clause('orders.ordered_at', date)}" if date else ""
        sql = (
            "SELECT products.name AS product, "
            "SUM(order_items.quantity * order_items.unit_price) AS revenue\n"
            "FROM order_items\n"
            "JOIN orders ON orders.id = order_items.order_id\n"
            "JOIN products ON products.id = order_items.product_id"
            f"{where}\n"
            "GROUP BY products.name\n"
            "ORDER BY revenue DESC\n"
            f"LIMIT {k}"
        )
        assumptions = ["Revenue = SUM(quantity * unit_price) over order line items."]
        if date:
            assumptions.append(f"Restricted to {date.description}.")
        return _Generated(
            sql,
            f"Top {k} products ranked by line-item revenue"
            + (f" during {date.description}." if date else "."),
            0.9,
            tuple(assumptions),
            ("order_items", "orders", "products"),
        )

    def _revenue_by_dimension(self, q: str, date) -> _Generated:  # type: ignore[no-untyped-def]
        joins = ["JOIN orders ON orders.id = order_items.order_id"]
        tables = ["order_items", "orders"]
        if "region" in q:
            joins.append("JOIN customers ON customers.id = orders.customer_id")
            joins.append("JOIN regions ON regions.id = customers.region_id")
            dim_expr, dim_alias = "regions.name", "region"
            tables += ["customers", "regions"]
        elif "category" in q:
            joins.append("JOIN products ON products.id = order_items.product_id")
            dim_expr, dim_alias = "products.category", "category"
            tables.append("products")
        elif "product" in q:
            joins.append("JOIN products ON products.id = order_items.product_id")
            dim_expr, dim_alias = "products.name", "product"
            tables.append("products")
        elif "month" in q:
            dim_expr, dim_alias = self._month_expr("orders.ordered_at"), "month"
        else:  # default: by customer
            joins.append("JOIN customers ON customers.id = orders.customer_id")
            dim_expr, dim_alias = "customers.name", "customer"
            tables.append("customers")

        conditions: list[str] = []
        assumptions = ["Revenue = SUM(quantity * unit_price) over order line items."]
        if "exclud" in q and "refund" in q:
            conditions.append("orders.status <> 'refunded'")
            assumptions.append("Excluded orders with status 'refunded'.")
        if date:
            conditions.append(self._date_clause("orders.ordered_at", date))
            assumptions.append(f"Restricted to {date.description}.")
        where = ("\nWHERE " + " AND ".join(conditions)) if conditions else ""

        sql = (
            f"SELECT {dim_expr} AS {dim_alias}, "
            "SUM(order_items.quantity * order_items.unit_price) AS revenue\n"
            "FROM order_items\n" + "\n".join(joins) + f"{where}\n"
            f"GROUP BY {dim_expr}\n"
            "ORDER BY revenue DESC"
        )
        return _Generated(
            sql,
            f"Revenue grouped by {dim_alias}.",
            0.88,
            tuple(assumptions),
            tuple(tables),
        )

    def _scalar_revenue(self, q: str, date) -> _Generated:  # type: ignore[no-untyped-def]
        conditions: list[str] = []
        assumptions = ["Revenue = SUM(quantity * unit_price) over order line items."]
        if date:
            conditions.append(self._date_clause("orders.ordered_at", date))
            assumptions.append(f"Restricted to {date.description}.")
        where = ("\nWHERE " + " AND ".join(conditions)) if conditions else ""
        sql = (
            "SELECT SUM(order_items.quantity * order_items.unit_price) AS revenue\n"
            "FROM order_items\n"
            "JOIN orders ON orders.id = order_items.order_id"
            f"{where}"
        )
        return _Generated(
            sql, "Total line-item revenue.", 0.85, tuple(assumptions), ("order_items", "orders")
        )

    def _customers_without_orders(self, date) -> _Generated:  # type: ignore[no-untyped-def]
        sql = (
            "SELECT customers.id, customers.name\n"
            "FROM customers\n"
            "WHERE NOT EXISTS (\n"
            "  SELECT 1 FROM orders\n"
            "  WHERE orders.customer_id = customers.id\n"
            f"    AND orders.ordered_at >= '{date.start_iso}'\n"
            ")"
        )
        return _Generated(
            sql,
            f"Customers with no orders since the start of {date.description}.",
            0.87,
            (f"'Recent' means on/after {date.start_iso} ({date.description}).",),
            ("customers", "orders"),
        )

    def _count(self, q: str, date) -> _Generated:  # type: ignore[no-untyped-def]
        table = self._detect_entity_table(q) or "customers"
        where = ""
        assumptions: tuple[str, ...] = ()
        if date:
            date_field = self._semantic.default_date_field(table) or "created_at"
            col = f"{table}.{date_field}"
            where = f"\nWHERE {self._date_clause(col, date)}"
            assumptions = (f"Counted rows within {date.description} using {col}.",)
        sql = f"SELECT COUNT(*) AS count\nFROM {table}{where}"
        return _Generated(sql, f"Count of rows in {table}.", 0.85, assumptions, (table,))

    def _status_listing(self, table: str, status: str, limit: int) -> _Generated:
        cols = self._safe_columns(table)
        col_list = ", ".join(f"{table}.{c}" for c in cols)
        sql = f"SELECT {col_list}\nFROM {table}\nWHERE {table}.status = '{status}'\nLIMIT {limit}"
        return _Generated(sql, f"{table} filtered to status '{status}'.", 0.86, (), (table,))

    def _listing(self, table: str, limit: int, date) -> _Generated:  # type: ignore[no-untyped-def]
        cols = self._safe_columns(table)
        col_list = ", ".join(f"{table}.{c}" for c in cols)
        sql = f"SELECT {col_list}\nFROM {table}\nLIMIT {limit}"
        return _Generated(sql, f"Listing of {table}.", 0.8, (), (table,))

    def _fallback(self, table: str | None, limit: int) -> _Generated:
        target = table or (self._schema.tables[0].name if self._schema.tables else "organizations")
        cols = self._safe_columns(target)
        col_list = ", ".join(f"{target}.{c}" for c in cols)
        sql = f"SELECT {col_list}\nFROM {target}\nLIMIT {limit}"
        return _Generated(
            sql,
            f"Best-effort listing of {target} (no strong pattern matched).",
            0.4,
            ("Low confidence: the question did not match a known pattern.",),
            (target,),
        )

    # ------------------------------------------------------------------ #
    def _detect_entity_table(self, q: str) -> str | None:
        # Prefer whichever entity keyword appears; ties broken by keyword order.
        for keyword, table in _ENTITY_TABLES.items():
            if re.search(rf"\b{keyword}s?\b", q) and self._schema.has_table(table):
                return table
        return None

    def _detect_status(self, q: str) -> str | None:
        for token in re.split(r"[^a-z_]+", q):
            if token in _STATUS_VALUES:
                return token
        return None

    def _safe_columns(self, table_name: str) -> list[str]:
        """Non-sensitive columns for a listing (avoids selecting secrets/PII)."""
        table = self._schema.table(table_name)
        if table is None:
            return ["id"]
        cols = [c.name for c in table.columns if not c.classification.is_sensitive]
        return cols[:8] or ["id"]
