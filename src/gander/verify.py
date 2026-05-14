from __future__ import annotations

import re
import unicodedata
from typing import TypeVar

from gander import obs

T = TypeVar("T")

_WS = re.compile(r"\s+")
# Accept any markdown header level (H1–H6); the section vocabulary is
# author-driven, not depth-driven.
_HEADER = re.compile(r"^#{1,6}\s+(.+)$", flags=re.MULTILINE)


def _normalize(text: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFC", text).strip().lower())


def _section_text(source: str, section: str) -> str | None:
    target = unicodedata.normalize("NFC", section).strip().lower()
    matches = list(_HEADER.finditer(source))
    if not matches:
        return None
    for i, m in enumerate(matches):
        header = unicodedata.normalize("NFC", m.group(1)).strip().lower()
        if header == target:
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(source)
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
