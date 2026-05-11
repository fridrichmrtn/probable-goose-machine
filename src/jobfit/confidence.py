"""L4c confidence judge — recompute-then-compare.

Step A receives only the sources and decides the tier (Low/Medium/High).
Step B writes the human-readable rationale, given the tier as a fixed fact.
Step A's tier is authoritative; Step B can never override it.

Signature widened from the T12 contract to ``Confidence | StageFailure`` for
parity with ``estimate_salary`` and ``score_profile``. The structural-isolation
test asserts on parameter keys only, so the recompute-then-compare contract
still holds.

``model="cheap"`` resolves through ``_PROFILE_MODELS`` in ``jobfit.llm`` to
MiniMax-M2.7-highspeed under the current profiles.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from jobfit.errors import StageFailure, stage_boundary
from jobfit.llm import LLMClient
from jobfit.obs import emit
from jobfit.schemas import Confidence, Source

_STEP_A_PROMPT = (Path(__file__).parent / "prompts" / "confidence_step_a.md").read_text(
    encoding="utf-8"
)
_STEP_B_PROMPT = (Path(__file__).parent / "prompts" / "confidence_step_b.md").read_text(
    encoding="utf-8"
)

_RATIONALE_LOW_REGEX = re.compile(r"insufficient|disagree", re.I)

# PRD §4.6 canonical user-facing copy for any confidence failure that escapes
# normal Step A / Step B logic. The reviewer-visible string is always this one;
# debug_detail carries the structured reason.
_FAILURE_MSG = "Could not generate this section reliably"

# Honest fallback when Step B refuses to surface the provisional nature of a
# Low-tier estimate even after one corrective regenerate. Pairing this sentence
# with tier="Low" is honest by construction.
_LOW_FALLBACK_RATIONALE = (
    "The underlying market data is insufficient or in disagreement, "
    "so treat this estimate as provisional."
)


class _TierOnly(BaseModel):
    tier: Literal["Low", "Medium", "High"]
    rationale_short: str


def _render_step_b(
    tier: str,
    low: int,
    high: int,
    currency: str,
    period: Literal["month", "year"],
) -> str:
    return f"Step A tier: {tier}\nProduced range: {low}-{high} {currency}/{period}"


async def judge(
    sources: list[Source],
    low: int,
    high: int,
    currency: str,
    period: Literal["month", "year"],
) -> Confidence | StageFailure:
    async with stage_boundary("confidence") as cm:
        client = LLMClient()

        step_a_user = json.dumps([s.model_dump(mode="json") for s in sources])
        try:
            tier_obj = await client.complete_json(
                system=_STEP_A_PROMPT,
                user=step_a_user,
                schema=_TierOnly,
                model="cheap",
                temperature=0.0,
            )
        except Exception as exc:
            emit(
                "confidence",
                "stage_failure",
                reason="step_a_llm_error",
                exc_type=type(exc).__name__,
            )
            return StageFailure(
                stage="confidence",
                user_message=_FAILURE_MSG,
                debug_detail=f"{type(exc).__name__}: {exc}",
            )
        if not isinstance(tier_obj, _TierOnly):
            emit(
                "confidence",
                "stage_failure",
                reason="invalid_step_a_output",
                got_type=type(tier_obj).__name__,
            )
            return StageFailure(
                stage="confidence",
                user_message=_FAILURE_MSG,
                debug_detail=f"complete_json returned {type(tier_obj).__name__}",
            )
        emit(
            "confidence",
            "confidence_step_a",
            tier=tier_obj.tier,
            sources_count=len(sources),
        )

        step_b_user = _render_step_b(tier_obj.tier, low, high, currency, period)
        try:
            rationale = await client.complete_text(
                system=_STEP_B_PROMPT,
                user=step_b_user,
                model="cheap",
                temperature=0.0,
            )
            regenerated = False
            if tier_obj.tier == "Low" and not _RATIONALE_LOW_REGEX.search(rationale):
                emit(
                    "confidence",
                    "confidence_step_b_regenerated",
                    reason="missing_low_marker",
                )
                retry_user = step_b_user + (
                    "\n\nThe previous draft did not include the words 'insufficient' or "
                    "'disagree'. Rewrite the paragraph keeping the same meaning, but use "
                    "one of those words to signal the provisional nature of the estimate."
                )
                rationale = await client.complete_text(
                    system=_STEP_B_PROMPT,
                    user=retry_user,
                    model="cheap",
                    temperature=0.0,
                )
                regenerated = True
                if not _RATIONALE_LOW_REGEX.search(rationale):
                    emit(
                        "confidence",
                        "confidence_low_fallback_used",
                        reason="regenerate_failed",
                    )
                    rationale = _LOW_FALLBACK_RATIONALE
        except Exception as exc:
            emit(
                "confidence",
                "stage_failure",
                reason="step_b_llm_error",
                exc_type=type(exc).__name__,
            )
            return StageFailure(
                stage="confidence",
                user_message=_FAILURE_MSG,
                debug_detail=f"{type(exc).__name__}: {exc}",
            )

        emit(
            "confidence",
            "confidence_step_b",
            regenerated=regenerated,
            rationale_len=len(rationale),
        )
        emit(
            "confidence",
            "confidence_decision",
            tier=tier_obj.tier,
            rationale_len=len(rationale),
        )
        return Confidence(tier=tier_obj.tier, rationale=rationale)

    return cm.failure  # type: ignore[return-value]
