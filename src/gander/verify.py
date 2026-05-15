from __future__ import annotations

import re
import unicodedata
from typing import TypeVar

from gander import obs
from gander.sections import NORMALIZED_SECTION_NAMES, normalize_section_name

T = TypeVar("T")

_WS = re.compile(r"\s+")
# Accept any markdown header level (H1–H6); the section vocabulary is
# author-driven, not depth-driven.
_HEADER = re.compile(r"^(#{1,6})\s+(.+)$", flags=re.MULTILINE)
_WORK_SECTION_NAMES = frozenset(
    normalize_section_name(name)
    for name in (
        "experience",
        "work experience",
        "professional experience",
        "pracovní zkušenosti",
        "zkušenosti",
    )
)
_GENERIC_NON_CHILD_HEADERS = frozenset(
    normalize_section_name(name)
    for name in (
        "community",
        "case studies",
        "interests",
        "leadership",
        "open source",
        "portfolio",
        "side projects",
        "selected case studies",
        "selected projects",
        "volunteer",
        "volunteering",
    )
)
_COMPANY_SUFFIXES = (
    " a.s.",
    " s.r.o.",
    " corp",
    " corporation",
    " gmbh",
    " group",
    " inc",
    " llc",
    " ltd",
    " plc",
)
_HEADER_TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ž][0-9A-Za-zÀ-ž.&+-]*", re.UNICODE)


def _normalize(text: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFC", text).strip().lower())


def _is_known_section_header(text: str) -> bool:
    return normalize_section_name(text) in NORMALIZED_SECTION_NAMES


def _looks_like_work_child_header(text: str) -> bool:
    """Return true for same-level employer headers nested by VLM/PDF output."""
    norm = normalize_section_name(text).removesuffix(":")
    if norm in _GENERIC_NON_CHILD_HEADERS:
        return False
    if any(suffix in f" {norm}" for suffix in _COMPANY_SUFFIXES):
        return True
    tokens = _HEADER_TOKEN_RE.findall(text)
    if not tokens or len(tokens) > 5:
        return False
    if any(token.isupper() and len(token.strip(".&+-")) >= 2 for token in tokens):
        return True
    return all(token[:1].isupper() for token in tokens)


def _is_child_header(parent_section: str, parent_level: int, match: re.Match[str]) -> bool:
    child_level = len(match.group(1))
    child_text = match.group(2)
    if child_level > parent_level:
        return True
    parent = normalize_section_name(parent_section)
    return parent in _WORK_SECTION_NAMES and _looks_like_work_child_header(child_text)


def _section_text(source: str, section: str) -> str | None:
    target = normalize_section_name(section)
    matches = list(_HEADER.finditer(source))
    if not matches:
        return None
    for i, m in enumerate(matches):
        header = normalize_section_name(m.group(2))
        if header == target:
            start = m.end()
            end = len(source)
            if _is_known_section_header(section):
                # VLM/PDF transcripts often mark employer names as `##` headers
                # inside Work Experience. Keep plausible child headers, but
                # stop at sibling/custom sections to preserve section scope.
                parent_level = len(m.group(1))
                for next_match in matches[i + 1 :]:
                    if _is_known_section_header(next_match.group(2)) or not _is_child_header(
                        section,
                        parent_level,
                        next_match,
                    ):
                        end = next_match.start()
                        break
            elif i + 1 < len(matches):
                end = matches[i + 1].start()
            return source[start:end]
    return None


def verify_quote(quote: str, source: str, *, section: str | None = None) -> bool:
    """Substring-verify `quote` against `source` (optionally restricted to a section).

    Rules (PLAN §"Hallucination guard hardened"):
      - normalize: Unicode NFC, lowercase + collapse whitespace; punctuation preserved.
      - <6 words → False.
      - 6–7 words → must appear exactly once.
      - >=8 words → must appear at least once.
      - if section given, search is restricted to the body under any H1–H6
        header whose text matches `<section>` (NFC, case-insensitive).
      - if section given but no matching header exists, fall back to whole-source
        match and emit `verify_section_miss` (T26 — bilingual CVs lose every
        anchor when section vocab misaligns; the 6/8-word literal floor still
        defends §4.5). The emit is attributed to the active stage_boundary
        (`obs.current_stage`), or `None` when called outside one — verify is a
        utility, not a stage.
    """
    if section is not None:
        sub = _section_text(source, section)
        if sub is None:
            obs.emit(
                obs.current_stage.get(),
                "verify_section_miss",
                section=section,
                fallback="whole_cv",
            )
            haystack = source
        else:
            haystack = sub
    else:
        haystack = source

    needle = _normalize(quote)
    word_count = len(needle.split())
    if word_count < 6:
        return False

    count = _normalize(haystack).count(needle)
    if word_count <= 7:
        return count == 1
    return count >= 1


def drop_unverified(
    items: list[T], source: str, *, anchor_attr: str = "anchor"
) -> tuple[list[T], int]:
    """Filter `items` to those whose anchor quote verifies against `source`.

    Returns `(kept, dropped_count)`. Each item must expose an attribute named
    `anchor_attr` with `.quote: str` and `.section: str | None`.
    """
    kept: list[T] = []
    for item in items:
        anchor = getattr(item, anchor_attr)
        if verify_quote(anchor.quote, source, section=anchor.section):
            kept.append(item)
    return kept, len(items) - len(kept)
