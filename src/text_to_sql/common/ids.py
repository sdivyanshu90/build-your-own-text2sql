"""Correlation and request identifier helpers.

Correlation IDs tie together every log line, span, and error for a single
request so operators can trace one question end-to-end. If the client supplies
a correlation ID we honour it (after sanitizing); otherwise we mint one.
"""

from __future__ import annotations

import re
import uuid

_SAFE_ID = re.compile(r"[^A-Za-z0-9_.:-]")
_MAX_ID_LEN = 128


def new_request_id() -> str:
    """Return a fresh, unique request identifier."""
    return f"req_{uuid.uuid4().hex}"


def new_correlation_id() -> str:
    """Return a fresh correlation identifier."""
    return f"corr_{uuid.uuid4().hex}"


def sanitize_correlation_id(value: str | None) -> str:
    """Sanitize a client-supplied correlation ID or mint a new one.

    Client-controlled identifiers are untrusted input. We strip characters
    outside a conservative allowlist (so IDs can't smuggle control characters
    or newlines into logs) and bound the length. Empty/invalid values yield a
    freshly generated ID.
    """
    if not value:
        return new_correlation_id()
    cleaned = _SAFE_ID.sub("", value)[:_MAX_ID_LEN]
    return cleaned or new_correlation_id()
