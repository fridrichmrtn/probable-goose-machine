from __future__ import annotations

import re
from typing import TypeVar

T = TypeVar("T")

_WS = re.compile(r"\s+")
_HEADER = re.compile(r"^##\s+(.+)$", flags=re.MULTILINE)


def _normalize(text: str) -> str:
    return _WS.sub(" ", text.strip().lower())


def _section_text(source: str, section: str) -> str | None:
    target = section.strip().lower()
    matches = list(_HEADER.finditer(source))
    if not matches:
        return None
    for i, m in enumerate(matches):
        if m.group(1).strip().lower() == target:
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(source)
            return source[start:end]
    return None


def verify_quote(quote: str, source: str, *, section: str | None = None) -> bool:
    """Substring-verify `quote` against `source` (optionally restricted to a section).

    Rules (PLAN §"Hallucination guard hardened"):
      - normalize: lowercase + collapse whitespace; punctuation preserved.
      - <6 words → False.
      - 6–7 words → must appear exactly once.
      - >=8 words → must appear at least once.
      - if section given, search is restricted to text under `## <section>`.
    """
    if section is not None:
        sub = _section_text(source, section)
        if sub is None:
            return False
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
