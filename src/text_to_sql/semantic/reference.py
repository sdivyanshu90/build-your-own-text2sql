"""The concrete semantic layer for the reference commerce schema.

This encodes the authoritative business meaning for the reference database:
metric formulas ("revenue"), entity disambiguation ("customer" vs "user"),
data classifications, table/column governance comments, and tenant columns.

In a real deployment this configuration would live in a governed store (dbt
metrics, a metrics layer, a data catalog) and be loaded at startup. Here it is
Python so it is deterministic, importable by tests, and version-controlled.
"""

from __future__ import annotations

from text_to_sql.domain.enums import DataClassification
from text_to_sql.semantic.models import (
    BusinessTerm,
    ColumnAnnotation,
    MetricDefinition,
    SemanticLayer,
    TableAnnotation,
    TermKind,
)

# Tables carrying the tenant column. ``regions`` is shared reference data.
_TENANT_TABLES = (
    "users",
    "customers",
    "products",
    "orders",
    "order_items",
    "payments",
    "refunds",
    "subscriptions",
    "support_tickets",
)

_METRICS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        name="net revenue",
        description=(
            "Authoritative revenue: gross line-item revenue minus approved refunds. "
            "This is what 'revenue' means unless a caller explicitly asks for gross."
        ),
        sql_expression=(
            "SUM(order_items.quantity * order_items.unit_price) "
            "- COALESCE((SELECT SUM(refunds.amount) FROM refunds "
            "WHERE refunds.order_id = orders.id), 0)"
        ),
        required_tables=("order_items", "orders", "refunds"),
        default_filters=("orders.status <> 'cancelled'",),
        synonyms=("revenue", "net sales"),
    ),
    MetricDefinition(
        name="gross revenue",
        description="Line-item revenue before refunds: SUM(quantity * unit_price).",
        sql_expression="SUM(order_items.quantity * order_items.unit_price)",
        required_tables=("order_items",),
        synonyms=("gross sales",),
    ),
    MetricDefinition(
        name="order count",
        description="Number of distinct orders.",
        sql_expression="COUNT(DISTINCT orders.id)",
        required_tables=("orders",),
        synonyms=("number of orders", "orders placed"),
    ),
    MetricDefinition(
        name="refund total",
        description="Total approved refund amount.",
        sql_expression="SUM(refunds.amount)",
        required_tables=("refunds",),
        synonyms=("total refunds", "refunded amount"),
    ),
    MetricDefinition(
        name="mrr",
        description="Monthly recurring revenue from active subscriptions.",
        sql_expression="SUM(subscriptions.mrr)",
        required_tables=("subscriptions",),
        default_filters=("subscriptions.status = 'active'",),
        synonyms=("monthly recurring revenue", "recurring revenue"),
    ),
)

_TERMS: tuple[BusinessTerm, ...] = (
    BusinessTerm(
        term="customer",
        kind=TermKind.ENTITY,
        definition=(
            "A customer ACCOUNT (a company that places orders). Distinct from an "
            "application 'user'. Commerce measures (revenue, orders) attach to "
            "customers, never to users."
        ),
        synonyms=("customers", "account", "accounts", "client", "clients"),
        related_tables=("customers",),
    ),
    BusinessTerm(
        term="user",
        kind=TermKind.ENTITY,
        definition="An application login belonging to an organization. Not a customer.",
        synonyms=("users", "login", "logins", "app user", "app users"),
        related_tables=("users",),
    ),
    BusinessTerm(
        term="region",
        kind=TermKind.DIMENSION,
        definition="A geographic region used to group customers and orders.",
        synonyms=("regions", "geography", "geo"),
        related_tables=("regions", "customers"),
        related_columns=("regions.name", "regions.code"),
    ),
    BusinessTerm(
        term="enterprise customer",
        kind=TermKind.FILTER,
        definition="A customer whose segment is 'enterprise'.",
        synonyms=("enterprise customers", "enterprise accounts"),
        related_tables=("customers",),
        related_columns=("customers.segment",),
    ),
    BusinessTerm(
        term="active customer",
        kind=TermKind.FILTER,
        definition="A customer that has not been soft-deleted (deleted_at IS NULL).",
        synonyms=("active customers",),
        related_tables=("customers",),
        related_columns=("customers.deleted_at",),
    ),
    BusinessTerm(
        term="refund",
        kind=TermKind.ENTITY,
        definition="An approved refund reducing net revenue.",
        synonyms=("refunds", "refunded orders"),
        related_tables=("refunds",),
    ),
    BusinessTerm(
        term="subscription",
        kind=TermKind.ENTITY,
        definition="A recurring subscription with monthly recurring revenue (MRR).",
        synonyms=("subscriptions",),
        related_tables=("subscriptions",),
    ),
)

