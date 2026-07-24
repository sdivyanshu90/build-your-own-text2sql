"""Relative-date resolution under a documented calendar policy.

Natural-language questions use relative dates ("last quarter", "past 90 days").
Resolving these deterministically — rather than letting the LLM guess — is what
makes results reproducible. The resolver takes an explicit ``now`` reference
(injected by the orchestrator, fixed in tests) so behaviour is testable and never
depends on wall-clock non-determinism.

Policy (UTC, Gregorian):
* "last quarter"  -> the most recently *completed* calendar quarter
* "this quarter"  -> current quarter to date
* "last month"    -> the most recently completed calendar month
* "this month"    -> current month to date
* "last year"     -> previous calendar year
* "this year"/"ytd" -> current calendar year to date
* "last N days"/"past N days" -> [now - N days, now]
* "today"/"yesterday" -> the respective calendar day
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class ResolvedDateRange:
    """An inclusive-start / exclusive-end date window and its description."""

    start: datetime
    end: datetime
    description: str
    matched_phrase: str

    def as_sql_predicate(self, column: str) -> str:
        """Render a half-open predicate ``col >= start AND col < end``.

        Values are ISO-formatted literals. These are *documented, engine-derived*
        constants injected into the prompt as guidance and later re-validated by
        the AST validator against the schema; they are not user-supplied strings.
        """
        return (
            f"{column} >= '{self.start.isoformat(sep=' ')}' "
            f"AND {column} < '{self.end.isoformat(sep=' ')}'"
        )


def _month_start(dt: datetime) -> datetime:
    return datetime(dt.year, dt.month, 1)


def _add_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = (year * 12 + (month - 1)) + delta
    return index // 12, index % 12 + 1


def _quarter_of(month: int) -> int:
    return (month - 1) // 3  # 0..3


_PATTERNS = {
    "last_quarter": re.compile(r"\blast\s+quarter\b"),
    "this_quarter": re.compile(r"\bthis\s+quarter\b"),
    "last_month": re.compile(r"\blast\s+month\b"),
    "this_month": re.compile(r"\bthis\s+month\b"),
    "last_year": re.compile(r"\blast\s+year\b"),
    "this_year": re.compile(r"\b(this\s+year|year\s+to\s+date|ytd)\b"),
    "yesterday": re.compile(r"\byesterday\b"),
    "today": re.compile(r"\btoday\b"),
    "last_n_days": re.compile(r"\b(?:last|past|previous)\s+(\d{1,4})\s+days?\b"),
    "last_week": re.compile(r"\blast\s+week\b"),
}


def resolve_relative_date(question: str, now: datetime) -> ResolvedDateRange | None:
    """Resolve the first relative-date phrase found in ``question``.

    Returns ``None`` when no known relative-date phrase is present.
    """
    text = question.lower()

    m = _PATTERNS["last_n_days"].search(text)
    if m:
        days = int(m.group(1))
        start = now - timedelta(days=days)
        return ResolvedDateRange(start, now, f"the last {days} days", m.group(0))

    if _PATTERNS["last_quarter"].search(text):
        q = _quarter_of(now.month)
        # Most recently completed quarter is the one before the current quarter.
        first_month_current_q = q * 3 + 1
        cur_q_start = datetime(now.year, first_month_current_q, 1)
        # last quarter start = current quarter start minus 3 months
        ly, lm = _add_month(cur_q_start.year, cur_q_start.month, -3)
        start = datetime(ly, lm, 1)
        return ResolvedDateRange(
            start, cur_q_start, "the last completed calendar quarter", "last quarter"
        )

    if _PATTERNS["this_quarter"].search(text):
        q = _quarter_of(now.month)
        start = datetime(now.year, q * 3 + 1, 1)
        return ResolvedDateRange(start, now, "the current quarter to date", "this quarter")

    if _PATTERNS["last_month"].search(text):
        ly, lm = _add_month(now.year, now.month, -1)
        start = datetime(ly, lm, 1)
        end = _month_start(now)
        return ResolvedDateRange(start, end, "the last completed calendar month", "last month")

    if _PATTERNS["this_month"].search(text):
        return ResolvedDateRange(_month_start(now), now, "the current month to date", "this month")

    if _PATTERNS["last_year"].search(text):
        start = datetime(now.year - 1, 1, 1)
        end = datetime(now.year, 1, 1)
        return ResolvedDateRange(start, end, "the previous calendar year", "last year")

    if _PATTERNS["this_year"].search(text):
        return ResolvedDateRange(
            datetime(now.year, 1, 1), now, "the current year to date", "this year"
        )

    if _PATTERNS["last_week"].search(text):
        # ISO week starting Monday; last completed week.
        weekday = now.weekday()
        this_week_start = datetime(now.year, now.month, now.day) - timedelta(days=weekday)
        start = this_week_start - timedelta(days=7)
        return ResolvedDateRange(start, this_week_start, "the last completed week", "last week")

    if _PATTERNS["yesterday"].search(text):
        day = datetime(now.year, now.month, now.day) - timedelta(days=1)
        return ResolvedDateRange(day, day + timedelta(days=1), "yesterday", "yesterday")

    if _PATTERNS["today"].search(text):
        day = datetime(now.year, now.month, now.day)
        return ResolvedDateRange(day, day + timedelta(days=1), "today", "today")

    return None


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]
