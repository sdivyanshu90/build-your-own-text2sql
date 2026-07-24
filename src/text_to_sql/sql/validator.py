"""AST-based safety and schema-reference validation.

This is the first deterministic security gate. Given parsed SQL it enforces, at
the AST level (never by string matching, except a redundant comment backstop):

* exactly one statement (semicolon smuggling → rejected here),
* a read-only statement class (SELECT / UNION / CTE-wrapped SELECT only),
* no DML/DDL/DCL/TCL node anywhere in the tree (nested destructive statements),
* no SQL comments (comment-hidden payloads),
* no denied/dangerous functions,
* no system-catalog access,
* no cross-database references (unless explicitly allowed),
* every referenced table/column exists in the schema catalog,
* no bare ``SELECT *`` (columns must be explicit so policy can reason about
  sensitivity).

It returns a machine-readable :class:`ValidationOutcome`. Authorization (allowed
tables/columns per role/tenant), tenant rewriting, and cost live in the security
layer and run *after* this.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlglot import exp

from text_to_sql.domain.enums import SQLDialect, StatementType
from text_to_sql.domain.models import ValidationIssue
from text_to_sql.domain.schema_models import DatabaseSchema, TableInfo
from text_to_sql.sql.parser import classify_statement, parse_statements

# Functions that can read files, sleep, exfiltrate, or execute code. Denied
# regardless of dialect. Not exhaustive of "all bad functions" — combined with
# the read-only + schema-reference rules it closes the practical attack surface.
DEFAULT_FUNCTION_DENYLIST = frozenset(
    {
        "pg_sleep",
        "sleep",
        "benchmark",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "lo_import",
        "lo_export",
        "load_extension",
        "readfile",
        "writefile",
        "load_file",
        "dblink",
        "dblink_exec",
        "copy",
        "xp_cmdshell",
        "system",
        "current_setting",
        "set_config",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "query_to_xml",
        "pg_client_encoding",
    }
)

SYSTEM_SCHEMAS = frozenset({"information_schema", "pg_catalog", "pg_temp", "sys"})
SYSTEM_TABLE_PREFIXES = ("pg_", "sqlite_")

# Node types that must never appear anywhere in a read-only query.
# TruncateTable / Grant exist in recent SQLGlot; resolved defensively so the
# validator still works on versions that model them differently.
_OPTIONAL_FORBIDDEN = tuple(
    node_type
    for node_type in (
        getattr(exp, "TruncateTable", None),
        getattr(exp, "Grant", None),
        getattr(exp, "Revoke", None),
    )
    if node_type is not None
)
_FORBIDDEN_NODE_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Set,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Command,
    *_OPTIONAL_FORBIDDEN,
)

# Backstop for comment smuggling: after stripping single-quoted string literals,
# a comment marker means the parser dropped a comment we should reject on.
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_COMMENT_MARKER = re.compile(r"(--|/\*|\*/|#)")


@dataclass
class ValidationOutcome:
    """Result of validating one statement."""

    is_valid: bool
    statement_type: StatementType
    expression: exp.Expression | None
    referenced_tables: list[str] = field(default_factory=list)
    referenced_columns: list[str] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)

    def add(self, code: str, message: str, location: str | None = None) -> None:
        self.is_valid = False
        # Dedupe: the same finding can be reached by two independent checks
        # (e.g. AST comment detection + the regex backstop).
        for existing in self.issues:
            if existing.code == code and existing.location == location:
                return
        self.issues.append(ValidationIssue(code=code, message=message, location=location))


class SQLValidator:
    """Deterministic AST validator."""

    def __init__(
        self,
        *,
        function_denylist: frozenset[str] = DEFAULT_FUNCTION_DENYLIST,
        allow_cross_database: bool = False,
        allowed_schemas: frozenset[str] = frozenset(),
    ) -> None:
        self._denylist = {f.lower() for f in function_denylist}
        self._allow_cross_db = allow_cross_database
        self._allowed_schemas = {s.lower() for s in allowed_schemas}

    def validate(self, sql: str, dialect: SQLDialect, schema: DatabaseSchema) -> ValidationOutcome:
        """Parse then validate. Raises :class:`SQLParseError` on parse failure."""
        statements = parse_statements(sql, dialect)
        outcome = self._new_outcome(statements)
        if len(statements) != 1:
            outcome.add(
                "multiple_statements",
                f"Exactly one statement is allowed; found {len(statements)}.",
            )
            return outcome
        self._comment_backstop(sql, outcome)
        self.validate_expression(statements[0], dialect, schema, outcome)
        return outcome

    def validate_expression(
        self,
        expression: exp.Expression,
        dialect: SQLDialect,
        schema: DatabaseSchema,
        outcome: ValidationOutcome | None = None,
    ) -> ValidationOutcome:
        """Validate an already-parsed (possibly rewritten) expression."""
        if outcome is None:
            outcome = self._new_outcome([expression])

        statement_type = classify_statement(expression)
        outcome.statement_type = statement_type

        # 1. Read-only statement class -------------------------------------
        if not statement_type.is_read_only:
            outcome.add(
                "non_read_only_statement",
                f"Statement type '{statement_type.value}' is not permitted (read-only only).",
            )

        # 2. No forbidden nodes anywhere -----------------------------------
        for node in expression.walk():
            if isinstance(node, _FORBIDDEN_NODE_TYPES):
                outcome.add(
                    "forbidden_statement",
                    f"Prohibited operation '{type(node).__name__.lower()}' found in the query.",
                )
                break

        # 3. Comments (AST-level) ------------------------------------------
        if any(getattr(node, "comments", None) for node in expression.walk()):
            outcome.add("comment_present", "SQL comments are not allowed.")

        # 4. Bare SELECT * -------------------------------------------------
        for star in expression.find_all(exp.Star):
            if star.find_ancestor(exp.Func) is None:
                outcome.add(
                    "select_star_forbidden",
                    "SELECT * is not allowed; list explicit columns so sensitivity "
                    "can be verified.",
                )
                break

        # 5. Functions -----------------------------------------------------
        self._check_functions(expression, outcome)

        # 6. Tables & columns vs catalog -----------------------------------
        self._check_tables_and_columns(expression, schema, outcome)

        return outcome

    # ------------------------------------------------------------------ #
    def _new_outcome(self, statements: list[exp.Expression]) -> ValidationOutcome:
        stype = classify_statement(statements[0]) if statements else StatementType.OTHER
        return ValidationOutcome(
            is_valid=True,
            statement_type=stype,
            expression=statements[0] if statements else None,
        )

    def _comment_backstop(self, sql: str, outcome: ValidationOutcome) -> None:
        stripped = _STRING_LITERAL.sub("''", sql)
        if _COMMENT_MARKER.search(stripped):
            outcome.add("comment_present", "SQL comments are not allowed.")

    def _check_functions(self, expression: exp.Expression, outcome: ValidationOutcome) -> None:
        seen: set[str] = set()
        for func in expression.find_all(exp.Func):
            if isinstance(func, exp.Anonymous):
                name = str(func.this).lower()
            else:
                try:
                    name = func.sql_name().lower()
                except Exception:
                    name = type(func).__name__.lower()
            if name in self._denylist and name not in seen:
                seen.add(name)
                outcome.add(
                    "denied_function",
                    f"Function '{name}' is not allowed.",
                    location=f"function: {name}",
                )

    def _check_tables_and_columns(
        self,
        expression: exp.Expression,
        schema: DatabaseSchema,
        outcome: ValidationOutcome,
    ) -> None:
        # Virtual sources (CTEs, derived-table aliases) are not catalog tables.
        virtual_aliases = self._virtual_aliases(expression)
        # Output/projection aliases (SELECT expr AS name) are referenceable by
        # GROUP BY / ORDER BY / HAVING and are NOT table columns.
        output_aliases = self._output_aliases(expression)

        # alias (lowercased) -> every catalog table that alias may denote. An
        # alias can be reused in different scopes, so this is a set, not a scalar.
        alias_to_real: dict[str, set[str]] = {}
        real_tables: list[str] = []

        for table in expression.find_all(exp.Table):
            name = table.name
            if not name or name.lower() in virtual_aliases:
                continue
            catalog = table.catalog  # cross-db catalog part
            db = table.db  # schema part

            if catalog and not self._allow_cross_db:
                outcome.add(
                    "cross_database_access",
                    f"Cross-database reference '{catalog}.{db or ''}.{name}' is not allowed.",
                    location=f"table: {name}",
                )
            if db and db.lower() in SYSTEM_SCHEMAS:
                outcome.add(
                    "system_catalog_access",
                    f"Access to system schema '{db}' is not allowed.",
                    location=f"table: {db}.{name}",
                )
            if name.lower().startswith(SYSTEM_TABLE_PREFIXES):
                outcome.add(
                    "system_catalog_access",
                    f"Access to system table '{name}' is not allowed.",
                    location=f"table: {name}",
                )
            if (
                self._allowed_schemas
                and db
                and db.lower() not in self._allowed_schemas
                and db.lower() not in SYSTEM_SCHEMAS
            ):
                outcome.add(
                    "schema_not_allowed",
                    f"Schema '{db}' is not in the allowed set.",
                    location=f"table: {db}.{name}",
                )

            table_info = schema.table(name)
            if table_info is None:
                outcome.add(
                    "unknown_table",
                    f"Unknown table '{name}'.",
                    location=f"table: {name}",
                )
                continue

            real_tables.append(table_info.qualified_name)
            # An alias is only unique WITHIN a scope: `refunds AS r` in a CTE and
            # `regions AS r` in the outer query legitimately coexist. So map each
            # alias to the SET of tables it may denote anywhere in the statement.
            alias = (table.alias or name).lower()
            alias_to_real.setdefault(alias, set()).add(name)
            alias_to_real.setdefault(name.lower(), set()).add(name)

        outcome.referenced_tables = sorted(set(real_tables))

        # Columns
        resolved_columns: set[str] = set()
        real_table_infos: list[TableInfo] = [
            info
            for info in (schema.table(name) for name in {r.split(".")[-1] for r in real_tables})
            if info is not None
        ]

        for column in expression.find_all(exp.Column):
            col_name = column.name
            if not col_name or col_name == "*":
                continue
            qualifier = (column.table or "").lower()

            if qualifier:
                if qualifier in virtual_aliases:
                    continue
                candidates = alias_to_real.get(qualifier)
                if not candidates:
                    # Qualifier isn't a known real table/alias; could be a CTE not
                    # captured — skip rather than false-positive.
                    continue
                # The alias may denote several tables (reused across scopes). The
                # column is valid if ANY candidate defines it. We record EVERY
                # matching candidate so the policy engine sees the strictest
                # possible set of base columns — over-reporting is safe, missing
                # a sensitive column would not be.
                owners = [
                    info
                    for info in (schema.table(cand) for cand in sorted(candidates))
                    if info is not None and info.has_column(col_name)
                ]
                if owners:
                    for info in owners:
                        resolved_columns.add(f"{info.name}.{col_name}")
                else:
                    shown = "', '".join(sorted(candidates))
                    outcome.add(
                        "unknown_column",
                        f"Unknown column '{col_name}' on table '{shown}'.",
                        location=f"column: {sorted(candidates)[0]}.{col_name}",
                    )
            else:
                if col_name.lower() in output_aliases:
                    # References a SELECT-list alias, not a table column.
                    continue
                # Unqualified: accept if it exists on any referenced real table.
                owners = [t for t in real_table_infos if t.has_column(col_name)]
                if owners:
                    resolved_columns.add(f"{owners[0].name}.{col_name}")
                elif real_table_infos:
                    outcome.add(
                        "unknown_column",
                        f"Unknown column '{col_name}' (not found on any referenced table).",
                        location=f"column: {col_name}",
                    )

        outcome.referenced_columns = sorted(resolved_columns)

    @staticmethod
    def _virtual_aliases(expression: exp.Expression) -> set[str]:
        """Names that refer to CTEs or derived tables, not catalog tables."""
        aliases: set[str] = set()
        for cte in expression.find_all(exp.CTE):
            if cte.alias:
                aliases.add(cte.alias.lower())
        for subq in expression.find_all(exp.Subquery):
            if subq.alias:
                aliases.add(subq.alias.lower())
        return aliases

    @staticmethod
    def _output_aliases(expression: exp.Expression) -> set[str]:
        """Collect SELECT-list output aliases (``expr AS name``)."""
        aliases: set[str] = set()
        for alias_node in expression.find_all(exp.Alias):
            name = alias_node.alias
            if name:
                aliases.add(name.lower())
        return aliases
