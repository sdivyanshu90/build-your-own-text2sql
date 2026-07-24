"""Public request/response DTOs for the API and orchestrator.

These are the models FastAPI serializes at the edge and the orchestrator returns
internally. They are intentionally explicit: every field a client might branch on
(status, validation outcome, timings, assumptions, confidence, trace id) is a
first-class attribute rather than buried in free text.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from text_to_sql.domain.context import ConversationState
from text_to_sql.domain.enums import (
    AmbiguityCategory,
    ResponseStatus,
    RiskLevel,
    SQLDialect,
)


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #
class GlossaryTermOverride(BaseModel):
    """A per-request business-term override supplied by an authorized client."""

    term: str
    definition: str
    sql_expression: str | None = None


class QueryRequest(BaseModel):
    """A natural-language query request.

    ``tenant_id`` here is *advisory*: the authoritative tenant used for policy
    enforcement always comes from the authenticated context. If both are present
    and disagree, the request is rejected (see the orchestrator).
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1, max_length=2000)
    data_source: str | None = Field(
        default=None, description="Logical data-source identifier (reserved for multi-DB)."
    )
    dialect: SQLDialect | None = Field(
        default=None, description="Override the configured default SQL dialect."
    )
    tenant_id: str | None = Field(
        default=None, description="Advisory tenant id; must match auth context if set."
    )
    conversation: ConversationState | None = None
    glossary_overrides: list[GlossaryTermOverride] = Field(default_factory=list)
    max_rows: int | None = Field(default=None, ge=1, le=100_000)
    dry_run: bool = Field(default=False, description="Generate & validate but do not execute.")
    sql_only: bool = Field(
        default=False, description="Return SQL only; skip execution & NL answer."
    )
    explain: bool = Field(default=True, description="Include a natural-language explanation.")
    correlation_id: str | None = None


class ValidateSQLRequest(BaseModel):
    """Validate caller-supplied SQL through the same deterministic policy engine."""

    model_config = ConfigDict(extra="forbid")

    sql: str = Field(..., min_length=1, max_length=20_000)
    dialect: SQLDialect | None = None
    tenant_id: str | None = None


# --------------------------------------------------------------------------- #
# Sub-structures
# --------------------------------------------------------------------------- #
class RetrievedObject(BaseModel):
    """A schema object selected by the retrieval stage, with its score/reason."""

    table: str
    score: float
    reason: str


class ValidationIssue(BaseModel):
    """A single machine-readable validation/policy finding."""

    code: str
    message: str
    location: str | None = None  # e.g. "column: users.password_hash"


class ValidationReport(BaseModel):
    """Outcome of the parse → validate → policy → cost pipeline for one SQL."""

    is_valid: bool
    statement_type: str | None = None
    referenced_tables: list[str] = Field(default_factory=list)
    referenced_columns: list[str] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)
    risk_level: RiskLevel | None = None
    estimated_cost: float | None = None
    applied_rewrites: list[str] = Field(default_factory=list)


class ClarificationInterpretation(BaseModel):
    """One possible reading of an ambiguous question."""

    label: str
    description: str


class Clarification(BaseModel):
    """Structured clarification returned when a question is materially ambiguous."""

    category: AmbiguityCategory
    explanation: str
    interpretations: list[ClarificationInterpretation] = Field(default_factory=list)
    suggested_question: str
    confidence: float = Field(ge=0.0, le=1.0)


class StageTimings(BaseModel):
    """Per-stage wall-clock timings in milliseconds."""

    retrieval_ms: float = 0.0
    generation_ms: float = 0.0
    validation_ms: float = 0.0
    execution_ms: float = 0.0
    total_ms: float = 0.0


class ExecutionMetadata(BaseModel):
    """Metadata describing execution (present only when SQL was executed)."""

    row_count: int
    truncated: bool
    duration_ms: float


class ModelMetadata(BaseModel):
    """Provider/model disclosure (omitted when disclosure is disabled)."""

    provider: str
    model: str
    prompt_version: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    repair_attempts: int = 0


# --------------------------------------------------------------------------- #
# Responses
# --------------------------------------------------------------------------- #
class QueryResponse(BaseModel):
    """The unified response for ``/query`` and ``/query/preview``."""

    status: ResponseStatus
    correlation_id: str

    # SQL & results
    sql: str | None = None
    dialect: SQLDialect | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int | None = None
    truncated: bool = False

    # Interpretation & grounding
    explanation: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    # Diagnostics
    validation: ValidationReport | None = None
    clarification: Clarification | None = None
    retrieval: list[RetrievedObject] = Field(default_factory=list)
    timings: StageTimings = Field(default_factory=StageTimings)
    execution: ExecutionMetadata | None = None
    model: ModelMetadata | None = None


class SchemaColumnSummary(BaseModel):
    name: str
    data_type: str
    nullable: bool
    is_primary_key: bool
    classification: str
    sensitive: bool


class SchemaTableSummary(BaseModel):
    name: str
    kind: str
    comment: str | None = None
    columns: list[SchemaColumnSummary]


class SchemaSummaryResponse(BaseModel):
    """Authorization-filtered schema summary for ``GET /schema``."""

    dialect: SQLDialect
    version: str
    tables: list[SchemaTableSummary]


class ErrorDetail(BaseModel):
    code: str
    message: str
    category: str
    retryable: bool
    details: dict[str, Any] | None = None
    remediation: str | None = None


class ErrorResponse(BaseModel):
    """Uniform error envelope for all non-2xx responses."""

    error: ErrorDetail
    correlation_id: str


class HealthResponse(BaseModel):
    status: str
    checks: dict[str, str] = Field(default_factory=dict)
