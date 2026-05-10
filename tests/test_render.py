"""Fast unit tests for jobfit.report (T14).

Fixtures construct fully-valid Report instances so the schema's validators
are exercised. No I/O, no LLM, no network.
"""

from __future__ import annotations

from typing import Literal, cast

import pytest

from jobfit.errors import StageFailure
from jobfit.report import render_body, render_tracker
from jobfit.schemas import (
    Anchor,
    Component,
    ComponentName,
    Confidence,
    GrowthAction,
    Profile,
    ProfileItem,
    Report,
    SalaryEstimate,
    Score,
    Source,
    StageName,
    StageStatus,
)

# ---------- fixture builders ----------


def _component(name: ComponentName, score: int, *, justification: str = "ok") -> Component:
    return Component(
        name=name,
        score_0_100=score,
        justification=justification,
        anchor=Anchor(quote=f"quote for {name}", section="Work Experience"),
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
        sources=[
            Source(
                url="https://platy.cz/path",
                snippet="median CZK 95k",
                domain="platy.cz",
            ),
            Source(
                url="https://example.com/page",
                snippet="range matches",
                domain="example.com",
            ),
        ],
        reasoning="market data triangulated across two sources",
    )


def _confidence() -> Confidence:
    return Confidence(tier="High", rationale="three sources agree")


def _growth() -> list[GrowthAction]:
    return [
        GrowthAction(
            what="learn rust",
            time_horizon_months=6,
            mechanism="ship a small CLI",
            anchor=Anchor(quote="C++ background"),
        ),
        GrowthAction(
            what="lead a project",
            time_horizon_months=12,
            mechanism="volunteer for cross-team work",
            anchor=Anchor(quote="senior engineer"),
        ),
    ]


def _statuses(**overrides: StageStatus) -> dict[StageName, StageStatus]:
    base: dict[StageName, StageStatus] = {
        "profile": "done",
        "score": "done",
        "salary": "done",
        "confidence": "done",
        "growth": "done",
    }
    for k, v in overrides.items():
        base[cast(StageName, k)] = v
    return base


def _make_report(
    *,
    profile: Profile | StageFailure | None = None,
    score: Score | StageFailure | None = None,
    salary: SalaryEstimate | StageFailure | None = None,
    confidence: Confidence | StageFailure | None = None,
    growth: list[GrowthAction] | StageFailure | None = None,
    statuses: dict[StageName, StageStatus] | None = None,
) -> Report:
    return Report(
        profile=profile if profile is not None else _profile(),
        score=score if score is not None else _score(),
        salary=salary if salary is not None else _salary(),
        confidence=confidence if confidence is not None else _confidence(),
        growth=growth if growth is not None else _growth(),
        statuses=statuses if statuses is not None else _statuses(),
        raw_cv_text="raw cv text",
    )


# ---------- render_tracker ----------


@pytest.mark.fast
def test_render_tracker_emits_five_pills_for_done_report() -> None:
    out = render_tracker(_make_report())
    # Five pill spans, each with the "pill " class prefix.
    assert out.count('<span class="pill ') == 5


@pytest.mark.fast
@pytest.mark.parametrize("status", ["pending", "running", "done", "failed", "skipped"])
def test_render_tracker_pill_class_matches_status(status: StageStatus) -> None:
    # Use score's status slot so we don't have to also coerce the data block
    # type for non-"failed" statuses; for "failed" the data must also be a
    # StageFailure to surface the tooltip.
    if status == "failed":
        report = _make_report(
            score=StageFailure(stage="score", user_message="scoring unavailable"),
            statuses=_statuses(score=status),
        )
    else:
        report = _make_report(statuses=_statuses(score=status))
    out = render_tracker(report)
    # Score is the second pill, label "Score".
    assert f'<span class="pill {status}"' in out
    assert ">Score</span>" in out


@pytest.mark.fast
def test_render_tracker_includes_prefers_reduced_motion_query() -> None:
    out = render_tracker(_make_report())
    assert "prefers-reduced-motion" in out


@pytest.mark.fast
def test_render_tracker_failed_pill_surfaces_user_message_in_tooltip() -> None:
    failure = StageFailure(stage="salary", user_message="Insufficient market data")
    report = _make_report(salary=failure, statuses=_statuses(salary="failed"))
    out = render_tracker(report)
    assert 'title="Insufficient market data"' in out
    # Failed pill carries the failed class.
    assert '<span class="pill failed"' in out


@pytest.mark.fast
def test_render_tracker_escapes_user_message_in_tooltip() -> None:
    # Defence in depth: a StageFailure that somehow carries HTML must not
    # break out of the title attribute.
    failure = StageFailure(
        stage="salary",
        user_message='<script>alert("x")</script>',
    )
    report = _make_report(salary=failure, statuses=_statuses(salary="failed"))
    out = render_tracker(report)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


# ---------- render_body — populated ----------


