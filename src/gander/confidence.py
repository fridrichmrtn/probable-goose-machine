"""L4c confidence judge — recompute-then-compare.

Step A receives only the sources and decides the tier (Low/Medium/High).
Step B writes the human-readable rationale, given the tier as a fixed fact.
Step A's tier is authoritative; Step B can never override it.

Signature widened from the T12 contract to ``Confidence | StageFailure`` for
parity with ``estimate_salary`` and ``score_profile``. The structural-isolation
test asserts on parameter keys only, so the recompute-then-compare contract
still holds.

``model="cheap"`` resolves through the OpenRouter registry in ``gander.llm``.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from gander.errors import StageFailure, stage_boundary
from gander.llm import get_client
from gander.obs import emit
from gander.schemas import Confidence, CVQualitySignals, Source
from gander.source_rubric import SourceRubricResult, evaluate_source_rubric

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
_CV_FLOOR_LOW_REGEX = re.compile(r"cv|extraction|component|thin|profile", re.I)


class _TierOnly(BaseModel):
    tier: Literal["Low", "Medium", "High"]
    rationale_short: str


_TIER_RANK: dict[str, int] = {"Low": 0, "Medium": 1, "High": 2}
_RANK_TIER: dict[int, Literal["Low", "Medium", "High"]] = {
    0: "Low",
    1: "Medium",
    2: "High",
}


def _cv_floor(cv_quality: CVQualitySignals) -> Literal["Low", "Medium", "High"]:
    if cv_quality.dropped_score_components >= 2:
        return "Low"
    if cv_quality.dropped_score_components == 1 or not cv_quality.canonical_role_resolved:
        return "Medium"
    if not cv_quality.location_detected:
        return "Medium"
    if cv_quality.market_provenance == "default":
        return "Medium"
    return "High"


def _cap_salary_tier_by_sources(
    model_tier: Literal["Low", "Medium", "High"],
    sources: list[Source],
) -> tuple[Literal["Low", "Medium", "High"], SourceRubricResult]:
    source_result = evaluate_source_rubric(sources)
    source_tier = source_result.tier
    if source_tier is None or _TIER_RANK[source_tier] >= _TIER_RANK[model_tier]:
        return model_tier, source_result
    return source_tier, source_result


def _apply_cv_floor(
    salary_tier: Literal["Low", "Medium", "High"],
    cv_quality: CVQualitySignals,
) -> tuple[Literal["Low", "Medium", "High"], Literal["Low", "Medium", "High"]]:
    floor = _cv_floor(cv_quality)
    final_rank = min(_TIER_RANK[salary_tier], _TIER_RANK[floor])
    return _RANK_TIER[final_rank], floor


def _cv_floor_reason(cv_quality: CVQualitySignals) -> str:
    if cv_quality.dropped_score_components >= 2:
        return "two or more score components were dropped during CV verification"
    if cv_quality.dropped_score_components == 1:
        return "one score component was dropped during CV verification"
    if not cv_quality.canonical_role_resolved:
        return "the canonical market role could not be resolved confidently"
    if not cv_quality.location_detected:
        return "the candidate location was not detected"
    if cv_quality.market_provenance == "default":
        return "the candidate's labor market could not be resolved, so the estimate is market-blind"
    return "no CV-quality cap was applied"


def _render_step_b(
    salary_tier: str,
    final_tier: str,
    cv_floor: str,
    cv_quality: CVQualitySignals,
    low: int,
    high: int,
    currency: str,
    period: Literal["month", "year"],
) -> str:
    return (
        f"Salary-source tier: {salary_tier}\n"
        f"Final tier: {final_tier}\n"
        f"CV-quality cap: {cv_floor}\n"
        f"CV-quality reason: {_cv_floor_reason(cv_quality)}\n"
        f"Produced range: {low}-{high} {currency}/{period}"
    )


def _low_fallback_rationale(
    *,
    salary_tier: Literal["Low", "Medium", "High"],
    low: int,
    high: int,
    currency: str,
    period: Literal["month", "year"],
    cv_quality: CVQualitySignals,
) -> str:
    if salary_tier == "Low":
        return _LOW_FALLBACK_RATIONALE
    return (
        "Confidence in this estimate is Low. "
        f"The {low}-{high} {currency}/{period} band has salary-source support, "
        f"but CV extraction is thin because {_cv_floor_reason(cv_quality)}, "
        "so treat the estimate as provisional."
    )


async def judge(
    sources: list[Source],
    low: int,
    high: int,
    currency: str,
    period: Literal["month", "year"],
    *,
    cv_quality: CVQualitySignals,
) -> Confidence | StageFailure:
    async with stage_boundary("confidence") as cm:
        t0 = time.perf_counter()

        def _ms() -> int:
            return int((time.perf_counter() - t0) * 1000)

        client = get_client()

        step_a_user = json.dumps({"sources": [s.model_dump(mode="json") for s in sources]})
        try:
            tier_obj = await client.complete_json(
                system=_STEP_A_PROMPT,
                user=step_a_user,
                schema=_TierOnly,
                model="cheap",
                temperature=0.0,
                max_tokens=128,
            )
        except Exception as exc:
            emit(
                "confidence",
                "stage_failure",
                reason="step_a_llm_error",
                exc_type=type(exc).__name__,
                duration_ms=_ms(),
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
                duration_ms=_ms(),
            )
            return StageFailure(
                stage="confidence",
                user_message=_FAILURE_MSG,
                debug_detail=f"complete_json returned {type(tier_obj).__name__}",
            )
        model_tier = tier_obj.tier
        salary_tier, source_result = _cap_salary_tier_by_sources(model_tier, sources)
        if salary_tier != model_tier:
            emit(
                "confidence",
                "confidence_source_rubric_applied",
                model_tier=model_tier,
                source_tier=source_result.tier,
                final_salary_tier=salary_tier,
                sources_count=len(sources),
                distinct_domains=source_result.distinct_domains,
                comparable_values=source_result.comparable_values,
                spread=source_result.spread,
                spread_known=source_result.spread is not None,
                reason=source_result.reason,
            )
        final_tier, cv_floor = _apply_cv_floor(salary_tier, cv_quality)
        if final_tier != salary_tier:
            emit(
                "confidence",
                "confidence_cv_floor_applied",
                salary_tier=salary_tier,
                cv_floor=cv_floor,
                final_tier=final_tier,
                dropped_score_components=cv_quality.dropped_score_components,
                canonical_role_resolved=cv_quality.canonical_role_resolved,
                location_detected=cv_quality.location_detected,
                market_provenance=cv_quality.market_provenance,
            )

        emit(
            "confidence",
            "confidence_step_a",
            tier=final_tier,
            salary_tier=salary_tier,
            cv_floor=cv_floor,
            sources_count=len(sources),
        )

        step_b_user = _render_step_b(
            salary_tier, final_tier, cv_floor, cv_quality, low, high, currency, period
        )
        try:
            rationale = await client.complete_text(
                system=_STEP_B_PROMPT,
                user=step_b_user,
                model="cheap",
                temperature=0.0,
                max_tokens=256,
            )
            regenerated = False
            low_regex = _RATIONALE_LOW_REGEX if salary_tier == "Low" else _CV_FLOOR_LOW_REGEX
            if final_tier == "Low" and not low_regex.search(rationale):
                emit(
                    "confidence",
                    "confidence_step_b_regenerated",
                    reason="missing_low_marker",
                )
                marker_instruction = (
                    "The previous draft did not include the words 'insufficient' or "
                    "'disagree'. Rewrite the paragraph keeping the same meaning, but use "
                    "one of those words to signal the provisional nature of the estimate."
                    if salary_tier == "Low"
                    else "The previous draft did not explain the CV-quality cap. Rewrite the "
                    "paragraph keeping the same meaning, but explicitly mention thin CV "
                    "extraction or dropped CV components."
                )
                retry_user = step_b_user + "\n\n" + marker_instruction
                rationale = await client.complete_text(
                    system=_STEP_B_PROMPT,
                    user=retry_user,
                    model="cheap",
                    temperature=0.0,
                    max_tokens=256,
                )
                regenerated = True
                if not low_regex.search(rationale):
                    emit(
                        "confidence",
                        "confidence_low_fallback_used",
                        reason="regenerate_failed",
                    )
                    rationale = _low_fallback_rationale(
                        salary_tier=salary_tier,
                        low=low,
                        high=high,
                        currency=currency,
                        period=period,
                        cv_quality=cv_quality,
                    )
        except Exception as exc:
            emit(
                "confidence",
                "stage_failure",
                reason="step_b_llm_error",
                exc_type=type(exc).__name__,
                duration_ms=_ms(),
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
            tier=final_tier,
            rationale_len=len(rationale),
        )
        emit(
            "confidence",
            "done",
            duration_ms=_ms(),
            tier=final_tier,
            salary_tier=salary_tier,
            cv_floor=cv_floor,
        )
        return Confidence(tier=final_tier, rationale=rationale)

    return cm.failure  # type: ignore[return-value]
