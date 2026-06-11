"""L5 growth-plan generator.

Generates 3-5 CV-specific salary-growth actions, each verifiable against the
source CV via ``verify_quote``, with a hard anti-slop ban list as the central
discriminator (PRD §4.4).

Signature widened from the T13_growth.md contract to take ``RedactedCV`` (needed
to call ``verify_quote`` on each action's anchor) and return
``list[GrowthAction] | StageFailure`` for parity with ``score_profile`` and
``estimate_salary``.

The ``_BAN_PHRASES`` tuple mirrors the verbatim phrases in ``prompts/growth.md``
as case-insensitive substrings on ``(what + " " + mechanism).lower()``. This list
is CONTRACTUAL — do not weaken it during heal cycles. PRD §4.4 names this
behaviour as the discriminator against off-the-shelf CV tools.
"""

from __future__ import annotations

import json
import re
import string
import time
import unicodedata
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel

from gander.errors import StageFailure, stage_boundary
from gander.llm import LLMClient
from gander.obs import emit
from gander.schemas import GrowthAction, Profile, ProfileItem, RedactedCV, Score
from gander.tenure import _PRESENT_TOKENS, work_experience_slice
from gander.timeline import scan_employer_timeline
from gander.verify import verify_quote

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "growth.md").read_text(encoding="utf-8")

# PRD §4.6:62 verbatim user-facing copy. Every failure branch surfaces this
# exact string; debug_detail carries the structured reason.
_FAILURE_MSG = "Could not generate this section reliably"
_GROWTH_LOGICAL_MAX_RETRIES = 1

# Case-insensitive substring match on (what + " " + mechanism).lower().
# "phd" catches "PhD", "Ph.D.", "complete a PhD"; the others are direct.
# DO NOT WEAKEN this list. Per PRD §4.4 anti-slop is the central design
# constraint and this list is the second line of defence after the prompt.
_BAN_PHRASES: tuple[str, ...] = (
    "phd",
    "found a startup",
    "improve communication",
    "learn more",
    "network more",
)

# "phd" needs a leading word boundary: punctuation-stripping turns "GraphDB"
# into "graphdb" and "graph-database" into "graphdatabase", both of which
# contain the bare substring. Trailing boundary stays open so "phds" and the
# post-strip form of "Ph.D." still match.
_PHD_RE = re.compile(r"(?<!\w)phd")

# Prompt rule 6 softeners, enforced on `what` only — "explore" in a mechanism
# sentence is commentary, but a softened imperative is slop (PRD §4.4).
_SOFTENER_RE = re.compile(r"\b(?:consider|explore|look into)\b", re.IGNORECASE)

_FORWARD_MARKERS: tuple[str, ...] = (
    "next role",
    "next employer",
    "next position",
    "new role",
    "new employer",
    "new position",
    "future role",
    "interview",
    "land a role",
    "land a job",
    "job hunt",
    "open source",
    "open-source",
    "certification",
    "certificate",
    "certify",
    "certified",
    "paper",
    "publish",
    "publication",
    "side project",
    "side-project",
)

# Word-boundary match: "oss" must not match inside "across"/"loss",
# "paper" must not match inside "whitepaper"/"newspaper".
_FORWARD_MARKER_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(m) for m in _FORWARD_MARKERS) + r")\b",
    flags=re.IGNORECASE,
)

_BOILERPLATE_JACCARD_THRESHOLD = 0.6
# Baseline lives inside the package so a wheel install keeps the smoke check wired.
# T17 owns the contents (writes the file after acceptance tests run); the runtime
# treats a missing file as "no baseline" via the `growth_baseline_missing` event.
_BASELINE_PATH = Path(__file__).parent / "data" / "growth_baseline.json"


class _GrowthList(BaseModel):
    """LLM response envelope: ``{"actions": [GrowthAction, ...]}``.

    Length (3-5) is NOT enforced here — surface the model's actual list to the
    verify/filter step so any shortfall after dropping cleanly becomes a
    StageFailure with a structured reason.
    """

    actions: list[GrowthAction]


def _normalize_for_ngrams(text: str) -> list[str]:
    """NFC-normalize, lowercase, strip punctuation off each token, split on whitespace."""
    normalized = unicodedata.normalize("NFC", text).lower()
    translator = str.maketrans("", "", string.punctuation)
    return [tok for tok in normalized.translate(translator).split() if tok]


