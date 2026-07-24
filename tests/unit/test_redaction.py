"""Unit tests for redaction utilities."""

from __future__ import annotations

import pytest

from text_to_sql.common.redaction import REDACTED, Redactor, redact_text

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "raw",
    [
        "user email is alice@example.com here",
        "call +1-555-123-4567 now",
        "card 4111 1111 1111 1111 ok",
        "api_key=sk-ABCDEF1234567890 secret",
        "password: hunter2seceret",
        "Authorization: Bearer abc.def.ghijkl",
    ],
)
def test_redact_text_removes_sensitive_shapes(raw: str) -> None:
    out = redact_text(raw)
    assert REDACTED in out
    assert "example.com" not in out or "@" not in out


def test_redact_preserves_connection_scheme_and_host() -> None:
    dsn = "postgresql+psycopg://admin:sup3rsecret@db.internal:5432/app"
    out = redact_text(dsn)
    assert "sup3rsecret" not in out
    assert "admin" not in out
    assert "db.internal" in out  # host preserved for diagnostics
    assert out.startswith("postgresql+psycopg://")


def test_redactor_removes_literal_values() -> None:
    r = Redactor(literals=["topsecretvalue", "abc"])  # short literals ignored (<4)
    out = r.redact("here is topsecretvalue and abc")
    assert "topsecretvalue" not in out
    assert "abc" in out  # too short to redact, avoids pathological replacement


def test_redactor_mapping_recurses() -> None:
    r = Redactor()
    result = r.redact_mapping({"a": "email x@y.com", "b": {"c": ["p@q.com", 1]}})
    assert REDACTED in result["a"]  # type: ignore[operator]
    assert REDACTED in result["b"]["c"][0]  # type: ignore[index]
    assert result["b"]["c"][1] == 1  # type: ignore[index]


def test_redact_empty_string_is_noop() -> None:
    assert redact_text("") == ""
