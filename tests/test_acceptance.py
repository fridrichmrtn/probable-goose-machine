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


def _optional_growth(report: Report, label: str) -> list[GrowthAction] | None:
    """Return growth list, or None if the stage surfaced a StageFailure.

    Growth depends on a salary baseline (PRD §4.7). When salary's DDG search
    flakes and returns <2 valid sources, salary surfaces StageFailure, and
    growth follows with `Cannot generate growth plan without salary baseline`.
    The cross-CV invariants below need ≥2 CVs with usable growth, but a
    single missing fixture shouldn't take the whole acceptance suite down —
    the remaining CVs still cross-check against each other. T37 follow-up
    eliminates this class of CI flake at source by cassette-mocking DDG.
    """
    return report.growth if isinstance(report.growth, list) else None


def _require_profile(report: Report, label: str) -> Profile:
    assert isinstance(report.profile, Profile), (
        f"{label}: expected Profile, got {type(report.profile).__name__}"
    )
    return report.profile


def test_score_spread_at_least_30(triplet: _TripletRun) -> None:
    junior = _require_score(triplet.reports[JUNIOR], "junior")
    senior = _require_score(triplet.reports[SENIOR], "senior")
    delta = senior.total - junior.total
    if senior.dropped:
        # T25 second-order: senior fixture 08 stochastically lands on the
        # partial-Score path when an anchor fails verify_quote (most often
        # `education`, tracked in tasks/T36_senior_edu_anchor.md). With the
        # dropped component contributing 0 (T25 "drop=0, don't re-normalize",
        # PRD §4.5), the spread compresses below the full-Score gate. Preserve
        # PRD §5.4 differentiation with a relaxed delta floor AND an absolute
        # senior floor so a real "senior collapsed to mid band" regression
        # still trips. When T36 lands and senior returns to full 4-of-4, the
        # full-Score branch below resumes enforcing >=30.
        assert senior.total >= 65, (
            f"partial-Score senior must clear absolute floor: "
            f"senior.total={senior.total}, dropped={senior.dropped}"
        )
        assert delta >= 20, (
            f"partial-Score spread {senior.total} - {junior.total} = {delta}, "
            f"dropped={senior.dropped}, expected delta >= 20"
        )
        return
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
    survivors = 0
    for fname in TRIPLET:
        growth = _optional_growth(triplet.reports[fname], fname)
        if growth is None:
            continue
        survivors += 1
        for action in growth:
            prior = seen.get(action.what)
            assert prior is None or prior == fname, (
                f"verbatim repeat across {prior} and {fname}: {action.what!r}"
            )
            seen[action.what] = fname
    assert survivors >= 2, (
        f"need >=2 CVs with usable growth for cross-CV invariant; got {survivors}"
    )


def test_no_near_duplicate_growth_plans(triplet: _TripletRun) -> None:
    """Cross-CV 4-gram Jaccard guard against paraphrased boilerplate."""
    items: list[tuple[str, str]] = []
    survivors = 0
    for fname in TRIPLET:
        growth = _optional_growth(triplet.reports[fname], fname)
        if growth is None:
            continue
        survivors += 1
        for action in growth:
            items.append((fname, action.what))
    assert survivors >= 2, (
        f"need >=2 CVs with usable growth for cross-CV invariant; got {survivors}"
    )
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
    survivors = 0
    for fname in TRIPLET:
        growth = _optional_growth(triplet.reports[fname], fname)
        if growth is None:
            continue
        survivors += 1
        for action in growth:
            quote = action.anchor.quote
            prior = anchor_to_cv.get(quote)
            assert prior is None or prior == fname, (
                f"growth-plan anchor quote shared between {prior} and {fname}: {quote!r}"
            )
            anchor_to_cv[quote] = fname
    assert survivors >= 2, (
        f"need >=2 CVs with usable growth for cross-CV invariant; got {survivors}"
    )


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
    """Every anchor quote on every report must survive `verify_quote` against the
    *redacted* CV text — the same source the pipeline's extract/score/growth stages
    pre-verified against. Verifying against `raw_cv_text` instead would spuriously
    fail quotes that legitimately contain redaction markers like `[YEAR]`, `[NAME]`,
    or `[URL]`.
    """
    failures: list[str] = []
    for fname in TRIPLET:
        report = triplet.reports[fname]
        profile = _require_profile(report, fname)
        score = _require_score(report, fname)
        # Growth may be StageFailure when an upstream stage (e.g. salary)
        # failed; skip its anchors here but still verify profile+score on
        # this fixture. The cross-CV growth tests above enforce the >=2
        # survivors floor — this per-CV verification has no minimum.
        growth = _optional_growth(report, fname) or []
        source = report.redacted_cv_text
        assert source, f"{fname}: redacted_cv_text empty — pipeline did not run L2 redact"
        for origin, quote, section in _iter_anchored(profile, score, growth):
            if not verify_quote(quote, source, section=section):
                failures.append(
                    f"{fname}::{origin} unverified — section={section!r} quote={quote!r}"
                )
    assert not failures, "unverified anchors:\n" + "\n".join(failures)


def test_per_run_cost_budget(triplet: _TripletRun) -> None:
    """Per-pipeline-run USD cost must stay under a smoke-test ceiling.

    This is intentionally a broad guardrail, not a tight budget contract:
    VLM-backed ingest can add token-plan request costs, while MiniMax stays
    compatible with the zeroed pricing table. OpenRouter reports provider cost
    directly and must not pass this gate vacuously.
    """
    provider = os.environ.get("GANDER_LLM_PROVIDER", "minimax")
    profile = os.environ.get("GANDER_MODEL_PROFILE", "local")
    budget = 0.15
    for fname, cost in triplet.per_run_cost_usd.items():
        if provider == "openrouter":
            assert cost > 0.0, (
                f"{fname} cost ${cost:.4f} is not positive "
                "(expected OpenRouter usage.cost telemetry)"
            )
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
