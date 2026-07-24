"""Property-based tests (Hypothesis) for security-critical invariants.

These assert properties that must hold across a wide range of generated inputs:

* destructive statements are NEVER accepted,
* validation never grants access to unknown tables,
* tenant scoping can never be removed,
* an enforced LIMIT never exceeds the configured maximum,
* quoting/whitespace/casing variations of a valid query still validate.
"""

from __future__ import annotations

import string

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from text_to_sql.common.errors import SQLParseError
from text_to_sql.domain.enums import DataClassification, SQLDialect
from text_to_sql.domain.schema_models import ColumnInfo, DatabaseSchema, TableInfo
from text_to_sql.security.rewriter import TenantRewriter
from text_to_sql.sql.normalizer import enforce_limit, normalize_sql
from text_to_sql.sql.parser import parse_statements
from text_to_sql.sql.validator import SQLValidator

pytestmark = pytest.mark.property
D = SQLDialect.SQLITE

# A compact, tenant-aware schema for pure (DB-free) property testing.
SCHEMA = DatabaseSchema(
    dialect=D,
    tables=(
        TableInfo(
            name="orders",
            tenant_column="organization_id",
            columns=(
                ColumnInfo(name="id", data_type="INT", is_primary_key=True),
                ColumnInfo(name="organization_id", data_type="INT"),
                ColumnInfo(name="status", data_type="TEXT"),
            ),
        ),
        TableInfo(
            name="customers",
            tenant_column="organization_id",
            columns=(
                ColumnInfo(name="id", data_type="INT", is_primary_key=True),
                ColumnInfo(name="organization_id", data_type="INT"),
                ColumnInfo(name="name", data_type="TEXT"),
                ColumnInfo(name="ssn", data_type="TEXT", classification=DataClassification.PII),
            ),
        ),
    ),
    version="prop",
)

VALIDATOR = SQLValidator()
EXISTING = {"orders", "customers"}

identifiers = st.text(alphabet=string.ascii_lowercase, min_size=3, max_size=10).filter(
    lambda s: s not in EXISTING
)
whitespace = st.sampled_from([" ", "  ", "\t", "\n", " \n "])
FAST = settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])


@FAST
@given(
    verb=st.sampled_from(["DROP TABLE", "DELETE FROM", "TRUNCATE TABLE", "ALTER TABLE"]),
    ident=st.sampled_from(["orders", "customers", "users"]),
)
def test_destructive_never_accepted(verb: str, ident: str) -> None:
    outcome = VALIDATOR.validate(f"{verb} {ident}", D, SCHEMA)
    assert not outcome.is_valid


@FAST
@given(ident=identifiers)
def test_unknown_table_never_valid(ident: str) -> None:
    # A random identifier is either an unknown table (rejected) or a reserved
    # word that fails to parse (also rejected). Either way it is never accepted.
    try:
        outcome = VALIDATOR.validate(f"SELECT id FROM {ident}", D, SCHEMA)
    except SQLParseError:
        return  # unparseable => rejected, invariant holds
    assert not outcome.is_valid
    assert any(i.code == "unknown_table" for i in outcome.issues)


@FAST
@given(
    limit=st.integers(min_value=1, max_value=10_000_000),
    max_rows=st.integers(min_value=1, max_value=5000),
)
def test_limit_never_exceeds_max(limit: int, max_rows: int) -> None:
    expr = parse_statements(f"SELECT id FROM orders LIMIT {limit}", D)[0]
    outcome = enforce_limit(expr, max_rows)
    assert outcome.effective_limit <= max_rows


@FAST
@given(table=st.sampled_from(["orders", "customers"]))
def test_tenant_scope_always_injected(table: str) -> None:
    expr = parse_statements(f"SELECT id FROM {table}", D)[0]
    scoped, applied = TenantRewriter().rewrite(expr, SCHEMA, "42")
    sql = normalize_sql(scoped, D, pretty=False)
    assert f"{table}.organization_id = 42" in sql
    assert applied


@FAST
@given(ws1=whitespace, ws2=whitespace, upper=st.booleans())
def test_whitespace_and_case_variation_still_valid(ws1: str, ws2: str, upper: bool) -> None:
    sql = f"SELECT{ws1}orders.id{ws2}FROM orders LIMIT 5"
    if upper:
        sql = sql.upper()
    outcome = VALIDATOR.validate(sql, D, SCHEMA)
    assert outcome.is_valid, [i.code for i in outcome.issues]
