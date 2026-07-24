"""The query orchestrator: the pipeline's single entry point.

Coordinates the full lifecycle for one request:

    normalize/authorize → ambiguity check → schema retrieval → date resolution
    → prompt build → generate (with bounded repair) → parse → AST validate
    → policy → tenant rewrite → re-validate → cost/EXPLAIN → execute → explain

Security-critical properties:

* Every generated candidate — original or repaired — passes through the *entire*
  deterministic gate (validate → policy → rewrite → re-validate → cost). Repair
  never bypasses a check.
* Tenant isolation and read-only enforcement do not depend on the model.
* Failures raise typed :class:`~text_to_sql.common.errors.EngineError`s carrying
  machine-readable, sanitized validation details; the API maps them to a uniform
  envelope.

Route handlers call only this class.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import Engine

from text_to_sql.application.ambiguity import AmbiguityDetector
from text_to_sql.application.explainer import ResultExplainer
from text_to_sql.application.repair import RepairPlanner
from text_to_sql.common.errors import (
    AuthorizationError,
    CostRejectedError,
    RepairExhaustedError,
    SQLParseError,
    SQLValidationError,
)
from text_to_sql.common.ids import sanitize_correlation_id
from text_to_sql.domain.context import AuthContext
from text_to_sql.domain.enums import ResponseStatus, SQLDialect, StatementType
from text_to_sql.domain.models import (
    ExecutionMetadata,
    ModelMetadata,
    QueryRequest,
    QueryResponse,
    StageTimings,
    ValidateSQLRequest,
    ValidationIssue,
    ValidationReport,
)
from text_to_sql.domain.schema_models import DatabaseSchema
from text_to_sql.execution.executor import ReadOnlyExecutor
from text_to_sql.llm.base import (
    GenerationRequest,
    GenerationResponse,
    LLMProvider,
    RepairContext,
    ResolvedDate,
)
from text_to_sql.llm.prompt import PromptBuilder, PromptContext, contains_injection_markers
from text_to_sql.observability.logging import (
    bind_correlation_id,
    get_correlation_id,
    get_logger,
)
from text_to_sql.observability.metrics import MetricsRegistry
from text_to_sql.observability.tracing import Tracer
from text_to_sql.retrieval.retriever import RetrievalResult, SchemaRetriever
from text_to_sql.schema.catalog import SchemaCatalog
from text_to_sql.security.config import SecurityPolicyConfig
from text_to_sql.security.cost import CostAnalyzer, CostReport
from text_to_sql.security.policy import PolicyEngine
from text_to_sql.security.rewriter import TenantRewriter
from text_to_sql.semantic.dates import resolve_relative_date
from text_to_sql.semantic.models import SemanticLayer
from text_to_sql.sql.normalizer import enforce_limit, normalize_sql
from text_to_sql.sql.validator import SQLValidator

_log = get_logger(__name__)

Clock = Callable[[], datetime]


@dataclass
class _Secured:
    """Internal result of running one candidate through all deterministic gates."""

    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    final_sql: str | None = None
    statement_type: StatementType = StatementType.OTHER
    referenced_tables: list[str] = field(default_factory=list)
    referenced_columns: list[str] = field(default_factory=list)
    applied_rewrites: list[str] = field(default_factory=list)
    cost: CostReport | None = None


class QueryOrchestrator:
    """Coordinates the end-to-end Text-to-SQL pipeline."""

    def __init__(
        self,
        *,
        settings_dialect: SQLDialect,
        max_rows: int,
        max_repair_attempts: int,
        disclose_model_metadata: bool,
        catalog: SchemaCatalog,
        semantic: SemanticLayer,
        retriever: SchemaRetriever,
        provider: LLMProvider,
        prompt_builder: PromptBuilder,
        validator: SQLValidator,
        policy: PolicyEngine,
        rewriter: TenantRewriter,
        cost_analyzer: CostAnalyzer,
        security_config: SecurityPolicyConfig,
        readonly_engine: Engine,
        statement_timeout_ms: int,
        ambiguity: AmbiguityDetector,
        repair_planner: RepairPlanner,
        explainer: ResultExplainer,
        metrics: MetricsRegistry,
        tracer: Tracer,
        clock: Clock | None = None,
    ) -> None:
        self._default_dialect = settings_dialect
        self._max_rows = max_rows
        self._max_repair = max_repair_attempts
        self._disclose = disclose_model_metadata
        self._catalog = catalog
        self._semantic = semantic
        self._retriever = retriever
        self._provider = provider
        self._prompt = prompt_builder
        self._validator = validator
        self._policy = policy
        self._rewriter = rewriter
        self._cost = cost_analyzer
        self._security = security_config
        self._readonly_engine = readonly_engine
        self._statement_timeout_ms = statement_timeout_ms
        self._ambiguity = ambiguity
        self._repair = repair_planner
        self._explainer = explainer
        self._metrics = metrics
        self._tracer = tracer
        self._clock = clock or (lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def process(
        self,
        request: QueryRequest,
        auth: AuthContext,
        *,
        execute: bool = True,
    ) -> QueryResponse:
        # Prefer an explicit body correlation id; otherwise reuse the one the
        # transport already bound (e.g. from the X-Correlation-Id header) so the
        # response body and response header always agree.
        bound = get_correlation_id()
        raw = request.correlation_id or (None if bound == "-" else bound)
        correlation_id = sanitize_correlation_id(raw)
        bind_correlation_id(correlation_id)
        start = time.perf_counter()
        timings = StageTimings()

        with self._tracer.start_span("query.process", user=auth.user_id, tenant=auth.tenant_id):
            self._authorize_tenant(request, auth)
            self._metrics.inc("t2sql_requests_total", 1.0, mode="execute" if execute else "preview")

            if contains_injection_markers(request.question):
                # Logged for detection; not a security boundary (validation is).
                self._metrics.inc("t2sql_injection_markers_total", 1.0, surface="question")
                _log.warning("injection_markers_in_question")

            # 1. Ambiguity — short-circuit before any generation.
            clarification = self._ambiguity.detect(request.question)
            if clarification is not None:
                self._metrics.inc(
                    "t2sql_clarifications_total", 1.0, category=clarification.category.value
                )
                timings.total_ms = (time.perf_counter() - start) * 1000.0
                return QueryResponse(
                    status=ResponseStatus.CLARIFICATION_REQUIRED,
                    correlation_id=correlation_id,
                    clarification=clarification,
                    timings=timings,
                )

            dialect = request.dialect or self._default_dialect
            max_rows = min(request.max_rows or self._max_rows, self._max_rows)

            # 2. Schema + retrieval
            schema = self._catalog.get_schema()
            with self._tracer.start_span("retrieval") as span:
                t0 = time.perf_counter()
                retrieval = self._retriever.retrieve(request.question, schema)
                timings.retrieval_ms = (time.perf_counter() - t0) * 1000.0
                span.set_attributes(table_count=len(retrieval.selected))

            # 3. Relative-date resolution
            resolved_date = self._resolve_date(request.question)

            # 4. Generation + bounded repair
            generation, secured, attempts = await self._generate_with_repair(
                request=request,
                auth=auth,
                dialect=dialect,
                max_rows=max_rows,
                schema=schema,
                retrieval=retrieval,
                resolved_date=resolved_date,
                timings=timings,
            )

            if not secured.ok:
                timings.total_ms = (time.perf_counter() - start) * 1000.0
                self._raise_for_failure(secured, attempts)

            assert secured.final_sql is not None
            report = self._build_report(secured, applied=secured.applied_rewrites)

            # 5. Execute (unless preview/dry-run/sql-only)
            do_execute = execute and not request.dry_run and not request.sql_only
            model_meta = self._model_metadata(generation, attempts)

            if not do_execute:
                timings.total_ms = (time.perf_counter() - start) * 1000.0
                self._metrics.inc("t2sql_requests_success_total", 1.0, mode="preview")
                return QueryResponse(
                    status=ResponseStatus.PREVIEW,
                    correlation_id=correlation_id,
                    sql=secured.final_sql,
                    dialect=dialect,
                    explanation=generation.explanation or None,
                    assumptions=list(generation.assumptions),
                    confidence=generation.confidence,
                    validation=report,
                    retrieval=retrieval.selected,
                    timings=timings,
                    model=model_meta,
                )

            with self._tracer.start_span("execution") as span:
                t0 = time.perf_counter()
                executor = ReadOnlyExecutor(
                    self._readonly_engine, dialect, statement_timeout_ms=self._statement_timeout_ms
                )
                exec_result = await asyncio.to_thread(
                    executor.execute, secured.final_sql, max_rows=max_rows
                )
                timings.execution_ms = (time.perf_counter() - t0) * 1000.0
                span.set_attributes(
                    row_count=exec_result.row_count, truncated=exec_result.truncated
                )
            self._metrics.observe("t2sql_execution_ms", timings.execution_ms)

            explanation: str | None = generation.explanation
            warnings: list[str] = []
            if request.explain:
                explanation, warnings = self._explainer.explain(
                    question=request.question,
                    result=exec_result,
                    assumptions=list(generation.assumptions),
                    confidence=generation.confidence,
                    truncated_note=exec_result.truncated,
                )

            timings.total_ms = (time.perf_counter() - start) * 1000.0
            self._metrics.inc("t2sql_requests_success_total", 1.0, mode="execute")
            self._metrics.observe("t2sql_total_ms", timings.total_ms)

            return QueryResponse(
                status=ResponseStatus.SUCCESS,
                correlation_id=correlation_id,
                sql=secured.final_sql,
                dialect=dialect,
                columns=exec_result.columns,
                rows=exec_result.rows,
                row_count=exec_result.row_count,
                truncated=exec_result.truncated,
                explanation=explanation,
                assumptions=list(generation.assumptions),
                warnings=warnings,
                confidence=generation.confidence,
                validation=report,
                retrieval=retrieval.selected,
                timings=timings,
                execution=ExecutionMetadata(
                    row_count=exec_result.row_count,
                    truncated=exec_result.truncated,
                    duration_ms=exec_result.duration_ms,
                ),
                model=model_meta,
            )

    def validate_sql(self, request: ValidateSQLRequest, auth: AuthContext) -> ValidationReport:
        """Validate caller-supplied SQL through the same deterministic engine.

        Never executes. Returns a report (does not raise for invalid SQL) so the
        endpoint can return 200 with structured findings.
        """
        bind_correlation_id(sanitize_correlation_id(None))
        dialect = request.dialect or self._default_dialect
        schema = self._catalog.get_schema()
        secured = self._secure_candidate(request.sql, dialect, schema, auth, self._max_rows)
        return self._build_report(secured, applied=secured.applied_rewrites)

    # ------------------------------------------------------------------ #
    # Generation + repair loop
    # ------------------------------------------------------------------ #
    async def _generate_with_repair(
        self,
        *,
        request: QueryRequest,
        auth: AuthContext,
        dialect: SQLDialect,
        max_rows: int,
        schema: DatabaseSchema,
        retrieval: RetrievalResult,
        resolved_date: ResolvedDate | None,
        timings: StageTimings,
    ) -> tuple[GenerationResponse, _Secured, int]:
        prompt_ctx = PromptContext(
            question=request.question,
            dialect=dialect,
            schema_text=retrieval.schema_subset.serialize_for_prompt(),
            semantic_text=self._prompt.render_semantic_context(
                self._semantic, retrieval.table_names
            ),
            max_rows=max_rows,
            resolved_date_text=(resolved_date.description if resolved_date else None),
            conversation_summary=self._conversation_summary(request),
        )
        payload = self._prompt.build(prompt_ctx)

        repair_context: RepairContext | None = None
        last_generation: GenerationResponse | None = None
        last_secured = _Secured(ok=False)
        attempts = 0

        for attempt in range(self._max_repair + 1):
            gen_req = GenerationRequest(
                question=request.question,
                dialect=dialect,
                schema_subset=retrieval.schema_subset,
                semantic_layer=self._semantic,
                prompt=payload,
                max_rows=max_rows,
                resolved_date=resolved_date,
                conversation=request.conversation,
                repair=repair_context,
                model=self._provider.model,
            )
            with self._tracer.start_span("generation", attempt=attempt) as span:
                t0 = time.perf_counter()
                generation = await self._provider.generate(gen_req)
                timings.generation_ms += (time.perf_counter() - t0) * 1000.0
                span.set_attributes(confidence=generation.confidence)
            self._metrics.observe("t2sql_generation_ms", timings.generation_ms)
            last_generation = generation

            secured = self._secure_candidate(generation.sql, dialect, schema, auth, max_rows)
            last_secured = secured
            if secured.ok:
                break

            if attempt < self._max_repair and self._repair.is_repairable(secured.issues):
                attempts += 1
                self._metrics.inc("t2sql_repair_attempts_total", 1.0)
                _log.info(
                    "repair_attempt",
                    attempt=attempts,
                    rejected_codes=",".join(sorted({i.code for i in secured.issues})),
                )
                repair_context = RepairContext(
                    attempt=attempts,
                    previous_sql=generation.sql,
                    errors=self._repair.sanitized_feedback(secured.issues),
                )
                continue
            break

        assert last_generation is not None
        return last_generation, last_secured, attempts

    # ------------------------------------------------------------------ #
    # Deterministic gate
    # ------------------------------------------------------------------ #
    def _secure_candidate(
        self,
        sql: str,
        dialect: SQLDialect,
        schema: DatabaseSchema,
        auth: AuthContext,
        max_rows: int,
    ) -> _Secured:
        with self._tracer.start_span("validate_and_secure"):
            # 1. Parse + structural/schema validation.
            try:
                outcome = self._validator.validate(sql, dialect, schema)
            except SQLParseError as exc:
                return _Secured(
                    ok=False,
                    issues=[
                        ValidationIssue(
                            code="sql_parse_failed",
                            message=str(exc.details.get("reason", "SQL could not be parsed.")),
                        )
                    ],
                )
            if not outcome.is_valid or outcome.expression is None:
                return _Secured(
                    ok=False,
                    issues=list(outcome.issues),
                    statement_type=outcome.statement_type,
                    referenced_tables=outcome.referenced_tables,
                    referenced_columns=outcome.referenced_columns,
                )

            # 2. Authorization policy (tables + column sensitivity).
            decision = self._policy.enforce(
                outcome.referenced_tables, outcome.referenced_columns, schema, auth
            )
            if not decision.allowed:
                return _Secured(
                    ok=False,
                    issues=list(decision.issues),
                    statement_type=outcome.statement_type,
                    referenced_tables=outcome.referenced_tables,
                    referenced_columns=outcome.referenced_columns,
                )

            # 3. Tenant rewrite (mandatory predicates via AST).
            scoped_expr, applied = self._rewriter.rewrite(
                outcome.expression, schema, auth.tenant_id
            )

            # 4. Enforce a bounded LIMIT.
            limit_outcome = enforce_limit(scoped_expr, max_rows)
            final_expr = limit_outcome.expression

            # 5. Re-validate the rewritten + limited AST (defense in depth).
            revalidation = self._validator.validate_expression(final_expr, dialect, schema)
            if not revalidation.is_valid:
                return _Secured(ok=False, issues=list(revalidation.issues))

            final_sql = normalize_sql(final_expr, dialect, pretty=False)

            # 6. Cost / complexity (+ EXPLAIN where available).
            cost = self._cost.analyze(final_expr, final_sql, dialect, self._readonly_engine)
            if not cost.allowed:
                return _Secured(ok=False, issues=list(cost.issues), cost=cost)

            return _Secured(
                ok=True,
                final_sql=final_sql,
                statement_type=revalidation.statement_type,
                referenced_tables=revalidation.referenced_tables,
                referenced_columns=revalidation.referenced_columns,
                applied_rewrites=applied,
                cost=cost,
            )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _authorize_tenant(self, request: QueryRequest, auth: AuthContext) -> None:
        if request.tenant_id is not None and request.tenant_id != auth.tenant_id:
            raise AuthorizationError(
                "The requested tenant does not match the authenticated tenant.",
                details={"code": "tenant_mismatch"},
            )

    def _resolve_date(self, question: str) -> ResolvedDate | None:
        rd = resolve_relative_date(question, self._clock())
        if rd is None:
            return None
        return ResolvedDate(
            description=rd.description,
            matched_phrase=rd.matched_phrase,
            start_iso=rd.start.isoformat(sep=" "),
            end_iso=rd.end.isoformat(sep=" "),
        )

    def _conversation_summary(self, request: QueryRequest) -> str | None:
        if not request.conversation or not request.conversation.last:
            return None
        last = request.conversation.last
        bits = [f"Previous question: {last.question}"]
        if last.metrics:
            bits.append(f"metrics: {', '.join(last.metrics)}")
        if last.dimensions:
            bits.append(f"dimensions: {', '.join(last.dimensions)}")
        if last.filters:
            bits.append(f"filters: {', '.join(last.filters)}")
        if last.date_range:
            bits.append(f"date range: {last.date_range}")
        return "; ".join(bits)

    def _build_report(self, secured: _Secured, *, applied: list[str]) -> ValidationReport:
        risk = secured.cost.risk_level if secured.cost else None
        est = secured.cost.estimated_rows if secured.cost else None
        return ValidationReport(
            is_valid=secured.ok,
            statement_type=secured.statement_type.value if secured.statement_type else None,
            referenced_tables=secured.referenced_tables,
            referenced_columns=secured.referenced_columns,
            issues=secured.issues,
            risk_level=risk,
            estimated_cost=est,
            applied_rewrites=applied,
        )

    def _model_metadata(
        self, generation: GenerationResponse, attempts: int
    ) -> ModelMetadata | None:
        if not self._disclose:
            return None
        return ModelMetadata(
            provider=generation.provider,
            model=generation.model,
            prompt_version=generation.prompt_version,
            prompt_tokens=generation.usage.prompt_tokens,
            completion_tokens=generation.usage.completion_tokens,
            repair_attempts=attempts,
        )

    def _raise_for_failure(self, secured: _Secured, attempts: int) -> None:
        codes = {issue.code for issue in secured.issues}
        details = {
            "issues": [issue.model_dump() for issue in secured.issues],
            "repair_attempts": attempts,
        }
        auth_codes = {"column_denied", "table_denied", "table_not_allowed"}
        cost_codes = {
            "cartesian_product",
            "too_many_joins",
            "subquery_too_deep",
            "too_many_columns",
            "estimated_cost_too_high",
        }
        security_codes = {
            "non_read_only_statement",
            "forbidden_statement",
            "multiple_statements",
            "comment_present",
            "system_catalog_access",
            "cross_database_access",
            "schema_not_allowed",
        }
        self._metrics.inc("t2sql_requests_rejected_total", 1.0)
        if codes & auth_codes:
            raise AuthorizationError(
                "The query accesses data you are not permitted to read.", details=details
            )
        if codes & cost_codes:
            raise CostRejectedError(
                "The query was rejected as too expensive or complex.", details=details
            )
        if codes & security_codes:
            raise SQLValidationError("The generated SQL violated a safety rule.", details=details)
        raise RepairExhaustedError(
            "A valid query could not be produced within the allowed repair attempts.",
            details=details,
        )
