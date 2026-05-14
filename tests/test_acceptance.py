"""T30 Phase 1 — §5.4 differentiation acceptance suite (EN triplet).

Runs the full L1→L5 pipeline once per fixture in the EN triplet
(junior / mid / senior) and asserts the cross-CV invariants PRD §5.4 names:
score spread, salary non-overlap, salary multiplier, growth-plan dedup,
substring-verified claims, per-run cost budget.

Marked `live, slow` — the session-scoped fixture pays the LLM cost once and
every test queries the cached `Report` dict. CI live job picks these up via
`pytest -m live`; no path-filter exclusion (prompt edits also regress these).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from gander import obs, pipeline
from gander.growth import _jaccard_4gram
from gander.schemas import (
    GrowthAction,
    Profile,
    ProfileItem,
    Report,
    SalaryEstimate,
    Score,
)
from gander.verify import verify_quote

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "cvs"

JUNIOR = "01_junior_da_novotny.docx"
MID = "03_ds_horak.pdf"
SENIOR = "08_staff_ml_engineer_dvorak.pdf"
TRIPLET: tuple[str, ...] = (JUNIOR, MID, SENIOR)


pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    # Pin all 7 tests + the session-scoped fixture to one xdist worker so the
    # 3-CV pipeline runs once per file rather than once per worker. Without
    # this, `-n 4 --dist=loadgroup` would multiply the LLM bill by 4x.
    pytest.mark.xdist_group("acceptance"),
]


@dataclass
class _TripletRun:
    reports: dict[str, Report] = field(default_factory=dict)
    per_run_cost_usd: dict[str, float] = field(default_factory=dict)


@pytest_asyncio.fixture(scope="session")
async def triplet() -> _TripletRun:
    """Run the pipeline once per triplet CV and cache the final Report + per-CV cost.

    Costs ~3× a single-pipeline run. Every test reads from the same cache,
    so the LLM bill scales with the triplet size, not the test count.
    """
    run = _TripletRun()
    for fname in TRIPLET:
        path = FIXTURE_DIR / fname
        file_bytes = path.read_bytes()
        cost_accum = [0.0]

        def _on_event(rec: dict[str, Any], _ref: list[float] = cost_accum) -> None:
            if rec.get("event") != "llm_call":
                return
            usd = rec.get("usd_cost")
            if isinstance(usd, int | float):
                _ref[0] += float(usd)

        final: Report | None = None
        with obs.subscribe(_on_event):
            async for snap in pipeline.run(file_bytes, fname):
                final = snap
        assert final is not None, f"pipeline.run yielded zero reports for {fname}"
        run.reports[fname] = final
        run.per_run_cost_usd[fname] = cost_accum[0]
    return run


def _require_score(report: Report, label: str) -> Score:
    assert isinstance(report.score, Score), (
        f"{label}: expected Score, got {type(report.score).__name__} — {report.score}"
    )
    return report.score


def _require_salary(report: Report, label: str) -> SalaryEstimate:
    assert isinstance(report.salary, SalaryEstimate), (
        f"{label}: expected SalaryEstimate, got {type(report.salary).__name__} — {report.salary}"
    )
    return report.salary


def _require_growth(report: Report, label: str) -> list[GrowthAction]:
    assert isinstance(report.growth, list), (
        f"{label}: expected list[GrowthAction], got {type(report.growth).__name__}"
    )
    return report.growth


def _require_profile(report: Report, label: str) -> Profile:
    assert isinstance(report.profile, Profile), (
        f"{label}: expected Profile, got {type(report.profile).__name__}"
    )
    return report.profile


def test_score_spread_at_least_30(triplet: _TripletRun) -> None:
    junior = _require_score(triplet.reports[JUNIOR], "junior")
    senior = _require_score(triplet.reports[SENIOR], "senior")
    delta = senior.total - junior.total
    assert delta >= 30, f"score spread {senior.total} - {junior.total} = {delta}, expected >= 30"


def test_salary_ranges_dont_overlap(triplet: _TripletRun) -> None:
    junior = _require_salary(triplet.reports[JUNIOR], "junior")
    senior = _require_salary(triplet.reports[SENIOR], "senior")
    assert senior.low > junior.high, (
        f"salary overlap: senior.low={senior.low} not > junior.high={junior.high}"
    )


def test_senior_multiplier_at_least_2_5x(triplet: _TripletRun) -> None:
    """Catches the 'senior collapsed to mid band' regression that pure non-overlap allows."""
    junior = _require_salary(triplet.reports[JUNIOR], "junior")
    senior = _require_salary(triplet.reports[SENIOR], "senior")
    threshold = 2.5 * junior.high
    assert senior.high >= threshold, (
        f"senior multiplier: senior.high={senior.high} < 2.5 * junior.high={threshold:.0f}"
    )


def test_no_verbatim_growth_plan_repeats(triplet: _TripletRun) -> None:
    seen: dict[str, str] = {}
    for fname in TRIPLET:
        for action in _require_growth(triplet.reports[fname], fname):
            prior = seen.get(action.what)
            assert prior is None or prior == fname, (
                f"verbatim repeat across {prior} and {fname}: {action.what!r}"
            )
            seen[action.what] = fname


def test_no_near_duplicate_growth_plans(triplet: _TripletRun) -> None:
    """Cross-CV 4-gram Jaccard guard against paraphrased boilerplate."""
    items: list[tuple[str, str]] = []
    for fname in TRIPLET:
        for action in _require_growth(triplet.reports[fname], fname):
            items.append((fname, action.what))
    threshold = 0.4
    for i, (fname_a, what_a) in enumerate(items):
        for fname_b, what_b in items[i + 1 :]:
            if fname_a == fname_b:
                continue
            score = _jaccard_4gram(what_a, what_b)
            assert score < threshold, (
                f"near-duplicate growth-plan across {fname_a} / {fname_b}: "
                f"jaccard_4gram={score:.3f} >= {threshold} — {what_a!r} vs {what_b!r}"
            )


def test_no_cross_anchor_repeats(triplet: _TripletRun) -> None:
    """No growth-plan anchor quote appears in more than one CV's plan."""
    anchor_to_cv: dict[str, str] = {}
    for fname in TRIPLET:
        for action in _require_growth(triplet.reports[fname], fname):
            quote = action.anchor.quote
            prior = anchor_to_cv.get(quote)
            assert prior is None or prior == fname, (
                f"growth-plan anchor quote shared between {prior} and {fname}: {quote!r}"
            )
            anchor_to_cv[quote] = fname


