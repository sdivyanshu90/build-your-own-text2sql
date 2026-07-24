"""Domain layer: framework-agnostic value objects and DTOs.

Everything here is a pure Pydantic v2 model or Enum. The domain layer depends
only on :mod:`text_to_sql.common` and the standard library — never on FastAPI,
SQLAlchemy, or provider SDKs. This keeps the core testable without a server or
database and gives the rest of the system a stable vocabulary.
"""

from __future__ import annotations

from text_to_sql.domain.enums import (
    AmbiguityCategory,
    DataClassification,
    ResponseStatus,
    RiskLevel,
    SQLDialect,
    StatementType,
)

__all__ = [
    "AmbiguityCategory",
    "DataClassification",
    "ResponseStatus",
    "RiskLevel",
    "SQLDialect",
    "StatementType",
]
