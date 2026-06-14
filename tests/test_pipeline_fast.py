"""Fast tests for the L6 pipeline orchestrator (T15).

Every stage worker is monkeypatched on the `gander.pipeline` module namespace
so the tests run with zero network and zero LLM cost. Real stage modules and
the obs subsystem are imported normally.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from ddgs.exceptions import RatelimitException

from gander import obs, pipeline, salary
from gander.errors import StageFailure
from gander.report import render_html
from gander.schemas import (
    Anchor,
    Component,
    ComponentName,
    Confidence,
    CVQualitySignals,
    GrowthAction,
    Profile,
    ProfileItem,
    RedactedCV,
    Report,
    SalaryEstimate,
    Score,
    Source,
)

# ---------- fixture builders (mirrored from test_render.py for isolation) ----------


def _component(name: ComponentName, score: int) -> Component:
    return Component(
        name=name,
        score_0_100=score,
        justification="ok",
        anchor=Anchor(quote="q", section="Work Experience"),
    )


def _profile() -> Profile:
    item = ProfileItem(text="python", anchor=Anchor(quote="Python"))
    return Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="engineer",
        detected_location=None,
        detected_years_experience=5,
    )


def _score() -> Score:
    return Score(
        components=[
            _component("skills", 80),
            _component("experience", 60),
            _component("education", 40),
            _component("soft_signals", 100),
        ]
    )


def _salary() -> SalaryEstimate:
    return SalaryEstimate(
        low=80_000,
        high=120_000,
        currency="CZK",
        period="month",
        sources=[Source(url="https://platy.cz", snippet="median 95k", domain="platy.cz")],
        reasoning="market data",
    )


def _confidence() -> Confidence:
    return Confidence(tier="High", rationale="three sources agree")


def _growth() -> list[GrowthAction]:
    return [
        GrowthAction(
            what="learn rust",
            time_horizon_months=6,
            mechanism="ship a CLI",
            setting="capability_artifact",
            anchor=Anchor(quote="C++ background"),
        )
    ]


def _redacted(text: str = "redacted cv text") -> RedactedCV:
    return RedactedCV(text=text, audit_log=[])


# ---------- monkeypatch helpers ----------


def _patch_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wire every stage to return canned-success values via pipeline imports."""

    async def _ingest_ok(file_bytes: bytes, filename: str) -> str:
        return "raw text"

    def _redact_ok(text: str) -> RedactedCV:
        return _redacted(text=text)

    async def _extract_ok(redacted: RedactedCV) -> Profile:
        return _profile()

    async def _score_ok(redacted: RedactedCV, profile: Profile) -> Score:
        return _score()

    async def _salary_ok(profile: Profile) -> SalaryEstimate:
        return _salary()

    async def _judge_ok(
        sources: list[Source],
        low: int,
        high: int,
        currency: str,
        period: str,
        *,
        cv_quality: CVQualitySignals,
    ) -> Confidence:
        return _confidence()

    async def _growth_ok(
        redacted: RedactedCV,
        profile: Profile,
        score: Score,
        salary_midpoint: int,
        currency: str,
        market_name: str | None = None,
    ) -> list[GrowthAction]:
        return _growth()

    monkeypatch.setattr(pipeline, "extract_text", _ingest_ok)
    monkeypatch.setattr(pipeline, "redact", _redact_ok)
    monkeypatch.setattr(pipeline, "extract_profile", _extract_ok)
    monkeypatch.setattr(pipeline, "score_profile", _score_ok)
    monkeypatch.setattr(pipeline, "estimate_salary", _salary_ok)
    monkeypatch.setattr(pipeline, "judge", _judge_ok)
    monkeypatch.setattr(pipeline, "plan_growth", _growth_ok)


async def _collect(it: Any) -> list[Report]:
    return [r async for r in it]


# ---------- tests ----------


@pytest.mark.fast
def test_profile_failure_cascade_contract_covers_downstream_stages() -> None:
    assert set(pipeline._CASCADE_PROFILE_FAILED) == {
        "score",
        "salary",
        "confidence",
        "growth",
    }
    assert all(pipeline._CASCADE_PROFILE_FAILED.values())


