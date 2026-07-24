"""Authenticated caller context and multi-turn conversation state.

These value objects thread the *who* and the *history* through the pipeline.
They are domain objects (pure Pydantic) so policy decisions can be unit-tested
without any HTTP or auth middleware.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from text_to_sql.domain.enums import SQLDialect


class AuthContext(BaseModel):
    """The authenticated caller's security context.

    In this reference implementation the API layer derives this from request
    headers (see ``docs/security/authorization.md``); in production it would come
    from a verified JWT / session. The engine treats it as *trusted* input — it
    is the anchor for every deterministic authorization decision, so it must be
    established by the transport layer, never by the LLM.
    """

    model_config = ConfigDict(frozen=True)

    user_id: str
    tenant_id: str = Field(..., description="Organization / tenant identifier.")
    roles: tuple[str, ...] = ()

    @property
    def is_admin(self) -> bool:
        return "admin" in {r.lower() for r in self.roles}

    def has_role(self, role: str) -> bool:
        return role.lower() in {r.lower() for r in self.roles}


class ConversationTurn(BaseModel):
    """A single prior turn's distilled intent (not raw chat text).

    We deliberately store *structured* state rather than concatenating message
    history: raw history is a prompt-injection vector and blows the token budget.
    Only the fields below are carried forward, and every follow-up is re-validated
    from scratch under the *current* security policy.
    """

    model_config = ConfigDict(frozen=True)

    question: str
    sql: str | None = None
    referenced_tables: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    filters: tuple[str, ...] = ()
    date_range: str | None = None
    assumptions: tuple[str, ...] = ()


class ConversationState(BaseModel):
    """Accumulated, structured conversation context for follow-up questions."""

    model_config = ConfigDict(frozen=True)

    turns: tuple[ConversationTurn, ...] = ()

    @property
    def last(self) -> ConversationTurn | None:
        return self.turns[-1] if self.turns else None

    def with_turn(self, turn: ConversationTurn) -> ConversationState:
        return ConversationState(turns=(*self.turns, turn))


class GenerationTarget(BaseModel):
    """Resolved generation parameters for a single request."""

    model_config = ConfigDict(frozen=True)

    dialect: SQLDialect
    max_rows: int
    tenant_id: str
