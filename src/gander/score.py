from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from gander.errors import StageFailure, stage_boundary
from gander.llm import LLMClient
from gander.obs import emit, subscribe
from gander.schemas import COMPONENT_WEIGHTS, Component, Profile, RedactedCV, Score
from gander.verify import verify_quote

# Per-stage cap on `verify_section_miss` events tolerated before declaring the
# stage section-blind. Half-plus-one of the 4 components — a CV that loses
# section restriction on >2 anchors has effectively no section vocabulary, and
# PRD §4.5's section-restriction signal is gone. Fail closed rather than let
# the whole-CV fallback silently carry every anchor (T26).
_SECTION_MISS_CAP = 2

_PROMPT_PATH = Path(__file__).parent / "prompts" / "score.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

# PRD §4.6 verbatim copy for model-output failures (transport error, parse failure).
# The logical `missing_categories` path keeps its more specific message because it
# describes a CV/model alignment problem, not a generation failure.
_GENERATION_FAILURE_MSG = "Could not generate this section reliably"
_SCORE_LLM_MAX_RETRIES = 2
_SCORE_LOGICAL_MAX_RETRIES = 1
_SALVAGE_RETRY_COMPONENTS = {"skills", "education", "soft_signals"}
_DOCTORATE_TOKENS = ("ph.d", "phd", "doctorate", "dphil", "csc", "drsc")
_MASTERS_TOKENS = ("m.sc", "msc", "master", "mgr.", "ing.", "m.eng", "mba")


class _ComponentList(BaseModel):
    """LLM response envelope: ``{"components": [Component, ...]}``.

    Reuses ``Component`` from schemas (which already enforces name/range/anchor shape).
    Length and per-category uniqueness are NOT enforced here — we surface the model's
    actual output (junk names, dupes, wrong length) to the verify-and-rebuild step,
    where any missing category cleanly becomes a StageFailure.
    """

    components: list[Component]


def _build_user_message(redacted: RedactedCV, profile: Profile) -> str:
    return (
        f"Detected role: {profile.detected_role}\n"
        f"Detected years of experience: {profile.detected_years_experience}\n"
        f"\n"
        f"Redacted CV:\n\n{redacted.text}"
    )


def _build_retry_user_message(user_message: str, missing: set[str], dropped: int) -> str:
    message = (
        user_message
        + "\n\nYour previous score output failed downstream verification: "
        + f"missing_categories={sorted(missing)} dropped={dropped}. "
        + "Return corrected JSON only. The experience component is mandatory; "
        + "choose an exact verbatim 8+ word quote from the CV that supports experience, "
        + "role progression, or shipped impact. If the section header is uncertain, "
        + "set anchor.section to null rather than guessing."
    )
    if missing & {"skills", "soft_signals"}:
        message += (
            " For skills and soft_signals, do not rely only on compact Skills/Soft "
            "sections; use longer literal lines from Experience, Projects, Profile, "
            "or Summary when they demonstrate named tools, leadership, mentorship, "
            "ownership, cross-team work, or stakeholder communication."
        )
    if "education" in missing:
        message += (
            " For education, choose an exact literal degree/institution line from the CV; "
            "preserve punctuation, accents, and redaction markers exactly as shown."
        )
    return message


def _build_education_floor_retry_message(user_message: str, floor: int, actual: int) -> str:
    return (
        user_message
        + "\n\nYour previous score output failed the education credential rubric: "
        + f"education_score={actual} but the CV contains a formal credential that "
        + f"requires education >= {floor}. Return corrected JSON only. For education, "
        + "choose an exact literal highest-credential degree/institution line from "
        + "the CV and score it according to the credential bands."
    )


