from __future__ import annotations

import re
import unicodedata
from typing import TypeVar

from gander import obs
from gander.sections import (
    NORMALIZED_SECTION_NAMES,
    normalize_section_name,
    section_name_candidates,
)

T = TypeVar("T")

_WS = re.compile(r"\s+")
# Accept any markdown header level (H1–H6); the section vocabulary is
# author-driven, not depth-driven.
_HEADER = re.compile(r"^(#{1,6})\s+(.+)$", flags=re.MULTILINE)
_WORK_SECTION_NAMES = frozenset(
    normalize_section_name(name)
    for name in (
        "academic experience",
        "academic practice",
        "experience",
        "research experience",
        "work experience",
        "professional experience",
        "akademická praxe",
        "praxe",
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
    return bool(section_name_candidates(text) & NORMALIZED_SECTION_NAMES)


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
    targets = section_name_candidates(section)
    matches = list(_HEADER.finditer(source))
    if not matches:
        return None
    for i, m in enumerate(matches):
        header = normalize_section_name(m.group(2))
        if header in targets:
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


# Stop words stripped before measuring claim-quote overlap. Without this,
# high-frequency function words dominate Jaccard and let an unrelated claim
# ride on shared "the/a/of". English-only on purpose: CZ claims/quotes share
# the same content nouns (names, tech, employers) that carry the signal.
_STOPWORDS = frozenset(
    (
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "as",
        "is",
        "was",
        "are",
        "were",
        "be",
        "been",
        "this",
        "that",
        "these",
        "those",
        "from",
        "into",
        "over",
        "under",
        "across",
        "it",
        "its",
        "their",
        "our",
        "your",
        "his",
        "her",
        "they",
        "we",
        "you",
        "i",
        "he",
        "she",
        "them",
        "us",
    )
)
_WORD_RE = re.compile(r"[0-9a-z]+", re.ASCII)
# What this gate catches and what it does NOT (measured, not assumed):
#   - It catches TOPICAL mismatch — a claim and quote about different things
#     share almost no content tokens (jaccard ~0): "increased revenue" anchored
#     to "reduced churn", or a security claim on a marketing quote.
#   - It does NOT catch fine-grained VERB SUBSTITUTION on a shared object:
#     "Led a team of engineers" vs "Joined a team of engineers" scores 0.25 —
#     above any threshold that still admits legitimate paraphrases (a real
#     skill restatement measured as low as 0.22). Bag-of-words overlap cannot
#     separate them; only an LLM judge can, which the latency/cost budget
#     rejects for a per-anchor check. This limitation is intentional.
# Threshold sits below the lowest measured legitimate-support pair (0.22) so the
# gate never false-drops a paraphrase, while still rejecting the near-zero
# topical mismatches. See test_claim_supports_quote_* for the measured pairs.
_COMPAT_THRESHOLD = 0.1


def _content_tokens(text: str) -> frozenset[str]:
    return frozenset(_WORD_RE.findall(_normalize(text))) - _STOPWORDS


def claim_quote_jaccard(claim: str, quote: str) -> float | None:
    """Jaccard overlap of content tokens, or None when either side is empty.

    None means "not enough signal to judge" — callers treat it as a pass.
    """
    claim_tokens = _content_tokens(claim)
    quote_tokens = _content_tokens(quote)
    if not claim_tokens or not quote_tokens:
        return None
    return len(claim_tokens & quote_tokens) / len(claim_tokens | quote_tokens)


def claim_supports_quote(claim: str, quote: str) -> bool:
    """Does `quote` plausibly support `claim`? (Jaccard token overlap gate.)

    Separate from `verify_quote`, which only proves the quote EXISTS in the CV.
    This catches the semantic gap where an existing quote is anchored to a claim
    it does not support. A None jaccard (too few content tokens to judge) passes:
    we defer to the existence check rather than drop a possibly-valid item.

    Applied only at extract, where ProfileItem.text restates the evidence in the
    quote. NOT applied to score justifications (evaluative synonyms like
    "doctorate" vs a "Ph.D." quote false-drop under lexical overlap) nor to
    forward-looking growth actions (which diverge from their anchor by design).
    """
    jaccard = claim_quote_jaccard(claim, quote)
    return jaccard is None or jaccard >= _COMPAT_THRESHOLD


def drop_unverified(
    items: list[T], source: str, *, anchor_attr: str = "anchor", claim_attr: str | None = None
) -> tuple[list[T], int]:
    """Filter `items` to those whose anchor quote verifies against `source`.

    Returns `(kept, dropped_count)`. Each item must expose an attribute named
    `anchor_attr` with `.quote: str` and `.section: str | None`.

    When `claim_attr` is given, an item also has to pass `claim_supports_quote`
    between `getattr(item, claim_attr)` and the anchor quote — this closes the
    semantic gap where the quote exists but does not support the claim. A drop
    on this path emits `verify_claim_mismatch` (token counts + jaccard, no CV
    text). Leave `claim_attr` None for items whose claim diverges from the anchor
    by design (growth actions).
    """
    kept: list[T] = []
    for item in items:
        anchor = getattr(item, anchor_attr)
        if not verify_quote(anchor.quote, source, section=anchor.section):
            continue
        if claim_attr is not None:
            claim = getattr(item, claim_attr)
            if not claim_supports_quote(claim, anchor.quote):
                _emit_claim_mismatch(claim, anchor.quote)
                continue
        kept.append(item)
    return kept, len(items) - len(kept)


def _emit_claim_mismatch(claim: str, quote: str) -> None:
    """Emit `verify_claim_mismatch` for a dropped claim (token counts + jaccard,
    never CV text)."""
    jaccard = claim_quote_jaccard(claim, quote)
    obs.emit(
        obs.current_stage.get(),
        "verify_claim_mismatch",
        claim_word_count=len(claim.split()),
        quote_word_count=len(quote.split()),
        jaccard=round(jaccard, 3) if jaccard is not None else None,
    )
