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
import unicodedata
from pathlib import Path

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

_FORWARD_MARKERS: tuple[str, ...] = (
    "next role",
    "next employer",
    "next position",
    "open source",
    "open-source",
    "oss",
    "certification",
    "certificate",
    "paper",
    "publication",
    "side project",
    "side-project",
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
        if phrase in haystack:
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
    }
)


def _employer_match_candidates(header: str) -> list[str]:
    # An EmployerEntry.header is "Title — Company"; an action's `what` rarely
    # quotes the full header. Match the whole header, each dash-split part
    # (>=4 chars), or any non-stopword token (>=3 chars) within those parts —
    # the latter catches "alza.cz" inside "alza.cz a.s.".
    normalized = _normalize_for_match(header)
    if not normalized:
        return []
    candidates: set[str] = {normalized}
    for part in re.split(r"\s+[-–—]\s+", normalized):
        part = part.strip()
        if len(part) >= 4:
            candidates.add(part)
        for token in part.split():
            stripped = token.strip(".,;:")
            if len(stripped) >= 3 and stripped not in _COMPANY_STOPWORDS:
                candidates.add(stripped)
    return [c for c in candidates if c]


def _violates_forward_setting(
    action: GrowthAction,
    current_employers: list[str],
    closed_employers: list[str],
) -> str | None:
    what = _normalize_for_match(action.what)
    current_candidates = [c for h in current_employers for c in _employer_match_candidates(h)]
    closed_candidates = [c for h in closed_employers for c in _employer_match_candidates(h)]
    if any(c in what for c in current_candidates):
        return None
    closed_hits = [c for c in closed_candidates if c in what]
    if not closed_hits:
        return None
    if any(marker in what for marker in _FORWARD_MARKERS):
        return None
    return "forward_setting_targets_closed_employer:" + closed_hits[0][:40]


def _compute_employer_hints(redacted: RedactedCV, profile: Profile) -> tuple[list[str], list[str]]:
    timeline = scan_employer_timeline(redacted.text)
    if timeline:
        current_hint = [e.header for e in timeline if e.is_current]
        closed_hint = [e.header for e in timeline if not e.is_current]
        return current_hint, closed_hint
    return _extract_current_employer_hint(redacted, profile), []


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


async def plan_growth(
    redacted: RedactedCV,
    profile: Profile,
    score: Score,
    salary_midpoint: int,
    currency: str,
) -> list[GrowthAction] | StageFailure:
    async with stage_boundary("growth"):
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
                emit(
                    "growth",
                    "stage_failure",
                    reason="llm_error",
                    exc_type=type(exc).__name__,
                )
                return StageFailure(
                    stage="growth",
                    user_message=_FAILURE_MSG,
                    debug_detail=f"{type(exc).__name__}: {exc}",
                )

            if not isinstance(raw, _GrowthList):
                emit(
                    "growth",
                    "stage_failure",
                    reason="invalid_llm_output",
                    got_type=type(raw).__name__,
                )
                return StageFailure(
                    stage="growth",
                    user_message=_FAILURE_MSG,
                    debug_detail=f"complete_json returned {type(raw).__name__}",
                )

            survivors: list[GrowthAction] = []
            dropped = 0
            for action in raw.actions:
                banned = _check_ban_phrase(action)
                if banned is not None:
                    emit(
                        "growth",
                        "growth_action_dropped",
                        reason="ban_phrase",
                        phrase=banned,
                        what=action.what[:80],
                    )
                    dropped += 1
                    continue
                if not verify_quote(
                    action.anchor.quote, redacted.text, section=action.anchor.section
                ):
                    emit(
                        "growth",
                        "growth_action_dropped",
                        reason="unverified_anchor",
                        what=action.what[:80],
                    )
                    dropped += 1
                    continue
                forward_violation = _violates_forward_setting(action, current_hint, closed_hint)
                if forward_violation is not None:
                    emit(
                        "growth",
                        "growth_action_dropped",
                        reason="closed_employer_setting",
                        what=action.what[:80],
                        detail=forward_violation,
                    )
                    dropped += 1
                    continue
                survivors.append(action)

            emit(
                "growth",
                "growth_anti_slop_check",
                returned=len(raw.actions),
                dropped=dropped,
                survived=len(survivors),
            )

            if len(survivors) < 3:
                emit(
                    "growth",
                    "stage_failure",
                    reason="insufficient_verified_actions",
                    survived=len(survivors),
                )
                return StageFailure(
                    stage="growth",
                    user_message=_FAILURE_MSG,
                    debug_detail=f"only {len(survivors)} verified actions, PRD §4.4 requires 3-5",
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
            return survivors
        except Exception as exc:
            emit(
                "growth",
                "stage_failure",
                reason="unexpected_error",
                exc_type=type(exc).__name__,
            )
            return StageFailure(
                stage="growth",
                user_message=_FAILURE_MSG,
                debug_detail=f"{type(exc).__name__}: {exc}",
            )
    # Unreachable: every branch above returns. Present for mypy + a final safety net
    # if `stage_boundary` ever gains pre-body exit semantics.
    return StageFailure(stage="growth", user_message=_FAILURE_MSG, debug_detail="unreachable")
