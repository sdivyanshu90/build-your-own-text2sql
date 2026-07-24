"""Schema discovery, catalog, and caching.

The catalog turns a live database into the engine's normalized
:class:`~text_to_sql.domain.schema_models.DatabaseSchema`, enriched with semantic
governance metadata (classifications, comments, tenant columns) and served from a
TTL cache with explicit invalidation. Only this enriched, sanitized catalog is
ever exposed to retrieval, prompting, and validation — never live rows.
"""

from __future__ import annotations

from text_to_sql.schema.cache import SchemaCache
from text_to_sql.schema.catalog import SchemaCatalog
from text_to_sql.schema.introspector import SchemaIntrospector

__all__ = ["SchemaCache", "SchemaCatalog", "SchemaIntrospector"]