@pytest.mark.fast
async def test_initial_yield_is_all_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_happy_path(monkeypatch)
    reports = await _collect(pipeline.run(b"x", "cv.pdf"))
    initial = reports[0]
    # First yield happens before any work — every block is None.
    assert initial.profile is None
    assert initial.score is None
    assert initial.salary is None
    assert initial.confidence is None
    assert initial.growth is None
    assert initial.redacted_cv_text == ""
    assert all(v == "pending" for v in initial.statuses.values())
    assert initial.total_cost_usd == 0.0
    assert initial.total_latency_ms == 0


@pytest.mark.fast
async def test_happy_path_final_report_fully_populated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)
    reports = await _collect(pipeline.run(b"x", "cv.pdf"))
    final = reports[-1]
    assert isinstance(final.profile, Profile)
    assert isinstance(final.score, Score)
    assert isinstance(final.salary, SalaryEstimate)
    assert isinstance(final.confidence, Confidence)
    assert isinstance(final.growth, list)
    assert all(v == "done" for v in final.statuses.values())
    # Redacted text propagated through L2 (mock redact is identity).
    assert final.redacted_cv_text == "raw text"


@pytest.mark.fast
async def test_pipeline_captures_degraded_ingest_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)

    async def _ingest_with_notice(file_bytes: bytes, filename: str) -> str:
        obs.emit(
            "ingest",
            "vision_budget_fallback_degraded",
            notice="Vision skipped: PDF over budget; used text extraction.",
            reason="page_count=9 max_pages=8",
        )
        return "raw text"

    monkeypatch.setattr(pipeline, "extract_text", _ingest_with_notice)

    reports = await _collect(pipeline.run(b"x", "cv.pdf"))

    assert reports[-1].notices == ["Vision skipped: PDF over budget; used text extraction."]


@pytest.mark.fast
async def test_happy_path_yields_in_expected_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)
    reports = await _collect(pipeline.run(b"x", "cv.pdf"))
    # Statuses progress strictly: every stage starts pending, transitions to
    # running, then done. Assert key transitions are observable in the yield
    # stream rather than asserting exact yield count (concurrent L4a/L4b
    # ordering is non-deterministic).
    profile_statuses = [r.statuses["profile"] for r in reports]
    assert "pending" in profile_statuses
    assert "running" in profile_statuses
    assert profile_statuses[-1] == "done"
    # Score + salary both reach running, then done.
    score_statuses = [r.statuses["score"] for r in reports]
    salary_statuses = [r.statuses["salary"] for r in reports]
    assert "running" in score_statuses and "done" in score_statuses
    assert "running" in salary_statuses and "done" in salary_statuses
    # Confidence + growth same shape.
    assert reports[-1].statuses["confidence"] == "done"
    assert reports[-1].statuses["growth"] == "done"


@pytest.mark.fast
async def test_happy_path_yields_after_redaction_before_profile_extract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)

    reports = await _collect(pipeline.run(b"x", "cv.pdf"))

    intermediate = [
        r
        for r in reports
        if r.statuses["profile"] == "running"
        and r.redacted_cv_text == "raw text"
        and r.profile is None
    ]
    assert intermediate


@pytest.mark.fast
async def test_ingest_failure_short_circuits_and_cascades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)

    async def _ingest_fail(file_bytes: bytes, filename: str) -> StageFailure:
        return StageFailure(stage="ingest", user_message="Cannot read PDF")

    monkeypatch.setattr(pipeline, "extract_text", _ingest_fail)
    reports = await _collect(pipeline.run(b"x", "cv.pdf"))
    final = reports[-1]
    # Ingest failure surfaces on the profile block (T14 mapping).
    assert isinstance(final.profile, StageFailure)
    assert "Cannot read PDF" in final.profile.user_message
    assert final.statuses["profile"] == "failed"
    # Downstream cascaded as StageFailure with the cascade message.
    for block in (final.score, final.salary, final.confidence, final.growth):
        assert isinstance(block, StageFailure)
    for stage in ("score", "salary", "confidence", "growth"):
        assert final.statuses[stage] == "failed"  # type: ignore[index]


