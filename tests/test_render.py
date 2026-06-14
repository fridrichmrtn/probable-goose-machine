"""Fast unit tests for gander.report (T14).

Fixtures construct fully-valid Report instances so the schema's validators
are exercised. No I/O, no LLM, no network.
"""

from __future__ import annotations

from typing import Literal, cast

import pytest

from gander.errors import StageFailure
from gander.report import STYLE, _md, render_html, render_markdown, render_tracker
from gander.schemas import (
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


def _profile_with_band(band: str) -> Profile:
    base = _profile()
    return base.model_copy(update={"seniority_band": band})


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
            setting="capability_artifact",
            anchor=Anchor(quote="C++ background"),
        ),
        GrowthAction(
            what="lead a project",
            time_horizon_months=12,
            mechanism="volunteer for cross-team work",
            setting="capability_artifact",
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
    )


# ---------- render_tracker ----------


@pytest.mark.fast
def test_render_tracker_emits_five_pills_for_done_report() -> None:
    out = render_tracker(_make_report())
    # Five pill spans, each with the "pill " class prefix.
    assert out.count('<span class="pill ') == 5


@pytest.mark.fast
def test_render_tracker_running_first_pill_shows_ingest_before_text() -> None:
    report = Report(
        profile=None,
        score=None,
        salary=None,
        confidence=None,
        growth=None,
        statuses=_statuses(
            profile="running",
            score="pending",
            salary="pending",
            confidence="pending",
            growth="pending",
        ),
        redacted_cv_text="",
    )

    out = render_tracker(report)

    assert out.count('<span class="pill ') == 5
    assert ">Ingest</span>" in out


@pytest.mark.fast
def test_render_tracker_running_first_pill_shows_profile_after_text() -> None:
    report = Report(
        profile=None,
        score=None,
        salary=None,
        confidence=None,
        growth=None,
        statuses=_statuses(
            profile="running",
            score="pending",
            salary="pending",
            confidence="pending",
            growth="pending",
        ),
        redacted_cv_text="redacted cv text",
    )

    out = render_tracker(report)

    assert out.count('<span class="pill ') == 5
    assert ">Profile</span>" in out


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
def test_render_tracker_does_not_emit_style_block() -> None:
    # render_tracker returns only a <div class="tracker" ...> fragment; all CSS
    # lives in the module-level STYLE constant injected once by app.py.
    out = render_tracker(_make_report())
    assert "<style>" not in out


@pytest.mark.fast
def test_style_constant_includes_prefers_reduced_motion_query() -> None:
    # CSS for reduced-motion is in the global STYLE constant, not in tracker output.
    assert "prefers-reduced-motion" in STYLE


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


# ---------- render_tracker — a11y live region (P2.1) ----------


@pytest.mark.fast
def test_render_tracker_pill_row_is_not_a_live_region() -> None:
    # The pill row must NOT be the live region — that re-announced all six pills
    # on every yield. It is now a labelled group.
    out = render_tracker(_make_report())
    tracker_div = out.split('<div class="tracker"', 1)[1].split("</div>", 1)[0]
    assert "aria-live" not in tracker_div
    assert 'role="group"' in tracker_div
    assert 'aria-label="Pipeline progress"' in tracker_div


@pytest.mark.fast
def test_render_tracker_has_exactly_one_polite_live_region() -> None:
    out = render_tracker(_make_report())
    # Exactly one aria-live in the whole fragment, and it's the sr-only region.
    assert out.count('aria-live="polite"') == 1
    # The class is USED in the tracker markup. The CSS rule itself now lives in
    # the global STYLE block (injected once by app.py), not in render_tracker's
    # output — see test_style_defines_sr_only_clip_rule for that half.
    assert 'class="gander-sr-only" role="status" aria-live="polite"' in out


@pytest.mark.fast
def test_style_defines_sr_only_clip_rule() -> None:
    # Centralized CSS: the visually-hidden clip pattern that hides the live
    # region from sighted users must be defined in the global STYLE block.
    assert ".gander-sr-only {" in STYLE


@pytest.mark.fast
def test_render_tracker_announces_running_stage() -> None:
    report = _make_report(
        statuses=_statuses(
            score="running", salary="pending", confidence="pending", growth="pending"
        )
    )
    out = render_tracker(report)
    assert ">Score: in progress</p>" in out


@pytest.mark.fast
def test_render_tracker_running_takes_precedence_over_failed() -> None:
    # A later running stage should still announce progress, not an earlier failure.
    failure = StageFailure(stage="score", user_message="scoring unavailable")
    report = _make_report(
        score=failure,
        statuses=_statuses(score="failed", salary="running", confidence="pending"),
    )
    out = render_tracker(report)
    assert ">Salary: in progress</p>" in out


@pytest.mark.fast
def test_render_tracker_announces_failure_when_nothing_running() -> None:
    failure = StageFailure(stage="salary", user_message="Insufficient market data")
    report = _make_report(salary=failure, statuses=_statuses(salary="failed"))
    out = render_tracker(report)
    assert ">Salary: failed</p>" in out


@pytest.mark.fast
def test_render_tracker_announces_completion_when_all_terminal() -> None:
    out = render_tracker(_make_report())
    assert ">Analysis complete</p>" in out


@pytest.mark.fast
def test_render_tracker_announces_waiting_not_complete_when_all_pending() -> None:
    # The pipeline's initial yield sets every stage pending. A polite live region
    # must not announce "Analysis complete" before anything has run — it says the
    # first waiting stage instead.
    report = _make_report(
        statuses=_statuses(
            profile="pending",
            score="pending",
            salary="pending",
            confidence="pending",
            growth="pending",
        )
    )
    out = render_tracker(report)
    assert ">Profile: waiting</p>" in out
    assert "Analysis complete" not in out


