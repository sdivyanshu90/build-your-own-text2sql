"""HTTP API layer (FastAPI).

Thin transport adapter: handlers parse/authorize requests and delegate to the
:class:`~text_to_sql.application.orchestrator.QueryOrchestrator`. No business
logic lives here. Typed engine errors are translated to a uniform error envelope
by the registered exception handlers.
"""

from __future__ import annotations

from text_to_sql.api.app import create_app

__all__ = ["create_app"]
