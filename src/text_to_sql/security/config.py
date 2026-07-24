"""Assembled security-policy configuration.

Bundles the deterministic-security knobs (limits, allowlists, tenant column,
function denylist) into one immutable object built from
:class:`~text_to_sql.configuration.settings.Settings`. Passing this single object
around keeps the policy/rewriter/cost components decoupled from global settings
and trivially unit-testable with custom thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from text_to_sql.configuration import Settings
from text_to_sql.sql.validator import DEFAULT_FUNCTION_DENYLIST


@dataclass(frozen=True)
class SecurityPolicyConfig:
    """Immutable security thresholds and allowlists."""

    tenant_column: str = "organization_id"
    max_rows: int = 1000
    max_joins: int = 6
    max_subquery_depth: int = 4
    max_selected_columns: int = 60
    cost_rows_medium_threshold: float = 100_000
    cost_rows_high_threshold: float = 1_000_000
    allowed_schemas: frozenset[str] = frozenset()
    allowed_tables: frozenset[str] | None = None  # None => all catalog tables
    denied_tables: frozenset[str] = frozenset()
    function_denylist: frozenset[str] = field(default_factory=lambda: DEFAULT_FUNCTION_DENYLIST)

    @classmethod
    def from_settings(cls, settings: Settings) -> SecurityPolicyConfig:
        return cls(
            tenant_column=settings.tenant_column,
            max_rows=settings.max_rows,
            max_joins=settings.max_joins,
            max_subquery_depth=settings.max_subquery_depth,
            max_selected_columns=settings.max_selected_columns,
            cost_rows_medium_threshold=settings.cost_rows_medium_threshold,
            cost_rows_high_threshold=settings.cost_rows_high_threshold,
            allowed_schemas=frozenset(settings.allowed_schemas),
        )
