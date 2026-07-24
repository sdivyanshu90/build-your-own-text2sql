"""Redaction utilities.

These functions scrub sensitive values from any text that might reach a log,
trace, exception, LLM prompt, or API response. Redaction is *defensive in
depth*: the schema/policy layers already prevent sensitive columns from being
selected, but if a sensitive value ever slips into a string destined for output
we want a second net.

Two mechanisms are provided:

* :func:`redact_text` — pattern-based scrubbing of well-known secret/PII shapes
  (connection strings, bearer tokens, emails, card-like numbers, phone numbers).
* :class:`Redactor` — a configurable object that additionally redacts a caller-
  supplied set of *literal* sensitive values (e.g. a resolved API key or known
  PII strings) via exact substring replacement.

Redaction is best-effort for free text and exact for known literals. It is *not*
a substitute for never handling the secret in the first place.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

REDACTED = "«redacted»"

# Order matters: connection strings before generic emails, etc.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # DSNs / connection strings with embedded credentials:
    #   scheme://user:password@host  ->  keep scheme+host, drop credentials
    (
        "credential_uri",
        re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)[^\s:@/]+:[^\s@/]+@"),
    ),
    # Authorization / bearer tokens and api keys in key=value form
    (
        "bearer",
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"),
    ),
    (
        "api_key_kv",
        re.compile(
            r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*"
            r"['\"]?[^\s'\"&,;]+"
        ),
    ),
    # Common provider key prefix (e.g. sk-...)
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{12,}\b")),
    # Emails
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    # Card-like sequences (13-19 digits, optional separators)
    ("card", re.compile(r"\b(?:\d[ \-]?){13,19}\b")),
    # Phone-like sequences (avoid over-matching short numbers)
    ("phone", re.compile(r"\b\+?\d[\d\s().\-]{7,}\d\b")),
)


def redact_text(text: str) -> str:
    """Return ``text`` with well-known secret/PII shapes replaced.

    For the credential-URI case we preserve the scheme and host so operators can
    still see *which* database/provider is involved, while removing the
    embedded ``user:password``.
    """
    if not text:
        return text
    result = text
    for name, pattern in _PATTERNS:
        if name == "credential_uri":
            result = pattern.sub(lambda m: f"{m.group('scheme')}{REDACTED}@", result)
        else:
            result = pattern.sub(REDACTED, result)
    return result


class Redactor:
    """Configurable redactor combining pattern-based and literal redaction.

    Parameters
    ----------
    literals:
        Exact strings to remove wherever they appear (e.g. a resolved API key,
        known sensitive sample values). Empty/short literals are ignored to
        avoid pathological substitutions.
    apply_patterns:
        Whether to also apply the built-in PII/secret pattern set.
    """

    _MIN_LITERAL_LEN = 4

    def __init__(
        self,
        literals: Iterable[str] | None = None,
        *,
        apply_patterns: bool = True,
    ) -> None:
        self._literals = sorted(
            {lit for lit in (literals or []) if lit and len(lit) >= self._MIN_LITERAL_LEN},
            key=len,
            reverse=True,  # replace longer literals first
        )
        self._apply_patterns = apply_patterns

    def redact(self, text: str) -> str:
        if not text:
            return text
        result = text
        for literal in self._literals:
            if literal in result:
                result = result.replace(literal, REDACTED)
        if self._apply_patterns:
            result = redact_text(result)
        return result

    def redact_mapping(self, mapping: dict[str, object]) -> dict[str, object]:
        """Recursively redact string values inside a JSON-like mapping."""
        return {key: self._redact_value(value) for key, value in mapping.items()}

    def _redact_value(self, value: object) -> object:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            return self.redact_mapping(value)  # type: ignore[arg-type]
        if isinstance(value, (list, tuple)):
            return [self._redact_value(item) for item in value]
        return value
