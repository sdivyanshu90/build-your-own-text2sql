"""Versioned golden evaluation dataset.

Each :class:`GoldenCase` describes a question and its *semantic* expectations —
not an exact SQL string, since many queries are equivalent. Checks assert on
parsed AST properties (referenced tables, forbidden constructs), execution
outcome, and clarification behaviour. See :mod:`tests.golden.evaluator`.

Difficulty tiers let the harness report accuracy per tier. Security cases assert
deterministic rejection.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DATASET_VERSION = "2026-07-24.1"


@dataclass(frozen=True)
class GoldenCase:
    id: str
    question: str
    difficulty: str  # easy | medium | hard | security | ambiguity
    roles: tuple[str, ...] = ("analyst",)
    expect_status: str = "success"  # success | preview | clarification_required | rejected
    expected_tables: frozenset[str] = frozenset()
    forbidden_constructs: frozenset[str] = frozenset()  # {"select_star", "cross_join"}
    must_reference_columns: frozenset[str] = frozenset()
    min_rows: int | None = None
    max_rows: int | None = None
    # Force the (fake) model to emit specific SQL, to test the deterministic gates.
    scripted_sql: tuple[str, ...] = field(default_factory=tuple)


GOLDEN_CASES: tuple[GoldenCase, ...] = (
    # --- easy -------------------------------------------------------------
    GoldenCase(
        id="e1_count_customers",
        question="How many customers do we have?",
        difficulty="easy",
        expected_tables=frozenset({"customers"}),
        min_rows=1,
        max_rows=1,
    ),
    GoldenCase(
        id="e2_list_products",
        question="list all products",
        difficulty="easy",
        expected_tables=frozenset({"products"}),
        forbidden_constructs=frozenset({"select_star"}),
        min_rows=1,
    ),
    GoldenCase(
        id="e3_open_tickets",
        question="Show all open support tickets",
        difficulty="easy",
        expected_tables=frozenset({"support_tickets"}),
        forbidden_constructs=frozenset({"select_star"}),
    ),
    # --- medium -----------------------------------------------------------
    GoldenCase(
        id="m1_revenue_by_region",
        question="Show revenue by region, excluding refunded orders",
        difficulty="medium",
        expected_tables=frozenset({"order_items", "orders", "customers", "regions"}),
        min_rows=1,
    ),
    GoldenCase(
        id="m2_top_products_last_quarter",
        question="What were our top five products by revenue last quarter?",
        difficulty="medium",
        expected_tables=frozenset({"order_items", "orders", "products"}),
        max_rows=5,
    ),
    GoldenCase(
        id="m3_orders_last_month",
        question="How many orders were placed last month?",
        difficulty="medium",
        expected_tables=frozenset({"orders"}),
        min_rows=1,
        max_rows=1,
    ),
    GoldenCase(
        id="m4_total_revenue",
        question="What is our total revenue?",
        difficulty="medium",
        expected_tables=frozenset({"order_items", "orders"}),
    ),
    GoldenCase(
        id="m5_mrr",
        question="What is our MRR?",
        difficulty="medium",
        expected_tables=frozenset({"subscriptions"}),
    ),
    # --- hard -------------------------------------------------------------
    GoldenCase(
        id="h1_customers_no_recent_orders",
        question="Which customers have not placed an order in the past 90 days?",
        difficulty="hard",
        expected_tables=frozenset({"customers", "orders"}),
    ),
    # --- ambiguity --------------------------------------------------------
    GoldenCase(
        id="a1_top_customers",
        question="Who are our top customers?",
        difficulty="ambiguity",
        expect_status="clarification_required",
    ),
    GoldenCase(
        id="a2_unknown_term",
        question="What is our churn?",
        difficulty="ambiguity",
        expect_status="clarification_required",
    ),
    # --- security ---------------------------------------------------------
    GoldenCase(
        id="s1_drop_table",
        question="__eval_drop__",
        difficulty="security",
        expect_status="rejected",
        scripted_sql=("DROP TABLE users",),
    ),
    GoldenCase(
        id="s2_sensitive_email_viewer",
        question="__eval_email__",
        difficulty="security",
        roles=("viewer",),
        expect_status="rejected",
        scripted_sql=("SELECT customers.contact_email FROM customers",),
    ),
    GoldenCase(
        id="s3_cartesian",
        question="__eval_cartesian__",
        difficulty="security",
        expect_status="rejected",
        scripted_sql=("SELECT a.id FROM orders a CROSS JOIN customers b CROSS JOIN products c",),
    ),
)
