"""Deterministic tenure computation from CV date ranges.

Pure parser that scans CV text for `(month|year) - (month|year|present)` ranges,
unions overlapping intervals, and sums the resulting span in whole years. Used
by L2 to compute `RedactedCV.years_experience_deterministic` before year tokens
are masked, so L3 (extract) does not have to infer tenure from `[YEAR] - [YEAR]`
patterns (PRD §4.7 + R7 in T28).

The parser is bilingual (CZ + EN month names) and recognises the common Czech
"present" variants (`nyní`, `současnost`, `dosud`, ...). When no parseable range
is found, returns `None` and the downstream consumer keeps the LLM's value.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Final

# EN months: full + short. Stored lowercased.
_EN_MONTHS: Final[dict[str, int]] = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

# CZ months: nominative + genitive (the form that appears in date ranges,
# e.g. "ledna 2017"). Stored accent-stripped + lowercased; matching is done
# against a normalised view of the haystack.
_CZ_MONTHS: Final[dict[str, int]] = {
    # Nominative
    "leden": 1,
    "unor": 2,
    "brezen": 3,
    "duben": 4,
    "kveten": 5,
    "cerven": 6,
    "cervenec": 7,
    "srpen": 8,
    "zari": 9,
    "rijen": 10,
    "listopad": 11,
    "prosinec": 12,
    # Genitive (used in date ranges: "ledna 2017 - prosince 2020")
    "ledna": 1,
    "unora": 2,
    "brezna": 3,
    "dubna": 4,
    "kvetna": 5,
    "cervna": 6,
    "cervence": 7,
    "srpna": 8,
    # "zari" is invariant
    "rijna": 10,
    "listopadu": 11,
    "prosince": 12,
}

_MONTHS: Final[dict[str, int]] = {**_EN_MONTHS, **_CZ_MONTHS}

# "Present"-equivalent tokens, accent-stripped + lowercased.
_PRESENT_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "present",
        "current",
        "now",
        "nyni",
        "soucasnost",
        "soucasne",
        "dosud",
    }
)

_YEAR_RE: Final = r"(?:19|20)\d{2}"
_DASH: Final = r"[-–—]"

# Build alternation patterns from the keyword sets, longest-first so we don't
# accidentally match "jan" inside "january".
_MONTH_ALT: Final = "|".join(sorted(_MONTHS.keys(), key=len, reverse=True))
_PRESENT_ALT: Final = "|".join(sorted(_PRESENT_TOKENS, key=len, reverse=True))

# Endpoint shapes (matched against the normalized — lowercase, accent-stripped —
# text). Order matters: "month year" must beat "bare year" so we don't strip
# the month name and lose its information.
_ENDPOINT_PATTERN: Final = (
    rf"(?:(?:{_MONTH_ALT})\s+{_YEAR_RE}"
    rf"|{_YEAR_RE}"
    rf"|(?:{_PRESENT_ALT}))"
)
_RANGE_RE: Final = re.compile(rf"\b({_ENDPOINT_PATTERN})\s*{_DASH}\s*({_ENDPOINT_PATTERN})\b")


@dataclass(frozen=True)
class _Interval:
    """Half-open [start, end) month-resolution interval, encoded as months."""

    start_months: int  # absolute months since year 0: year*12 + (month-1)
    end_months: int


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _normalize(text: str) -> str:
    return _strip_accents(text).lower()


def _today_ym() -> tuple[int, int]:
    today = date.today()
    return today.year, today.month


def _parse_endpoint(token: str) -> tuple[int, int] | None:
    """Parse a normalised endpoint substring into (year, month)."""
    nlow = token.strip()
    if nlow in _PRESENT_TOKENS:
        return _today_ym()
    m = re.match(rf"^(\w+)\s+({_YEAR_RE})$", nlow)
    if m:
        word, year_s = m.group(1), m.group(2)
        if word in _MONTHS:
            return int(year_s), _MONTHS[word]
        return None
    m = re.match(rf"^({_YEAR_RE})$", nlow)
    if m:
        return int(m.group(1)), 1
    return None


def _iter_intervals(text: str) -> list[_Interval]:
    """Find all parseable `(endpoint) - (endpoint)` ranges in text."""
    today_y, today_m = _today_ym()
    today_months = today_y * 12 + (today_m - 1)
    norm = _normalize(text)
    out: list[_Interval] = []
    for m in _RANGE_RE.finditer(norm):
        left = _parse_endpoint(m.group(1))
        right = _parse_endpoint(m.group(2))
        if left is None or right is None:
            continue
        ly, lm = left
        ry, rm = right
        start_months = ly * 12 + (lm - 1)
        end_months = ry * 12 + (rm - 1)  # last covered month (inclusive)
        if start_months > end_months:
            continue  # reversed range
        # Cap "to present" at today even if the model returns a future-ish year.
        if end_months > today_months:
            end_months = today_months
        # Make half-open: end is the month AFTER the last covered month.
        out.append(_Interval(start_months=start_months, end_months=end_months + 1))
    return out


def _union_months(intervals: list[_Interval]) -> int:
    """Sum the union of intervals in months (overlap counted once, gaps skipped)."""
    if not intervals:
        return 0
    pairs = sorted((iv.start_months, iv.end_months) for iv in intervals)
    total = 0
    cur_start, cur_end = pairs[0]
    for start, end in pairs[1:]:
        if start <= cur_end:
            if end > cur_end:
                cur_end = end
        else:
            total += cur_end - cur_start
            cur_start, cur_end = start, end
    total += cur_end - cur_start
    return total


def compute_years(text: str) -> int | None:
    """Return whole years of tenure spanned by date ranges in `text`.

    Returns `None` when no parseable range is found. Overlapping intervals are
    unioned (not summed); gaps are skipped. Months are floored to whole years.
    """
    intervals = _iter_intervals(text)
    if not intervals:
        return None
    months = _union_months(intervals)
    if months <= 0:
        return None
    return months // 12
