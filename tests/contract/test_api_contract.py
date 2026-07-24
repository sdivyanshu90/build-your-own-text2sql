"""Contract tests: stable API surface and error-envelope shape."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.contract

H = {"X-User-Id": "u", "X-Tenant-Id": "1", "X-Roles": "analyst"}


async def test_openapi_declares_all_endpoints(client) -> None:  # type: ignore[no-untyped-def]
    spec = (await client.get("/api/v1/openapi.json")).json()
    paths = spec["paths"]
    for path in [
        "/api/v1/query",
        "/api/v1/query/preview",
        "/api/v1/query/validate",
        "/api/v1/schema",
        "/api/v1/schema/refresh",
        "/api/v1/health/live",
        "/api/v1/health/ready",
    ]:
        assert path in paths, f"missing {path}"


async def test_success_response_shape(client) -> None:  # type: ignore[no-untyped-def]
    body = (
        await client.post("/api/v1/query", headers=H, json={"question": "list all products"})
    ).json()
    for key in [
        "status",
        "correlation_id",
        "sql",
        "columns",
        "rows",
        "row_count",
        "validation",
        "timings",
        "retrieval",
    ]:
        assert key in body, f"missing key {key}"


async def test_error_envelope_shape(client) -> None:  # type: ignore[no-untyped-def]
    # Missing identity → 403 with the uniform envelope.
    resp = await client.post("/api/v1/query", json={"question": "x"})
    assert resp.status_code == 403
    body = resp.json()
    assert set(body.keys()) == {"error", "correlation_id"}
    err = body["error"]
    for key in ["code", "message", "category", "retryable"]:
        assert key in err


async def test_validation_report_shape(client) -> None:  # type: ignore[no-untyped-def]
    body = (
        await client.post("/api/v1/query/validate", headers=H, json={"sql": "DROP TABLE users"})
    ).json()
    assert body["is_valid"] is False
    assert isinstance(body["issues"], list)
    assert all({"code", "message"} <= set(i) for i in body["issues"])


async def test_correlation_id_echoed_in_header(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post(
        "/api/v1/query",
        headers={**H, "X-Correlation-Id": "corr_test123"},
        json={"question": "list all products"},
    )
    assert resp.headers["X-Correlation-Id"] == "corr_test123"
    assert resp.json()["correlation_id"] == "corr_test123"