def _iter_anchored(
    profile: Profile, score: Score, growth: list[GrowthAction]
) -> list[tuple[str, str, str | None]]:
    """Yield `(origin, quote, section)` for every anchored claim in a Report."""
    out: list[tuple[str, str, str | None]] = []
    for fname in ("skills", "experience", "education", "soft_signals"):
        items: list[ProfileItem] = getattr(profile, fname)
        for item in items:
            out.append((f"profile.{fname}", item.anchor.quote, item.anchor.section))
    for comp in score.components:
        out.append((f"score.{comp.name}", comp.anchor.quote, comp.anchor.section))
    for action in growth:
        out.append(("growth", action.anchor.quote, action.anchor.section))
    return out


def test_all_claims_substring_verified(triplet: _TripletRun) -> None:
    """Every anchor quote on every report must survive `verify_quote` against the source CV."""
    failures: list[str] = []
    for fname in TRIPLET:
        report = triplet.reports[fname]
        profile = _require_profile(report, fname)
        score = _require_score(report, fname)
        growth = _require_growth(report, fname)
        source = report.raw_cv_text
        for origin, quote, section in _iter_anchored(profile, score, growth):
            if not verify_quote(quote, source, section=section):
                failures.append(
                    f"{fname}::{origin} unverified — section={section!r} quote={quote!r}"
                )
    assert not failures, "unverified anchors:\n" + "\n".join(failures)


def test_per_run_cost_budget(triplet: _TripletRun) -> None:
    """Per-pipeline-run USD cost must stay under $0.05 (or $0.02 on the CI profile).

    Today MiniMax-M2.7-highspeed has zeroed `MODEL_PRICES` entries, so
    `usd_cost` is 0.0 on every event and this gate passes vacuously. The
    test still anchors the contract: when pricing lands, the budget bites
    without further code change.
    """
    profile = os.environ.get("GANDER_MODEL_PROFILE", "local")
    budget = 0.02 if profile == "ci" else 0.05
    for fname, cost in triplet.per_run_cost_usd.items():
        assert cost < budget, f"{fname} cost ${cost:.4f} >= ${budget:.2f} (profile={profile})"


def test_pipeline_emits_latency(triplet: _TripletRun) -> None:
    """Sanity: every report carries non-zero `total_latency_ms`.

    If the obs accumulator ever regresses (subscriber not wired, llm_call
    not emitted), the cost-budget test would pass vacuously even when the
    pricing table lands. This gate notices.
    """
    for fname in TRIPLET:
        rep = triplet.reports[fname]
        assert rep.total_latency_ms > 0, (
            f"{fname}: total_latency_ms is {rep.total_latency_ms}, "
            "expected >0 (no LLM calls fired?)"
        )