@pytest.mark.fast
def test_render_tracker_announces_next_waiting_stage_in_gap() -> None:
    # After profile finishes but before score/salary start (a real intermediate
    # yield) nothing is running and nothing failed — announce the next waiting
    # stage, not completion.
    report = _make_report(
        statuses=_statuses(
            profile="done",
            score="pending",
            salary="pending",
            confidence="pending",
            growth="pending",
        )
    )
    out = render_tracker(report)
    assert ">Score: waiting</p>" in out
    assert "Analysis complete" not in out


# ---------- render_html — populated ----------


@pytest.mark.fast
def test_render_html_populated_contains_expected_content() -> None:
    out = render_html(_make_report())
    # Salary block.
    assert "CZK" in out
    assert "80,000" in out and "120,000" in out
    # Score total (80*0.35 + 60*0.30 + 40*0.20 + 100*0.15 = 69).
    assert "69" in out
    # All four component display names render in the grid.
    for label in ("Skills", "Experience", "Education", "Soft"):
        assert label in out
    # Source domain rendered as <span>, NOT as a bare URL or `[domain]` markdown.
    assert '<span class="gander-source-domain">platy.cz</span>' in out
    assert "https://platy.cz" not in out
    # [domain]: markdown syntax must NOT appear in HTML output.
    assert "[platy.cz]:" not in out
    # Components render as always-visible tiles in a grid.
    assert '<div class="gander-components-grid" role="list">' in out
    assert out.count('class="gander-component"') == 4
    assert 'role="listitem"' in out
    # Component names are headings (keyboard/SR navigable) carrying the CSS class.
    assert '<h3 id="gander-score-skills" class="gander-component-name">Skills</h3>' in out
    # Evidence quotes in blockquote elements (full, no truncation).
    assert '<blockquote class="gander-component-quote">' in out
    # Plan / growth list renders as structured HTML with horizon chips.
    assert '<ol class="gander-plan">' in out
    assert '<p class="gander-plan-title">learn rust</p>' in out
    assert '<span class="gander-chip" aria-label="Time horizon: 6 months">6 months</span>' in out
    # The action title precedes its time-horizon chip in the <li> so the <ol> marker
    # numbers the action, not the chip (UX fix: list number aligns to the title).
    assert out.index('<p class="gander-plan-title">learn rust</p>') < out.index(
        '<span class="gander-chip" aria-label="Time horizon: 6 months">6 months</span>'
    )
    assert "**learn rust**" not in out
    # Confidence badge is visually separated from the rationale.
    assert '<span class="gander-chip" aria-label="Confidence: High">[!] High</span>' in out


@pytest.mark.fast
def test_render_html_long_quote_clamps_with_accessible_disclosure() -> None:
    """A long evidence quote is wrapped in a <details> disclosure (full text in the
    DOM); a short quote stays a plain blockquote. Keeps verbose anchors from
    ballooning their card while leaving the quote screen-reader-readable."""
    long_quote = (
        "Led end-to-end delivery of a real-time fraud detection pipeline processing "
        "over fifty million events per day, reducing the false-positive rate by 34% "
        "through careful feature engineering on transaction velocity and merchant "
        "category embeddings across several quarters of iteration."
    )
    # Guard: the fixture must actually exceed the clamp threshold, else this test
    # silently stops exercising the disclosure path.
    assert len(long_quote) > 220
    score = Score(
        components=[
            Component(
                name="experience",
                score_0_100=80,
                justification="ok",
                anchor=Anchor(quote=long_quote, section="Work Experience"),
            ),
            Component(
                name="skills",
                score_0_100=70,
                justification="ok",
                anchor=Anchor(quote="short quote", section="Skills"),
            ),
        ]
    )
    out = render_html(_make_report(score=score))

    # Long quote: exactly one accessible disclosure; full text intact in the DOM.
    assert out.count('<details class="gander-evidence">') == 1
    assert '<summary class="gander-evidence-summary">' in out
    assert long_quote in out
    # Short quote: plain blockquote, no disclosure wrapper.
    assert '<blockquote class="gander-component-quote">"short quote"' in out


@pytest.mark.fast
def test_render_html_with_salary_failure_keeps_score_block() -> None:
    failure = StageFailure(
        stage="salary",
        user_message="Insufficient market data for this profile",
    )
    report = _make_report(salary=failure, statuses=_statuses(salary="failed"))
    out = render_html(report)
    # Score block still present as the lede.
    assert 'class="gander-score-num"' in out
    assert 'class="gander-component"' in out
    # Salary section is a callout, not a price.
    assert "Insufficient market data for this profile" in out
    assert "CZK" not in out
    # Confidence + plan still render.
    assert '<span class="gander-chip" aria-label="Confidence: High">[!] High</span>' in out
    assert '<p class="gander-plan-title">learn rust</p>' in out


@pytest.mark.fast
def test_render_html_with_profile_failure_short_circuits() -> None:
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
    out = render_html(report)
    assert "Unable to read this file" in out
    # No downstream content.
    assert "CZK" not in out
    assert "Skills" not in out
    assert "Plan" not in out
    # Score section uses gander-score-num, not a markdown heading.
    assert 'class="gander-score-num"' not in out
    # The honest-AI banner must not render for a single failure callout.
    assert "About this report" not in out


@pytest.mark.fast
def test_render_html_includes_about_banner_on_success_path() -> None:
    out = render_html(_make_report())
    assert "About this report" in out
    # Grounded framing, not invented claims.
    assert "candidate hypotheses to validate" in out
    assert "not validated for fairness across protected groups" in out


