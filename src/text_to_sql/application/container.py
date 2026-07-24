"""Composition root.

Builds the fully-wired object graph (database, catalog, semantic layer, retriever,
provider, validator, policy, rewriter, cost, orchestrator) from
:class:`~text_to_sql.configuration.settings.Settings`. This is the *only* place
concrete implementations are chosen; everything else depends on interfaces, so
swapping the provider or retriever is a one-line change here.

The API layer builds one :class:`AppContainer` at startup and injects the
orchestrator into route handlers.
"""

from __future__ import annotations

from dataclasses import dataclass

from text_to_sql.application.ambiguity import AmbiguityDetector
from text_to_sql.application.explainer import ResultExplainer
from text_to_sql.application.orchestrator import Clock, QueryOrchestrator
from text_to_sql.application.repair import RepairPlanner
from text_to_sql.common.errors import ConfigurationError
from text_to_sql.configuration import Settings
from text_to_sql.domain.enums import SQLDialect
from text_to_sql.infrastructure.database import Database, make_database
from text_to_sql.llm.base import LLMProvider
from text_to_sql.llm.fake import DeterministicFakeProvider
from text_to_sql.llm.openai_adapter import OpenAICompatibleProvider
from text_to_sql.llm.prompt import PromptBuilder
from text_to_sql.observability.metrics import MetricsRegistry, get_metrics
from text_to_sql.observability.tracing import Tracer, get_tracer
from text_to_sql.retrieval.retriever import LexicalSchemaRetriever
from text_to_sql.schema.cache import SchemaCache
from text_to_sql.schema.catalog import SchemaCatalog
from text_to_sql.schema.introspector import SchemaIntrospector
from text_to_sql.security.classification import ColumnAccessPolicy
from text_to_sql.security.config import SecurityPolicyConfig
from text_to_sql.security.cost import CostAnalyzer
from text_to_sql.security.policy import PolicyEngine
from text_to_sql.security.rewriter import TenantRewriter
from text_to_sql.semantic.models import SemanticLayer
from text_to_sql.semantic.reference import build_reference_semantic_layer
from text_to_sql.sql.validator import SQLValidator


def build_provider(settings: Settings) -> LLMProvider:
    """Instantiate the configured LLM provider."""
    if settings.llm_provider == "fake":
        return DeterministicFakeProvider(model=settings.llm_model)
    if settings.llm_provider == "openai":
        return OpenAICompatibleProvider(
            api_key=settings.resolve_llm_api_key(),
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            temperature=settings.llm_temperature,
        )
    raise ConfigurationError(f"Unknown LLM provider '{settings.llm_provider}'.")


@dataclass
class AppContainer:
    """The wired application object graph."""

    settings: Settings
    database: Database
    metrics: MetricsRegistry
    tracer: Tracer
    semantic: SemanticLayer
    catalog: SchemaCatalog
    provider: LLMProvider
    security_config: SecurityPolicyConfig
    orchestrator: QueryOrchestrator
    column_policy: ColumnAccessPolicy

    @classmethod
    def create(
        cls,
        settings: Settings,
        *,
        provider: LLMProvider | None = None,
        database: Database | None = None,
        clock: Clock | None = None,
        metrics: MetricsRegistry | None = None,
        tracer: Tracer | None = None,
    ) -> AppContainer:
        metrics = metrics or get_metrics()
        tracer = tracer or get_tracer()
        database = database or make_database(settings)
        semantic = build_reference_semantic_layer()

        dialect = SQLDialect(settings.sql_dialect)
        cache = SchemaCache(settings.schema_cache_ttl_seconds)
        catalog = SchemaCatalog(SchemaIntrospector(database.engine), semantic, cache, metrics)

        provider = provider or build_provider(settings)
        security_config = SecurityPolicyConfig.from_settings(settings)
        column_policy = ColumnAccessPolicy()

        orchestrator = QueryOrchestrator(
            settings_dialect=dialect,
            max_rows=settings.max_rows,
            max_repair_attempts=settings.max_repair_attempts,
            disclose_model_metadata=settings.disclose_model_metadata,
            catalog=catalog,
            semantic=semantic,
            retriever=LexicalSchemaRetriever(semantic, top_k=settings.retrieval_top_k),
            provider=provider,
            prompt_builder=PromptBuilder(),
            validator=SQLValidator(
                function_denylist=security_config.function_denylist,
                allowed_schemas=security_config.allowed_schemas,
            ),
            policy=PolicyEngine(security_config, column_policy),
            rewriter=TenantRewriter(security_config.tenant_column),
            cost_analyzer=CostAnalyzer(security_config),
            security_config=security_config,
            readonly_engine=database.readonly_engine,
            statement_timeout_ms=settings.statement_timeout_ms,
            ambiguity=AmbiguityDetector(semantic),
            repair_planner=RepairPlanner(),
            explainer=ResultExplainer(),
            metrics=metrics,
            tracer=tracer,
            clock=clock,
        )

        return cls(
            settings=settings,
            database=database,
            metrics=metrics,
            tracer=tracer,
            semantic=semantic,
            catalog=catalog,
            provider=provider,
            security_config=security_config,
            orchestrator=orchestrator,
            column_policy=column_policy,
        )

    def dispose(self) -> None:
        self.database.dispose()
