"""Security tests: deterministic rejection of unsafe SQL.

Every case forces the (fake) model to emit a specific hostile payload via
scripting, then asserts the deterministic pipeline rejects it — proving rejection
happens at our enforcement layers, NOT because "the LLM refused".

These go through the orchestrator (the same path production uses), so they cover
parse → AST validate → policy → rewrite → cost end to end.
"""

from __future__ import annotations

import pytest

from text_to_sql.application.container import AppContainer
from text_to_sql.common.errors import (
    AuthorizationError,
    CostRejectedError,
    EngineError,
    SQLValidationError,
)
from text_to_sql.domain.context import AuthContext
from text_to_sql.domain.models import QueryRequest
from text_to_sql.llm.fake import DeterministicFakeProvider

pytestmark = pytest.mark.security

ANALYST = AuthContext(user_id="u", tenant_id="1", roles=("analyst",))


async def _run(make_container, question: str, sql: str, auth: AuthContext = ANALYST):  # type: ignore[no-untyped-def]
    provider = DeterministicFakeProvider(scripts={question: [sql]})
    container: AppContainer = make_container(provider=provider)
    return await container.orchestrator.process(QueryRequest(question=question), auth)


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE users",
        "DELETE FROM orders",
        "UPDATE users SET role = 'admin'",
        "INSERT INTO users (email) VALUES ('x@y.com')",
        "TRUNCATE TABLE orders",
        "ALTER TABLE users ADD COLUMN backdoor int",
        "GRANT SELECT ON users TO attacker",
    ],
)
async def test_destructive_statements_rejected(make_container, sql: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(EngineError) as exc:
        await _run(make_container, "do it", sql)
    # Rejected as a hard failure (validation), never executed.
    assert exc.value.error_code in {"sql_validation_failed", "repair_exhausted"}


async def test_semicolon_smuggling_rejected(make_container) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(SQLValidationError):
        await _run(make_container, "q", "SELECT id FROM users; DROP TABLE users")


async def test_comment_hidden_payload_rejected(make_container) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(EngineError):
        await _run(make_container, "q", "SELECT id FROM users -- ; DROP TABLE users")


async def test_union_exfiltration_of_secret_rejected(make_container) -> None:  # type: ignore[no-untyped-def]
    # UNION attempt to pull password_hash is blocked by column policy.
    sql = "SELECT name FROM products UNION SELECT password_hash FROM users"
    with pytest.raises(AuthorizationError):
        await _run(make_container, "q", sql)


async def test_system_catalog_access_rejected(make_container) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(SQLValidationError):
        await _run(make_container, "q", "SELECT name FROM sqlite_master")


async def test_cartesian_product_rejected(make_container) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(CostRejectedError):
        await _run(
            make_container,
            "q",
            "SELECT a.id FROM orders a CROSS JOIN customers b CROSS JOIN products c",
        )


async def test_sensitive_column_denied_for_viewer(make_container) -> None:  # type: ignore[no-untyped-def]
    viewer = AuthContext(user_id="v", tenant_id="1", roles=("viewer",))
    with pytest.raises(AuthorizationError):
        await _run(make_container, "q", "SELECT customers.contact_email FROM customers", viewer)


async def test_auth_secret_denied_even_for_admin(make_container) -> None:  # type: ignore[no-untyped-def]
    admin = AuthContext(user_id="a", tenant_id="1", roles=("admin", "pii_read"))
    with pytest.raises(AuthorizationError):
        await _run(make_container, "q", "SELECT users.password_hash FROM users", admin)
