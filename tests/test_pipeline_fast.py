"""Fast tests for the L6 pipeline orchestrator (T15).

Every stage worker is monkeypatched on the `gander.pipeline` module namespace
so the tests run with zero network and zero LLM cost. Real stage modules and
the obs subsystem are imported normally.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from gander import obs, pipeline
from gander.errors import StageFailure
from gander.schemas import (
    Anchor,
    Component,
    ComponentName,
    Confidence,
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
            anchor=Anchor(quote="C++ background"),
        )
    ]


def _redacted(text: str = "redacted cv text") -> RedactedCV:
    return RedactedCV(text=text, audit_log=[])


# ---------- monkeypatch helpers ----------


def _patch_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wire every stage to return canned-success values via pipeline imports."""

    def _ingest_ok(file_bytes: bytes, filename: str) -> str:
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
    ) -> Confidence:
        return _confidence()

    async def _growth_ok(
        redacted: RedactedCV,
        profile: Profile,
        score: Score,
        salary_midpoint: int,
        currency: str,
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
    assert initial.raw_cv_text == ""
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
    # Raw text propagated through L1.
    assert final.raw_cv_text == "raw text"


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
async def test_ingest_failure_short_circuits_and_cascades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_happy_path(monkeypatch)

    def _ingest_fail(file_bytes: bytes, filename: str) -> StageFailure:
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
        sources: list[Source], low: int, high: int, currency: str, period: str
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
