"""Integration tests: schema introspection and query execution vs a real DB."""

from __future__ import annotations

import pytest

from text_to_sql.application.container import AppContainer
from text_to_sql.common.errors import ExecutionError
from text_to_sql.domain.enums import SQLDialect
from text_to_sql.execution.executor import ReadOnlyExecutor

pytestmark = pytest.mark.integration


# --- Introspection -------------------------------------------------------- #
def test_reflects_all_reference_tables(container: AppContainer) -> None:
    schema = container.catalog.get_schema()
    names = set(schema.table_names)
    assert {"orders", "order_items", "customers", "products", "refunds"} <= names


def test_reflects_primary_and_foreign_keys(container: AppContainer) -> None:
    schema = container.catalog.get_schema()
    order_items = schema.table("order_items")
    assert order_items is not None
    assert "id" in order_items.primary_key
    referred = {fk.referred_table for fk in order_items.foreign_keys}
    assert {"orders", "products"} <= referred


def test_columns_have_types_and_nullability(container: AppContainer) -> None:
    schema = container.catalog.get_schema()
    customers = schema.table("customers")
    assert customers is not None
    email = customers.column("contact_email")
    assert email is not None and email.nullable  # nullable contact email


# --- Execution ------------------------------------------------------------ #
def _executor(container: AppContainer) -> ReadOnlyExecutor:
    return ReadOnlyExecutor(container.database.readonly_engine, SQLDialect.SQLITE)


def test_execute_returns_rows(container: AppContainer) -> None:
    result = _executor(container).execute(
        "SELECT COUNT(*) AS c FROM customers WHERE organization_id = 1", max_rows=100
    )
    assert result.columns == ["c"]
    assert result.rows[0][0] == 8
    assert result.row_count == 1


def test_execute_truncates_and_flags(container: AppContainer) -> None:
    result = _executor(container).execute("SELECT id FROM orders ORDER BY id", max_rows=3)
    assert result.row_count == 3
    assert result.truncated is True


def test_execute_coerces_datetime_to_iso(container: AppContainer) -> None:
    result = _executor(container).execute(
        "SELECT ordered_at FROM orders ORDER BY id LIMIT 1", max_rows=1
    )
    assert isinstance(result.rows[0][0], str)  # datetime -> ISO string


def test_read_only_blocks_writes(container: AppContainer) -> None:
    # PRAGMA query_only is set on the read-only engine; a write must fail.
    with pytest.raises(ExecutionError):
        _executor(container).execute("UPDATE orders SET status = 'x'", max_rows=1)


def test_invalid_sql_maps_to_execution_error(container: AppContainer) -> None:
    with pytest.raises(ExecutionError):
        _executor(container).execute("SELECT nope FROM nope", max_rows=1)
