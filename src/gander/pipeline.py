"""L6 pipeline orchestrator — async iterator over a streaming Report.

`run(file_bytes, filename)` walks the L1→L5 stages and yields a fresh `Report`
after every meaningful state change so the L7 Gradio UI (T16) can re-render
the stage tracker and report body. Stage workers (T07–T13) already self-wrap
their failures into `StageFailure`; this module sequences them, fans out
L4a+L4b concurrently, applies the conditional L4c/L5 flow, and accumulates
cost/latency totals via an `obs.subscribe` callback.

Spec drift notes (T15 task file vs canonical schema):

* `statuses["ingest"]` / `statuses["redact"]` don't exist — `StageName` is the
  5 schema stages. Ingest or redact failures surface as
  `report.profile = StageFailure(stage="profile", ...)` because profile is the
  first stage gated on successful ingest+redact (PLAN L2). Same mapping T14
  adopted for the renderer's short-circuit.
* Initial yield carries `None` for every block (schema accepts `None` after the
  T15 schema patch) rather than zero-filled sentinels. The renderer treats
  `None` as "not yet rendered", so the body is empty until profile completes.
* `total_cost_usd` / `total_latency_ms` are populated by the subscriber on
  every yield. `total_latency_ms` is summed provider-call latency; `wall_clock_ms`
  is measured from pipeline start for every snapshot. The footer in
  `gander.report` interpolates them.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, cast

from gander import obs
from gander.confidence import judge
from gander.errors import StageFailure
from gander.extract import extract_profile
from gander.growth import plan_growth
from gander.ingest import extract_text
from gander.market import resolve_market
from gander.redact import redact
from gander.salary import estimate_salary
from gander.schemas import (
    REPORT_STAGE_NAMES,
    Confidence,
    CVQualitySignals,
    GrowthAction,
    Profile,
    RedactedCV,
    Report,
    SalaryEstimate,
    Score,
    StageName,
    StageStatus,
)
from gander.score import score_profile

# Cascade messages shown to the user when an upstream stage failed and the
# downstream stage cannot meaningfully run. Keyed by the downstream stage so
# the wording matches the section header the reviewer will see.
#
# Every growth cascade message carries GROWTH_CASCADE_PREFIX — consumers
# (scripts/eval_corpus.py) use it to tell "growth never ran" apart from a
# genuine growth StageFailure, which carries the §4.6 copy instead.
GROWTH_CASCADE_PREFIX = "Cannot generate growth plan without"
_CASCADE_PROFILE_FAILED: dict[StageName, str] = {
    "score": "Cannot score without profile extraction.",
    "salary": "Cannot estimate salary without profile extraction.",
    "confidence": "Cannot judge confidence without salary estimate.",
    "growth": f"{GROWTH_CASCADE_PREFIX} profile extraction.",
}
_CONFIDENCE_NO_SALARY_RATIONALE = "Insufficient market data. See salary block."
_GROWTH_NO_BASELINE = f"{GROWTH_CASCADE_PREFIX} scoring or salary baseline."
_GROWTH_NEEDS_SCORE = f"{GROWTH_CASCADE_PREFIX} scoring; salary baseline alone is insufficient."
_GROWTH_NEEDS_SALARY = f"{GROWTH_CASCADE_PREFIX} salary baseline; scoring alone is insufficient."


@dataclass
class _Run:
    """Mutable accumulator for one pipeline run.

    Holds the streaming state for each yield + the cost/latency totals
    populated by the obs.subscribe callback. `snapshot()` rebuilds an
    immutable `Report` for each yield so the caller can hold references
    across iterations without being affected by subsequent mutation.
    """

    raw_cv_text: str = ""
    redacted_cv_text: str = ""
    profile: Profile | StageFailure | None = None
    score: Score | StageFailure | None = None
    salary: SalaryEstimate | StageFailure | None = None
    confidence: Confidence | StageFailure | None = None
    growth: list[GrowthAction] | StageFailure | None = None
    statuses: dict[StageName, StageStatus] = field(
        default_factory=lambda: dict.fromkeys(REPORT_STAGE_NAMES, "pending")
    )
    total_cost_usd: float = 0.0
    total_latency_ms: int = 0
    started_at: float = field(default_factory=time.perf_counter)
    notices: list[str] = field(default_factory=list)

    def snapshot(self) -> Report:
        return Report(
            profile=self.profile,
            score=self.score,
            salary=self.salary,
            confidence=self.confidence,
            growth=self.growth,
            statuses=dict(self.statuses),
            raw_cv_text=self.raw_cv_text,
            redacted_cv_text=self.redacted_cv_text,
            total_cost_usd=self.total_cost_usd,
            total_latency_ms=self.total_latency_ms,
            wall_clock_ms=int((time.perf_counter() - self.started_at) * 1000),
            notices=list(self.notices),
        )


def _cascade_failure(stage: StageName, reason: str) -> StageFailure:
    return StageFailure(stage=stage, user_message=reason)


def _cascade_all_downstream(run: _Run, upstream_failure: str) -> None:
    """Fill every downstream block with a cascade StageFailure.

    Called after ingest/redact/profile failure: there is nothing left to
    compute, but the schema requires `statuses` to cover every key, so we
    surface the upstream failure to the user across every section as a
    callout while marking statuses `failed`.
    """
    run.score = StageFailure(stage="score", user_message=upstream_failure)
    run.salary = StageFailure(stage="salary", user_message=upstream_failure)
    run.confidence = StageFailure(stage="confidence", user_message=upstream_failure)
    run.growth = StageFailure(stage="growth", user_message=upstream_failure)
    run.statuses["score"] = "failed"
    run.statuses["salary"] = "failed"
    run.statuses["confidence"] = "failed"
    run.statuses["growth"] = "failed"


def _make_accumulator(run: _Run) -> Any:
    """Return an obs subscriber that sums llm_call cost/latency into `run`.

    Filters on `event == "llm_call"` (gander.llm emits this with `usd_cost` +
    `duration_ms` fields). Defensive .get() lookups so a malformed record
    cannot raise into obs.emit (which already protects its callbacks from
    exceptions, but extra defence is cheap).
    """

    def _accumulate(record: dict[str, Any]) -> None:
        if record.get("event") != "llm_call":
            if record.get("event") == "vision_budget_fallback_degraded":
                notice = record.get("notice")
                if isinstance(notice, str) and notice not in run.notices:
                    run.notices.append(notice)
            return
        cost = record.get("usd_cost")
        if isinstance(cost, int | float):
            run.total_cost_usd += float(cost)
        duration = record.get("duration_ms")
        if isinstance(duration, int):
            run.total_latency_ms += duration

    return _accumulate


async def run(file_bytes: bytes, filename: str) -> AsyncIterator[Report]:
    """Run the full L1→L5 pipeline, yielding a `Report` after every state change.

    Yields:
        * Initial snapshot with all blocks `None` and statuses `pending`.
        * After each stage transition (`running` start, then `done`/`failed`).
        * Final snapshot with cost/latency totals populated.

    The caller (T16 UI) is expected to re-render tracker + body on every yield.
    No exception escapes — every stage already returns `StageFailure` rather
    than raising. The `obs.subscribe` context manager isolates the cost
    accumulator to this run only.
    """
    state = _Run()
    obs.emit(None, "pipeline_start", filename=filename, bytes=len(file_bytes))

    with obs.subscribe(_make_accumulator(state)):
        # Initial yield: tracker says pending, body is empty (renderer
        # short-circuits on profile=None).
        yield state.snapshot()

        # === L1 ingest (async) ===
        state.statuses["profile"] = "running"
        yield state.snapshot()
        text_result = await extract_text(file_bytes, filename)
        if isinstance(text_result, StageFailure):
            state.profile = StageFailure(
                stage="profile",
                user_message=text_result.user_message,
                debug_detail=text_result.debug_detail,
            )
            state.statuses["profile"] = "failed"
            _cascade_all_downstream(state, "Cannot run without successful ingest.")
            obs.emit(None, "pipeline_done", outcome="ingest_failed")
            yield state.snapshot()
            return
        state.raw_cv_text = text_result

        # === L2 redact (sync) ===
        redacted_result = redact(text_result)
        if isinstance(redacted_result, StageFailure):
            state.profile = StageFailure(
                stage="profile",
                user_message=redacted_result.user_message,
                debug_detail=redacted_result.debug_detail,
            )
            state.statuses["profile"] = "failed"
            _cascade_all_downstream(state, "Cannot run without successful redaction.")
            obs.emit(None, "pipeline_done", outcome="redact_failed")
            yield state.snapshot()
            return
        redacted: RedactedCV = redacted_result
        state.redacted_cv_text = redacted.text
        yield state.snapshot()

        # === L3 extract (async) ===
        profile_result = await extract_profile(redacted)
        if isinstance(profile_result, StageFailure):
            state.profile = profile_result
            state.statuses["profile"] = "failed"
            state.score = _cascade_failure("score", _CASCADE_PROFILE_FAILED["score"])
            state.salary = _cascade_failure("salary", _CASCADE_PROFILE_FAILED["salary"])
            state.confidence = _cascade_failure("confidence", _CASCADE_PROFILE_FAILED["confidence"])
            state.growth = _cascade_failure("growth", _CASCADE_PROFILE_FAILED["growth"])
            state.statuses["score"] = "failed"
            state.statuses["salary"] = "failed"
            state.statuses["confidence"] = "failed"
            state.statuses["growth"] = "failed"
            obs.emit(None, "pipeline_done", outcome="profile_failed")
            yield state.snapshot()
            return
        state.profile = profile_result
        state.statuses["profile"] = "done"
        yield state.snapshot()
        profile: Profile = profile_result

        # === L4a + L4b concurrent ===
        state.statuses["score"] = "running"
        state.statuses["salary"] = "running"
        yield state.snapshot()

        score_task = asyncio.create_task(score_profile(redacted, profile))
        salary_task = asyncio.create_task(estimate_salary(profile))
        for completed in asyncio.as_completed([score_task, salary_task]):
            result = await completed
            # Route by result type rather than task identity. score_profile
            # returns Score|StageFailure; estimate_salary returns
            # SalaryEstimate|StageFailure. The two real types are disjoint,
            # so isinstance routing is unambiguous. For StageFailure we
            # disambiguate via `result.stage` (each stage sets its own).
            if isinstance(result, Score):
                state.score = result
                state.statuses["score"] = "done"
            elif isinstance(result, SalaryEstimate):
                state.salary = result
                state.statuses["salary"] = "done"
            elif isinstance(result, StageFailure):
                if result.stage == "score":
                    state.score = result
                    state.statuses["score"] = "failed"
                elif result.stage == "salary":
                    state.salary = result
                    state.statuses["salary"] = "failed"
                else:
                    obs.emit(
                        None,
                        "pipeline_warn",
                        reason="unknown_stagefailure",
                        result_stage=result.stage,
                    )
            yield state.snapshot()

        # === L4c confidence + L5 growth (conditional, concurrent) ===
        async def _run_confidence() -> tuple[StageName, object]:
            if isinstance(state.salary, SalaryEstimate):
                cv_quality = CVQualitySignals(
                    dropped_score_components=len(state.score.dropped)
                    if isinstance(state.score, Score)
                    else 3,
                    canonical_role_resolved=isinstance(state.profile, Profile)
                    and state.profile.role_normalization_source != "unrecognized",
                    location_detected=isinstance(state.profile, Profile)
                    and state.profile.detected_location is not None,
                    market_provenance=resolve_market(state.profile).provenance
                    if isinstance(state.profile, Profile)
                    else "default",
                )
                return (
                    "confidence",
                    await judge(
                        state.salary.sources,
                        state.salary.low,
                        state.salary.high,
                        state.salary.currency,
                        state.salary.period,
                        cv_quality=cv_quality,
                    ),
                )

            # Salary failed — short-circuit confidence to Low without an LLM call.
            return (
                "confidence",
                Confidence(
                    tier="Low",
                    rationale=_CONFIDENCE_NO_SALARY_RATIONALE,
                ),
            )

        async def _run_growth() -> tuple[StageName, object]:
            # Decision A (T15 plan): growth requires BOTH score AND salary. If
            # either upstream failed we cascade; only the all-green path calls T13.
            score_block = state.score
            salary_block = state.salary
            if isinstance(score_block, Score) and isinstance(salary_block, SalaryEstimate):
                mid = (salary_block.low + salary_block.high) // 2
                ccy = salary_block.currency
                market_name = resolve_market(profile).country_name
                return "growth", await plan_growth(
                    redacted, profile, score_block, mid, ccy, market_name=market_name
                )
            if not isinstance(score_block, Score) and not isinstance(salary_block, SalaryEstimate):
                return "growth", _cascade_failure("growth", _GROWTH_NO_BASELINE)
            if not isinstance(score_block, Score):
                return "growth", _cascade_failure("growth", _GROWTH_NEEDS_SCORE)
            return "growth", _cascade_failure("growth", _GROWTH_NEEDS_SALARY)

        state.statuses["confidence"] = "running"
        state.statuses["growth"] = "running"
        yield state.snapshot()

        final_tasks = [
            asyncio.create_task(_run_confidence()),
            asyncio.create_task(_run_growth()),
        ]
        for i, final_completed in enumerate(asyncio.as_completed(final_tasks)):
            final_stage, final_result = await final_completed
            if final_stage == "confidence":
                conf_result = cast(Confidence | StageFailure, final_result)
                state.confidence = conf_result
                state.statuses["confidence"] = (
                    "done" if isinstance(conf_result, Confidence) else "failed"
                )
            elif final_stage == "growth":
                growth_result = cast(list[GrowthAction] | StageFailure, final_result)
                state.growth = growth_result
                state.statuses["growth"] = "done" if isinstance(growth_result, list) else "failed"
            else:
                obs.emit(
                    None,
                    "pipeline_warn",
                    reason="unknown_final_stage",
                    final_stage=final_stage,
                )
            if i < len(final_tasks) - 1:
                yield state.snapshot()

        obs.emit(None, "pipeline_done", outcome="ok")
        yield state.snapshot()
