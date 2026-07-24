"""SQL parsing and statement classification via SQLGlot.

``parse_statements`` returns every top-level statement in the input (SQLGlot
splits on statement boundaries). The validator uses this to enforce the
"exactly one statement" rule — semicolon smuggling shows up here as ``len > 1``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from text_to_sql.common.errors import SQLParseError
from text_to_sql.domain.enums import SQLDialect, StatementType


@dataclass
class ParsedSQL:
    """A single parsed statement plus its classification."""

    expression: exp.Expression
    statement_type: StatementType
    dialect: SQLDialect


def parse_statements(sql: str, dialect: SQLDialect) -> list[exp.Expression]:
    """Parse ``sql`` into a list of top-level expressions.

    Raises
    ------
    SQLParseError
        If SQLGlot cannot parse the input.
    """
    try:
        parsed = sqlglot.parse(sql, read=dialect.sqlglot_name)
    except (ParseError, TokenError) as exc:
        raise SQLParseError(
            "The generated SQL could not be parsed.",
            details={"reason": _first_line(str(exc))},
        ) from exc
    # SQLGlot yields ``None`` for empty statements (e.g. a trailing semicolon).
    statements = cast("list[exp.Expression]", [stmt for stmt in parsed if stmt is not None])
    if not statements:
        raise SQLParseError("No SQL statement was found in the input.")
    return statements


# Mapping of SQLGlot ``Command`` names to statement types. ``Command`` is used by
# SQLGlot for statements it does not model with a dedicated node (TRUNCATE, GRANT,
# VACUUM, etc.), so we inspect the command keyword.
_COMMAND_MAP = {
    "TRUNCATE": StatementType.TRUNCATE,
    "GRANT": StatementType.GRANT,
    "REVOKE": StatementType.REVOKE,
    "VACUUM": StatementType.OTHER,
    "ANALYZE": StatementType.OTHER,
    "CALL": StatementType.CALL,
    "EXECUTE": StatementType.CALL,
    "COPY": StatementType.OTHER,
}


def classify_statement(expression: exp.Expression) -> StatementType:
    """Classify a top-level expression into a :class:`StatementType`."""
    if isinstance(expression, exp.Select):
        return StatementType.SELECT
    if isinstance(expression, (exp.Union, exp.Intersect, exp.Except)):
        return StatementType.UNION
    if isinstance(expression, exp.Subquery):
        return StatementType.SELECT
    if isinstance(expression, exp.Insert):
        return StatementType.INSERT
    if isinstance(expression, exp.Update):
        return StatementType.UPDATE
    if isinstance(expression, exp.Delete):
        return StatementType.DELETE
    if isinstance(expression, exp.Merge):
        return StatementType.MERGE
    if isinstance(expression, exp.Drop):
        return StatementType.DROP
    if isinstance(expression, exp.Alter):
        return StatementType.ALTER
    if isinstance(expression, exp.Create):
        return StatementType.CREATE
    # TRUNCATE and GRANT/REVOKE have dedicated node types in recent SQLGlot.
    _truncate = getattr(exp, "TruncateTable", None)
    if _truncate is not None and isinstance(expression, _truncate):
        return StatementType.TRUNCATE
    _grant = getattr(exp, "Grant", None)
    if _grant is not None and isinstance(expression, _grant):
        return StatementType.GRANT
    if isinstance(expression, exp.Set):
        return StatementType.SET
    if isinstance(expression, (exp.Transaction, exp.Commit, exp.Rollback)):
        return StatementType.TRANSACTION
    if isinstance(expression, exp.Pragma):
        return StatementType.PRAGMA
    if isinstance(expression, exp.Command):
        keyword = (expression.name or "").upper()
        return _COMMAND_MAP.get(keyword, StatementType.OTHER)
    return StatementType.OTHER


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0][:200] if text.strip() else "parse error"