def _jaccard_4gram(a: str, b: str) -> float:
    """Word 4-gram Jaccard similarity. Returns 0.0 if either side has <4 tokens."""
    tokens_a = _normalize_for_ngrams(a)
    tokens_b = _normalize_for_ngrams(b)
    if len(tokens_a) < 4 or len(tokens_b) < 4:
        return 0.0
    grams_a = {tuple(tokens_a[i : i + 4]) for i in range(len(tokens_a) - 3)}
    grams_b = {tuple(tokens_b[i : i + 4]) for i in range(len(tokens_b) - 3)}
    union = grams_a | grams_b
    if not union:
        return 0.0
    return len(grams_a & grams_b) / len(union)


def _load_baseline() -> list[str]:
    """Best-effort load of the boilerplate baseline. T17 owns the file's contents."""
    if not _BASELINE_PATH.exists():
        return []
    try:
        data = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, str)]


def _check_ban_phrase(action: GrowthAction) -> str | None:
    # Lowercase, strip punctuation, collapse whitespace so "Ph.D.", "start-up",
    # and "learn\nmore" all reduce to forms the substring check catches.
    raw = f"{action.what} {action.mechanism}".lower()
    translator = str.maketrans("", "", string.punctuation)
    haystack = " ".join(raw.translate(translator).split())
    for phrase in _BAN_PHRASES:
        if phrase == "phd":
            if _PHD_RE.search(haystack):
                return phrase
        elif phrase in haystack:
            return phrase
    return None


def _contains_present_token(text: str) -> bool:
    normalized = "".join(
        c for c in unicodedata.normalize("NFKD", text).lower() if not unicodedata.combining(c)
    )
    token_alt = "|".join(sorted((re.escape(t) for t in _PRESENT_TOKENS), key=len, reverse=True))
    return re.search(rf"\b(?:{token_alt})\b", normalized) is not None


def _normalized_with_offsets(text: str) -> tuple[str, list[int]]:
    normalized = unicodedata.normalize("NFC", text).casefold()
    chars: list[str] = []
    offsets: list[int] = []
    in_ws = False
    for i, ch in enumerate(normalized):
        if ch.isspace():
            if not in_ws:
                chars.append(" ")
                offsets.append(i)
                in_ws = True
            continue
        chars.append(ch)
        offsets.append(i)
        in_ws = False

    start = 1 if chars and chars[0] == " " else 0
    end = len(chars) - 1 if chars and chars[-1] == " " else len(chars)
    return "".join(chars[start:end]), offsets[start:end]


def _find_normalized_span(source: str, quote: str) -> tuple[int, int] | None:
    haystack, offsets = _normalized_with_offsets(source)
    needle = " ".join(unicodedata.normalize("NFC", quote).casefold().split())
    idx = haystack.find(needle)
    if idx < 0:
        return None
    end_idx = idx + len(needle) - 1
    if idx >= len(offsets) or end_idx >= len(offsets):
        return None
    return offsets[idx], offsets[end_idx] + 1


def _extract_current_employer_hint(redacted: RedactedCV, profile: Profile) -> list[str]:
    """Return experience item texts whose anchor sits near a present-tense date."""
    scoped = work_experience_slice(redacted.text) or redacted.text
    hints: list[str] = []
    seen: set[str] = set()
    spans: list[tuple[int, int, ProfileItem]] = []
    for item in profile.experience:
        span = _find_normalized_span(scoped, item.anchor.quote)
        if span is None:
            continue
        spans.append((span[0], span[1], item))

    spans.sort(key=lambda row: row[0])
    for i, (start, end, item) in enumerate(spans):
        prev_end = spans[i - 1][1] if i > 0 else 0
        next_start = spans[i + 1][0] if i + 1 < len(spans) else len(scoped)
        context_start = (prev_end + start) // 2 if i > 0 else 0
        context_end = (end + next_start) // 2 if i + 1 < len(spans) else len(scoped)
        context = scoped[context_start:context_end]
        if not _contains_present_token(context):
            continue
        key = " ".join(item.text.casefold().split())
        if key in seen:
            continue
        seen.add(key)
        hints.append(item.text)
    return hints


def _normalize_for_match(text: str) -> str:
    stripped = "".join(
        c for c in unicodedata.normalize("NFKD", text).lower() if not unicodedata.combining(c)
    )
    return " ".join(stripped.split())


