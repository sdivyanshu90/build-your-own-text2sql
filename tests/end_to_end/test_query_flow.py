"""End-to-end HTTP tests exercising the full stack (fake provider + real DB).

Each test asserts more than a status code: SQL content, tenant scoping, results,
metadata, and explanations.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e

H = {"X-User-Id": "u1", "X-Tenant-Id": "1", "X-Roles": "analyst"}


async def test_health_endpoints(client) -> None:  # type: ignore[no-untyped-def]
    assert (await client.get("/api/v1/health/live")).status_code == 200
    ready = await client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"]["database"] == "ok"


async def test_revenue_by_region_full_response(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post(
        "/api/v1/query", headers=H, json={"question": "Show revenue by region"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert "SUM(order_items.quantity * order_items.unit_price)" in body["sql"]
    assert "organization_id = 1" in body["sql"]  # tenant scoping injected
    assert body["row_count"] >= 1
    assert body["columns"] == ["region", "revenue"]
    assert body["explanation"]
    assert body["validation"]["is_valid"] is True
    assert body["validation"]["applied_rewrites"]
    assert body["model"]["provider"] == "fake"
    assert body["timings"]["total_ms"] >= 0
    assert resp.headers["X-Correlation-Id"]


async def test_relative_date_query(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post(
        "/api/v1/query", headers=H, json={"question": "How many orders were placed last month?"}
    )
    body = resp.json()
    assert body["status"] == "success"
    assert "2026-06-01" in body["sql"]
    assert body["rows"][0][0] >= 0


async def test_zero_result_query(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post(
        "/api/v1/query",
        headers=H,
        json={"question": "Show all cancelled support tickets"},
    )
    body = resp.json()
    assert body["status"] == "success"
    # 'cancelled' is not a valid ticket status → zero rows, grounded explanation.
    assert body["row_count"] == 0
    assert "no matching rows" in body["explanation"].lower()


async def test_clarification_returns_409(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post("/api/v1/query", headers=H, json={"question": "top customers"})
    assert resp.status_code == 409
    body = resp.json()
    assert body["status"] == "clarification_required"
    assert body["clarification"]["suggested_question"]


async def test_preview_does_not_execute(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post(
        "/api/v1/query/preview", headers=H, json={"question": "list all products"}
    )
    body = resp.json()
    assert body["status"] == "preview"
    assert body["sql"]
    assert body["rows"] == []
    assert body["execution"] is None


async def test_dry_run_flag(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post(
        "/api/v1/query", headers=H, json={"question": "list all products", "dry_run": True}
    )
    assert resp.json()["status"] == "preview"


async def test_validate_endpoint_accepts_good_sql(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post(
        "/api/v1/query/validate",
        headers=H,
        json={"sql": "SELECT products.name FROM products LIMIT 5"},
    )
    assert resp.status_code == 200
    assert resp.json()["is_valid"] is True


async def test_schema_endpoint_filtered(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.get("/api/v1/schema", headers=H)
    body = resp.json()
    users = next(t for t in body["tables"] if t["name"] == "users")
    names = {c["name"] for c in users["columns"]}
    assert "password_hash" not in names
    assert "email" not in names  # PII hidden from analyst


async def test_metrics_endpoint(client) -> None:  # type: ignore[no-untyped-def]
    await client.post("/api/v1/query", headers=H, json={"question": "Show revenue by region"})
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "t2sql_requests_total" in resp.text


async def test_missing_body_field_is_422(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post("/api/v1/query", headers=H, json={})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_request"


async def test_openapi_available(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.get("/api/v1/openapi.json")
    assert resp.status_code == 200
    assert "/api/v1/query" in resp.json()["paths"]