@pytest.mark.fast
def test_render_html_score_headline_is_outside_about_banner_details() -> None:
    # Score is the lede — it appears BEFORE <details class="gander-about">.
    # Using .index() ordering to assert structural position.
    out = render_html(_make_report())
    score_idx = out.index("gander-score-num")
    about_idx = out.index('<details class="gander-about">')
    assert score_idx < about_idx, "score headline must appear before the about banner"


@pytest.mark.fast
def test_render_html_score_headline_not_nested_inside_about_details() -> None:
    # The score headline must not be inside the <details class="gander-about"> element.
    out = render_html(_make_report())
    about_start = out.index('<details class="gander-about">')
    about_end = out.index("</details>", about_start)
    about_block = out[about_start:about_end]
    assert "gander-score-num" not in about_block


@pytest.mark.fast
def test_render_html_shows_seniority_band_in_tier_chip() -> None:
    report = _make_report(profile=_profile_with_band("senior"))
    out = render_html(report)
    assert '<span class="gander-tier-chip" aria-hidden="true">senior</span>' in out
    # The tier is also carried in the screen-reader value phrase.
    assert "out of 100, senior tier" in out


@pytest.mark.fast
def test_render_html_score_omits_tier_chip_when_band_absent() -> None:
    # _profile() leaves seniority_band None; no chip should render.
    out = _make_report()
    html_out = render_html(out)
    assert 'class="gander-tier-chip"' not in html_out
    # Screen-reader value phrase renders the figure without a tier suffix.
    assert '<span class="gander-visually-hidden">' in html_out
    assert "out of 100, " not in html_out


@pytest.mark.fast
def test_render_html_band_with_newline_collapses_whitespace() -> None:
    # D3: a band value carrying a newline must be collapsed; no second <h2>
    # may be injected into the HTML output.
    report = _make_report(profile=_profile_with_band("senior\n## Injected"))
    out = render_html(report)
    # Whitespace collapsed to a single space inside the chip.
    assert '<span class="gander-tier-chip" aria-hidden="true">senior ## Injected</span>' in out
    # No injected h2 element.
    assert "<h2>Injected" not in out
    assert "<h2> Injected" not in out


@pytest.mark.fast
def test_render_html_salary_caption_shows_canonical_role_and_location() -> None:
    # The caption anchors the range to a specific role + market so the number
    # never reads as a generic figure. Canonical role wins over detected_role.
    profile = _profile().model_copy(
        update={"canonical_role": "Software Engineer", "detected_location": "Prague"}
    )
    out = render_html(_make_report(profile=profile))
    assert '<p class="gander-salary-context">Software Engineer · Prague</p>' in out
    # The caption sits above the range line.
    assert out.index("gander-salary-context") < out.index("gander-salary-range")


@pytest.mark.fast
def test_render_html_salary_caption_falls_back_to_detected_role() -> None:
    # _profile() leaves canonical_role None; the caption uses detected_role.
    profile = _profile().model_copy(update={"detected_location": "Brno"})
    out = render_html(_make_report(profile=profile))
    assert '<p class="gander-salary-context">engineer · Brno</p>' in out


@pytest.mark.fast
def test_render_html_salary_caption_falls_back_when_canonical_role_blank() -> None:
    # A whitespace-only canonical_role is not a usable role: it must fall back to
    # detected_role, not suppress the caption (it is falsy after strip()).
    profile = _profile().model_copy(update={"canonical_role": "   ", "detected_location": "Brno"})
    out = render_html(_make_report(profile=profile))
    assert '<p class="gander-salary-context">engineer · Brno</p>' in out


@pytest.mark.fast
def test_render_html_salary_caption_omits_location_when_absent() -> None:
    # _profile() has detected_location None — caption shows role only, no
    # trailing separator.
    profile = _profile().model_copy(update={"canonical_role": "Data Analyst"})
    out = render_html(_make_report(profile=profile))
    assert '<p class="gander-salary-context">Data Analyst</p>' in out
    assert "Data Analyst ·" not in out


@pytest.mark.fast
def test_render_html_salary_caption_omitted_when_role_empty() -> None:
    # No role at all (canonical None, detected blank) ⇒ no caption element.
    profile = _profile().model_copy(update={"detected_role": "", "canonical_role": None})
    out = render_html(_make_report(profile=profile))
    assert "gander-salary-context" not in out


@pytest.mark.fast
def test_render_html_salary_caption_escapes_injection_in_role() -> None:
    # Role is LLM-derived → must be HTML-escaped and whitespace-collapsed so it
    # cannot break out of the caption paragraph or inject markup.
    profile = _profile().model_copy(
        update={"canonical_role": "<script>alert(1)</script>", "detected_location": None}
    )
    out = render_html(_make_report(profile=profile))
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


@pytest.mark.fast
def test_render_html_escapes_html_in_user_content() -> None:
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
    out = render_html(report)
    assert "<script>" not in out
    assert 'alert("xss")' not in out
    assert "&lt;script&gt;" in out


@pytest.mark.fast
def test_render_html_escapes_html_in_source_snippet() -> None:
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
    out = render_html(report)
    # The brackets being escaped is sufficient: without `<` the markup cannot
    # execute even though the literal text "onerror=" survives inside the
    # escaped string.
    assert "<img" not in out
    assert "&lt;img" in out


# ---------- render_html — inline stage failures ----------


