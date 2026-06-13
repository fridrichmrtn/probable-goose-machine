from __future__ import annotations

import re
import unicodedata
from collections.abc import Awaitable, Callable, Sequence
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
# Unicode-aware (letters + digits, no underscore). The old `re.ASCII` form
# fragmented diacritic words — "inženýrů" tokenized as "in","en","r" — so a
# same-script accented quote lost the very content nouns the gate measures. We
# fold diacritics first (`_fold`), so this regex sees base letters; the Unicode
# class is the backstop for scripts that don't fold to ASCII (e.g. Cyrillic).
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
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


def _fold(text: str) -> str:
    """Diacritic-insensitive fold for the lexical-overlap path ONLY.

    NFD-decompose, drop combining marks, lowercase, collapse whitespace. This
    makes same-script accented Latin (Czech/German/…) compare on its base
    letters, so an English claim summary and a diacritic CV quote overlap on the
    content nouns they actually share (names, tech, employers). Deliberately
    SEPARATE from `_normalize` (NFC): `verify_quote`'s hardened existence check
    relies on the literal-substring floor that defends §4.5, and folding there
    would weaken it. On plain ASCII this is a no-op, so the lexical gate's
    measured thresholds (see below) are unchanged.
    """
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WS.sub(" ", stripped.strip().lower())


def _content_tokens(text: str) -> frozenset[str]:
    return frozenset(_WORD_RE.findall(_fold(text))) - _STOPWORDS


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
    missing_claim = 0
    for item in items:
        anchor = getattr(item, anchor_attr)
        if not verify_quote(anchor.quote, source, section=anchor.section):
            continue
        if claim_attr is not None:
            # Tolerate a missing claim attr: skip the compat gate rather than
            # raise an AttributeError that stage_boundary would turn into an
            # opaque generic StageFailure. A wrong `claim_attr` then degrades to
            # the pre-gate (existence-only) behaviour instead of crashing — but
            # we surface it (count only) so a misconfiguration is visible.
            claim = getattr(item, claim_attr, None)
            if claim is None:
                missing_claim += 1
            else:
                # Compute the jaccard once and reuse it for the emit, rather than
                # routing through `claim_supports_quote` and recomputing on drop.
                jaccard = claim_quote_jaccard(claim, anchor.quote)
                if jaccard is not None and jaccard < _COMPAT_THRESHOLD:
                    _emit_claim_mismatch(claim, anchor.quote, jaccard)
                    continue
        kept.append(item)
    if missing_claim:
        _emit_claim_attr_missing(claim_attr, missing_claim)
    return kept, len(items) - len(kept)


def _emit_claim_mismatch(claim: str, quote: str, jaccard: float | None) -> None:
    """Emit `verify_claim_mismatch` for a dropped claim (token counts + jaccard,
    never CV text). The caller passes the already-computed jaccard."""
    obs.emit(
        obs.current_stage.get(),
        "verify_claim_mismatch",
        claim_word_count=len(claim.split()),
        quote_word_count=len(quote.split()),
        jaccard=round(jaccard, 3) if jaccard is not None else None,
    )


def _emit_claim_attr_missing(claim_attr: str | None, count: int) -> None:
    """Warn that `count` items lacked the requested `claim_attr` (count only).

    A silent skip hides a wrong `claim_attr` wiring; this makes the degradation
    to existence-only verification observable without leaking any CV text.
    """
    obs.emit(
        obs.current_stage.get(),
        "verify_claim_attr_missing",
        claim_attr=claim_attr,
        count=count,
    )


# A judge adjudicates (claim, quote) pairs the lexical gate flagged as suspect:
# it takes the pairs and returns one bool per pair (True = supportive = keep).
# Injected by the caller (extract.py wires the cheap LLM slot) so verify.py
# stays provider-free and the grader is a separate call from the generator
# (CLAUDE.md §9: separate generation from grading).
CompatJudge = Callable[[list[tuple[str, str]]], Awaitable[Sequence[bool]]]


