"""Reference domain schema (single source of truth).

This module defines the reference database used for development, tests, and the
golden evaluation suite as SQLAlchemy Core :class:`~sqlalchemy.MetaData`. Defining
it once here means:

* the Alembic initial migration can create it,
* the ``init_db`` script can create it for SQLite,
* the seed script and tests can reference the exact ``Table`` objects,

so schema, migrations, and fixtures can never drift apart.

The schema is a realistic multi-tenant B2B commerce model. Tenant isolation is
anchored on ``organization_id`` (present on every tenant-scoped table). It
includes sensitive columns (email, phone, ``password_hash``, ``payment_token``,
``card_last4``, monetary values), soft-deletion (``deleted_at``), status enums,
nullable relationships, and foreign-key chains suitable for joins, aggregations,
window functions, and refund math.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
)

# Deterministic naming convention so Alembic autogenerate is stable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


organizations = Table(
    "organizations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(200), nullable=False, comment="Organization / tenant display name."),
    Column("plan", String(20), nullable=False, comment="Billing plan: free|pro|enterprise."),
    Column("created_at", DateTime, nullable=False),
    Column(
        "deleted_at", DateTime, nullable=True, comment="Soft-deletion timestamp; NULL if active."
    ),
    CheckConstraint("plan in ('free','pro','enterprise')", name="plan_valid"),
    comment="Tenants. Every tenant-scoped table references organizations.id.",
)

regions = Table(
    "regions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False, comment="Human-readable region name."),
    Column("code", String(10), nullable=False, comment="Short region code, e.g. NA, EMEA."),
    UniqueConstraint("code", name="code"),
    comment="Geographic regions (shared reference data, not tenant-scoped).",
)

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("organization_id", Integer, ForeignKey("organizations.id"), nullable=False),
    Column("email", String(320), nullable=False, comment="Login email address (PII)."),
    Column("full_name", String(200), nullable=False, comment="User full name (PII)."),
    Column(
        "password_hash",
        String(200),
        nullable=False,
        comment="Salted password hash (authentication secret; never selectable).",
    ),
    Column("role", String(30), nullable=False, comment="App role: admin|analyst|viewer."),
    Column("created_at", DateTime, nullable=False),
    Column("deleted_at", DateTime, nullable=True),
    UniqueConstraint("organization_id", "email", name="org_email"),
    Index("ix_users_organization_id", "organization_id"),
    comment="Application users belonging to an organization.",
)

customers = Table(
    "customers",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("organization_id", Integer, ForeignKey("organizations.id"), nullable=False),
    Column("region_id", Integer, ForeignKey("regions.id"), nullable=True),
    Column("name", String(200), nullable=False, comment="Customer account/company name."),
    Column("contact_email", String(320), nullable=True, comment="Primary contact email (PII)."),
    Column("contact_phone", String(40), nullable=True, comment="Primary contact phone (PII)."),
    Column("segment", String(20), nullable=False, comment="Segment: smb|mid_market|enterprise."),
    Column("created_at", DateTime, nullable=False),
    Column("deleted_at", DateTime, nullable=True),
    Index("ix_customers_organization_id", "organization_id"),
    Index("ix_customers_region_id", "region_id"),
    comment="Customer accounts (companies), distinct from application users.",
)

products = Table(
    "products",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("organization_id", Integer, ForeignKey("organizations.id"), nullable=False),
    Column("sku", String(40), nullable=False, comment="Stock-keeping unit."),
    Column("name", String(200), nullable=False),
    Column("category", String(60), nullable=False, comment="Product category."),
    Column("unit_price", Numeric(12, 2), nullable=False, comment="List unit price."),
    Column("active", Integer, nullable=False, comment="1 if sellable, 0 if retired."),
    Column("created_at", DateTime, nullable=False),
    UniqueConstraint("organization_id", "sku", name="org_sku"),
    Index("ix_products_organization_id", "organization_id"),
    comment="Sellable products per organization.",
)

orders = Table(
    "orders",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("organization_id", Integer, ForeignKey("organizations.id"), nullable=False),
    Column("customer_id", Integer, ForeignKey("customers.id"), nullable=False),
    Column(
        "status",
        String(20),
        nullable=False,
        comment="pending|paid|shipped|refunded|cancelled.",
    ),
    Column("ordered_at", DateTime, nullable=False, comment="Business order timestamp."),
    Column("created_at", DateTime, nullable=False),
    Column("deleted_at", DateTime, nullable=True),
    Index("ix_orders_organization_id", "organization_id"),
    Index("ix_orders_customer_id", "customer_id"),
    Index("ix_orders_ordered_at", "ordered_at"),
    comment="Customer orders.",
)

order_items = Table(
    "order_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("organization_id", Integer, ForeignKey("organizations.id"), nullable=False),
    Column("order_id", Integer, ForeignKey("orders.id"), nullable=False),
    Column("product_id", Integer, ForeignKey("products.id"), nullable=False),
    Column("quantity", Integer, nullable=False, comment="Units ordered."),
    Column(
        "unit_price",
        Numeric(12, 2),
        nullable=False,
        comment="Unit price captured at order time (revenue basis).",
    ),
    Index("ix_order_items_organization_id", "organization_id"),
    Index("ix_order_items_order_id", "order_id"),
    Index("ix_order_items_product_id", "product_id"),
    comment="Line items. Revenue = SUM(quantity * unit_price) minus approved refunds.",
)

payments = Table(
    "payments",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("organization_id", Integer, ForeignKey("organizations.id"), nullable=False),
    Column("order_id", Integer, ForeignKey("orders.id"), nullable=False),
    Column("amount", Numeric(12, 2), nullable=False, comment="Captured amount (financial)."),
    Column("method", String(20), nullable=False, comment="card|bank|paypal."),
    Column("card_last4", String(4), nullable=True, comment="Last 4 card digits (sensitive)."),
    Column(
        "payment_token",
        String(64),
        nullable=True,
        comment="Processor payment token (authentication secret; never selectable).",
    ),
    Column("status", String(20), nullable=False, comment="succeeded|failed|pending."),
    Column("paid_at", DateTime, nullable=True),
    Index("ix_payments_organization_id", "organization_id"),
    Index("ix_payments_order_id", "order_id"),
    comment="Payment records for orders.",
)

refunds = Table(
    "refunds",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("organization_id", Integer, ForeignKey("organizations.id"), nullable=False),
    Column("order_id", Integer, ForeignKey("orders.id"), nullable=False),
    Column("payment_id", Integer, ForeignKey("payments.id"), nullable=True),
    Column("amount", Numeric(12, 2), nullable=False, comment="Refunded amount (financial)."),
    Column("reason", String(200), nullable=True),
    Column("refunded_at", DateTime, nullable=False),
    Index("ix_refunds_organization_id", "organization_id"),
    Index("ix_refunds_order_id", "order_id"),
    comment="Approved refunds; subtracted from gross revenue.",
)

subscriptions = Table(
    "subscriptions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("organization_id", Integer, ForeignKey("organizations.id"), nullable=False),
    Column("customer_id", Integer, ForeignKey("customers.id"), nullable=False),
    Column("plan", String(20), nullable=False, comment="free|pro|enterprise."),
    Column("status", String(20), nullable=False, comment="active|canceled|past_due."),
    Column("mrr", Numeric(12, 2), nullable=False, comment="Monthly recurring revenue (financial)."),
    Column("started_at", DateTime, nullable=False),
    Column("canceled_at", DateTime, nullable=True),
    Index("ix_subscriptions_organization_id", "organization_id"),
    Index("ix_subscriptions_customer_id", "customer_id"),
    comment="Recurring subscriptions per customer.",
)

support_tickets = Table(
    "support_tickets",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("organization_id", Integer, ForeignKey("organizations.id"), nullable=False),
    Column("customer_id", Integer, ForeignKey("customers.id"), nullable=False),
    Column("subject", String(200), nullable=False),
    Column("status", String(20), nullable=False, comment="open|pending|closed."),
    Column("priority", String(10), nullable=False, comment="low|medium|high."),
    Column("created_at", DateTime, nullable=False),
    Column("resolved_at", DateTime, nullable=True),
    Index("ix_support_tickets_organization_id", "organization_id"),
    Index("ix_support_tickets_customer_id", "customer_id"),
    comment="Customer support tickets.",
)


# Ordered for FK-safe creation / truncation.
ALL_TABLES: tuple[Table, ...] = (
    organizations,
    regions,
    users,
    customers,
    products,
    orders,
    order_items,
    payments,
    refunds,
    subscriptions,
    support_tickets,
)