@pytest.mark.fast
@pytest.mark.parametrize(
    ("stage", "message"),
    [
        ("profile", "Unable to read this file. Please upload a valid PDF or DOCX."),
        ("score", "Could not generate this section reliably"),
        ("salary", "Insufficient market data for this profile"),
        ("confidence", "Could not generate this section reliably"),
        ("growth", "Could not generate this section reliably"),
    ],
)
def test_render_html_renders_failure_copy_for_each_stage(
    stage: StageName,
    message: str,
) -> None:
    failure = StageFailure(stage=stage, user_message=message)

    if stage == "profile":
        downstream = StageFailure(stage="x", user_message="skipped")
        report = _make_report(
            profile=failure,
            score=downstream,
            salary=downstream,
            confidence=downstream,
            growth=downstream,
            statuses=_statuses(
                profile="failed",
                score="skipped",
                salary="skipped",
                confidence="skipped",
                growth="skipped",
            ),
        )
    elif stage == "score":
        report = _make_report(score=failure, statuses=_statuses(score="failed"))
    elif stage == "salary":
        report = _make_report(salary=failure, statuses=_statuses(salary="failed"))
    elif stage == "confidence":
        report = _make_report(confidence=failure, statuses=_statuses(confidence="failed"))
    else:
        report = _make_report(growth=failure, statuses=_statuses(growth="failed"))

    out = render_html(report)

    assert message in out
    assert "Traceback" not in out


@pytest.mark.fast
def test_render_html_partial_score_shows_dropped_footer() -> None:
    # T25: partial Score renders only surviving components in the grid and a
    # one-line italic footer naming the dropped categories.
    partial_score = Score(
        components=[
            _component("experience", 80),
            _component("education", 60),
            _component("soft_signals", 40),
        ],
        dropped=["skills"],
    )
    report = _make_report(score=partial_score)
    out = render_html(report)

    # Total: 80*0.30 + 60*0.20 + 40*0.15 = 24 + 12 + 6 = 42.
    assert "42" in out
    # Surviving component labels render as tiles; dropped one absent.
    for label in ("Experience", "Education", "Soft"):
        assert label in out
    assert 'id="gander-score-skills"' not in out
    # Dropped-components footer note.
    assert "1 component(s) dropped (Skills)" in out
    assert "no anchor verified against CV text" in out


@pytest.mark.fast
def test_render_html_score_failure_keeps_other_sections() -> None:
    failure = StageFailure(
        stage="score",
        user_message="Could not generate this section reliably",
    )
    report = _make_report(score=failure, statuses=_statuses(score="failed"))
    out = render_html(report)
    assert '<h2 class="gander-h2">Score</h2>' in out
    assert "Could not generate this section reliably" in out
    # Salary, confidence, growth still render.
    assert "CZK" in out
    assert "80,000" in out
    assert '<span class="gander-chip" aria-label="Confidence: High">[!] High</span>' in out
    assert '<p class="gander-plan-title">learn rust</p>' in out


@pytest.mark.fast
def test_render_html_confidence_failure_keeps_other_sections() -> None:
    failure = StageFailure(
        stage="confidence",
        user_message="Confidence judge unavailable",
    )
    report = _make_report(confidence=failure, statuses=_statuses(confidence="failed"))
    out = render_html(report)
    assert '<h2 class="gander-h2">Confidence</h2>' in out
    assert "Confidence judge unavailable" in out
    # Score, salary, growth still render.
    assert 'class="gander-score-num"' in out
    assert "CZK" in out
    assert '<p class="gander-plan-title">learn rust</p>' in out


@pytest.mark.fast
def test_render_html_growth_failure_keeps_other_sections() -> None:
    failure = StageFailure(
        stage="growth",
        user_message="Plan generation failed",
    )
    report = _make_report(growth=failure, statuses=_statuses(growth="failed"))
    out = render_html(report)
    assert '<h2 class="gander-h2">Plan</h2>' in out
    assert "Plan generation failed" in out
    # Score, salary, confidence still render.
    assert 'class="gander-score-num"' in out
    assert "CZK" in out
    assert '<span class="gander-chip" aria-label="Confidence: High">[!] High</span>' in out


# ---------- render_html — confidence badge tiers ----------


_ConfidenceTier = Literal["High", "Medium", "Low"]


@pytest.mark.fast
@pytest.mark.parametrize(
    ("tier", "glyph"),
    [("High", "[!]"), ("Medium", "[~]"), ("Low", "[?]")],
)
def test_render_html_confidence_badge_matches_tier(tier: _ConfidenceTier, glyph: str) -> None:
    conf = Confidence(tier=tier, rationale="ok")
    report = _make_report(confidence=conf)
    out = render_html(report)
    assert f"{glyph} {tier}" in out


# ---------- render_html — footer ----------


@pytest.mark.fast
def test_render_html_footer_shows_component_weights() -> None:
    out = render_html(_make_report())
    # COMPONENT_WEIGHTS in schemas: skills 0.35, experience 0.30, education 0.20, soft_signals 0.15.
    for pct in ("35%", "30%", "20%", "15%"):
        assert pct in out


@pytest.mark.fast
def test_render_html_footer_interpolates_cost_and_latency_totals() -> None:
    # Pipeline (T15) populates total_cost_usd / total_latency_ms; footer must
    # reflect them rather than the legacy "populated by T15" placeholder.
    report = Report(
        profile=_profile(),
        score=_score(),
        salary=_salary(),
        confidence=_confidence(),
        growth=_growth(),
        statuses=_statuses(),
        total_cost_usd=0.0234,
        total_latency_ms=12_345,
        wall_clock_ms=6_789,
    )
    out = render_html(report)
    assert "$0.0234" in out
    assert "LLM time (sum)" in out
    assert "12,345 ms" in out
    assert "Total elapsed" in out
    assert "6,789 ms" in out
    assert "LLM time can exceed total elapsed" in out
    # Legacy placeholder gone.
    assert "populated by T15" not in out


