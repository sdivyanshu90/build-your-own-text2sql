"""Deterministic security enforcement.

Security here does **not** depend on the LLM following instructions. After
generation, every query passes through deterministic gates:

* :mod:`~text_to_sql.security.classification` — column sensitivity → role access.
* :mod:`~text_to_sql.security.policy` — allowed tables, denied/sensitive columns,
  role checks; emits machine-readable denials.
* :mod:`~text_to_sql.security.rewriter` — injects mandatory tenant predicates into
  the AST (never via string concatenation) so cross-tenant reads are impossible.
* :mod:`~text_to_sql.security.cost` — complexity/cost limits and EXPLAIN-based risk.

The engine's tenant-isolation and read-only guarantees are *deterministic*; the
quality/correctness of generated SQL remains *probabilistic*. See
``docs/security/threat_model.md``.
"""

from __future__ import annotations

from text_to_sql.security.classification import ColumnAccessPolicy
from text_to_sql.security.config import SecurityPolicyConfig
from text_to_sql.security.cost import CostAnalyzer, CostReport
from text_to_sql.security.policy import PolicyDecision, PolicyEngine
from text_to_sql.security.rewriter import TenantRewriter

__all__ = [
    "ColumnAccessPolicy",
    "CostAnalyzer",
    "CostReport",
    "PolicyDecision",
    "PolicyEngine",
    "SecurityPolicyConfig",
    "TenantRewriter",
]