# (table, column, classification) governance triples.
_CLASSIFICATIONS: tuple[tuple[str, str, DataClassification], ...] = (
    ("users", "email", DataClassification.PII),
    ("users", "full_name", DataClassification.PII),
    ("users", "password_hash", DataClassification.AUTH_SECRET),
    ("customers", "contact_email", DataClassification.PII),
    ("customers", "contact_phone", DataClassification.PII),
    ("payments", "amount", DataClassification.FINANCIAL),
    ("payments", "card_last4", DataClassification.PII),
    ("payments", "payment_token", DataClassification.AUTH_SECRET),
    ("refunds", "amount", DataClassification.FINANCIAL),
    ("subscriptions", "mrr", DataClassification.FINANCIAL),
)

_SAMPLE_VALUES: dict[tuple[str, str], tuple[str, ...]] = {
    ("orders", "status"): ("pending", "paid", "shipped", "refunded", "cancelled"),
    ("customers", "segment"): ("smb", "mid_market", "enterprise"),
    ("organizations", "plan"): ("free", "pro", "enterprise"),
    ("payments", "method"): ("card", "bank", "paypal"),
    ("support_tickets", "status"): ("open", "pending", "closed"),
    ("support_tickets", "priority"): ("low", "medium", "high"),
    ("regions", "code"): ("NA", "EMEA", "APAC", "LATAM"),
}

_DEFAULT_DATE_FIELDS: tuple[tuple[str, str], ...] = (
    ("orders", "ordered_at"),
    ("order_items", "ordered_at"),  # via joined orders.ordered_at
    ("payments", "paid_at"),
    ("refunds", "refunded_at"),
    ("subscriptions", "started_at"),
    ("support_tickets", "created_at"),
    ("users", "created_at"),
    ("customers", "created_at"),
)


def _build_column_annotations() -> tuple[ColumnAnnotation, ...]:
    annotations: dict[tuple[str, str], ColumnAnnotation] = {}
    for table, column, classification in _CLASSIFICATIONS:
        annotations[(table, column)] = ColumnAnnotation(
            table=table,
            column=column,
            classification=classification,
            sample_values=_SAMPLE_VALUES.get((table, column), ()),
        )
    # Add non-sensitive sample-bearing columns not already annotated.
    for (table, column), samples in _SAMPLE_VALUES.items():
        annotations.setdefault(
            (table, column),
            ColumnAnnotation(
                table=table,
                column=column,
                classification=DataClassification.INTERNAL,
                sample_values=samples,
            ),
        )
    return tuple(annotations.values())


def _build_table_annotations() -> tuple[TableAnnotation, ...]:
    result: list[TableAnnotation] = []
    for table in _TENANT_TABLES:
        result.append(TableAnnotation(table=table, tenant_column="organization_id"))
    result.append(TableAnnotation(table="regions", tenant_column=None))
    result.append(TableAnnotation(table="organizations", tenant_column="id"))
    return tuple(result)


def build_reference_semantic_layer() -> SemanticLayer:
    """Construct the immutable semantic layer for the reference schema."""
    return SemanticLayer(
        terms=_TERMS,
        metrics=_METRICS,
        column_annotations=_build_column_annotations(),
        table_annotations=_build_table_annotations(),
        default_date_fields=_DEFAULT_DATE_FIELDS,
    )