@pytest.mark.fast
def test_render_html_footer_surfaces_notices() -> None:
    report = Report(
        profile=_profile(),
        score=_score(),
        salary=_salary(),
        confidence=_confidence(),
        growth=_growth(),
        statuses=_statuses(),
        notices=["Vision skipped: PDF over budget; used text extraction."],
    )

    out = render_html(report)

    assert "Vision skipped: PDF over budget; used text extraction." in out


# ---------- render_html — None = pending (T15 streaming) ----------


@pytest.mark.fast
def test_render_html_profile_none_returns_empty_string() -> None:
    # Initial pipeline yield carries profile=None; tracker drives the UI,
    # body has nothing to show yet.
    report = Report(
        statuses={
            "profile": "pending",
            "score": "pending",
            "salary": "pending",
            "confidence": "pending",
            "growth": "pending",
        },
    )
    assert render_html(report) == ""


@pytest.mark.fast
def test_render_html_skips_none_blocks_but_renders_completed_ones() -> None:
    # Mid-pipeline: profile done, score done, downstream still pending.
    report = Report(
        profile=_profile(),
        score=_score(),
        salary=None,
        confidence=None,
        growth=None,
        statuses={
            "profile": "done",
            "score": "done",
            "salary": "running",
            "confidence": "pending",
            "growth": "pending",
        },
    )
    out = render_html(report)
    # Score section rendered as the lede.
    assert 'class="gander-score-num"' in out
    # No salary/confidence/plan sections (None ⇒ skipped).
    assert '<h2 class="gander-h2">Salary</h2>' not in out
    assert '<h2 class="gander-h2">Confidence</h2>' not in out
    assert '<h2 class="gander-h2">Plan</h2>' not in out
    # Footer still renders (it always does for a populated profile).
    assert "How is this scored?" in out


# ---------- render_html — empty growth ----------


@pytest.mark.fast
def test_render_html_empty_growth_renders_no_actions_marker() -> None:
    report = _make_report(growth=[])
    out = render_html(report)
    assert '<p class="gander-empty">No actions.</p>' in out
    # Markdown form must not appear in HTML output.
    assert "_(no actions)_" not in out


# ---------- render_html — Czech diacritics ----------


@pytest.mark.fast
def test_render_html_handles_czech_diacritics() -> None:
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
    out = render_html(report)
    # Diacritics survive html.escape and end up in the rendered body.
    assert "Tomáš Dvořák" in out
    assert "Pracovní zkušenosti" in out
    assert "Silné dovednosti v Pythonu" in out
    # Sanity: the full diacritic alphabet is not mangled.
    for ch in "áčďéěíňóřšťúůýž":
        assert ch in out


# ---------- render_html — escape coverage for additional fields ----------


@pytest.mark.fast
def test_render_html_escapes_html_in_confidence_rationale() -> None:
    bad = Confidence(tier="Medium", rationale='<script>alert("c")</script>')
    report = _make_report(confidence=bad)
    out = render_html(report)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


@pytest.mark.fast
def test_render_html_escapes_html_in_salary_reasoning() -> None:
    salary = SalaryEstimate(
        low=80_000,
        high=120_000,
        currency="CZK",
        period="month",
        sources=[Source(url="https://example.com", snippet="ok", domain="example.com")],
        reasoning='<script>alert("r")</script>',
    )
    report = _make_report(salary=salary)
    out = render_html(report)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


@pytest.mark.fast
def test_render_html_escapes_html_in_growth_action_fields() -> None:
    bad_what = '<script>alert("w")</script>'
    bad_mech = "<img src=x onerror=alert(1)>"
    growth = [
        GrowthAction(
            what=bad_what,
            time_horizon_months=6,
            mechanism=bad_mech,
            setting="capability_artifact",
            anchor=Anchor(quote="C++ background"),
        )
    ]
    report = _make_report(growth=growth)
    out = render_html(report)
    assert "<script>" not in out
    assert "<img" not in out
    assert "&lt;script&gt;" in out
    assert "&lt;img" in out


# ---------- render_html — failure callout HTML escaping ----------


@pytest.mark.fast
def test_render_html_failure_callout_escapes_html() -> None:
    # A failure message containing HTML must not inject raw markup.
    failure = StageFailure(
        stage="salary",
        user_message='<script>alert("f")</script>',
    )
    report = _make_report(salary=failure, statuses=_statuses(salary="failed"))
    out = render_html(report)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert 'class="gander-callout"' in out


# ---------- render_html — salary sources use HTML, not markdown ----------


@pytest.mark.fast
def test_render_html_salary_source_uses_span_not_markdown_bracket() -> None:
    # HTML path uses <span class="gander-source-domain">, not `[domain]:`.
    report = _make_report()
    out = render_html(report)
    assert '<span class="gander-source-domain">platy.cz</span>' in out
    assert "[platy.cz]:" not in out


# ---------- render_markdown — core structure ----------


@pytest.mark.fast
def test_render_markdown_score_heading_format() -> None:
    out = render_markdown(_make_report())
    # Score is rendered as `## Score: {total}/100`.
    assert "## Score: 69/100" in out


@pytest.mark.fast
def test_render_markdown_shows_seniority_band_in_score_heading() -> None:
    report = _make_report(profile=_profile_with_band("senior"))
    out = render_markdown(report)
    assert "## Score: 69/100 (senior)" in out


@pytest.mark.fast
def test_render_markdown_score_heading_omits_band_when_absent() -> None:
    # _profile() leaves seniority_band None; heading must stay clean.
    out = render_markdown(_make_report())
    assert "## Score: 69/100\n" in out
    assert "## Score: 69/100 (" not in out