@pytest.mark.fast
def test_render_body_populated_contains_expected_content() -> None:
    out = render_body(_make_report())
    # Salary block.
    assert "CZK" in out
    assert "80,000" in out and "120,000" in out
    # Score total (80*0.35 + 60*0.30 + 40*0.20 + 100*0.15 = 69).
    assert "69" in out
    # All four component display names render in the table headers.
    for label in ("Skills", "Experience", "Education", "Soft"):
        assert label in out
    # First source's domain renders as `[domain]`, NOT as a bare URL.
    assert "[platy.cz]" in out
    assert "https://platy.cz" not in out
    # First component <details> is opened so the reviewer sees a quote immediately.
    assert "<details open>" in out
    # Plan / growth list renders with literal markdown emphasis.
    assert "**learn rust**" in out
    assert "*6 months*" in out
    # Confidence badge.
    assert "[!] High" in out


@pytest.mark.fast
def test_render_body_with_salary_failure_keeps_score_block() -> None:
    failure = StageFailure(
        stage="salary",
        user_message="Insufficient market data for this profile",
    )
    report = _make_report(salary=failure, statuses=_statuses(salary="failed"))
    out = render_body(report)
    # Score block still present.
    assert "## Score: 69/100" in out
    assert "<details open>" in out
    # Salary section is a callout, not a price.
    assert "Insufficient market data for this profile" in out
    assert "CZK" not in out
    # Confidence + plan still render.
    assert "[!] High" in out
    assert "**learn rust**" in out


@pytest.mark.fast
def test_render_body_with_profile_failure_short_circuits() -> None:
    failure = StageFailure(
        stage="profile",
        user_message="Unable to read this file. Please upload a valid PDF or DOCX.",
    )
    # When profile fails, downstream stages won't have run — but the schema
    # requires each block to be either a value or a StageFailure. Fill the
    # rest with their own failures so we build a valid Report.
    downstream = StageFailure(stage="x", user_message="skipped")
    report = _make_report(
        profile=failure,
        score=downstream,
        salary=downstream,
        confidence=downstream,
        growth=downstream,
        statuses={
            "profile": "failed",
            "score": "skipped",
            "salary": "skipped",
            "confidence": "skipped",
            "growth": "skipped",
        },
    )
    out = render_body(report)
    assert "Unable to read this file" in out
    # No downstream content.
    assert "CZK" not in out
    assert "Skills" not in out
    assert "Plan" not in out
    assert "## Score" not in out


@pytest.mark.fast
def test_render_body_escapes_html_in_user_content() -> None:
    malicious = '<script>alert("xss")</script>'
    bad_score = Score(
        components=[
            _component("skills", 80, justification=malicious),
            Component(
                name="experience",
                score_0_100=60,
                justification="ok",
                anchor=Anchor(quote=malicious, section="Work Experience"),
            ),
            _component("education", 40),
            _component("soft_signals", 100),
        ]
    )
    report = _make_report(score=bad_score)
    out = render_body(report)
    assert "<script>" not in out
    assert 'alert("xss")' not in out
    assert "&lt;script&gt;" in out


@pytest.mark.fast
def test_render_body_escapes_html_in_source_snippet() -> None:
    bad_source = Source(
        url="https://example.com",
        snippet="<img src=x onerror=alert(1)>",
        domain="example.com",
    )
    salary = SalaryEstimate(
        low=80_000,
        high=120_000,
        currency="CZK",
        period="month",
        sources=[bad_source],
        reasoning="ok",
    )
    report = _make_report(salary=salary)
    out = render_body(report)
    # The brackets being escaped is sufficient: without `<` the markup cannot
    # execute even though the literal text "onerror=" survives inside the
    # escaped string.
    assert "<img" not in out
    assert "&lt;img" in out


# ---------- render_body — inline stage failures ----------


@pytest.mark.fast
def test_render_body_score_failure_keeps_other_sections() -> None:
    failure = StageFailure(
        stage="score",
        user_message="Could not generate this section reliably",
    )
    report = _make_report(score=failure, statuses=_statuses(score="failed"))
    out = render_body(report)
    assert "## Score" in out
    assert "Could not generate this section reliably" in out
    # Salary, confidence, growth still render.
    assert "CZK" in out
    assert "80,000" in out
    assert "[!] High" in out
    assert "**learn rust**" in out


@pytest.mark.fast
def test_render_body_confidence_failure_keeps_other_sections() -> None:
    failure = StageFailure(
        stage="confidence",
        user_message="Confidence judge unavailable",
    )
    report = _make_report(confidence=failure, statuses=_statuses(confidence="failed"))
    out = render_body(report)
    assert "## Confidence" in out
    assert "Confidence judge unavailable" in out
    # Score, salary, growth still render.
    assert "## Score: 69/100" in out
    assert "CZK" in out
    assert "**learn rust**" in out


