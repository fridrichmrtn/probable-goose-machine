"""L5 growth-plan generator.

Generates CV-specific salary-growth actions, each verifiable against the
source CV via ``verify_quote``, with a hard anti-slop ban list as the central
discriminator (PRD §4.4). The 3-5 action count is the prompt/internal
contract — PRD §4.4 itself asks only for "a concrete set of actions" — and a
run with just 1-2 verified survivors ships them as a degraded partial list
(PRD §4.5) instead of failing.

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
from gander.llm import get_client
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
    # Punctuation becomes a space so legal-suffix and dash variants compare
    # equal ("s.r.o." vs "s. r. o.", "Acme—Retail" vs "Acme-Retail") and a
    # lone "—" can never substring-match the "Title — Company" hint join.
    stripped = "".join(
        c for c in unicodedata.normalize("NFKD", text).lower() if not unicodedata.combining(c)
    )
    cleaned = "".join(c if c.isalnum() else " " for c in stripped)
    return " ".join(cleaned.split())


def _hint_segments(headers: list[str]) -> list[list[str]]:
    """Tokenized match candidates per hint header: each dash-separated part
    ("Title — Company" → "Title", "Company") plus the full header. Splitting
    happens before normalization so hyphenated names ("Acme-Retail") stay
    whole; em/en-dash company joins still match via the full-header candidate.
    Empty headers yield no candidates — they must never match anything."""
    segments: list[list[str]] = []
    for header in headers:
        for part in [*re.split(r"\s+-\s+|[—–]", header), header]:
            tokens = _normalize_for_match(part).split()
            if tokens:
                segments.append(tokens)
    return segments


def _tokens_match(a: list[str], b: list[str]) -> bool:
    """True when one token list appears as a contiguous subsequence of the
    other. Token-level containment keeps "ING" from matching inside
    "Consulting" while letting short verbatim employers ("O2") through."""

    def contains(haystack: list[str], needle: list[str]) -> bool:
        if not needle or len(needle) > len(haystack):
            return False
        return any(
            haystack[i : i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1)
        )

    return contains(a, b) or contains(b, a)


def _setting_violation(
    action: GrowthAction,
    current_employers: list[str],
    closed_employers: list[str],
) -> tuple[str, str] | None:
    """Validate the model's declared setting instead of keyword-guessing.

    Only `current_employer` declarations are checkable. A target that is
    token-for-token equal to a full closed-employer header was copied verbatim
    from a CLOSED entry and drops as `closed_employer_target` before any
    current-hint matching — shared title segments ("Senior Manager — ...")
    must not rubber-stamp it. Exception: a target token-equal to a CURRENT
    hint segment (rehire headers, company-only closed headers) names a place
    the candidate provably works now. Otherwise the target must token-match a
    current-employer hint segment (contiguous token subsequence, either
    direction). A target matching only a closed-employer hint is also a
    `closed_employer_target` violation — actions never happen at a past
    employer. A target matching neither, or whose normalized form has fewer
    than 2 alphanumeric characters, drops as `unverified_target_employer`.
    `future_role` / `capability_artifact` have no employer to verify. With no
    current hints only the closed check applies — otherwise same skip as the
    old gate, kept observable via the `growth_employer_hints` event.
    """
    if action.setting != "current_employer":
        return None
    if not action.target_employer:
        if current_employers:
            return ("unverified_target_employer", "missing_target")
        return None
    detail = action.target_employer[:40]
    normalized = _normalize_for_match(action.target_employer)
    if sum(c.isalnum() for c in normalized) >= 2:
        target_tokens = normalized.split()
        current_segments = _hint_segments(current_employers)
        # Token equality with a current segment exempts the verbatim guard:
        # rehires carry the same header in both lists, and a company-only
        # closed header ("Alza.cz") equals the company segment of the current
        # one — both name a place the candidate provably works now.
        if not any(target_tokens == seg for seg in current_segments) and any(
            target_tokens == _normalize_for_match(header).split() for header in closed_employers
        ):
            return ("closed_employer_target", detail)
        if any(_tokens_match(target_tokens, seg) for seg in current_segments):
            return None
        if any(_tokens_match(target_tokens, seg) for seg in _hint_segments(closed_employers)):
            return ("closed_employer_target", detail)
    if not current_employers:
        return None
    return ("unverified_target_employer", detail)


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
    market_name: str | None = None,
) -> str:
    if current_hint is None or closed_hint is None:
        current_hint, closed_hint = _compute_employer_hints(redacted, profile)
    payload = {
        "salary_midpoint": salary_midpoint,
        "currency": currency,
        "market_name": market_name or "the candidate's market",
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
    # "ban_phrase" | "softener_phrase" | "unverified_anchor"
    # | "unverified_target_employer" | "closed_employer_target"
    reason: str
    detail: str | None  # matched phrase / employer token
    quote: str | None  # rejected anchor quote (first 120 chars), unverified_anchor only


# Caps the rejected anchor quote stored on drop events and _Drop records so a
# runaway model quote cannot bloat telemetry or the retry prompt.
_QUOTE_SNIPPET_LIMIT = 120


def _action_key(action: GrowthAction) -> str:
    # Keyed on normalized `what` only: the same action re-anchored on retry
    # (different quote) must not pool twice and ship as a duplicate.
    return " ".join(action.what.casefold().split())


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
        if action.setting != "current_employer" and action.target_employer is not None:
            # Prompt rule 7 says target_employer must be null here; the field
            # is never rendered, so silently normalize instead of dropping.
            action = action.model_copy(update={"target_employer": None})
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
        # Existence-only: a growth action's `what` is a forward-looking
        # deliverable that deliberately diverges from its anchor (prompts/growth.md
        # rule 1), so the claim_supports_quote overlap gate (applied at extract
        # only; score verifies anchors directly via verify_quote) would wrongly
        # drop valid actions and must NOT be applied here.
        if not verify_quote(action.anchor.quote, redacted_text, section=action.anchor.section):
            emit(
                "growth",
                "growth_action_dropped",
                reason="unverified_anchor",
                what=action.what[:80],
                quote=action.anchor.quote[:_QUOTE_SNIPPET_LIMIT],
            )
            _record(
                _Drop(
                    index,
                    action.what,
                    "unverified_anchor",
                    None,
                    action.anchor.quote[:_QUOTE_SNIPPET_LIMIT],
                )
            )
            continue
        setting_violation = _setting_violation(action, current_employers, closed_employers)
        if setting_violation is not None:
            reason, detail = setting_violation
            emit(
                "growth",
                "growth_action_dropped",
                reason=reason,
                what=action.what[:80],
                detail=detail,
            )
            _record(_Drop(index, action.what, reason, detail, None))
            continue
        survivors.append(action)
    return survivors, drops, drop_reasons


def _build_retry_user_message(
    base_user_message: str,
    *,
    kept: list[GrowthAction],
    drops: list[_Drop],
    needed: int,
    current_employers: list[str],
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
            elif drop.reason == "unverified_target_employer":
                declared = "null" if drop.detail == "missing_target" else drop.detail
                hints = ", ".join(current_employers) if current_employers else "none"
                lines.append(
                    f'  Declared target_employer "{declared}" does not match the '
                    f"current-employer hint(s): {hints}. Copy the employer verbatim from "
                    'the hint, or use setting "future_role" or "capability_artifact".'
                )
            elif drop.reason == "closed_employer_target":
                hints = ", ".join(current_employers) if current_employers else "none"
                lines.append(
                    f'  Declared target_employer "{drop.detail}" is a past employer per '
                    "closed_employer_hint — an action never happens at a closed employer. "
                    f"Set the action at a current employer ({hints}) or use setting "
                    '"future_role" or "capability_artifact".'
                )
            elif drop.detail:
                lines.append(f"  Matched: {drop.detail}")
    max_new = 5 - len(kept)
    lines.append(
        f"Return a JSON object with {needed} to {max_new} NEW action(s) in the same schema. "
        "Do not include the kept actions."
    )
    return "\n".join(lines)


async def plan_growth(
    redacted: RedactedCV,
    profile: Profile,
    score: Score,
    salary_midpoint: int,
    currency: str,
    market_name: str | None = None,
) -> list[GrowthAction] | StageFailure:
    async with stage_boundary("growth") as cm:
        t0 = time.perf_counter()

        def _ms() -> int:
            return int((time.perf_counter() - t0) * 1000)

        try:
            client = get_client()
            current_hint, closed_hint = _compute_employer_hints(redacted, profile)
            user_message = _build_user_message(
                redacted,
                profile,
                score,
                salary_midpoint,
                currency,
                current_hint,
                closed_hint,
                market_name=market_name,
            )

            base_user_message = user_message
            # Survivors pool across attempts (keyed on normalized what), so a
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
                        current_employers=current_hint,
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
                    debug_detail="only 0 verified actions; prompt contract asks for 3-5",
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
    return cm.failure  # type: ignore[return-value]
