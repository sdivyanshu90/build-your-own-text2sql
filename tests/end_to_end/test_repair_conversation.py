"""End-to-end tests for the repair loop and multi-turn conversation."""

from __future__ import annotations

import httpx
import pytest

from text_to_sql.api.app import create_app
from text_to_sql.llm.fake import DeterministicFakeProvider

pytestmark = pytest.mark.e2e

H = {"X-User-Id": "u1", "X-Tenant-Id": "1", "X-Roles": "analyst"}


async def _client_with(make_container, settings, provider):  # type: ignore[no-untyped-def]
    container = make_container(provider=provider)
    app = create_app(settings, container=container)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_repair_fixes_unknown_column(make_container, settings) -> None:  # type: ignore[no-untyped-def]
    provider = DeterministicFakeProvider(
        scripts={
            "show product names please": [
                "SELECT products.title FROM products",  # unknown column -> repair
                "SELECT products.name FROM products LIMIT 10",
            ]
        }
    )
    async with await _client_with(make_container, settings, provider) as client:
        resp = await client.post(
            "/api/v1/query", headers=H, json={"question": "show product names please"}
        )
        body = resp.json()
        assert resp.status_code == 200
        assert body["status"] == "success"
        assert body["model"]["repair_attempts"] == 1
        assert "products.name" in body["sql"]


async def test_repair_exhausted_returns_422(make_container, settings) -> None:  # type: ignore[no-untyped-def]
    provider = DeterministicFakeProvider(
        scripts={
            "give me broken sql": [
                "SELECT bad FROM products",
                "SELECT worse FROM products",
                "SELECT terrible FROM products",
            ]
        }
    )
    async with await _client_with(make_container, settings, provider) as client:
        resp = await client.post(
            "/api/v1/query", headers=H, json={"question": "give me broken sql"}
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "repair_exhausted"


async def test_followup_is_revalidated_and_tenant_scoped(make_container, settings) -> None:  # type: ignore[no-untyped-def]
    provider = DeterministicFakeProvider(
        scripts={
            "now group that by region": [
                "SELECT regions.name AS region, "
                "SUM(order_items.quantity * order_items.unit_price) AS revenue "
                "FROM order_items "
                "JOIN orders ON orders.id = order_items.order_id "
                "JOIN customers ON customers.id = orders.customer_id "
                "JOIN regions ON regions.id = customers.region_id "
                "GROUP BY regions.name"
            ]
        }
    )
    async with await _client_with(make_container, settings, provider) as client:
        follow_up = {
            "question": "now group that by region",
            "conversation": {
                "turns": [
                    {
                        "question": "What is our total revenue?",
                        "sql": "SELECT SUM(...) FROM order_items",
                        "metrics": ["net revenue"],
                    }
                ]
            },
        }
        resp = await client.post("/api/v1/query", headers=H, json=follow_up)
        body = resp.json()
        assert resp.status_code == 200
        assert body["status"] == "success"
        assert body["columns"] == ["region", "revenue"]
        # Every follow-up is re-scoped to the caller's tenant regardless of history.
        assert body["sql"].count("organization_id = 1") >= 2
