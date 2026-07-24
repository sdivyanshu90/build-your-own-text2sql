"""Text-to-SQL Engine.

A production-oriented natural-language-to-SQL platform that converts questions
into safe, validated, executable read-only SQL. Security is enforced
deterministically *after* generation (parsing, AST validation, policy, tenant
rewriting, cost analysis) rather than trusted to the LLM.

See ``docs/`` for architecture, concepts, security, and testing documentation.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
