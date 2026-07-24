"""Schema creation and deterministic seed data for the reference database.

Used by the ``init_db`` / ``seed`` scripts, integration tests, and the golden
evaluation suite. Seed generation is fully deterministic (fixed RNG seed, fixed
base date) so tests can assert on exact aggregates and the golden suite has
stable expected results.

The data is intentionally shaped to exercise: aggregations, multi-table joins,
date filtering across quarters/years, window/ranking queries, refunds, NULL
handling (customers without a region/phone), tenant boundaries (two orgs whose
data must never mix), duplicates, zero-result cases, and higher-cardinality
result sets.

All data is synthetic.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Engine, insert

from text_to_sql.infrastructure import reference_schema as ref
from text_to_sql.observability.logging import get_logger

_log = get_logger(__name__)

# Anchor so relative-date queries ("last quarter", "last year") have data.
SEED_BASE_DATE = datetime(2026, 7, 24)
_RNG_SEED = 42


def create_schema(engine: Engine, *, drop_first: bool = False) -> None:
    """Create all reference tables (optionally dropping them first)."""
    if drop_first:
        ref.metadata.drop_all(engine)
    ref.metadata.create_all(engine)


def seed_database(engine: Engine, *, base_date: datetime = SEED_BASE_DATE) -> dict[str, int]:
    """Insert deterministic seed data. Returns per-table row counts.

    Assumes the schema exists and is empty (call :func:`create_schema` with
    ``drop_first=True`` beforehand for a clean slate).
    """
    rng = random.Random(_RNG_SEED)
    counts: dict[str, int] = {}

    with engine.begin() as conn:
        # --- Organizations (tenants) --------------------------------------
        orgs: list[dict[str, Any]] = [
            {
                "id": 1,
                "name": "Acme Corp",
                "plan": "pro",
                "created_at": base_date - timedelta(days=900),
                "deleted_at": None,
            },
            {
                "id": 2,
                "name": "Globex Inc",
                "plan": "enterprise",
                "created_at": base_date - timedelta(days=800),
                "deleted_at": None,
            },
        ]
        conn.execute(insert(ref.organizations), orgs)
        counts["organizations"] = len(orgs)

        # --- Regions (shared reference data) ------------------------------
        regions = [
            {"id": 1, "name": "North America", "code": "NA"},
            {"id": 2, "name": "Europe, Middle East & Africa", "code": "EMEA"},
            {"id": 3, "name": "Asia Pacific", "code": "APAC"},
            {"id": 4, "name": "Latin America", "code": "LATAM"},
        ]
        conn.execute(insert(ref.regions), regions)
        counts["regions"] = len(regions)

        # --- Users --------------------------------------------------------
        users: list[dict] = []
        uid = 0
        for org in orgs:
            for i in range(3):
                uid += 1
                role = ("admin", "analyst", "viewer")[i % 3]
                users.append(
                    {
                        "id": uid,
                        "organization_id": org["id"],
                        "email": f"user{i}@{org['name'].split()[0].lower()}.example",
                        "full_name": f"User {i} of {org['name']}",
                        "password_hash": f"$2b$12$deadbeefhash{uid:04d}",
                        "role": role,
                        "created_at": org["created_at"] + timedelta(days=10 + i),
                        "deleted_at": None,
                    }
                )
        conn.execute(insert(ref.users), users)
        counts["users"] = len(users)

        # --- Customers ----------------------------------------------------
        customers: list[dict] = []
        cid = 0
        segments = ("smb", "mid_market", "enterprise")
        customers_per_org = {1: 8, 2: 5}
        for org in orgs:
            for i in range(customers_per_org[org["id"]]):
                cid += 1
                # One customer per org has a NULL region and NULL phone (null tests).
                has_region = i != 0
                customers.append(
                    {
                        "id": cid,
                        "organization_id": org["id"],
                        "region_id": (rng.randint(1, 4) if has_region else None),
                        "name": f"Customer {cid}",
                        "contact_email": (
                            f"contact{cid}@customer{cid}.example" if i % 2 == 0 else None
                        ),
                        "contact_phone": (f"+1-555-01{cid:02d}" if has_region else None),
                        "segment": segments[i % 3],
                        "created_at": org["created_at"] + timedelta(days=30 + i * 5),
                        "deleted_at": None,
                    }
                )
        conn.execute(insert(ref.customers), customers)
        counts["customers"] = len(customers)

        # --- Products -----------------------------------------------------
        products: list[dict] = []
        pid = 0
        categories = ("hardware", "software", "services", "accessories")
        products_per_org = {1: 6, 2: 4}
        for org in orgs:
            for i in range(products_per_org[org["id"]]):
                pid += 1
                products.append(
                    {
                        "id": pid,
                        "organization_id": org["id"],
                        "sku": f"SKU-{org['id']}-{i:03d}",
                        "name": f"Product {pid}",
                        "category": categories[i % len(categories)],
                        "unit_price": round(20 + (pid * 7.5) % 480, 2),
                        "active": 1 if i % 5 != 4 else 0,
                        "created_at": org["created_at"] + timedelta(days=20),
                    }
                )
        conn.execute(insert(ref.products), products)
        counts["products"] = len(products)

        org_customers = {
            org["id"]: [c for c in customers if c["organization_id"] == org["id"]] for org in orgs
        }
        org_products = {
            org["id"]: [p for p in products if p["organization_id"] == org["id"]] for org in orgs
        }

        # --- Orders, items, payments, refunds -----------------------------
        orders: list[dict] = []
        order_items: list[dict] = []
        payments: list[dict] = []
        refunds: list[dict] = []
        oid = 0
        iid = 0
        pay_id = 0
        ref_id = 0
        statuses = ("paid", "shipped", "paid", "pending", "refunded", "cancelled")

        # Spread order dates across the previous year and this year, monthly.
        month_anchors: list[datetime] = []
        for year in (base_date.year - 1, base_date.year):
            for month in range(1, 13):
                dt = datetime(year, month, 15)
                if dt < base_date:
                    month_anchors.append(dt)

        for org in orgs:
            custs = org_customers[org["id"]]
            prods = org_products[org["id"]]
            n_orders = 60 if org["id"] == 1 else 25
            for _ in range(n_orders):
                oid += 1
                cust = rng.choice(custs)
                ordered_at = rng.choice(month_anchors) + timedelta(days=rng.randint(0, 25))
                status = rng.choice(statuses)
                orders.append(
                    {
                        "id": oid,
                        "organization_id": org["id"],
                        "customer_id": cust["id"],
                        "status": status,
                        "ordered_at": ordered_at,
                        "created_at": ordered_at,
                        "deleted_at": None,
                    }
                )
                n_items = rng.randint(1, 3)
                order_total = 0.0
                for _ in range(n_items):
                    iid += 1
                    prod = rng.choice(prods)
                    qty = rng.randint(1, 5)
                    unit_price = float(prod["unit_price"])
                    order_total += qty * unit_price
                    order_items.append(
                        {
                            "id": iid,
                            "organization_id": org["id"],
                            "order_id": oid,
                            "product_id": prod["id"],
                            "quantity": qty,
                            "unit_price": round(unit_price, 2),
                        }
                    )
                if status in {"paid", "shipped", "refunded"}:
                    pay_id += 1
                    method = rng.choice(("card", "bank", "paypal"))
                    payments.append(
                        {
                            "id": pay_id,
                            "organization_id": org["id"],
                            "order_id": oid,
                            "amount": round(order_total, 2),
                            "method": method,
                            "card_last4": (
                                f"{rng.randint(0, 9999):04d}" if method == "card" else None
                            ),
                            "payment_token": (
                                f"tok_{rng.randrange(16**16):016x}" if method == "card" else None
                            ),
                            "status": "succeeded",
                            "paid_at": ordered_at + timedelta(days=1),
                        }
                    )
                    if status == "refunded":
                        ref_id += 1
                        refunds.append(
                            {
                                "id": ref_id,
                                "organization_id": org["id"],
                                "order_id": oid,
                                "payment_id": pay_id,
                                "amount": round(order_total * rng.choice((0.5, 1.0)), 2),
                                "reason": rng.choice(
                                    ("defective", "customer_request", "duplicate")
                                ),
                                "refunded_at": ordered_at + timedelta(days=rng.randint(2, 20)),
                            }
                        )

        conn.execute(insert(ref.orders), orders)
        conn.execute(insert(ref.order_items), order_items)
        if payments:
            conn.execute(insert(ref.payments), payments)
        if refunds:
            conn.execute(insert(ref.refunds), refunds)
        counts.update(
            orders=len(orders),
            order_items=len(order_items),
            payments=len(payments),
            refunds=len(refunds),
        )

        # --- Subscriptions ------------------------------------------------
        subscriptions: list[dict] = []
        sub_id = 0
        for org in orgs:
            for cust in org_customers[org["id"]]:
                if rng.random() < 0.6:
                    sub_id += 1
                    status = rng.choice(("active", "active", "canceled", "past_due"))
                    started = cust["created_at"] + timedelta(days=5)
                    subscriptions.append(
                        {
                            "id": sub_id,
                            "organization_id": org["id"],
                            "customer_id": cust["id"],
                            "plan": rng.choice(("pro", "enterprise", "free")),
                            "status": status,
                            "mrr": round(rng.choice((49.0, 99.0, 199.0, 499.0)), 2),
                            "started_at": started,
                            "canceled_at": (
                                started + timedelta(days=200) if status == "canceled" else None
                            ),
                        }
                    )
        if subscriptions:
            conn.execute(insert(ref.subscriptions), subscriptions)
        counts["subscriptions"] = len(subscriptions)

        # --- Support tickets ----------------------------------------------
        tickets: list[dict] = []
        tid = 0
        for org in orgs:
            for _ in range(15 if org["id"] == 1 else 8):
                tid += 1
                cust = rng.choice(org_customers[org["id"]])
                created = base_date - timedelta(days=rng.randint(1, 200))
                status = rng.choice(("open", "pending", "closed", "closed"))
                tickets.append(
                    {
                        "id": tid,
                        "organization_id": org["id"],
                        "customer_id": cust["id"],
                        "subject": f"Issue #{tid}",
                        "status": status,
                        "priority": rng.choice(("low", "medium", "high")),
                        "created_at": created,
                        "resolved_at": (
                            created + timedelta(days=rng.randint(1, 10))
                            if status == "closed"
                            else None
                        ),
                    }
                )
        conn.execute(insert(ref.support_tickets), tickets)
        counts["support_tickets"] = len(tickets)

    _log.info("database_seeded", **{f"count_{k}": v for k, v in counts.items()})
    return counts
