"""Cross-cutting primitives shared by every layer.

Contains the typed error hierarchy, correlation-ID helpers, and the redaction
utilities used to keep secrets and sensitive values out of logs, traces, and
error responses. This package must not import from higher layers (domain,
application, api) to avoid cycles.
"""

from __future__ import annotations

from text_to_sql.common.errors import (
    AmbiguousQuestionError,
    AuthorizationError,
    ConfigurationError,
    CostRejectedError,
    DependencyUnavailableError,
    EngineError,
    ErrorCategory,
    ExecutionError,
    InvalidRequestError,
    ProviderError,
    ProviderOutputError,
    ProviderTimeoutError,
    RepairExhaustedError,
    SchemaRetrievalError,
    SQLParseError,
    SQLValidationError,
)
from text_to_sql.common.ids import new_correlation_id, new_request_id
from text_to_sql.common.redaction import Redactor, redact_text

__all__ = [
    "AmbiguousQuestionError",
    "AuthorizationError",
    "ConfigurationError",
    "CostRejectedError",
    "DependencyUnavailableError",
    "EngineError",
    "ErrorCategory",
    "ExecutionError",
    "InvalidRequestError",
    "ProviderError",
    "ProviderOutputError",
    "ProviderTimeoutError",
    "Redactor",
    "RepairExhaustedError",
    "SQLParseError",
    "SQLValidationError",
    "SchemaRetrievalError",
    "new_correlation_id",
    "new_request_id",
    "redact_text",
]
