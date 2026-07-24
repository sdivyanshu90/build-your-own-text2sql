"""LLM provider abstraction and prompt construction.

The engine never couples to a single vendor. All generation goes through the
:class:`~text_to_sql.llm.base.LLMProvider` protocol, which returns a *structured*
:class:`~text_to_sql.llm.base.GenerationResponse` (not free text we have to parse
heuristically). Two providers ship:

* :class:`~text_to_sql.llm.fake.DeterministicFakeProvider` — no credentials, fully
  deterministic; powers every test and CI. Supports scripted responses so tests
  can force any output (including unsafe SQL) to exercise downstream validation.
* :class:`~text_to_sql.llm.openai_adapter.OpenAICompatibleProvider` — targets any
  OpenAI-compatible chat-completions endpoint with JSON structured output.

Prompt construction lives in :mod:`text_to_sql.llm.prompt` and is versioned; the
version used is recorded on every response for reproducibility and auditing.
"""

from __future__ import annotations

from text_to_sql.llm.base import (
    GenerationClarification,
    GenerationRequest,
    GenerationResponse,
    LLMProvider,
    RepairContext,
    TokenUsage,
)
from text_to_sql.llm.fake import DeterministicFakeProvider
from text_to_sql.llm.prompt import PromptBuilder, PromptContext, PromptPayload

__all__ = [
    "DeterministicFakeProvider",
    "GenerationClarification",
    "GenerationRequest",
    "GenerationResponse",
    "LLMProvider",
    "PromptBuilder",
    "PromptContext",
    "PromptPayload",
    "RepairContext",
    "TokenUsage",
]