def _education_credential_floor(source: str) -> int | None:
    if (
        re.search(
            r"^#{1,6}\s*(?:education|vzdělání)\b",
            source,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        is None
    ):
        return None
    text = source.casefold()
    if any(token in text for token in _DOCTORATE_TOKENS):
        return 86
    if any(token in text for token in _MASTERS_TOKENS):
        return 66
    return None


def _verify_components(
    raw: _ComponentList, redacted: RedactedCV
) -> tuple[dict[str, Component], int, int]:
    verified: dict[str, Component] = {}
    dropped = 0
    section_miss_count = 0

    def _count_section_miss(record: dict[str, Any]) -> None:
        nonlocal section_miss_count
        if record.get("event") == "verify_section_miss":
            section_miss_count += 1

    with subscribe(_count_section_miss):
        for comp in raw.components:
            if comp.name in verified:
                dropped += 1
                continue
            if verify_quote(comp.anchor.quote, redacted.text, section=comp.anchor.section):
                verified[comp.name] = comp
            else:
                dropped += 1

    return verified, dropped, section_miss_count


async def score_profile(redacted: RedactedCV, profile: Profile) -> Score | StageFailure:
    with stage_boundary("score") as cm:
        t0 = time.perf_counter()

        def _ms() -> int:
            return int((time.perf_counter() - t0) * 1000)

        client = LLMClient()
        user_message = _build_user_message(redacted, profile)

        required = set(COMPONENT_WEIGHTS.keys())
        # Best-of merge across attempts: a retry can only *add* components, never
        # lose ones a prior attempt already verified. Without this, attempt 1
        # paraphrasing a previously-verified experience anchor would collapse a
        # working partial score into a hard StageFailure.
        best_verified: dict[str, Component] = {}
        for attempt in range(_SCORE_LOGICAL_MAX_RETRIES + 1):
            try:
                raw = await client.complete_json(
                    system=_SYSTEM_PROMPT,
                    user=user_message,
                    schema=_ComponentList,
                    model="reasoning",
                    temperature=0.0,
                    max_retries=_SCORE_LLM_MAX_RETRIES,
                    max_tokens=1024,
                )
            except Exception as exc:
                emit(
                    "score",
                    "stage_failure",
                    reason="llm_error",
                    exc_type=type(exc).__name__,
                    duration_ms=_ms(),
                )
                return StageFailure(
                    stage="score",
                    user_message=_GENERATION_FAILURE_MSG,
                    debug_detail=f"{type(exc).__name__}: {exc}",
                )
            if not isinstance(raw, _ComponentList):
                emit(
                    "score",
                    "stage_failure",
                    reason="invalid_llm_output",
                    got_type=type(raw).__name__,
                    duration_ms=_ms(),
                )
                return StageFailure(
                    stage="score",
                    user_message=_GENERATION_FAILURE_MSG,
                    debug_detail=f"complete_json returned {type(raw).__name__}",
                )

            verified, dropped, section_miss_count = _verify_components(raw, redacted)
            for name, comp in verified.items():
                previous = best_verified.get(name)
                if previous is None or (
                    name == "education" and comp.score_0_100 > previous.score_0_100
                ):
                    best_verified[name] = comp
            emit(
                "score",
                "score_components",
                returned=len(raw.components),
                verified=len(verified),
                dropped=dropped,
            )

            if section_miss_count > _SECTION_MISS_CAP:
                duration_ms = _ms()
                emit("score", "section_blind_fail", miss_count=section_miss_count)
                emit(
                    "score",
                    "stage_failure",
                    reason="section_blind",
                    miss_count=section_miss_count,
                    duration_ms=duration_ms,
                )
                return StageFailure(
                    stage="score",
                    user_message=(
                        "Section anchors unavailable on this CV — could not verify "
                        "scoring components against named sections."
                    ),
                    debug_detail=(
                        f"section_miss_count={section_miss_count} cap={_SECTION_MISS_CAP}"
                    ),
                )

            missing = required - best_verified.keys()
            if "experience" in missing:
                # T25: experience is the only mandatory component. Losing it means
                # the score has nothing to anchor against — fail closed after one
                # targeted retry, because live models sometimes pick a paraphrased
                # experience anchor despite otherwise valid scoring output.
                if attempt < _SCORE_LOGICAL_MAX_RETRIES:
                    emit(
                        "score",
                        "score_retry",
                        reason="missing_experience",
                        missing=sorted(missing),
                        dropped=dropped,
                    )
                    user_message = _build_retry_user_message(user_message, missing, dropped)
                    continue
                emit(
                    "score",
                    "stage_failure",
                    reason="missing_categories",
                    missing=sorted(missing),
                    dropped=dropped,
                    duration_ms=_ms(),
                )
                return StageFailure(
                    stage="score",
                    user_message="Could not verify enough scoring components from CV.",
                    debug_detail=f"missing_categories={sorted(missing)} dropped={dropped}",
                )
            if missing & _SALVAGE_RETRY_COMPONENTS and attempt < _SCORE_LOGICAL_MAX_RETRIES:
                reason = "missing_salvageable_components"
                if missing <= {"skills", "soft_signals"}:
                    reason = "missing_skills_or_soft_signals"
                elif missing == {"education"}:
                    reason = "missing_education"
                emit(
                    "score",
                    "score_retry",
                    reason=reason,
                    missing=sorted(missing),
                    dropped=dropped,
                )
                user_message = _build_retry_user_message(user_message, missing, dropped)
                continue
            education_floor = _education_credential_floor(redacted.text)
            education = best_verified.get("education")
            if (
                education_floor is not None
                and education is not None
                and education.score_0_100 < education_floor
                and attempt < _SCORE_LOGICAL_MAX_RETRIES
            ):
                emit(
                    "score",
                    "score_retry",
                    reason="education_below_credential_floor",
                    score=education.score_0_100,
                    floor=education_floor,
                )
                user_message = _build_education_floor_retry_message(
                    user_message,
                    floor=education_floor,
                    actual=education.score_0_100,
                )
                continue
            break

        # Partial-score path: experience verified, but ≥1 of {skills, education,
        # soft_signals} dropped. Build Score over surviving components; the
        # missing weights silently zero-contribute to `total` (drop-as-zero —
        # see schemas.Score docstring). The renderer surfaces `dropped` in the
        # footer so the reviewer can see what was zero-weighted.
        score = Score(
            components=[best_verified[name] for name in COMPONENT_WEIGHTS if name in best_verified],
            dropped=sorted(missing),  # type: ignore[arg-type]
        )
        if missing:
            emit(
                "score",
                "score_partial",
                dropped=sorted(missing),
                surviving=sorted(best_verified.keys()),
            )
        emit("score", "score_total", total=score.total)
        emit(
            "score",
            "done",
            duration_ms=_ms(),
            total=score.total,
            components=len(score.components),
            dropped=len(score.dropped),
        )
        return score

    return cm.failure  # type: ignore[return-value]
