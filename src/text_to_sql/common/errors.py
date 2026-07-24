"""Typed error hierarchy for the engine.

Every failure in the pipeline raises a subclass of :class:`EngineError`. Each
error carries:

* a **stable machine-readable code** (``error_code``) that clients can branch on
  and that never changes across releases,
* an **HTTP status** used when the error surfaces through the API,
* a **retryable** flag telling clients whether a naive retry might succeed,
* a **category** for metrics/alerting,
* optional **safe details** — a dict guaranteed to be free of secrets and raw
  driver output. Raw exceptions/stack traces are *never* placed here.

The API layer maps these to a single public error envelope
(:class:`text_to_sql.domain.models.ErrorResponse`). Internal specifics
(SQL text, driver messages, provider payloads) are deliberately excluded from
public output; they live only in server-side structured logs.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCategory(str, Enum):
    """Coarse grouping used for metrics and alert routing."""

    CLIENT = "client"  # caller's fault; usually not retryable
    AMBIGUITY = "ambiguity"  # needs clarification, not an error per se
    AUTHORIZATION = "authorization"
    VALIDATION = "validation"
    PROVIDER = "provider"  # upstream LLM problem
    DATABASE = "database"
    COST = "cost"
    CONFIGURATION = "configuration"
    DEPENDENCY = "dependency"
    INTERNAL = "internal"


class EngineError(Exception):
    """Base class for all engine errors.

    Attributes
    ----------
    message:
        Human-readable, *safe* message suitable for returning to API clients.
    error_code:
        Stable identifier, e.g. ``"sql_validation_failed"``.
    http_status:
        Status code used by the API layer.
    retryable:
        Whether a client retry might plausibly succeed unchanged.
    category:
        :class:`ErrorCategory` for observability.
    details:
        Optional mapping of *safe* structured details (no secrets, no raw SQL,
        no driver output).
    remediation:
        Optional short hint on how to resolve the problem.
    """

    error_code: str = "engine_error"
    http_status: int = 500
    retryable: bool = False
    category: ErrorCategory = ErrorCategory.INTERNAL

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        remediation: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}
        self.remediation = remediation
        if retryable is not None:
            self.retryable = retryable

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize to a safe dict for API error envelopes."""
        payload: dict[str, Any] = {
            "code": self.error_code,
            "message": self.message,
            "category": self.category.value,
            "retryable": self.retryable,
        }
        if self.details:
            payload["details"] = self.details
        if self.remediation:
            payload["remediation"] = self.remediation
        return payload


# --------------------------------------------------------------------------- #
# Client / request errors
# --------------------------------------------------------------------------- #
class InvalidRequestError(EngineError):
    """The request was malformed or violated a documented constraint."""

    error_code = "invalid_request"
    http_status = 422
    retryable = False
    category = ErrorCategory.CLIENT


class AmbiguousQuestionError(EngineError):
    """The question is materially ambiguous and requires clarification.

    This is not a hard failure: the API returns HTTP 409 with a structured
    clarification payload so the caller can refine the question.
    """

    error_code = "clarification_required"
    http_status = 409
    retryable = False
    category = ErrorCategory.AMBIGUITY


# --------------------------------------------------------------------------- #
# Authorization / policy
# --------------------------------------------------------------------------- #
class AuthorizationError(EngineError):
    """A deterministic policy check denied the query (table/column/tenant/role)."""

    error_code = "authorization_denied"
    http_status = 403
    retryable = False
    category = ErrorCategory.AUTHORIZATION


# --------------------------------------------------------------------------- #
# SQL parsing / validation
# --------------------------------------------------------------------------- #
class SQLParseError(EngineError):
    """Generated (or supplied) SQL could not be parsed into an AST."""

    error_code = "sql_parse_failed"
    http_status = 422
    retryable = False
    category = ErrorCategory.VALIDATION


class SQLValidationError(EngineError):
    """SQL parsed but failed an AST-level safety/schema validation rule."""

    error_code = "sql_validation_failed"
    http_status = 422
    retryable = False
    category = ErrorCategory.VALIDATION


class CostRejectedError(EngineError):
    """The query's estimated cost/complexity exceeded configured thresholds."""

    error_code = "query_cost_rejected"
    http_status = 422
    retryable = False
    category = ErrorCategory.COST


# --------------------------------------------------------------------------- #
# Provider / LLM
# --------------------------------------------------------------------------- #
class ProviderError(EngineError):
    """Generic upstream LLM provider failure."""

    error_code = "provider_error"
    http_status = 502
    retryable = True
    category = ErrorCategory.PROVIDER


class ProviderTimeoutError(ProviderError):
    """The provider did not respond within the configured timeout."""

    error_code = "provider_timeout"
    http_status = 504
    retryable = True


class ProviderOutputError(ProviderError):
    """The provider returned output that did not match the required schema."""

    error_code = "provider_output_invalid"
    http_status = 502
    retryable = True


# --------------------------------------------------------------------------- #
# Repair / retrieval / execution / config / dependency
# --------------------------------------------------------------------------- #
class RepairExhaustedError(EngineError):
    """The bounded repair loop exhausted its attempts without valid SQL."""

    error_code = "repair_exhausted"
    http_status = 422
    retryable = False
    category = ErrorCategory.VALIDATION


class SchemaRetrievalError(EngineError):
    """Schema discovery or retrieval failed."""

    error_code = "schema_retrieval_failed"
    http_status = 500
    retryable = True
    category = ErrorCategory.DATABASE


class ExecutionError(EngineError):
    """Executing validated SQL failed (timeout, DB error, cancellation)."""

    error_code = "execution_failed"
    http_status = 500
    retryable = True
    category = ErrorCategory.DATABASE


class ConfigurationError(EngineError):
    """The application is misconfigured (invalid or missing settings)."""

    error_code = "configuration_error"
    http_status = 500
    retryable = False
    category = ErrorCategory.CONFIGURATION


class DependencyUnavailableError(EngineError):
    """A critical dependency (DB, provider) is unavailable."""

    error_code = "dependency_unavailable"
    http_status = 503
    retryable = True
    category = ErrorCategory.DEPENDENCY