async def _adjudicate(judge: CompatJudge, pairs: list[tuple[str, str]]) -> list[bool]:
    """Run `judge` over suspect pairs and FAIL OPEN.

    Returns one bool per pair (True = keep). On ANY failure mode — the judge
    raises, returns the wrong length, or returns non-bools — keep every suspect
    (all True). A grader failure must never false-drop valid evidence
    (CLAUDE.md §9: model output is untrusted; a failed grader degrades to the
    existence+lexical result, it does not delete data).
    """
    if not pairs:
        return []
    try:
        raw = await judge(pairs)
    except Exception as err:
        obs.emit(
            obs.current_stage.get(),
            "verify_compat_judge_error",
            suspects=len(pairs),
            error=type(err).__name__,
        )
        return [True] * len(pairs)
    verdicts = list(raw)
    if len(verdicts) != len(pairs) or not all(isinstance(v, bool) for v in verdicts):
        obs.emit(
            obs.current_stage.get(),
            "verify_compat_judge_malformed",
            suspects=len(pairs),
            returned=len(verdicts),
        )
        return [True] * len(pairs)
    return verdicts


async def drop_unverified_compat(
    fields: dict[str, list[T]],
    source: str,
    *,
    anchor_attr: str = "anchor",
    claim_attr: str,
    judge: CompatJudge,
) -> tuple[dict[str, list[T]], int, int]:
    """Two-phase claim–quote gate across all `fields`, with ONE batched judge call.

    Phase 1 (sync, free): for every item, existence-verify the anchor quote
    against `source` (drop on failure), then classify the (claim, quote) pair by
    lexical Jaccard — `None` or `>= _COMPAT_THRESHOLD` keeps it outright; below
    threshold marks it a *suspect* (held, not dropped).

    Phase 2 (async): all suspects across all fields are adjudicated in a single
    `judge` call (≤1 LLM call per CV, not per anchor). The judge resolves the
    cross-language blind spot the lexical path cannot: `item.text` is the
    extractor's English summary while the anchor quote is verbatim CV text, often
    Czech/German — near-zero token overlap on a perfectly valid pair. Suspects
    the judge calls supportive are kept; the rest are dropped. The judge fails
    OPEN (see `_adjudicate`).

    Returns `(kept_by_field, existence_dropped, compat_dropped)`, preserving
    per-field input order. The two drop counts are kept SEPARATE on purpose:
    `existence_dropped` are hallucination-guard drops (anchor quote absent from
    the CV); `compat_dropped` are claim/quote support drops (quote present but
    the judge ruled it unsupportive). extract.py emits them as distinct counters
    so the live anchor-survival gate (a hallucination guard) is not polluted by
    the orthogonal compat axis — a stricter compat gate must never fail it.
    Obs: aggregate counts only — never claim/quote text (both are CV-derived).
    """
    # Each slot is (item, suspect_index | None). None = decided-keep in phase 1.
    field_slots: dict[str, list[tuple[T, int | None]]] = {}
    pairs: list[tuple[str, str]] = []  # suspect (claim, quote) in judge order
    suspect_meta: list[tuple[str, str, float | None]] = []  # (claim, quote, jaccard)
    existence_dropped = 0
    lexical_pass = 0
    missing_claim = 0

    for field, items in fields.items():
        slots: list[tuple[T, int | None]] = []
        for item in items:
            anchor = getattr(item, anchor_attr)
            if not verify_quote(anchor.quote, source, section=anchor.section):
                existence_dropped += 1
                continue
            claim = getattr(item, claim_attr, None)
            if claim is None:
                missing_claim += 1
                slots.append((item, None))
                continue
            jaccard = claim_quote_jaccard(claim, anchor.quote)
            if jaccard is None or jaccard >= _COMPAT_THRESHOLD:
                lexical_pass += 1
                slots.append((item, None))
            else:
                slots.append((item, len(pairs)))
                pairs.append((claim, anchor.quote))
                suspect_meta.append((claim, anchor.quote, jaccard))
        field_slots[field] = slots

    verdicts = await _adjudicate(judge, pairs)

    kept_lists: dict[str, list[T]] = {}
    llm_dropped = 0
    for field, slots in field_slots.items():
        kept: list[T] = []
        for item, suspect_idx in slots:
            if suspect_idx is None or verdicts[suspect_idx]:
                kept.append(item)
            else:
                claim, quote, jaccard = suspect_meta[suspect_idx]
                _emit_claim_mismatch(claim, quote, jaccard)
                llm_dropped += 1
        kept_lists[field] = kept

    if missing_claim:
        _emit_claim_attr_missing(claim_attr, missing_claim)
    obs.emit(
        obs.current_stage.get(),
        "verify_compat",
        lexical_pass=lexical_pass,
        llm_checked=len(pairs),
        llm_dropped=llm_dropped,
        existence_dropped=existence_dropped,
    )
    return kept_lists, existence_dropped, llm_dropped