@pytest.mark.fast
def test_render_markdown_band_with_newline_does_not_split_heading() -> None:
    # D3: a band value carrying a newline + `##` must not break out of the
    # `## Score` heading line and inject a sibling heading.
    report = _make_report(profile=_profile_with_band("senior\n## Injected"))
    out = render_markdown(report)
    assert "## Score: 69/100 (senior ## Injected)" in out
    assert "\n## Injected" not in out


@pytest.mark.fast
def test_render_markdown_source_line_uses_bracket_domain_format() -> None:
    # Markdown download path uses `[domain]: "snippet"` format.
    out = render_markdown(_make_report())
    assert "[platy.cz]:" in out
    assert "https://platy.cz" not in out


@pytest.mark.fast
def test_render_markdown_salary_section_format() -> None:
    out = render_markdown(_make_report())
    assert "## Salary" in out
    assert "**80,000 – 120,000 CZK / month**" in out
    assert "### Sources" in out


@pytest.mark.fast
def test_render_markdown_salary_caption_shows_role_and_location() -> None:
    # Download parity with render_html (P2.2): the markdown archive carries the
    # same role · market caption, as an italic line above the range.
    profile = _profile().model_copy(
        update={"canonical_role": "Software Engineer", "detected_location": "Prague"}
    )
    out = render_markdown(_make_report(profile=profile))
    assert "_Software Engineer · Prague_" in out
    # Caption sits above the range line.
    assert out.index("_Software Engineer · Prague_") < out.index("**80,000")


@pytest.mark.fast
def test_render_markdown_salary_caption_falls_back_to_detected_role() -> None:
    # canonical_role None ⇒ detected_role; no location ⇒ role only, no separator.
    out = render_markdown(_make_report())
    assert "_engineer_" in out
    assert "engineer ·" not in out


@pytest.mark.fast
def test_render_markdown_salary_caption_omitted_when_role_empty() -> None:
    profile = _profile().model_copy(update={"detected_role": "", "canonical_role": None})
    out = render_markdown(_make_report(profile=profile))
    # No italic role caption emitted; the range line is still present.
    assert "**80,000 – 120,000 CZK / month**" in out
    assert "_engineer_" not in out


@pytest.mark.fast
def test_render_markdown_empty_growth_renders_no_actions() -> None:
    report = _make_report(growth=[])
    out = render_markdown(report)
    assert "_(no actions)_" in out


@pytest.mark.fast
def test_render_markdown_growth_section_format() -> None:
    out = render_markdown(_make_report())
    assert "## Plan" in out
    # Numbered list with bold action and horizon in parens.
    assert "**learn rust**" in out
    assert "_(6 months)_" in out


@pytest.mark.fast
def test_render_markdown_confidence_section_format() -> None:
    out = render_markdown(_make_report())
    assert "## Confidence" in out
    assert "**[!] High**" in out


@pytest.mark.fast
def test_render_markdown_about_section_present() -> None:
    out = render_markdown(_make_report())
    assert "## About this report" in out
    assert "candidate hypotheses to validate" in out
    assert "not validated for fairness across protected groups" in out


@pytest.mark.fast
def test_render_markdown_footer_shows_component_weights() -> None:
    out = render_markdown(_make_report())
    for pct in ("35%", "30%", "20%", "15%"):
        assert pct in out


@pytest.mark.fast
def test_render_markdown_footer_interpolates_cost_and_latency_totals() -> None:
    report = Report(
        profile=_profile(),
        score=_score(),
        salary=_salary(),
        confidence=_confidence(),
        growth=_growth(),
        statuses=_statuses(),
        total_cost_usd=0.0234,
        total_latency_ms=12_345,
        wall_clock_ms=6_789,
    )
    out = render_markdown(report)
    assert "$0.0234" in out
    assert "LLM time (sum)" in out
    assert "12,345 ms" in out
    assert "Total elapsed" in out
    assert "6,789 ms" in out
    assert "LLM time can exceed total elapsed" in out
    assert "populated by T15" not in out


@pytest.mark.fast
def test_render_markdown_footer_surfaces_notices() -> None:
    report = Report(
        profile=_profile(),
        score=_score(),
        salary=_salary(),
        confidence=_confidence(),
        growth=_growth(),
        statuses=_statuses(),
        notices=["Vision skipped: PDF over budget; used text extraction."],
    )
    out = render_markdown(report)
    assert "Vision skipped: PDF over budget; used text extraction." in out


@pytest.mark.fast
def test_render_markdown_profile_none_returns_empty_string() -> None:
    report = Report(
        statuses={
            "profile": "pending",
            "score": "pending",
            "salary": "pending",
            "confidence": "pending",
            "growth": "pending",
        },
    )
    assert render_markdown(report) == ""


@pytest.mark.fast
def test_render_markdown_with_profile_failure_short_circuits() -> None:
    failure = StageFailure(
        stage="profile",
        user_message="Unable to read this file. Please upload a valid PDF or DOCX.",
    )
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
    out = render_markdown(report)
    # Profile failure renders as markdown blockquote callout.
    assert "> ⚠" in out
    assert "Unable to read this file" in out
    # No downstream content.
    assert "## Score" not in out
    assert "## Salary" not in out


@pytest.mark.fast
def test_render_markdown_with_salary_failure_keeps_score_block() -> None:
    failure = StageFailure(
        stage="salary",
        user_message="Insufficient market data for this profile",
    )
    report = _make_report(salary=failure, statuses=_statuses(salary="failed"))
    out = render_markdown(report)
    # Score block still present.
    assert "## Score: 69/100" in out
    # Salary section has failure callout.
    assert "## Salary" in out
    assert "Insufficient market data for this profile" in out
    assert "CZK" not in out


