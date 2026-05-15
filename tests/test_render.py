"""Fast unit tests for gander.report (T14).

Fixtures construct fully-valid Report instances so the schema's validators
are exercised. No I/O, no LLM, no network.
"""

from __future__ import annotations

from typing import Literal, cast

import pytest

from gander.errors import StageFailure
from gander.report import _md, render_body, render_tracker
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
        raw_cv_text="",
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
        raw_cv_text="raw cv text",
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
    # First source's domain renders as `[domain]`, NOT as a bare URL. The
    # bracket characters in the template are literal; `_md()` only escapes
    # bracket characters when they appear *inside* the user-controlled domain
    # (covered by test_render_body_escapes_markdown_link_in_source_domain).
    assert "[platy.cz]" in out
    assert "https://platy.cz" not in out
    # Components render as always-visible tiles, not a table+accordion stack.
    assert '<div class="gander-components-grid" role="list">' in out
    assert out.count('class="gander-component"') == 4
    assert 'role="listitem"' in out
    assert '<h3 id="gander-score-skills" class="gander-component-head">' in out
    assert '<blockquote class="gander-component-quote" title=' in out
    assert "<details open>" not in out
    # Plan / growth list renders as structured HTML with horizon chips.
    assert '<ol class="gander-plan">' in out
    assert '<p class="gander-plan-title">learn rust</p>' in out
    assert '<span class="gander-chip" aria-label="Time horizon: 6 months">6 months</span>' in out
    assert "**learn rust**" not in out
    # Confidence badge is visually separated from the rationale.
    assert '<span class="gander-chip" aria-label="Confidence: High">[!] High</span>' in out


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
    assert 'class="gander-component"' in out
    # Salary section is a callout, not a price.
    assert "Insufficient market data for this profile" in out
    assert "CZK" not in out
    # Confidence + plan still render.
    assert '<span class="gander-chip" aria-label="Confidence: High">[!] High</span>' in out
    assert '<p class="gander-plan-title">learn rust</p>' in out


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
def test_render_body_renders_failure_copy_for_each_stage(
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

    out = render_body(report)

    assert message in out
    assert "Traceback" not in out


@pytest.mark.fast
def test_render_body_partial_score_shows_dropped_footer() -> None:
    # T25: partial Score renders only surviving components in the table and a
    # one-line italic footer naming the dropped categories. The total reflects
    # drop-as-zero arithmetic; the reviewer can see why the score is depressed
    # without us silently omitting categories.
    partial_score = Score(
        components=[
            _component("experience", 80),
            _component("education", 60),
            _component("soft_signals", 40),
        ],
        dropped=["skills"],
    )
    report = _make_report(score=partial_score)
    out = render_body(report)

    # Total: 80*0.30 + 60*0.20 + 40*0.15 = 24 + 12 + 6 = 42.
    assert "## Score: 42/100" in out
    # Surviving component labels render as tiles; dropped one absent.
    for label in ("Experience", "Education", "Soft"):
        assert f">{label} <span" in out
    assert ">Skills <span" not in out
    # Italic dropped-components footer (matches T25 §Deliverables wording).
    assert "1 component(s) dropped (Skills)" in out
    assert "no anchor verified against CV text" in out


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
    assert '<span class="gander-chip" aria-label="Confidence: High">[!] High</span>' in out
    assert '<p class="gander-plan-title">learn rust</p>' in out


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
    assert '<p class="gander-plan-title">learn rust</p>' in out


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
    assert '<span class="gander-chip" aria-label="Confidence: High">[!] High</span>' in out


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


@pytest.mark.fast
def test_render_body_footer_interpolates_cost_and_latency_totals() -> None:
    # Pipeline (T15) populates total_cost_usd / total_latency_ms; footer must
    # reflect them rather than the legacy "populated by T15" placeholder.
    report = Report(
        profile=_profile(),
        score=_score(),
        salary=_salary(),
        confidence=_confidence(),
        growth=_growth(),
        statuses=_statuses(),
        raw_cv_text="x",
        total_cost_usd=0.0234,
        total_latency_ms=12_345,
    )
    out = render_body(report)
    assert "$0.0234" in out
    assert "12,345 ms" in out
    # Legacy placeholder gone.
    assert "populated by T15" not in out


# ---------- render_body — None = pending (T15 streaming) ----------


@pytest.mark.fast
def test_render_body_profile_none_returns_empty_string() -> None:
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
        raw_cv_text="",
    )
    assert render_body(report) == ""


