"""Provider-independent generation interface and DTOs.

The rest of the engine depends only on the :class:`LLMProvider` protocol and the
structured request/response models here — never on a concrete SDK. This makes the
provider swappable (Acceptance Checklist: "The provider can be replaced through an
adapter") and lets the whole pipeline run deterministically in tests via the fake
provider.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from text_to_sql.domain.context import ConversationState
from text_to_sql.domain.enums import AmbiguityCategory, SQLDialect
from text_to_sql.domain.schema_models import DatabaseSchema
from text_to_sql.llm.prompt import PromptPayload
from text_to_sql.semantic.models import SemanticLayer


class TokenUsage(BaseModel):
    """Token accounting for cost metadata."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ResolvedDate(BaseModel):
    """A resolved relative-date window handed to the provider as guidance."""

    model_config = ConfigDict(frozen=True)

    description: str
    matched_phrase: str
    start_iso: str
    end_iso: str


class RepairContext(BaseModel):
    """Feedback for a repair attempt.

    Only *sanitized* error strings are included — never raw driver output. The
    original question/intent is preserved so the provider fixes rather than
    re-interprets.
    """

    model_config = ConfigDict(frozen=True)

    attempt: int = Field(ge=1)
    previous_sql: str
    errors: tuple[str, ...]


class GenerationClarification(BaseModel):
    """Provider-signalled ambiguity (a secondary check; the deterministic
    ambiguity analyzer runs first)."""

    model_config = ConfigDict(frozen=True)

    category: AmbiguityCategory
    question: str
    interpretations: tuple[str, ...] = ()


class GenerationRequest(BaseModel):
    """Everything a provider needs to produce SQL for one attempt."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    question: str
    dialect: SQLDialect
    schema_subset: DatabaseSchema
    semantic_layer: SemanticLayer
    prompt: PromptPayload
    max_rows: int
    resolved_date: ResolvedDate | None = None
    conversation: ConversationState | None = None
    repair: RepairContext | None = None
    model: str = "deterministic-fake"
    temperature: float = 0.0
    timeout_seconds: float = 30.0


class GenerationResponse(BaseModel):
    """Structured generation output.

    This is the contract the OpenAI adapter enforces via JSON schema and the fake
    provider produces natively. ``prompt_version`` and ``usage`` support
    reproducibility and cost tracking.
    """

    model_config = ConfigDict(frozen=True)

    sql: str
    dialect: SQLDialect
    explanation: str = ""
    referenced_tables: tuple[str, ...] = ()
    referenced_columns: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    needs_clarification: bool = False
    clarification: GenerationClarification | None = None
    prompt_version: str = "unknown"
    provider: str = "unknown"
    model: str = "unknown"
    usage: TokenUsage = Field(default_factory=TokenUsage)


@runtime_checkable
class LLMProvider(Protocol):
    """The generation interface every provider implements."""

    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def generate(self, request: GenerationRequest) -> GenerationResponse: ...