@pytest.mark.fast
async def test_redact_failure_short_circuits_and_cascades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)

    def _redact_fail(text: str) -> StageFailure:
        return StageFailure(stage="redact", user_message="Empty document")

    monkeypatch.setattr(pipeline, "redact", _redact_fail)
    reports = await _collect(pipeline.run(b"x", "cv.pdf"))
    final = reports[-1]
    assert isinstance(final.profile, StageFailure)
    assert "Empty document" in final.profile.user_message
    assert final.statuses["profile"] == "failed"
    for block in (final.score, final.salary, final.confidence, final.growth):
        assert isinstance(block, StageFailure)


@pytest.mark.fast
async def test_profile_failure_cascades_with_specific_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)

    async def _extract_fail(redacted: RedactedCV) -> StageFailure:
        return StageFailure(stage="profile", user_message="LLM returned garbage")

    monkeypatch.setattr(pipeline, "extract_profile", _extract_fail)
    reports = await _collect(pipeline.run(b"x", "cv.pdf"))
    final = reports[-1]
    assert isinstance(final.profile, StageFailure)
    # Each downstream stage carries its specific cascade message.
    assert isinstance(final.score, StageFailure)
    assert "without profile extraction" in final.score.user_message
    assert isinstance(final.salary, StageFailure)
    assert "without profile extraction" in final.salary.user_message
    assert isinstance(final.confidence, StageFailure)
    assert isinstance(final.growth, StageFailure)


@pytest.mark.fast
async def test_salary_failure_short_circuits_confidence_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)
    judge_called = False

    async def _salary_fail(profile: Profile) -> StageFailure:
        return StageFailure(stage="salary", user_message="Insufficient market data")

    async def _judge_should_not_run(
        sources: list[Source], low: int, high: int, currency: str, period: str
    ) -> Confidence:
        nonlocal judge_called
        judge_called = True
        return _confidence()

    monkeypatch.setattr(pipeline, "estimate_salary", _salary_fail)
    monkeypatch.setattr(pipeline, "judge", _judge_should_not_run)
    reports = await _collect(pipeline.run(b"x", "cv.pdf"))
    final = reports[-1]
    # Salary failed.
    assert isinstance(final.salary, StageFailure)
    # Confidence short-circuited to Low, no LLM call.
    assert isinstance(final.confidence, Confidence)
    assert final.confidence.tier == "Low"
    assert "Insufficient market data" in final.confidence.rationale
    assert judge_called is False
    # Score still ran (parallel with salary), so growth can use it… but Decision
    # A in the T15 plan requires BOTH score AND salary. Growth cascades.
    assert isinstance(final.growth, StageFailure)


