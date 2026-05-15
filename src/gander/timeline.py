"""Deterministic header/date-range scan over the work-experience slice.

Returns an `EmployerEntry` per detected `(header → date-range)` block in CV
order, with `is_current` flagged when the right-hand side of the range
contains a `_PRESENT_TOKENS` word. Pure parser; no LLM, no heuristics over
anchor proximity. The L5 growth stage uses these entries to populate the
`current_employer_hint` / `closed_employer_hint` payload fields and to gate
post-generation actions against past-employer settings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from gander.tenure import (
    _NON_WORK_SECTION_ALIASES,
    _PRESENT_TOKENS,
    _WORK_SECTION_ALIASES,
    _is_heading_line,
    _normalize,
    work_experience_slice,
)

_YEAR_MARKER_RE: Final = re.compile(r"\[YEAR\]")
_BARE_YEAR_RE: Final = re.compile(r"\b(?:19|20)\d{2}\b")
_DASH_CHARS: Final = ("—", "–", "-")
_BULLET_GLYPHS: Final = ("-", "*", "•", "–", "—")

_PRESENT_ALT: Final = "|".join(
    sorted((re.escape(t) for t in _PRESENT_TOKENS), key=len, reverse=True)
)
_PRESENT_TOKEN_RE: Final = re.compile(rf"\b(?:{_PRESENT_ALT})\b")


@dataclass(frozen=True)
class EmployerEntry:
    header: str
    dates_raw: str
    is_current: bool


def _is_date_range_line(line: str) -> bool:
    if len(line) > 80:
        return False
    if not any(d in line for d in _DASH_CHARS):
        return False
    # Require a year-shaped anchor (bare 4-digit year or the literal [YEAR]
    # post-redaction marker). Bare month names are too noisy — headers like
    # "ML Engineer — May Mobility" would otherwise be misread as a range.
    # A bare present-token ("current"/"now") is also unsafe: titles like
    # "Current Platform Lead — Stealth" carry the word but aren't dates.
    return bool(_YEAR_MARKER_RE.search(line) or _BARE_YEAR_RE.search(line))


def _split_on_first_dash(line: str) -> tuple[str, str]:
    # Splitting on the *first* dash captures everything after the range start,
    # so "January 2024 - Present - Remote" yields "Present - Remote" on the
    # RHS rather than just "Remote" — preserving the present-token signal
    # when the line carries a trailing modifier segment.
    positions = [p for p in (line.find(d) for d in _DASH_CHARS) if p >= 0]
    if not positions:
        return line, ""
    idx = min(positions)
    return line[:idx], line[idx + 1 :]


def _clean_header_line(line: str) -> str:
    s = line.strip()
    while s and s[0] in _BULLET_GLYPHS:
        s = s[1:].lstrip()
    return s.strip()


def _is_section_heading(line: str) -> bool:
    norm = _normalize(line).strip()
    if not norm:
        return False
    return _is_heading_line(norm, _WORK_SECTION_ALIASES) or _is_heading_line(
        norm, _NON_WORK_SECTION_ALIASES
    )


def scan_employer_timeline(redacted_text: str) -> list[EmployerEntry]:
    slice_text = work_experience_slice(redacted_text)
    if slice_text is None:
        return []
    lines = slice_text.split("\n")
    out: list[EmployerEntry] = []
    for i, line in enumerate(lines):
        if not _is_date_range_line(line):
            continue
        header_parts: list[str] = []
        for j in range(i - 1, max(-1, i - 4), -1):
            prev = lines[j]
            if not prev.strip():
                break
            if _is_date_range_line(prev):
                break
            if _is_section_heading(prev):
                break
            cleaned = _clean_header_line(prev)
            if not cleaned:
                continue
            header_parts.append(cleaned)
        header_parts.reverse()
        header = " — ".join(header_parts)
        right_of_dash = _split_on_first_dash(line)[1]
        is_current = bool(_PRESENT_TOKEN_RE.search(_normalize(right_of_dash)))
        out.append(EmployerEntry(header=header, dates_raw=line.strip(), is_current=is_current))
    return out