@pytest.mark.fast
def test_render_markdown_skips_none_blocks_but_renders_completed_ones() -> None:
    # Mid-pipeline: profile done, score done, downstream still pending.
    report = Report(
        profile=_profile(),
        score=_score(),
        salary=None,
        confidence=None,
        growth=None,
        statuses={
            "profile": "done",
            "score": "done",
            "salary": "running",
            "confidence": "pending",
            "growth": "pending",
        },
    )
    out = render_markdown(report)
    assert "## Score: 69/100" in out
    assert "## Salary" not in out
    assert "## Confidence" not in out
    assert "## Plan" not in out
    assert "How is this scored?" in out


# ---------- render_markdown — stage failure callouts ----------


@pytest.mark.fast
@pytest.mark.parametrize(
    ("stage", "message"),
    [
        ("profile", "Unable to read this file. Please upload a valid PDF or DOCX."),
        ("score", "Could not generate this section reliably"),
        ("salary", "Insufficient market data for this profile"),
        ("confidence", "Could not generate this section reliably"),
        ("growth", "Could not generate this section reliably"),
    ],
)
def test_render_markdown_renders_failure_copy_for_each_stage(
    stage: StageName,
    message: str,
) -> None:
    failure = StageFailure(stage=stage, user_message=message)

    if stage == "profile":
        downstream = StageFailure(stage="x", user_message="skipped")
        report = _make_report(
            profile=failure,
            score=downstream,
            salary=downstream,
            confidence=downstream,
            growth=downstream,
            statuses=_statuses(
                profile="failed",
                score="skipped",
                salary="skipped",
                confidence="skipped",
                growth="skipped",
            ),
        )
    elif stage == "score":
        report = _make_report(score=failure, statuses=_statuses(score="failed"))
    elif stage == "salary":
        report = _make_report(salary=failure, statuses=_statuses(salary="failed"))
    elif stage == "confidence":
        report = _make_report(confidence=failure, statuses=_statuses(confidence="failed"))
    else:
        report = _make_report(growth=failure, statuses=_statuses(growth="failed"))

    out = render_markdown(report)

    assert message in out
    assert "Traceback" not in out


@pytest.mark.fast
def test_render_markdown_partial_score_shows_dropped_note() -> None:
    # T25: partial Score shows surviving components and a dropped-note in markdown.
    partial_score = Score(
        components=[
            _component("experience", 80),
            _component("education", 60),
            _component("soft_signals", 40),
        ],
        dropped=["skills"],
    )
    report = _make_report(score=partial_score)
    out = render_markdown(report)

    # Total: 80*0.30 + 60*0.20 + 40*0.15 = 42.
    assert "## Score: 42/100" in out
    # Surviving components as ### headings.
    for label in ("Experience", "Education", "Soft"):
        assert f"### {label}" in out
    # Skills dropped note in italic markdown.
    assert "_Note: 1 component(s) dropped (Skills):" in out
    assert "no anchor verified against CV text._" in out


# ---------- render_markdown — markdown-injection defence ----------


@pytest.mark.fast
def test_render_markdown_escapes_link_in_source_domain() -> None:
    # A domain containing `]` would otherwise close the visual `[domain]`
    # label and let `](javascript:alert(1))` forge a link target.
    bad = Source(
        url="https://example.com",
        snippet="ok",
        domain="evil](javascript:alert(1))",
    )
    salary = SalaryEstimate(
        low=80_000,
        high=120_000,
        currency="CZK",
        period="month",
        sources=[bad],
        reasoning="ok",
    )
    report = _make_report(salary=salary)
    out = render_markdown(report)
    # The escaped bracket sequence survives; the unescaped `](javascript:` form
    # is gone, so no link target can be forged in the rendered markdown.
    assert "](javascript:" not in out
    assert "\\]\\(javascript:alert\\(1\\)\\)" in out


@pytest.mark.fast
def test_render_markdown_escapes_link_in_source_snippet() -> None:
    bad = Source(
        url="https://example.com",
        snippet="see [docs](javascript:alert(1)) here",
        domain="example.com",
    )
    salary = SalaryEstimate(
        low=80_000,
        high=120_000,
        currency="CZK",
        period="month",
        sources=[bad],
        reasoning="ok",
    )
    report = _make_report(salary=salary)
    out = render_markdown(report)
    assert "](javascript:" not in out
    assert "\\[docs\\]\\(javascript:alert\\(1\\)\\)" in out


@pytest.mark.fast
@pytest.mark.parametrize(
    "field",
    ["reasoning", "rationale", "growth_what", "growth_mechanism"],
)
def test_render_markdown_escapes_link_payload_in_body_fields(field: str) -> None:
    payload = "click [here](javascript:alert(1))"
    kwargs: dict[str, object] = {}
    if field == "reasoning":
        kwargs["salary"] = SalaryEstimate(
            low=80_000,
            high=120_000,
            currency="CZK",
            period="month",
            sources=[Source(url="https://example.com", snippet="ok", domain="example.com")],
            reasoning=payload,
        )
    elif field == "rationale":
        kwargs["confidence"] = Confidence(tier="High", rationale=payload)
    elif field == "growth_what":
        kwargs["growth"] = [
            GrowthAction(
                what=payload,
                time_horizon_months=6,
                mechanism="ok",
                setting="capability_artifact",
                anchor=Anchor(quote="C++ background"),
            )
        ]
    elif field == "growth_mechanism":
        kwargs["growth"] = [
            GrowthAction(
                what="learn rust",
                time_horizon_months=6,
                mechanism=payload,
                setting="capability_artifact",
                anchor=Anchor(quote="C++ background"),
            )
        ]
    report = _make_report(**kwargs)  # type: ignore[arg-type]
    out = render_markdown(report)
    assert "](javascript:" not in out
    assert "[here]" not in out