@pytest.mark.fast
async def test_salary_ratelimit_degrades_only_salary_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PRD §4.6: a rate-limited salary search degrades only the salary block.

    Runs the REAL estimate_salary against a DDG stub that always rate-limits;
    every other stage stays canned-success. The rendered body must carry the
    rate-limit copy in the salary block while score renders real content and
    growth degrades with its cascade copy instead of crashing the report.
    """
    _patch_happy_path(monkeypatch)
    monkeypatch.setattr(pipeline, "estimate_salary", salary.estimate_salary)

    def _ratelimited_ddg(query: str, timeout_s: float | None = None) -> list[dict[str, Any]]:
        raise RatelimitException("202 rate limit")

    monkeypatch.setattr(salary, "_ddg_text", _ratelimited_ddg)

    reports = await _collect(pipeline.run(b"x", "cv.pdf"))
    final = reports[-1]

    assert isinstance(final.salary, StageFailure)
    assert final.statuses["salary"] == "failed"
    assert final.statuses["score"] == "done"

    body = render_html(final)
    assert "temporarily rate-limited" in body
    assert "Overall score" in body
    assert "Confidence" in body
    assert "Plan" in body
    assert "Cannot generate growth plan without salary baseline" in body


@pytest.mark.fast
async def test_score_failure_cascades_growth_without_calling_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)
    growth_called = False

    async def _score_fail(redacted: RedactedCV, profile: Profile) -> StageFailure:
        return StageFailure(stage="score", user_message="Scoring failed")

    async def _growth_should_not_run(*args: Any, **kwargs: Any) -> list[GrowthAction]:
        nonlocal growth_called
        growth_called = True
        return _growth()

    monkeypatch.setattr(pipeline, "score_profile", _score_fail)
    monkeypatch.setattr(pipeline, "plan_growth", _growth_should_not_run)
    reports = await _collect(pipeline.run(b"x", "cv.pdf"))
    final = reports[-1]
    assert isinstance(final.score, StageFailure)
    # Salary succeeded but growth cascades per Decision A.
    assert isinstance(final.salary, SalaryEstimate)
    assert isinstance(final.growth, StageFailure)
    assert "without scoring" in final.growth.user_message
    assert growth_called is False


@pytest.mark.fast
async def test_score_and_salary_both_fail_growth_uses_combined_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)

    async def _score_fail(redacted: RedactedCV, profile: Profile) -> StageFailure:
        return StageFailure(stage="score", user_message="Scoring failed")

    async def _salary_fail(profile: Profile) -> StageFailure:
        return StageFailure(stage="salary", user_message="Search failed")

    monkeypatch.setattr(pipeline, "score_profile", _score_fail)
    monkeypatch.setattr(pipeline, "estimate_salary", _salary_fail)
    reports = await _collect(pipeline.run(b"x", "cv.pdf"))
    final = reports[-1]
    assert isinstance(final.score, StageFailure)
    assert isinstance(final.salary, StageFailure)
    # Confidence short-circuits to Low when salary failed.
    assert isinstance(final.confidence, Confidence)
    assert final.confidence.tier == "Low"
    # Growth uses the "no baseline" message (both upstream failed).
    assert isinstance(final.growth, StageFailure)
    assert "scoring or salary" in final.growth.user_message


@pytest.mark.fast
async def test_prd_observability_counters_visible_on_golden_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)
    events: list[dict[str, Any]] = []

    async def _extract_emit(redacted: RedactedCV) -> Profile:
        obs.emit("extract", "verify", kept=3, dropped=1)
        return _profile()

    async def _salary_emit(profile: Profile) -> SalaryEstimate:
        obs.emit("salary", "salary_search", raw_results=4, dedup_results=3)
        return _salary()

    async def _judge_emit(
        sources: list[Source],
        low: int,
        high: int,
        currency: str,
        period: str,
        *,
        cv_quality: CVQualitySignals,
    ) -> Confidence:
        obs.emit("confidence", "confidence_decision", tier="High")
        return _confidence()

    monkeypatch.setattr(pipeline, "extract_profile", _extract_emit)
    monkeypatch.setattr(pipeline, "estimate_salary", _salary_emit)
    monkeypatch.setattr(pipeline, "judge", _judge_emit)

    with obs.subscribe(events.append):
        await _collect(pipeline.run(b"x", "cv.pdf"))

    event_names = {event["event"] for event in events}
    assert {"verify", "salary_search", "confidence_decision"} <= event_names


@pytest.mark.fast
async def test_run_id_correlates_all_events_in_one_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)
    events: list[dict[str, Any]] = []

    with obs.subscribe(events.append):
        await _collect(pipeline.run(b"x", "cv.pdf"))

    run_ids = {e["run_id"] for e in events}
    assert len(run_ids) == 1
    only = run_ids.pop()
    assert isinstance(only, str) and only  # a non-empty uuid string
    # The contextvar is reset after the run completes.
    assert obs.current_run_id.get() is None


@pytest.mark.fast
async def test_run_id_present_on_stage_boundary_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stronger than the correlation test above: the happy-path stubs are
    obs-silent, so that test only ever sees pipeline_start/pipeline_done. Here
    the stage stubs emit the same counter events the golden-run test checks, so
    we prove the actual stage events (verify / salary_search /
    confidence_decision) carry the one non-None run_id — not just the
    orchestrator's own bookend events."""
    _patch_happy_path(monkeypatch)
    events: list[dict[str, Any]] = []

    async def _extract_emit(redacted: RedactedCV) -> Profile:
        obs.emit("extract", "verify", kept=3, dropped=1)
        return _profile()

    async def _salary_emit(profile: Profile) -> SalaryEstimate:
        obs.emit("salary", "salary_search", raw_results=4, dedup_results=3)
        return _salary()

    async def _judge_emit(
        sources: list[Source],
        low: int,
        high: int,
        currency: str,
        period: str,
        *,
        cv_quality: CVQualitySignals,
    ) -> Confidence:
        obs.emit("confidence", "confidence_decision", tier="High")
        return _confidence()

    monkeypatch.setattr(pipeline, "extract_profile", _extract_emit)
    monkeypatch.setattr(pipeline, "estimate_salary", _salary_emit)
    monkeypatch.setattr(pipeline, "judge", _judge_emit)

    with obs.subscribe(events.append):
        await _collect(pipeline.run(b"x", "cv.pdf"))

    stage_events = {"verify", "salary_search", "confidence_decision"}
    seen = {e["event"] for e in events}
    assert stage_events <= seen, f"missing stage events: {stage_events - seen}"

    # Every event from those stages shares one non-None run_id.
    stage_run_ids = {e["run_id"] for e in events if e["event"] in stage_events}
    assert len(stage_run_ids) == 1
    only = stage_run_ids.pop()
    assert isinstance(only, str) and only
    # And the bookend events agree with the stage events.
    assert {e["run_id"] for e in events} == {only}


