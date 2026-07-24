"""Authorization policy engine.

Runs *after* AST validation and operates on the resolved tables/columns the
validator produced. It enforces, deterministically and independent of anything the
LLM said:

* table allow/deny lists,
* per-column sensitivity vs the caller's roles (see
  :class:`~text_to_sql.security.classification.ColumnAccessPolicy`),

emitting machine-readable denials. Because it consumes *resolved* column
references (including those produced inside CTEs/subqueries), attempts to launder
a sensitive column through a derived table are still caught — the inner reference
was already resolved to its base column.

Tenant isolation is handled separately by the :class:`TenantRewriter` so it can
mutate the AST; keeping "deny" (policy) and "constrain" (rewrite) apart keeps each
piece simple and independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from text_to_sql.domain.context import AuthContext
from text_to_sql.domain.models import ValidationIssue
from text_to_sql.domain.schema_models import DatabaseSchema
from text_to_sql.security.classification import ColumnAccessPolicy
from text_to_sql.security.config import SecurityPolicyConfig


@dataclass
class PolicyDecision:
    """Outcome of policy enforcement."""

    allowed: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    def deny(self, code: str, message: str, location: str | None = None) -> None:
        self.allowed = False
        self.issues.append(ValidationIssue(code=code, message=message, location=location))


class PolicyEngine:
    """Deterministic table/column authorization."""

    def __init__(
        self,
        config: SecurityPolicyConfig,
        column_policy: ColumnAccessPolicy | None = None,
    ) -> None:
        self._config = config
        self._columns = column_policy or ColumnAccessPolicy()

    def enforce(
        self,
        referenced_tables: list[str],
        referenced_columns: list[str],
        schema: DatabaseSchema,
        auth: AuthContext,
    ) -> PolicyDecision:
        decision = PolicyDecision(allowed=True)

        # --- Tables -------------------------------------------------------
        for qualified in referenced_tables:
            bare = qualified.split(".")[-1].lower()
            if bare in {t.lower() for t in self._config.denied_tables}:
                decision.deny(
                    "table_denied",
                    f"Access to table '{bare}' is denied by policy.",
                    location=f"table: {bare}",
                )
            if self._config.allowed_tables is not None:
                allowed = {t.lower() for t in self._config.allowed_tables}
                if bare not in allowed:
                    decision.deny(
                        "table_not_allowed",
                        f"Table '{bare}' is not in the allowed set for this request.",
                        location=f"table: {bare}",
                    )

        # --- Columns ------------------------------------------------------
        for ref in referenced_columns:
            table_name, _, column_name = ref.partition(".")
            table = schema.table(table_name)
            if table is None:
                continue
            column = table.column(column_name)
            if column is None:
                continue
            if not self._columns.can_view(column.classification, auth.roles):
                decision.deny(
                    "column_denied",
                    f"{self._columns.deny_reason(column.classification)} "
                    f"(column '{table_name}.{column_name}', "
                    f"classification '{column.classification.value}').",
                    location=f"column: {table_name}.{column_name}",
                )
        return decision