@pytest.mark.fast
def test_render_markdown_multiline_failure_message_stays_quoted() -> None:
    # Every line of a multi-line user_message must remain inside the
    # blockquote, otherwise lines starting with `#`, `-`, `*` etc. would break
    # the callout and render as headings/lists below it.
    failure = StageFailure(
        stage="salary",
        user_message="first line\n# rogue heading\n- rogue bullet",
    )
    report = _make_report(salary=failure, statuses=_statuses(salary="failed"))
    out = render_markdown(report)
    # All three lines are inside the blockquote.
    assert "> ⚠ first line" in out
    assert "> # rogue heading" in out
    assert "> - rogue bullet" in out
    # Lines do NOT appear unquoted (which would render as a real heading).
    assert "\n# rogue heading" not in out
    assert "\n- rogue bullet" not in out


@pytest.mark.fast
def test_render_markdown_salary_reasoning_cannot_inject_heading() -> None:
    # `salary.reasoning` newlines must be collapsed so an LLM-controlled
    # `"ok\n# Pwned"` cannot render as an H1.
    salary = SalaryEstimate(
        low=80_000,
        high=120_000,
        currency="CZK",
        period="month",
        sources=[Source(url="https://example.com", snippet="ok", domain="example.com")],
        reasoning="market data ok\n# Injected heading",
    )
    report = _make_report(salary=salary)
    out = render_markdown(report)
    assert "\n# Injected heading" not in out
    assert "market data ok" in out


@pytest.mark.fast
def test_render_markdown_confidence_rationale_cannot_inject_heading() -> None:
    bad = Confidence(tier="Medium", rationale="three sources agree\n# Pwned")
    report = _make_report(confidence=bad)
    out = render_markdown(report)
    assert "\n# Pwned" not in out
    assert "three sources agree" in out


@pytest.mark.fast
def test_render_markdown_growth_action_what_cannot_inject_list() -> None:
    growth = [
        GrowthAction(
            what="learn rust\n- rogue bullet",
            time_horizon_months=6,
            mechanism="ship a small CLI",
            setting="capability_artifact",
            anchor=Anchor(quote="C++ background"),
        )
    ]
    report = _make_report(growth=growth)
    out = render_markdown(report)
    assert "\n- rogue bullet" not in out
    assert "learn rust" in out


@pytest.mark.fast
def test_render_markdown_growth_action_mechanism_cannot_inject_table() -> None:
    growth = [
        GrowthAction(
            what="learn rust",
            time_horizon_months=6,
            mechanism="ship a CLI\n| col | col |\n| --- | --- |",
            setting="capability_artifact",
            anchor=Anchor(quote="C++ background"),
        )
    ]
    report = _make_report(growth=growth)
    out = render_markdown(report)
    assert "\n|" not in out
    assert "ship a CLI" in out


@pytest.mark.fast
def test_render_markdown_source_snippet_cannot_inject_heading() -> None:
    bad = Source(
        url="https://example.com",
        snippet="legit excerpt\n# Pwned",
        domain="example.com",
    )
    salary = SalaryEstimate(
        low=80_000,
        high=120_000,
        currency="CZK",
        period="month",
        sources=[bad],
        reasoning="ok",
    )
    report = _make_report(salary=salary)
    out = render_markdown(report)
    assert "\n# Pwned" not in out
    assert "legit excerpt" in out


# ---------- render_html — inline injection defence ----------


@pytest.mark.fast
def test_render_html_salary_reasoning_does_not_inject_script() -> None:
    # HTML path uses _html_inline; injected <script> must be escaped.
    salary = SalaryEstimate(
        low=80_000,
        high=120_000,
        currency="CZK",
        period="month",
        sources=[Source(url="https://example.com", snippet="ok", domain="example.com")],
        reasoning="ok\n<script>alert(1)</script>",
    )
    report = _make_report(salary=salary)
    out = render_html(report)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


@pytest.mark.fast
def test_render_html_confidence_rationale_does_not_inject_script() -> None:
    bad = Confidence(tier="Medium", rationale="three sources\n<script>alert(1)</script>")
    report = _make_report(confidence=bad)
    out = render_html(report)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


# ---------- _md — block-level markdown injection defence ----------


@pytest.mark.fast
def test_md_collapses_newlines_to_single_space() -> None:
    # Direct unit test on the chokepoint helper. Any newline in an LLM-
    # controlled string must collapse so block-level tokens (`#`, `-`, `+`,
    # `|`, fenced code, table pipes) cannot appear at line-start.
    out = _md("hello\n# Pwned")
    assert "\n" not in out
    assert "\n# Pwned" not in out
    # The escaped text still contains the safe substring and the (now mid-line)
    # `#` character — but it's no longer at line-start, so markdown won't
    # promote it to a heading.
    assert "hello" in out
    assert "# Pwned" in out


@pytest.mark.fast
def test_md_collapses_runs_of_whitespace() -> None:
    # `_md` uses str.split() / " ".join() which also collapses interior
    # whitespace runs. Acceptable because markdown collapses them on render
    # anyway and the inputs are conceptually inline.
    assert _md("a\t\tb") == "a b"
    assert _md("a  \n  b") == "a b"
    assert _md("  leading and trailing  ") == "leading and trailing"


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
