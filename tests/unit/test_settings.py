"""Unit tests for configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from text_to_sql.configuration.settings import Environment, Settings

pytestmark = pytest.mark.unit


def _settings(**kw: object) -> Settings:
    base: dict[str, object] = {"_env_file": None}
    base.update(kw)
    return Settings(**base)  # type: ignore[arg-type]


def test_defaults_are_safe() -> None:
    s = _settings()
    assert s.llm_provider == "fake"
    assert s.is_sqlite
    assert not s.is_production
    assert s.max_rows == 1000


def test_log_level_is_validated_and_uppercased() -> None:
    assert _settings(log_level="debug").log_level == "DEBUG"
    with pytest.raises(ValidationError):
        _settings(log_level="verbose")


def test_allowed_schemas_split_from_csv() -> None:
    s = _settings(allowed_schemas="public, analytics ,")
    assert s.allowed_schemas == ("public", "analytics")


def test_cost_threshold_ordering_enforced() -> None:
    with pytest.raises(ValidationError):
        _settings(cost_rows_medium_threshold=10, cost_rows_high_threshold=5)


def test_production_flag() -> None:
    s = _settings(environment="production")
    assert s.environment is Environment.PRODUCTION
    assert s.is_production


def test_effective_readonly_url_falls_back() -> None:
    s = _settings(database_url="sqlite:///./x.db")
    assert s.effective_readonly_url == "sqlite:///./x.db"
    s2 = _settings(database_url="sqlite:///./x.db", readonly_database_url="sqlite:///./ro.db")
    assert s2.effective_readonly_url == "sqlite:///./ro.db"


def test_api_key_resolved_from_named_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_KEY", "secret-value")
    s = _settings(llm_api_key_env="MY_KEY")
    assert s.resolve_llm_api_key() == "secret-value"
    s2 = _settings(llm_api_key_env="ABSENT_KEY")
    monkeypatch.delenv("ABSENT_KEY", raising=False)
    assert s2.resolve_llm_api_key() is None


def test_settings_are_frozen() -> None:
    s = _settings()
    with pytest.raises(ValidationError):
        s.max_rows = 5  # type: ignore[misc]
