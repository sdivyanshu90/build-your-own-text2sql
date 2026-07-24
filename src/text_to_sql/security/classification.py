"""Column sensitivity → role access rules.

A single, testable place that answers: *may a caller with these roles select a
column of this classification?* The rules are deliberately conservative and
default-deny for secrets:

* ``AUTH_SECRET`` / ``HIGHLY_RESTRICTED`` — never selectable by anyone via this
  engine (there is no analytical reason to read a password hash or payment token).
* ``PII`` — only ``admin`` or a role holding ``pii_read``.
* ``FINANCIAL`` — only ``admin`` / ``analyst`` or a role holding ``finance_read``.
* ``CONFIDENTIAL`` — only ``admin`` / ``analyst``.
* ``INTERNAL`` / ``PUBLIC`` — anyone authenticated.

These map cleanly onto the reference seed roles (admin, analyst, viewer).
"""

from __future__ import annotations

from collections.abc import Iterable

from text_to_sql.domain.enums import DataClassification

# classification -> (allowed roles, required grant name or None)
_RULES: dict[DataClassification, tuple[frozenset[str], str | None]] = {
    DataClassification.PUBLIC: (frozenset({"*"}), None),
    DataClassification.INTERNAL: (frozenset({"*"}), None),
    DataClassification.CONFIDENTIAL: (frozenset({"admin", "analyst"}), None),
    DataClassification.FINANCIAL: (frozenset({"admin", "analyst"}), "finance_read"),
    DataClassification.PII: (frozenset({"admin"}), "pii_read"),
    DataClassification.AUTH_SECRET: (frozenset(), None),
    DataClassification.HIGHLY_RESTRICTED: (frozenset(), None),
}


class ColumnAccessPolicy:
    """Decides column visibility from classification + caller roles."""

    def can_view(self, classification: DataClassification, roles: Iterable[str]) -> bool:
        allowed_roles, required_grant = _RULES[classification]
        role_set = {r.lower() for r in roles}
        if "admin" in role_set:
            # Admin can view everything except always-secret classes.
            return classification not in {
                DataClassification.AUTH_SECRET,
                DataClassification.HIGHLY_RESTRICTED,
            }
        if "*" in allowed_roles:
            return True
        if role_set & allowed_roles:
            return True
        return bool(required_grant and required_grant in role_set)

    def deny_reason(self, classification: DataClassification) -> str:
        if classification in {
            DataClassification.AUTH_SECRET,
            DataClassification.HIGHLY_RESTRICTED,
        }:
            return f"Columns classified '{classification.value}' can never be selected."
        return f"Your role is not permitted to select '{classification.value}' data."
