"""SQL parsing, AST validation, and normalization (SQLGlot-based).

All generated or user-supplied SQL is parsed into an abstract syntax tree before
anything else happens. We *never* rely on regular expressions or string matching
to decide whether SQL is safe — the AST is the source of truth. Regex is used only
as a redundant backup for one narrow case (comment smuggling).

* :mod:`~text_to_sql.sql.parser` — parse + statement classification.
* :mod:`~text_to_sql.sql.validator` — read-only + schema-reference validation.
* :mod:`~text_to_sql.sql.normalizer` — pretty/normalize + LIMIT enforcement +
  cross-dialect transpilation.
"""

from __future__ import annotations

from text_to_sql.sql.normalizer import enforce_limit, normalize_sql, transpile_sql
from text_to_sql.sql.parser import ParsedSQL, classify_statement, parse_statements
from text_to_sql.sql.validator import SQLValidator, ValidationOutcome

__all__ = [
    "ParsedSQL",
    "SQLValidator",
    "ValidationOutcome",
    "classify_statement",
    "enforce_limit",
    "normalize_sql",
    "parse_statements",
    "transpile_sql",
]