_COMPANY_STOPWORDS: frozenset[str] = frozenset(
    {
        "manager",
        "senior",
        "junior",
        "lead",
        "principal",
        "staff",
        "engineer",
        "scientist",
        "analyst",
        "director",
        "data",
        "ai",
        "science",
        "research",
        "platform",
        "software",
        "head",
        "of",
        "and",
        "the",
        "member",
        # Employer-descriptor / contract-shape words that aren't a company
        # name. Without these, "Research Engineer — Independent" emits the
        # candidate "independent", and an action mentioning "independent
        # contractor" would falsely satisfy the current-employer bypass.
        "independent",
        "freelance",
        "freelancer",
        "contract",
        "contractor",
        "consultant",
        "consulting",
        "remote",
        "onsite",
        "hybrid",
        "self",
        "employed",
        "current",
        "present",
        # Common legal/entity suffixes that survive normalization but don't
        # discriminate (Alza.cz a.s., Acme Inc., Foo LLC, …).
        "inc",
        "llc",
        "ltd",
        "corp",
        "gmbh",
        "spol",
        "sro",
        "kft",
        # Location tokens common in CZ employer headers ("O2 Czech Republic",
        # "Prague, Czech Republic"). A location is never the company-name
        # evidence an action should be matched on.
        "czech",
        "republic",
        "prague",
        "praha",
        "brno",
        "ostrava",
    }
)

# Legal-entity suffixes qualify a header part as company-shaped but are NEVER
# emitted as match candidates — "a.s." hitting another company's suffix is a
# real false-positive vector. Compared against normalized, edge-stripped tokens.
_LEGAL_SUFFIXES: frozenset[str] = frozenset(
    {
        "a.s",
        "s.r.o",
        "sro",
        "spol",
        "k.s",
        "v.o.s",
        "b.v",
        "n.v",
        "inc",
        "llc",
        "ltd",
        "corp",
        "corporation",
        "gmbh",
        "plc",
        "kft",
    }
)


def _token_in(needle: str, haystack: str) -> bool:
    """Word-boundary match for single-token candidates, substring for phrases.

    Bare substring (`needle in haystack`) lets short tokens like "inc" match
    inside "increase" and "oss" match inside "across". Multi-word candidates
    (after `_normalize_for_match` collapses whitespace, the candidate retains
    spaces only when it was a multi-word header part) keep substring
    semantics — false-positive risk is low and word boundaries get muddled
    by internal punctuation like "alza.cz a.s.".
    """
    if not needle:
        return False
    if " " in needle:
        return needle in haystack
    pattern = re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)")
    return bool(pattern.search(haystack))


def _employer_match_candidates(header: str) -> list[str]:
    # An EmployerEntry.header is "Title — Company"; an action's `what` rarely
    # quotes the full header. Only company-shaped parts may emit candidates:
    # title parts ("Lead Data Scientist") and location parts ("Prague, Czech
    # Republic") used to leak tokens that false-matched ordinary action text.
    # Shape evidence is inspected on the ORIGINAL case — all-caps detection is
    # impossible after `_normalize_for_match` lowercases.
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(candidate: str) -> None:
        if candidate and candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)

    for part in re.split(r"\s+[-–—]\s+", header):
        tokens = [t for t in (tok.strip(".,;:") for tok in part.split()) if t]
        if not tokens:
            continue
        normalized_tokens = [_normalize_for_match(t) for t in tokens]
        has_shape_evidence = False
        has_stopword = False
        for original, norm in zip(tokens, normalized_tokens, strict=True):
            if norm in _COMPANY_STOPWORDS:
                has_stopword = True
            if (
                norm in _LEGAL_SUFFIXES
                or "." in norm
                or any(ch.isdigit() for ch in norm)
                or (
                    len(original) >= 2
                    and original.isalpha()
                    and original.isupper()
                    and norm not in _COMPANY_STOPWORDS
                )
            ):
                has_shape_evidence = True
        # Qualify on shape evidence (legal suffix, digit/dot token, all-caps
        # token) or on the zero-stopword catch-all that keeps plain-name
        # companies ("Stealth Mode Startup", bare "Alza") while excluding
        # all-stopword title and location parts.
        if not has_shape_evidence and has_stopword:
            continue
        normalized_part = _normalize_for_match(part)
        if " " in normalized_part and len(normalized_part) >= 4:
            _add(normalized_part)
        for original, norm in zip(tokens, normalized_tokens, strict=True):
            if norm in _COMPANY_STOPWORDS or norm in _LEGAL_SUFFIXES:
                continue
            dotted_or_digit = "." in norm or any(ch.isdigit() for ch in norm)
            all_caps = len(original) >= 2 and original.isalpha() and original.isupper()
            if (len(norm) >= 2 and (dotted_or_digit or all_caps)) or len(norm) >= 3:
                _add(norm)
            if "." in norm:
                for sub in norm.split("."):
                    if len(sub) >= 3 and sub not in _COMPANY_STOPWORDS:
                        _add(sub)
    return candidates


