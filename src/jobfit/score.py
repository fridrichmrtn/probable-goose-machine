from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from jobfit.errors import StageFailure, stage_boundary
from jobfit.llm import LLMClient
from jobfit.obs import emit
from jobfit.schemas import COMPONENT_WEIGHTS, Component, Profile, RedactedCV, Score
from jobfit.verify import verify_quote

_PROMPT_PATH = Path(__file__).parent / "prompts" / "score.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


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

        raw = await client.complete_json(
            system=_SYSTEM_PROMPT,
            user=user_message,
            schema=_ComponentList,
            model="reasoning",
            temperature=0.0,
        )
        assert isinstance(raw, _ComponentList)

        verified: dict[str, Component] = {}
        dropped = 0
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

        required = set(COMPONENT_WEIGHTS.keys())
        missing = required - verified.keys()
        if missing:
            # Explicit failure event so observability sees the path that
            # stage_boundary's exception handler does not — we return a
            # StageFailure rather than raising, so the boundary never sees it.
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

        score = Score(components=[verified[name] for name in COMPONENT_WEIGHTS])
        emit("score", "score_total", total=score.total)
        return score

    return cm.failure  # type: ignore[return-value]
