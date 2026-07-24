"""Application orchestration layer.

Wires the pipeline components (retrieval → generation → validation → policy →
rewrite → cost → execution → explanation) behind a single
:class:`~text_to_sql.application.orchestrator.QueryOrchestrator`. Route handlers
call only the orchestrator; all business logic lives here and in the layers it
composes, never in FastAPI handlers.
"""

from __future__ import annotations

from text_to_sql.application.ambiguity import AmbiguityDetector
from text_to_sql.application.explainer import ResultExplainer
from text_to_sql.application.orchestrator import QueryOrchestrator
from text_to_sql.application.repair import RepairPlanner

__all__ = [
    "AmbiguityDetector",
    "QueryOrchestrator",
    "RepairPlanner",
    "ResultExplainer",
]