@pytest.mark.fast
def test_render_body_growth_failure_keeps_other_sections() -> None:
    failure = StageFailure(
        stage="growth",
        user_message="Plan generation failed",
    )
    report = _make_report(growth=failure, statuses=_statuses(growth="failed"))
    out = render_body(report)
    assert "## Plan" in out
    assert "Plan generation failed" in out
    # Score, salary, confidence still render.
    assert "## Score: 69/100" in out
    assert "CZK" in out
    assert "[!] High" in out


# ---------- render_body — confidence badge tiers ----------


_ConfidenceTier = Literal["High", "Medium", "Low"]


@pytest.mark.fast
@pytest.mark.parametrize(
    ("tier", "glyph"),
    [("High", "[!]"), ("Medium", "[~]"), ("Low", "[?]")],
)
def test_render_body_confidence_badge_matches_tier(tier: _ConfidenceTier, glyph: str) -> None:
    conf = Confidence(tier=tier, rationale="ok")
    report = _make_report(confidence=conf)
    out = render_body(report)
    assert f"{glyph} {tier}" in out


# ---------- render_body — footer ----------


@pytest.mark.fast
def test_render_body_footer_shows_component_weights() -> None:
    out = render_body(_make_report())
    # COMPONENT_WEIGHTS in schemas: skills 0.35, experience 0.30, education 0.20, soft_signals 0.15.
    for pct in ("35%", "30%", "20%", "15%"):
        assert pct in out


# ---------- render_body — empty growth ----------


@pytest.mark.fast
def test_render_body_empty_growth_renders_no_actions_marker() -> None:
    report = _make_report(growth=[])
    out = render_body(report)
    assert "_(no actions)_" in out


# ---------- render_body — Czech diacritics ----------


@pytest.mark.fast
def test_render_body_handles_czech_diacritics() -> None:
    # Cover the full diacritic alphabet across the three fields.
    czech_quote = "Tomáš Dvořák — pět let zkušeností (áčďéěíňóřšťúůýž)"
    czech_section = "Pracovní zkušenosti"
    czech_just = "Silné dovednosti v Pythonu, učí se rychle"
    score = Score(
        components=[
            Component(
                name="skills",
                score_0_100=80,
                justification=czech_just,
                anchor=Anchor(quote=czech_quote, section=czech_section),
            ),
            _component("experience", 60),
            _component("education", 40),
            _component("soft_signals", 100),
        ]
    )
    report = _make_report(score=score)
    out = render_body(report)
    # Diacritics survive html.escape and end up in the rendered body.
    assert "Tomáš Dvořák" in out
    assert "Pracovní zkušenosti" in out
    assert "Silné dovednosti v Pythonu" in out
    # Sanity: the full diacritic alphabet is not mangled.
    for ch in "áčďéěíňóřšťúůýž":
        assert ch in out


# ---------- render_body — escape coverage for additional fields ----------


@pytest.mark.fast
def test_render_body_escapes_html_in_confidence_rationale() -> None:
    bad = Confidence(tier="Medium", rationale='<script>alert("c")</script>')
    report = _make_report(confidence=bad)
    out = render_body(report)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


@pytest.mark.fast
def test_render_body_escapes_html_in_salary_reasoning() -> None:
    salary = SalaryEstimate(
        low=80_000,
        high=120_000,
        currency="CZK",
        period="month",
        sources=[Source(url="https://example.com", snippet="ok", domain="example.com")],
        reasoning='<script>alert("r")</script>',
    )
    report = _make_report(salary=salary)
    out = render_body(report)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


@pytest.mark.fast
def test_render_body_escapes_html_in_growth_action_fields() -> None:
    bad_what = '<script>alert("w")</script>'
    bad_mech = "<img src=x onerror=alert(1)>"
    growth = [
        GrowthAction(
            what=bad_what,
            time_horizon_months=6,
            mechanism=bad_mech,
            anchor=Anchor(quote="C++ background"),
        )
    ]
    report = _make_report(growth=growth)
    out = render_body(report)
    assert "<script>" not in out
    assert "<img" not in out
    assert "&lt;script&gt;" in out
    assert "&lt;img" in out


# ---------- render_tracker — failed-pill fallback tooltip ----------


@pytest.mark.fast
def test_render_tracker_failed_status_without_stage_failure_block() -> None:
    # Schema doesn't enforce status<->block consistency: status="failed" with
    # a populated Score is legal. The tracker must still surface a diagnostic
    # tooltip rather than silently render a tooltip-less pill.
    report = _make_report(statuses=_statuses(score="failed"))
    out = render_tracker(report)
    assert '<span class="pill failed"' in out
    # A non-empty title attribute is present on the failed pill.
    failed_idx = out.find('<span class="pill failed"')
    failed_pill = out[failed_idx : out.find("</span>", failed_idx)]
    assert "title=" in failed_pill
    # Title attribute is non-empty (not `title=""`).
    assert 'title=""' not in failed_pill
