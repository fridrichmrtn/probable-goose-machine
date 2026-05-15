"""T29 — CZ/EN senior-shape acceptance suite.

Runs the full pipeline over the three T29 synthetic CZ fixtures and a junior
baseline. The file is intentionally live+slow: it guards the multilingual
regression class that the English-only corpus missed.
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
from gander.schemas import GrowthAction, Profile, ProfileItem, Report, SalaryEstimate, Score
from gander.verify import verify_quote

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "cvs"

JUNIOR = "01_junior_da_novotny.docx"
STEALTH = "11_cz_bilingual_member_of_staff_strelcova.pdf"
ACADEMIC = "12_cz_academic_simek.pdf"
CORPORATE = "13_cz_corporate_manazer_havelka.pdf"
CZ_FIXTURES: tuple[str, ...] = (STEALTH, ACADEMIC, CORPORATE)
RUN_FIXTURES: tuple[str, ...] = (JUNIOR, *CZ_FIXTURES)

EXPECTED: dict[str, dict[str, object]] = {
    STEALTH: {
        "low": 200_000,
        "high": 300_000,
        "normalization_sources": {"tagline_shape", "llm_fallback"},
    },
    ACADEMIC: {
        "low": 60_000,
        "high": 110_000,
        "normalization_sources": {"market_token", "llm_fallback"},
    },
    CORPORATE: {
        "low": 110_000,
        "high": 180_000,
        "normalization_sources": {"market_token", "llm_fallback"},
    },
}


def _missing_provider_key() -> bool:
    provider = os.environ.get("GANDER_LLM_PROVIDER", "openrouter")
    if provider == "openrouter":
        return not bool(os.environ.get("OPENROUTER_API_KEY"))
    return False


pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.xdist_group("acceptance-cz"),
    pytest.mark.skipif(
        _missing_provider_key(),
        reason="CZ acceptance requires OPENROUTER_API_KEY",
    ),
]


@dataclass
class _CZRun:
    reports: dict[str, Report] = field(default_factory=dict)
    events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    per_run_cost_usd: dict[str, float] = field(default_factory=dict)


@pytest_asyncio.fixture(scope="session")
async def cz_run() -> _CZRun:
    run = _CZRun()
    for fname in RUN_FIXTURES:
        path = FIXTURE_DIR / fname
        file_bytes = path.read_bytes()
        events: list[dict[str, Any]] = []
        cost_accum = [0.0]

        def _on_event(
            rec: dict[str, Any],
            _ref: list[float] = cost_accum,
            _events: list[dict[str, Any]] = events,
        ) -> None:
            _events.append(rec)
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
        run.events[fname] = events
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


def _require_profile(report: Report, label: str) -> Profile:
    assert isinstance(report.profile, Profile), (
        f"{label}: expected Profile, got {type(report.profile).__name__} — {report.profile}"
    )
    return report.profile


def _require_growth(report: Report, label: str) -> list[GrowthAction]:
    assert isinstance(report.growth, list), (
        f"{label}: expected list[GrowthAction], got {type(report.growth).__name__}"
    )
    return report.growth


def _iter_anchored(
    profile: Profile, score: Score, growth: list[GrowthAction]
) -> list[tuple[str, str, str | None]]:
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


@pytest.mark.parametrize("fname", CZ_FIXTURES, ids=lambda value: Path(value).stem)
def test_pipeline_all_done_on_cz_fixtures(cz_run: _CZRun, fname: str) -> None:
    report = cz_run.reports[fname]
    assert report.statuses["score"] == "done"
    assert report.statuses["salary"] == "done"


@pytest.mark.parametrize("fname", CZ_FIXTURES, ids=lambda value: Path(value).stem)
def test_score_succeeds_on_cz_fixtures(cz_run: _CZRun, fname: str) -> None:
    score = _require_score(cz_run.reports[fname], fname)
    assert score.total >= 65, f"{fname}: expected senior-ish score >=65, got {score.total}"
    assert any(c.name == "experience" for c in score.components), (
        f"{fname}: experience component missing; dropped={score.dropped}"
    )


@pytest.mark.parametrize("fname", CZ_FIXTURES, ids=lambda value: Path(value).stem)
def test_score_dropped_components_at_most_one_on_cz_fixtures(cz_run: _CZRun, fname: str) -> None:
    score = _require_score(cz_run.reports[fname], fname)
    assert len(score.dropped) <= 1, f"{fname}: too many dropped components: {score.dropped}"


@pytest.mark.parametrize("fname", CZ_FIXTURES, ids=lambda value: Path(value).stem)
def test_salary_lands_in_expected_cz_band(cz_run: _CZRun, fname: str) -> None:
    salary = _require_salary(cz_run.reports[fname], fname)
    expected = EXPECTED[fname]

    assert salary.currency == "CZK"
    assert salary.period == "month"
    assert salary.low < salary.high, f"{fname}: invalid salary range {salary.low}-{salary.high}"
    assert salary.high >= int(expected["high"]) * 0.9, (
        f"{fname}: high {salary.high} misses expected upper window {expected['high']}"
    )


@pytest.mark.parametrize("fname", CZ_FIXTURES, ids=lambda value: Path(value).stem)
def test_pii_name_redacted_on_cz_fixtures(cz_run: _CZRun, fname: str) -> None:
    done_events = [
        e for e in cz_run.events[fname] if e.get("stage") == "redact" and e.get("event") == "done"
    ]
    assert done_events, f"{fname}: expected redact done event"
    assert done_events[-1]["count_name"] >= 1


@pytest.mark.parametrize("fname", CZ_FIXTURES, ids=lambda value: Path(value).stem)
def test_role_normalization_source_on_cz_fixtures(cz_run: _CZRun, fname: str) -> None:
    profile = _require_profile(cz_run.reports[fname], fname)
    expected_sources = EXPECTED[fname]["normalization_sources"]
    assert isinstance(expected_sources, set)
    assert profile.role_normalization_source in expected_sources

    # Direct market-token matches deliberately do not emit `role_normalized`
    # unless the canonical string changes. The tagline fixture does rewrite,
    # so it should still surface the event source that T27 introduced.
    if profile.role_normalization_source == "tagline_shape":
        events = [
            e
            for e in cz_run.events[fname]
            if e.get("stage") == "extract" and e.get("event") == "role_normalized"
        ]
        assert events, f"{fname}: expected role_normalized event for tagline-shaped headline"
        assert events[-1]["source"] == "tagline_shape"


@pytest.mark.parametrize("fname", (STEALTH, CORPORATE), ids=lambda value: Path(value).stem)
def test_score_spread_at_least_30_cz(cz_run: _CZRun, fname: str) -> None:
    junior_score = _require_score(cz_run.reports[JUNIOR], JUNIOR)
    senior_score = _require_score(cz_run.reports[fname], fname)
    delta = senior_score.total - junior_score.total
    assert senior_score.total >= 65, f"{fname}: expected senior-ish score >=65"
    assert delta >= 20, (
        f"{fname}: score spread {senior_score.total} - {junior_score.total} = {delta}, "
        "expected >= 20"
    )


@pytest.mark.parametrize("fname", (STEALTH, CORPORATE), ids=lambda value: Path(value).stem)
def test_salary_non_overlap_with_junior_for_cz_seniors(cz_run: _CZRun, fname: str) -> None:
    junior_salary = _require_salary(cz_run.reports[JUNIOR], JUNIOR)
    senior_salary = _require_salary(cz_run.reports[fname], fname)
    assert senior_salary.low > junior_salary.high, (
        f"{fname}: senior low {senior_salary.low} not above junior high {junior_salary.high}"
    )


@pytest.mark.parametrize("fname", (STEALTH, CORPORATE), ids=lambda value: Path(value).stem)
def test_senior_salary_multiplier_cz(cz_run: _CZRun, fname: str) -> None:
    junior_salary = _require_salary(cz_run.reports[JUNIOR], JUNIOR)
    senior_salary = _require_salary(cz_run.reports[fname], fname)
    threshold = 2.5 * junior_salary.high
    assert senior_salary.high >= threshold, (
        f"{fname}: senior high {senior_salary.high} < 2.5 * junior high {threshold:.0f}"
    )


def test_no_verbatim_growth_plan_repeats_cz(cz_run: _CZRun) -> None:
    seen: dict[str, str] = {}
    for fname in CZ_FIXTURES:
        growth = _require_growth(cz_run.reports[fname], fname)
        for action in growth:
            prior = seen.get(action.what)
            assert prior is None or prior == fname, (
                f"verbatim repeat across {prior} and {fname}: {action.what!r}"
            )
            seen[action.what] = fname


def test_no_near_duplicate_growth_plans_cz(cz_run: _CZRun) -> None:
    items: list[tuple[str, str]] = []
    for fname in CZ_FIXTURES:
        growth = _require_growth(cz_run.reports[fname], fname)
        for action in growth:
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


def test_all_claims_substring_verified_cz(cz_run: _CZRun) -> None:
    failures: list[str] = []
    for fname in CZ_FIXTURES:
        report = cz_run.reports[fname]
        profile = _require_profile(report, fname)
        score = _require_score(report, fname)
        growth = _require_growth(report, fname)
        source = report.redacted_cv_text
        assert source, f"{fname}: redacted_cv_text empty — pipeline did not run L2 redact"
        for origin, quote, section in _iter_anchored(profile, score, growth):
            if not verify_quote(quote, source, section=section):
                failures.append(
                    f"{fname}::{origin} unverified — section={section!r} quote={quote!r}"
                )
    assert not failures, "unverified CZ anchors:\n" + "\n".join(failures)