def _violates_forward_setting(
    action: GrowthAction,
    current_employers: list[str],
    closed_employers: list[str],
) -> str | None:
    what = _normalize_for_match(action.what)
    # A token appearing in any CURRENT entry can never count as a closed hit:
    # same-company promotions ("Data Scientist — CSOB" → "Senior Data
    # Scientist — CSOB") share every company token, and the old direction of
    # this exclusion made the current-employer rescue unreachable for them.
    current_candidates = {c for h in current_employers for c in _employer_match_candidates(h)}
    closed_candidates = [
        c
        for h in closed_employers
        for c in _employer_match_candidates(h)
        if c not in current_candidates
    ]
    closed_hits = [c for c in closed_candidates if _token_in(c, what)]
    if not closed_hits:
        return None
    if _FORWARD_MARKER_RE.search(what):
        return None
    current_hits = [c for c in current_candidates if _token_in(c, what)]
    if current_hits:
        return None
    return "forward_setting_targets_closed_employer:" + closed_hits[0][:40]


def _compute_employer_hints(redacted: RedactedCV, profile: Profile) -> tuple[list[str], list[str]]:
    timeline = scan_employer_timeline(redacted.text)
    if timeline:
        current_hint = [e.header for e in timeline if e.is_current]
        closed_hint = [e.header for e in timeline if not e.is_current]
        emit(
            "growth",
            "growth_employer_hints",
            source="timeline",
            current_count=len(current_hint),
            closed_count=len(closed_hint),
        )
        return current_hint, closed_hint
    current_hint = _extract_current_employer_hint(redacted, profile)
    emit(
        "growth",
        "growth_employer_hints",
        source="anchor_fallback",
        current_count=len(current_hint),
        closed_count=0,
    )
    return current_hint, []


def _build_user_message(
    redacted: RedactedCV,
    profile: Profile,
    score: Score,
    salary_midpoint: int,
    currency: str,
    current_hint: list[str] | None = None,
    closed_hint: list[str] | None = None,
) -> str:
    if current_hint is None or closed_hint is None:
        current_hint, closed_hint = _compute_employer_hints(redacted, profile)
    payload = {
        "salary_midpoint": salary_midpoint,
        "currency": currency,
        "detected_role": profile.detected_role,
        "detected_location": profile.detected_location,
        "detected_years_experience": profile.detected_years_experience,
        "current_employer_hint": current_hint,
        "closed_employer_hint": closed_hint,
        "dropped_components": list(score.dropped),
        "components": [
            {
                "name": c.name,
                "score_0_100": c.score_0_100,
                "justification": c.justification,
            }
            for c in score.components
        ],
        "redacted_cv": redacted.text,
    }
    return json.dumps(payload, ensure_ascii=False)


class _Drop(NamedTuple):
    idx: int
    what: str
    reason: str  # "ban_phrase" | "unverified_anchor" | "closed_employer_setting"
    detail: str | None  # matched phrase / employer token
    quote: str | None  # rejected anchor quote, unverified_anchor only


def _action_key(action: GrowthAction) -> str:
    def norm(s: str) -> str:
        return " ".join(s.casefold().split())

    return norm(action.what) + "\x00" + norm(action.anchor.quote)


