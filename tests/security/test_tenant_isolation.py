"""Security tests: tenant isolation is deterministic and unbypassable."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from text_to_sql.application.container import AppContainer
from text_to_sql.common.errors import AuthorizationError
from text_to_sql.domain.context import AuthContext
from text_to_sql.domain.models import QueryRequest
from text_to_sql.llm.fake import DeterministicFakeProvider

pytestmark = pytest.mark.security

ANALYST_T1 = AuthContext(user_id="u1", tenant_id="1", roles=("analyst",))
ANALYST_T2 = AuthContext(user_id="u2", tenant_id="2", roles=("analyst",))


async def test_attacker_supplied_tenant_filter_is_overridden(make_container) -> None:  # type: ignore[no-untyped-def]
    # The model tries to read tenant 2 while the caller is tenant 1.
    provider = DeterministicFakeProvider(
        scripts={
            "revenue": [
                "SELECT SUM(order_items.quantity * order_items.unit_price) AS revenue "
                "FROM order_items JOIN orders ON orders.id = order_items.order_id "
                "WHERE orders.organization_id = 2"
            ]
        }
    )
    container: AppContainer = make_container(provider=provider)
    resp = await container.orchestrator.process(QueryRequest(question="revenue"), ANALYST_T1)
    # Rewriter ANDs organization_id = 1, so the org=2 predicate yields no rows.
    assert "organization_id = 1" in resp.sql
    assert resp.rows[0][0] is None  # SUM over empty set


async def test_results_differ_by_tenant(make_container) -> None:  # type: ignore[no-untyped-def]
    q = "How many orders do we have?"
    container: AppContainer = make_container()
    r1 = await container.orchestrator.process(QueryRequest(question=q), ANALYST_T1)
    r2 = await container.orchestrator.process(QueryRequest(question=q), ANALYST_T2)
    assert r1.rows[0][0] != r2.rows[0][0]  # different tenants, different counts


async def test_tenant_counts_match_ground_truth(make_container) -> None:  # type: ignore[no-untyped-def]
    container: AppContainer = make_container()
    resp = await container.orchestrator.process(
        QueryRequest(question="How many orders do we have?"), ANALYST_T1
    )
    with container.database.readonly_engine.connect() as conn:
        truth = conn.execute(text("SELECT COUNT(*) FROM orders WHERE organization_id = 1")).scalar()
    assert resp.rows[0][0] == truth


async def test_request_tenant_mismatch_rejected(make_container) -> None:  # type: ignore[no-untyped-def]
    container: AppContainer = make_container()
    with pytest.raises(AuthorizationError):
        await container.orchestrator.process(
            QueryRequest(question="revenue", tenant_id="2"), ANALYST_T1
        )
