"""TTL cache for the enriched schema with explicit invalidation.

Schema introspection is comparatively expensive and rarely-changing, so we cache
the enriched catalog. The cache is:

* **TTL-bounded** — entries expire after ``ttl_seconds`` so slow schema drift is
  eventually picked up automatically.
* **Explicitly invalidatable** — ``POST /schema/refresh`` clears it for immediate
  pickup after a migration.
* **Version-aware** — the cached schema carries a structural ``version`` hash; a
  refresh that yields a different version is logged as drift.

The cache stores exactly one schema (single data source in this reference build).
It is deliberately *not* keyed by tenant: the schema shape is identical across
tenants; per-tenant *authorization filtering* happens at read time in the catalog,
never by caching different shapes.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from text_to_sql.domain.schema_models import DatabaseSchema


@dataclass
class _Entry:
    schema: DatabaseSchema
    stored_monotonic: float


class SchemaCache:
    """Thread-safe single-slot schema cache with TTL and manual invalidation."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._entry: _Entry | None = None

    def get(self) -> DatabaseSchema | None:
        with self._lock:
            if self._entry is None:
                return None
            if self._ttl > 0 and (time.monotonic() - self._entry.stored_monotonic) > self._ttl:
                # Expired: drop and force a refresh on next access.
                self._entry = None
                return None
            return self._entry.schema

    def set(self, schema: DatabaseSchema) -> None:
        with self._lock:
            self._entry = _Entry(schema=schema, stored_monotonic=time.monotonic())

    def invalidate(self) -> None:
        with self._lock:
            self._entry = None

    @property
    def current_version(self) -> str | None:
        with self._lock:
            return self._entry.schema.version if self._entry else None