def _filter_actions(
    actions: list[GrowthAction],
    redacted_text: str,
    current_employers: list[str],
    closed_employers: list[str],
) -> tuple[list[GrowthAction], list[_Drop], dict[str, int]]:
    survivors: list[GrowthAction] = []
    drops: list[_Drop] = []
    drop_reasons: dict[str, int] = {}

    def _record(drop: _Drop) -> None:
        drops.append(drop)
        drop_reasons[drop.reason] = drop_reasons.get(drop.reason, 0) + 1

    for index, action in enumerate(actions):
        banned = _check_ban_phrase(action)
        if banned is not None:
            emit(
                "growth",
                "growth_action_dropped",
                reason="ban_phrase",
                phrase=banned,
                what=action.what[:80],
            )
            _record(_Drop(index, action.what, "ban_phrase", banned, None))
            continue
        softener = _SOFTENER_RE.search(action.what)
        if softener is not None:
            emit(
                "growth",
                "growth_action_dropped",
                reason="softener_phrase",
                phrase=softener.group(0).lower(),
                what=action.what[:80],
            )
            _record(_Drop(index, action.what, "softener_phrase", softener.group(0).lower(), None))
            continue
        if not verify_quote(action.anchor.quote, redacted_text, section=action.anchor.section):
            emit(
                "growth",
                "growth_action_dropped",
                reason="unverified_anchor",
                what=action.what[:80],
                quote=action.anchor.quote[:120],
            )
            _record(_Drop(index, action.what, "unverified_anchor", None, action.anchor.quote))
            continue
        forward_violation = _violates_forward_setting(action, current_employers, closed_employers)
        if forward_violation is not None:
            emit(
                "growth",
                "growth_action_dropped",
                reason="closed_employer_setting",
                what=action.what[:80],
                detail=forward_violation,
            )
            _record(_Drop(index, action.what, "closed_employer_setting", forward_violation, None))
            continue
        survivors.append(action)
    return survivors, drops, drop_reasons


def _build_retry_user_message(
    base_user_message: str,
    *,
    kept: list[GrowthAction],
    drops: list[_Drop],
    needed: int,
) -> str:
    lines = [base_user_message, ""]
    if kept:
        lines.append(
            f"Of your previous actions, {len(kept)} passed verification and are KEPT — "
            "do not repeat or rephrase them:"
        )
        lines.extend(f"- {action.what}" for action in kept)
    if drops:
        lines.append("These actions FAILED verification:")
        for drop in drops:
            lines.append(f'- action {drop.idx}: "{drop.what[:80]}" — {drop.reason}')
            if drop.reason == "unverified_anchor" and drop.quote is not None:
                lines.append(
                    f'  The anchor quote "{drop.quote}" was not found verbatim in '
                    "redacted_cv. Copy at least 8 consecutive words "
                    "character-for-character from one CV section."
                )
            elif drop.detail:
                lines.append(f"  Matched: {drop.detail}")
    lines.append(
        f"Return a JSON object with exactly {needed} NEW action(s) in the same schema. "
        "Do not include the kept actions."
    )
    return "\n".join(lines)


