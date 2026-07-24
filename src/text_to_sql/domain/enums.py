"""Enumerations shared across the domain.

Kept in one module so both the configuration layer and the pipeline reference a
single source of truth for dialects, classifications, and status codes.
"""

from __future__ import annotations

from enum import Enum


class SQLDialect(str, Enum):
    """Supported SQL dialects.

    SQLGlot uses the same lowercase names, so the value doubles as the SQLGlot
    ``read``/``write`` argument. Only dialects the engine has been validated
    against are listed; adding one requires dialect-specific tests.
    """

    SQLITE = "sqlite"
    POSTGRES = "postgres"

    @property
    def sqlglot_name(self) -> str:
        return self.value


class DataClassification(str, Enum):
    """Sensitivity classification for columns.

    Ordered loosely from least to most sensitive. The policy engine uses this to
    decide whether a role may select a column and whether values must be redacted
    from logs/traces/explanations.
    """

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PII = "pii"
    FINANCIAL = "financial"
    AUTH_SECRET = "auth_secret"  # nosec B105 - classification label, not a credential
    HIGHLY_RESTRICTED = "highly_restricted"

    @property
    def is_sensitive(self) -> bool:
        """Whether values of this class must be redacted from logs/output."""
        return self in {
            DataClassification.PII,
            DataClassification.FINANCIAL,
            DataClassification.AUTH_SECRET,
            DataClassification.HIGHLY_RESTRICTED,
        }


class RiskLevel(str, Enum):
    """Coarse query risk rating produced by the cost analyzer."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AmbiguityCategory(str, Enum):
    """Categories of material ambiguity the analyzer can detect."""

    METRIC_DEFINITION = "metric_definition"  # e.g. "sales" with multiple defs
    TIME_RANGE = "time_range"  # e.g. "last month" w/o timezone
    ENTITY_REFERENCE = "entity_reference"  # e.g. "users" vs "customers"
    MEASURE_UNSPECIFIED = "measure_unspecified"  # e.g. "top customers" by what?
    UNKNOWN_TERM = "unknown_term"  # references undefined term


class ResponseStatus(str, Enum):
    """Top-level outcome of a query request."""

    SUCCESS = "success"
    CLARIFICATION_REQUIRED = "clarification_required"
    PREVIEW = "preview"  # SQL generated/validated but not executed
    REJECTED = "rejected"  # deterministically blocked (policy/cost)
    ERROR = "error"


class StatementType(str, Enum):
    """Classification of a parsed SQL statement's top-level type."""

    SELECT = "select"
    WITH = "with"  # CTE wrapping a SELECT (read-only)
    UNION = "union"
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    MERGE = "merge"
    DROP = "drop"
    ALTER = "alter"
    TRUNCATE = "truncate"
    CREATE = "create"
    GRANT = "grant"
    REVOKE = "revoke"
    TRANSACTION = "transaction"
    PRAGMA = "pragma"
    SET = "set"
    CALL = "call"
    OTHER = "other"

    @property
    def is_read_only(self) -> bool:
        return self in {StatementType.SELECT, StatementType.WITH, StatementType.UNION}
