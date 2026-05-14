from __future__ import annotations

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


async def score_profile(redacted: RedactedCV, profile: Profile) -> Score | StageFailure:
    with stage_boundary("score") as cm:
        client = LLMClient()
        user_message = _build_user_message(redacted, profile)

        try:
            raw = await client.complete_json(
                system=_SYSTEM_PROMPT,
                user=user_message,
                schema=_ComponentList,
                model="reasoning",
                temperature=0.0,
            )
        except Exception as exc:
            emit(
                "score",
                "stage_failure",
                reason="llm_error",
                exc_type=type(exc).__name__,
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
            )
            return StageFailure(
                stage="score",
                user_message=_GENERATION_FAILURE_MSG,
                debug_detail=f"complete_json returned {type(raw).__name__}",
            )

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

        emit(
            "score",
            "score_components",
            returned=len(raw.components),
            verified=len(verified),
            dropped=dropped,
        )

        if section_miss_count > _SECTION_MISS_CAP:
            emit("score", "section_blind_fail", miss_count=section_miss_count)
            return StageFailure(
                stage="score",
                user_message=(
                    "Section anchors unavailable on this CV — could not verify "
                    "scoring components against named sections."
                ),
                debug_detail=(f"section_miss_count={section_miss_count} cap={_SECTION_MISS_CAP}"),
            )

        required = set(COMPONENT_WEIGHTS.keys())
        missing = required - verified.keys()
        if "experience" in missing:
            # T25: experience is the only mandatory component. Losing it means
            # the score has nothing to anchor against — fail closed. Other
            # categories take the partial-score branch below.
            emit(
                "score",
                "stage_failure",
                reason="missing_categories",
                missing=sorted(missing),
                dropped=dropped,
            )
            return StageFailure(
                stage="score",
                user_message="Could not verify enough scoring components from CV.",
                debug_detail=f"missing_categories={sorted(missing)} dropped={dropped}",
            )

        # Partial-score path: experience verified, but ≥1 of {skills, education,
        # soft_signals} dropped. Build Score over surviving components; the
        # missing weights silently zero-contribute to `total` (drop-as-zero —
        # see schemas.Score docstring). The renderer surfaces `dropped` in the
        # footer so the reviewer can see what was zero-weighted.
        score = Score(
            components=[verified[name] for name in COMPONENT_WEIGHTS if name in verified],
            dropped=sorted(missing),  # type: ignore[arg-type]
        )
        if missing:
            emit(
                "score",
                "score_partial",
                dropped=sorted(missing),
                surviving=sorted(verified.keys()),
            )
        emit("score", "score_total", total=score.total)
        return score

    return cm.failure  # type: ignore[return-value]