async def plan_growth(
    redacted: RedactedCV,
    profile: Profile,
    score: Score,
    salary_midpoint: int,
    currency: str,
) -> list[GrowthAction] | StageFailure:
    async with stage_boundary("growth"):
        t0 = time.perf_counter()

        def _ms() -> int:
            return int((time.perf_counter() - t0) * 1000)

        try:
            client = LLMClient()
            current_hint, closed_hint = _compute_employer_hints(redacted, profile)
            user_message = _build_user_message(
                redacted,
                profile,
                score,
                salary_midpoint,
                currency,
                current_hint,
                closed_hint,
            )

            base_user_message = user_message
            # Survivors pool across attempts (keyed on normalized what+quote), so a
            # verified action from attempt 1 is never discarded by a weaker attempt 2.
            pool: dict[str, GrowthAction] = {}
            last_returned = 0
            last_drop_reasons: dict[str, int] = {}
            for attempt in range(_GROWTH_LOGICAL_MAX_RETRIES + 1):
                try:
                    # temperature=0.0 for determinism — matches T10/T11/T12 stages.
                    raw = await client.complete_json(
                        system=_SYSTEM_PROMPT,
                        user=user_message,
                        schema=_GrowthList,
                        model="reasoning",
                        temperature=0.0,
                        max_tokens=1536,
                    )
                except Exception as exc:
                    if pool:
                        # A failed top-up call must not throw away already-verified
                        # actions — degrade to the pooled partial list (PRD §4.5).
                        emit(
                            "growth",
                            "growth_attempt_error",
                            reason="llm_error",
                            exc_type=type(exc).__name__,
                            attempt=attempt,
                        )
                        break
                    emit(
                        "growth",
                        "stage_failure",
                        reason="llm_error",
                        exc_type=type(exc).__name__,
                        duration_ms=_ms(),
                    )
                    return StageFailure(
                        stage="growth",
                        user_message=_FAILURE_MSG,
                        debug_detail=f"{type(exc).__name__}: {exc}",
                    )

                if not isinstance(raw, _GrowthList):
                    if pool:
                        emit(
                            "growth",
                            "growth_attempt_error",
                            reason="invalid_llm_output",
                            got_type=type(raw).__name__,
                            attempt=attempt,
                        )
                        break
                    emit(
                        "growth",
                        "stage_failure",
                        reason="invalid_llm_output",
                        got_type=type(raw).__name__,
                        duration_ms=_ms(),
                    )
                    return StageFailure(
                        stage="growth",
                        user_message=_FAILURE_MSG,
                        debug_detail=f"complete_json returned {type(raw).__name__}",
                    )

                attempt_survivors, drops, drop_reasons = _filter_actions(
                    raw.actions, redacted.text, current_hint, closed_hint
                )
                for action in attempt_survivors:
                    pool.setdefault(_action_key(action), action)
                last_returned = len(raw.actions)
                last_drop_reasons = drop_reasons

                emit(
                    "growth",
                    "growth_anti_slop_check",
                    returned=len(raw.actions),
                    dropped=len(drops),
                    survived=len(attempt_survivors),
                    pooled=len(pool),
                    attempt=attempt,
                )

                if len(pool) >= 3:
                    break
                if attempt < _GROWTH_LOGICAL_MAX_RETRIES:
                    emit(
                        "growth",
                        "growth_retry",
                        reason="insufficient_verified_actions",
                        returned=len(raw.actions),
                        survived=len(pool),
                        dropped=len(drops),
                        drop_reasons=drop_reasons,
                    )
                    user_message = _build_retry_user_message(
                        base_user_message,
                        kept=list(pool.values()),
                        drops=drops,
                        needed=3 - len(pool),
                    )

            survivors = list(pool.values())
            if not survivors:
                emit(
                    "growth",
                    "stage_failure",
                    reason="insufficient_verified_actions",
                    survived=0,
                    returned=last_returned,
                    drop_reasons=last_drop_reasons,
                    duration_ms=_ms(),
                )
                return StageFailure(
                    stage="growth",
                    user_message=_FAILURE_MSG,
                    debug_detail="only 0 verified actions, PRD §4.4 requires 3-5",
                )
            if len(survivors) < 3:
                # PRD §4.5: a shorter list, not a placeholder.
                emit(
                    "growth",
                    "growth_degraded",
                    count=len(survivors),
                    returned=last_returned,
                    drop_reasons=last_drop_reasons,
                )

            if len(survivors) > 5:
                emit(
                    "growth",
                    "growth_actions_truncated",
                    count_before=len(survivors),
                    count_after=5,
                    dropped=len(survivors) - 5,
                )
            # Order preserved from the model's emitted list — prompt instructs "strongest-first".
            survivors = survivors[:5]

            baseline = _load_baseline()
            if baseline:
                for action in survivors:
                    max_overlap = max(
                        (_jaccard_4gram(action.what, item) for item in baseline),
                        default=0.0,
                    )
                    if max_overlap > _BOILERPLATE_JACCARD_THRESHOLD:
                        emit(
                            "growth",
                            "growth_possible_boilerplate",
                            what=action.what[:80],
                            max_overlap=round(max_overlap, 3),
                        )
            else:
                emit("growth", "growth_baseline_missing")

            emit("growth", "growth_actions_returned", count=len(survivors))
            emit("growth", "done", duration_ms=_ms(), count=len(survivors))
            return survivors
        except Exception as exc:
            emit(
                "growth",
                "stage_failure",
                reason="unexpected_error",
                exc_type=type(exc).__name__,
                duration_ms=_ms(),
            )
            return StageFailure(
                stage="growth",
                user_message=_FAILURE_MSG,
                debug_detail=f"{type(exc).__name__}: {exc}",
            )
    # Unreachable: every branch above returns. Present for mypy + a final safety net
    # if `stage_boundary` ever gains pre-body exit semantics.
    return StageFailure(stage="growth", user_message=_FAILURE_MSG, debug_detail="unreachable")
