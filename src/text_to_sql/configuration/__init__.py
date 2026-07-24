"""Strongly-typed application configuration.

Configuration is loaded once from environment variables (and an optional
``.env`` file) into an immutable :class:`~text_to_sql.configuration.settings.Settings`
object, validated at startup. No module reads ``os.environ`` directly; everything
flows through this object so behaviour is centralized, testable, and overridable.
"""

from __future__ import annotations

from text_to_sql.configuration.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