@pytest.mark.fast
def test_render_body_skips_none_blocks_but_renders_completed_ones() -> None:
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
        raw_cv_text="x",
    )
    out = render_body(report)
    # Score section rendered.
    assert "## Score: 69/100" in out
    # No salary/confidence/plan sections (None ⇒ skipped).
    assert "## Salary" not in out
    assert "## Confidence" not in out
    assert "## Plan" not in out
    # Footer still renders (it always does for a populated profile).
    assert "How is this scored?" in out


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


# ---------- render_body — markdown-injection defence ----------


@pytest.mark.fast
def test_render_body_escapes_markdown_link_in_source_domain() -> None:
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
    out = render_body(report)
    # The escaped bracket sequence survives; the unescaped `](javascript:` form
    # is gone, so no link target can be forged in the rendered markdown.
    assert "](javascript:" not in out
    assert "\\]\\(javascript:alert\\(1\\)\\)" in out


@pytest.mark.fast
def test_render_body_escapes_markdown_link_in_source_snippet() -> None:
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
    out = render_body(report)
    assert "](javascript:" not in out
    assert "\\[docs\\]\\(javascript:alert\\(1\\)\\)" in out


@pytest.mark.fast
@pytest.mark.parametrize(
    "field",
    ["reasoning", "rationale", "growth_what", "growth_mechanism"],
)
def test_render_body_escapes_markdown_link_payload_in_body_fields(field: str) -> None:
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
                anchor=Anchor(quote="C++ background"),
            )
        ]
    elif field == "growth_mechanism":
        kwargs["growth"] = [
            GrowthAction(
                what="learn rust",
                time_horizon_months=6,
                mechanism=payload,
                anchor=Anchor(quote="C++ background"),
            )
        ]
    report = _make_report(**kwargs)  # type: ignore[arg-type]
    out = render_body(report)
    assert "](javascript:" not in out
    assert "[here]" not in out


@pytest.mark.fast
def test_render_body_multiline_failure_message_stays_quoted() -> None:
    # Every line of a multi-line user_message must remain inside the
    # blockquote, otherwise lines starting with `#`, `-`, `*` etc. would break
    # the callout and render as headings/lists below it.
    failure = StageFailure(
        stage="salary",
        user_message="first line\n# rogue heading\n- rogue bullet",
    )
    report = _make_report(salary=failure, statuses=_statuses(salary="failed"))
    out = render_body(report)
    # All three lines are inside the blockquote.
    assert "> ⚠ first line" in out
    assert "> # rogue heading" in out
    assert "> - rogue bullet" in out
    # Lines do NOT appear unquoted (which would render as a real heading).
    assert "\n# rogue heading" not in out
    assert "\n- rogue bullet" not in out


# ---------- _md — block-level markdown injection defence (PR #7 heal) ----------


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


@pytest.mark.fast
def test_render_body_salary_reasoning_cannot_inject_heading() -> None:
    # `salary.reasoning` is interpolated at line-start after `\n\n`; without
    # newline collapse, a model-controlled `"ok\n# Pwned"` would render as
    # an H1 in the body. Guard.
    salary = SalaryEstimate(
        low=80_000,
        high=120_000,
        currency="CZK",
        period="month",
        sources=[Source(url="https://example.com", snippet="ok", domain="example.com")],
        reasoning="market data ok\n# Injected heading",
    )
    report = _make_report(salary=salary)
    out = render_body(report)
    assert "\n# Injected heading" not in out
    assert "market data ok" in out


@pytest.mark.fast
def test_render_body_confidence_rationale_cannot_inject_heading() -> None:
    bad = Confidence(tier="Medium", rationale="three sources agree\n# Pwned")
    report = _make_report(confidence=bad)
    out = render_body(report)
    assert "\n# Pwned" not in out
    assert "three sources agree" in out


@pytest.mark.fast
def test_render_body_growth_action_what_cannot_inject_list() -> None:
    growth = [
        GrowthAction(
            what="learn rust\n- rogue bullet",
            time_horizon_months=6,
            mechanism="ship a small CLI",
            anchor=Anchor(quote="C++ background"),
        )
    ]
    report = _make_report(growth=growth)
    out = render_body(report)
    assert "\n- rogue bullet" not in out
    assert "learn rust" in out


@pytest.mark.fast
def test_render_body_growth_action_mechanism_cannot_inject_table() -> None:
    growth = [
        GrowthAction(
            what="learn rust",
            time_horizon_months=6,
            mechanism="ship a CLI\n| col | col |\n| --- | --- |",
            anchor=Anchor(quote="C++ background"),
        )
    ]
    report = _make_report(growth=growth)
    out = render_body(report)
    assert "\n|" not in out
    assert "ship a CLI" in out


@pytest.mark.fast
def test_render_body_source_snippet_cannot_inject_heading() -> None:
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
    out = render_body(report)
    assert "\n# Pwned" not in out
    assert "legit excerpt" in out


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
