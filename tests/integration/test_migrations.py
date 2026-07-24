"""Integration test: Alembic migrations run and are reversible."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from text_to_sql.configuration import get_settings

pytestmark = pytest.mark.integration


def test_upgrade_and_downgrade(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setenv("T2SQL_DATABASE_URL", url)
    monkeypatch.setenv("T2SQL_LLM_PROVIDER", "fake")
    get_settings.cache_clear()
    try:
        cfg = Config("alembic.ini")
        cfg.set_main_option("script_location", "migrations")

        command.upgrade(cfg, "head")
        engine = create_engine(url)
        tables = set(inspect(engine).get_table_names())
        assert {"orders", "order_items", "customers"} <= tables

        command.downgrade(cfg, "base")
        tables_after = set(inspect(engine).get_table_names())
        assert "orders" not in tables_after
        engine.dispose()
    finally:
        get_settings.cache_clear()