@pytest.mark.fast
async def test_run_id_resets_after_partial_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Gradio cancel path calls aclose() on the generator, which unwinds it
    mid-run. Breaking iteration early must still trigger run_scope's finally and
    reset current_run_id — otherwise a cancelled run leaks its id into the next
    run reusing the same context."""
    _patch_happy_path(monkeypatch)

    agen = pipeline.run(b"x", "cv.pdf")
    first = await agen.__anext__()
    assert first is not None
    # Mid-run the contextvar may be set; the contract is that it clears on close.
    await agen.aclose()
    assert obs.current_run_id.get() is None


@pytest.mark.fast
async def test_run_ids_differ_across_separate_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)
    events: list[dict[str, Any]] = []

    with obs.subscribe(events.append):
        await _collect(pipeline.run(b"x", "cv.pdf"))
        first_run_ids = {e["run_id"] for e in events}
        events.clear()
        await _collect(pipeline.run(b"x", "cv.pdf"))
        second_run_ids = {e["run_id"] for e in events}

    assert first_run_ids.isdisjoint(second_run_ids)


@pytest.mark.fast
async def test_cost_and_latency_accumulate_from_obs_emit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)

    # Stages that emit fake llm_call events while running. The pipeline
    # subscribes inside run() so these events should sum into the final
    # report's total_cost_usd / total_latency_ms.
    async def _score_emit(redacted: RedactedCV, profile: Profile) -> Score:
        obs.emit("score", "llm_call", usd_cost=0.01, duration_ms=100)
        return _score()

    async def _salary_emit(profile: Profile) -> SalaryEstimate:
        obs.emit("salary", "llm_call", usd_cost=0.02, duration_ms=200)
        return _salary()

    async def _judge_emit(
        sources: list[Source],
        low: int,
        high: int,
        currency: str,
        period: str,
        *,
        cv_quality: CVQualitySignals,
    ) -> Confidence:
        obs.emit("confidence", "llm_call", usd_cost=0.005, duration_ms=50)
        return _confidence()

    monkeypatch.setattr(pipeline, "score_profile", _score_emit)
    monkeypatch.setattr(pipeline, "estimate_salary", _salary_emit)
    monkeypatch.setattr(pipeline, "judge", _judge_emit)

    reports = await _collect(pipeline.run(b"x", "cv.pdf"))
    final = reports[-1]
    assert final.total_cost_usd == pytest.approx(0.035)
    assert final.total_latency_ms == 350
    assert final.wall_clock_ms >= 0


@pytest.mark.fast
async def test_wall_clock_is_distinct_from_summed_provider_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)

    async def _score_emit(redacted: RedactedCV, profile: Profile) -> Score:
        await asyncio.sleep(0.02)
        obs.emit("score", "llm_call", usd_cost=0.01, duration_ms=1000)
        return _score()

    async def _salary_emit(profile: Profile) -> SalaryEstimate:
        await asyncio.sleep(0.02)
        obs.emit("salary", "llm_call", usd_cost=0.02, duration_ms=1000)
        return _salary()

    monkeypatch.setattr(pipeline, "score_profile", _score_emit)
    monkeypatch.setattr(pipeline, "estimate_salary", _salary_emit)

    final = (await _collect(pipeline.run(b"x", "cv.pdf")))[-1]

    assert final.total_latency_ms == 2000
    assert 0 <= final.wall_clock_ms < final.total_latency_ms


@pytest.mark.fast
async def test_score_and_salary_run_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Salary sleeps 1ms, score sleeps 50ms. If the pipeline ran them
    # sequentially, total wall time would be ≥51ms. With as_completed, salary
    # should yield first AND wall time should be ≈50ms (the slower of the two).
    _patch_happy_path(monkeypatch)
    score_done_at = 0.0
    salary_done_at = 0.0
    t0 = asyncio.get_event_loop().time()

    async def _slow_score(redacted: RedactedCV, profile: Profile) -> Score:
        nonlocal score_done_at
        await asyncio.sleep(0.05)
        score_done_at = asyncio.get_event_loop().time() - t0
        return _score()

    async def _fast_salary(profile: Profile) -> SalaryEstimate:
        nonlocal salary_done_at
        await asyncio.sleep(0.001)
        salary_done_at = asyncio.get_event_loop().time() - t0
        return _salary()

    monkeypatch.setattr(pipeline, "score_profile", _slow_score)
    monkeypatch.setattr(pipeline, "estimate_salary", _fast_salary)

    reports = await _collect(pipeline.run(b"x", "cv.pdf"))
    # Salary completed before score.
    assert salary_done_at < score_done_at
    # Find the yield where salary first became "done"; at that point score
    # should still be "running" (proves concurrent fan-out, not sequential).
    salary_done_idx = next(i for i, r in enumerate(reports) if r.statuses["salary"] == "done")
    assert reports[salary_done_idx].statuses["score"] == "running"


@pytest.mark.fast
async def test_confidence_and_growth_run_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)
    confidence_done_at = 0.0
    growth_done_at = 0.0
    t0 = asyncio.get_event_loop().time()

    async def _slow_judge(
        sources: list[Source],
        low: int,
        high: int,
        currency: str,
        period: str,
        *,
        cv_quality: CVQualitySignals,
    ) -> Confidence:
        nonlocal confidence_done_at
        await asyncio.sleep(0.05)
        confidence_done_at = asyncio.get_event_loop().time() - t0
        return _confidence()

    async def _fast_growth(
        redacted: RedactedCV,
        profile: Profile,
        score: Score,
        salary_midpoint: int,
        currency: str,
        market_name: str | None = None,
    ) -> list[GrowthAction]:
        nonlocal growth_done_at
        await asyncio.sleep(0.001)
        growth_done_at = asyncio.get_event_loop().time() - t0
        return _growth()

    monkeypatch.setattr(pipeline, "judge", _slow_judge)
    monkeypatch.setattr(pipeline, "plan_growth", _fast_growth)

    reports = await _collect(pipeline.run(b"x", "cv.pdf"))

    assert growth_done_at < confidence_done_at
    growth_done_idx = next(i for i, r in enumerate(reports) if r.statuses["growth"] == "done")
    assert reports[growth_done_idx].statuses["confidence"] == "running"


@pytest.mark.fast
async def test_pipeline_done_emits_once_at_terminal_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)
    events: list[dict[str, Any]] = []

    with obs.subscribe(events.append):
        reports = await _collect(pipeline.run(b"x", "cv.pdf"))

    done_events = [e for e in events if e["event"] == "pipeline_done"]
    assert len(done_events) == 1
    assert done_events[0]["outcome"] == "ok"
    assert all(v != "running" for v in reports[-1].statuses.values())


@pytest.mark.fast
async def test_every_yield_is_a_valid_report_with_all_status_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)
    reports = await _collect(pipeline.run(b"x", "cv.pdf"))
    # Schema validators run inside Report construction, so this is implicit;
    # explicit assertion documents the streaming contract for T18.
    for r in reports:
        assert isinstance(r, Report)
        assert set(r.statuses.keys()) == {
            "profile",
            "score",
            "salary",
            "confidence",
            "growth",
        }


@pytest.mark.fast
async def test_final_report_has_no_running_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # T18 contract: when the iterator is exhausted, no stage is left in the
    # "running" state. Either done, failed, or pending (skipped is reserved).
    _patch_happy_path(monkeypatch)
    reports = await _collect(pipeline.run(b"x", "cv.pdf"))
    final = reports[-1]
    assert all(v != "running" for v in final.statuses.values())


@pytest.mark.fast
async def test_cancel_propagates_into_inflight_l4_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A2 regression: Gradio's `cancels=[run_event]` aborts the pipeline by
    # raising GeneratorExit at the suspended `yield`. That alone does NOT cancel
    # the L4a/L4b stage tasks spawned via asyncio.create_task — they would keep
    # spending LLM budget headless. The loop's `finally` must cancel the sibling
    # that is still in flight.
    _patch_happy_path(monkeypatch)
    score_started = asyncio.Event()
    score_cancelled = False

    async def _hanging_score(redacted: RedactedCV, profile: Profile) -> Score:
        nonlocal score_cancelled
        score_started.set()
        try:
            await asyncio.Event().wait()  # never resolves; only cancellation ends it
        except asyncio.CancelledError:
            score_cancelled = True
            raise
        return _score()  # unreachable

    async def _fast_salary(profile: Profile) -> SalaryEstimate:
        return _salary()

    monkeypatch.setattr(pipeline, "score_profile", _hanging_score)
    monkeypatch.setattr(pipeline, "estimate_salary", _fast_salary)

    gen = pipeline.run(b"x", "cv.pdf")
    # Drive until salary has completed but score is still hanging — the generator
    # is now suspended at the post-salary `yield`, score_task still pending.
    async for report in gen:
        if report.statuses["salary"] == "done" and report.statuses["score"] == "running":
            break
    assert score_started.is_set()

    # Simulate the UI cancel. A clean aclose() (no RuntimeError) also proves the
    # generator does not try to `yield` while handling GeneratorExit.
    await gen.aclose()
    assert score_cancelled


@pytest.mark.fast
async def test_cancel_propagates_into_inflight_final_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same A2 guarantee for the L4c/L5 (confidence/growth) fan-out.
    _patch_happy_path(monkeypatch)
    judge_started = asyncio.Event()
    judge_cancelled = False

    async def _hanging_judge(
        sources: list[Source],
        low: int,
        high: int,
        currency: str,
        period: str,
        *,
        cv_quality: CVQualitySignals,
    ) -> Confidence:
        nonlocal judge_cancelled
        judge_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            judge_cancelled = True
            raise
        return _confidence()  # unreachable

    async def _fast_growth(
        redacted: RedactedCV,
        profile: Profile,
        score: Score,
        salary_midpoint: int,
        currency: str,
        market_name: str | None = None,
    ) -> list[GrowthAction]:
        return _growth()

    monkeypatch.setattr(pipeline, "judge", _hanging_judge)
    monkeypatch.setattr(pipeline, "plan_growth", _fast_growth)

    gen = pipeline.run(b"x", "cv.pdf")
    async for report in gen:
        if report.statuses["growth"] == "done" and report.statuses["confidence"] == "running":
            break
    assert judge_started.is_set()

    await gen.aclose()
    assert judge_cancelled
