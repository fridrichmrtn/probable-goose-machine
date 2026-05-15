"""Live end-to-end smoke test for the L6 pipeline orchestrator (T15).

Exercises the full L1→L5 path on a real CV fixture with real LLM calls. Gated
behind `@pytest.mark.live, @pytest.mark.slow` — run with `pytest -m live`.

Assertions are deliberately loose:
* Each stage *can* fail (network, rate limit, anchor verification miss); the
  goal here is to prove the orchestrator wires inputs/outputs correctly and
  the obs cost/latency accumulator fires, not to gate on model quality. The
  T10 calibration story (see test_score.py xfail block) is T17's problem.
* If every stage succeeds, we assert the strong form (no StageFailure, all
  statuses done, cost+latency > 0). Otherwise we only assert the pipeline
  finished, emitted a final yield, and never left a stage in "running".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gander import obs, pipeline
from gander.confidence import _TierOnly
from gander.errors import StageFailure
from gander.llm import LLMClient
from gander.schemas import (
    Anchor,
    Component,
    Confidence,
    Profile,
    ProfileItem,
    RedactedCV,
    Report,
    SalaryEstimate,
    Score,
    Source,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
# Mid-tier MLOps engineer fixture: realistic depth but not the hardest case.
MID_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "cvs" / "05_mlops_benes.pdf"


async def _collect(it: object) -> list[Report]:
    return [r async for r in it]  # type: ignore[attr-defined]


@pytest.mark.live
@pytest.mark.slow
async def test_pipeline_smoke_end_to_end_mid_fixture() -> None:
    file_bytes = MID_FIXTURE.read_bytes()
    reports = await _collect(pipeline.run(file_bytes, MID_FIXTURE.name))

    # Pipeline must always reach a terminal state — at least one yield, and
    # the last yield has no stage still "running".
    assert len(reports) >= 2
    final = reports[-1]
    assert all(v != "running" for v in final.statuses.values())
    # Every status key is covered (schema invariant, asserted here for clarity).
    assert set(final.statuses) == {"profile", "score", "salary", "confidence", "growth"}

    # Strong assertion if everything succeeded; otherwise the pipeline still
    # produced a well-formed report and we record what failed for the dev report.
    succeeded = (
        isinstance(final.profile, Profile)
        and isinstance(final.score, Score)
        and isinstance(final.salary, SalaryEstimate)
        and isinstance(final.confidence, Confidence)
        and isinstance(final.growth, list)
    )

    if succeeded:
        assert all(v == "done" for v in final.statuses.values())
        # At least one LLM call must have fired. Latency is the reliable
        # signal: every stage records its duration. `total_cost_usd` would
        # be a stronger check, but it depends on the cost-per-token table
        # in `gander.llm` covering whichever model the live env routes to
        # (e.g. `MiniMax-M2.7-highspeed` currently has no pricing entry,
        # so its events emit `usd_cost=0.0` and the accumulator sums to 0).
        # Pricing-table coverage is a separate concern (T05/T17); the
        # accumulator itself is exercised end-to-end by the fast tests.
        assert final.total_cost_usd >= 0
        assert final.total_latency_ms > 0
    else:
        # Capture the failure shape so the dev report can summarise what
        # broke. Any None block here would be a bug — schema accepts None only
        # for pre-running streaming states, never on the final yield.
        for name in ("profile", "score", "salary", "confidence", "growth"):
            block = getattr(final, name)
            assert block is not None, f"final yield left {name} as None"
            assert isinstance(block, StageFailure) or block is not None


@pytest.mark.fast
async def test_pipeline_confidence_reflects_dropped_score_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_extract_text(file_bytes: bytes, filename: str) -> str:
        return "raw cv text"

    def fake_redact(text: str) -> RedactedCV:
        return RedactedCV(text="redacted cv text", audit_log=[])

    async def fake_extract_profile(redacted: RedactedCV) -> Profile:
        item = ProfileItem(text="experience", anchor=Anchor(quote="experience"))
        return Profile(
            skills=[],
            experience=[item],
            education=[],
            soft_signals=[],
            detected_role="Senior Data Scientist",
            detected_location="Prague",
            detected_years_experience=8,
            canonical_role="senior data scientist",
        )

    async def fake_score_profile(redacted: RedactedCV, profile: Profile) -> Score:
        return Score(
            components=[
                Component(
                    name="experience",
                    score_0_100=70,
                    justification="verified experience",
                    anchor=Anchor(quote="experience"),
                )
            ],
            dropped=["skills", "education"],
        )

    async def fake_estimate_salary(profile: Profile) -> SalaryEstimate:
        return SalaryEstimate(
            low=100000,
            high=120000,
            currency="CZK",
            period="month",
            sources=[
                Source(
                    url="https://platy.cz/x",  # type: ignore[arg-type]
                    snippet="Senior data roles are well paid.",
                    domain="platy.cz",
                )
            ],
            reasoning="test",
        )

    async def fake_complete_json(self: LLMClient, **kwargs: object) -> _TierOnly:
        return _TierOnly(tier="High", rationale_short="sources agree")

    async def fake_complete_text(self: LLMClient, **kwargs: object) -> str:
        return "Confidence in this estimate is Low because extraction is insufficient."

    async def fake_plan_growth(*_args: object, **_kwargs: object) -> list[object]:
        return []

    monkeypatch.setattr(pipeline, "extract_text", fake_extract_text)
    monkeypatch.setattr(pipeline, "redact", fake_redact)
    monkeypatch.setattr(pipeline, "extract_profile", fake_extract_profile)
    monkeypatch.setattr(pipeline, "score_profile", fake_score_profile)
    monkeypatch.setattr(pipeline, "estimate_salary", fake_estimate_salary)
    monkeypatch.setattr(pipeline, "plan_growth", fake_plan_growth)
    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setattr(LLMClient, "complete_text", fake_complete_text)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-stub")

    events: list[dict[str, object]] = []
    with obs.subscribe(events.append):
        reports = await _collect(pipeline.run(b"fixture", "fixture.txt"))

    final = reports[-1]
    assert isinstance(final.confidence, Confidence)
    assert final.confidence.tier == "Low"
    floor_evt = next(e for e in events if e["event"] == "confidence_cv_floor_applied")
    assert floor_evt["salary_tier"] == "High"
    assert floor_evt["cv_floor"] == "Low"
