import pytest
from pydantic import ValidationError

from gander.errors import StageFailure, stage_boundary
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


def _component(name: ComponentName, score: int) -> Component:
    return Component(
        name=name,
        score_0_100=score,
        justification=".",
        anchor=Anchor(quote="x"),
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
        sources=[Source(url="https://example.com", snippet="...", domain="example.com")],
        reasoning="market data",
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
        )
    ]


def _statuses() -> dict[StageName, StageStatus]:
    return {
        "profile": "done",
        "score": "done",
        "salary": "done",
        "confidence": "done",
        "growth": "done",
    }


@pytest.mark.fast
def test_score_total_recomputes_from_components_and_weights() -> None:
    score = _score()
    # 80*0.35 + 60*0.30 + 40*0.20 + 100*0.15 = 28 + 18 + 8 + 15 = 69
    assert score.total == 69


@pytest.mark.fast
def test_score_total_rounds_half_up() -> None:
    score = Score(
        components=[
            _component("skills", 2),
            _component("experience", 6),
            _component("education", 0),
            _component("soft_signals", 0),
        ]
    )
    # 2*0.35 + 6*0.30 = 2.5; half-up keeps calibration deterministic.
    assert score.total == 3


@pytest.mark.fast
def test_score_rejects_duplicate_component_names() -> None:
    with pytest.raises(ValidationError):
        Score(
            components=[
                _component("skills", 80),
                _component("skills", 70),
                _component("experience", 60),
                _component("education", 40),
                _component("soft_signals", 100),
            ]
        )


@pytest.mark.fast
def test_score_rejects_missing_experience_component() -> None:
    # T25: experience is the only mandatory category. The Score model accepts
    # any subset of {skills, education, soft_signals} via `dropped`, but a
    # score without `experience` has no anchor against the CV — reject at
    # the schema layer so the partial-score path never produces this state.
    with pytest.raises(ValidationError):
        Score(
            components=[
                _component("skills", 80),
                _component("education", 40),
                _component("soft_signals", 100),
            ]
        )


@pytest.mark.fast
def test_score_accepts_partial_components_with_dropped() -> None:
    # T25: experience-only Score is valid when {skills, education, soft_signals}
    # all dropped. Total reflects the surviving weighted contribution alone.
    score = Score(
        components=[_component("experience", 80)],
        dropped=["skills", "education", "soft_signals"],
    )
    # 80 * 0.30 = 24.0 → int(24.0 + 0.5) = 24.
    assert score.total == 24
    assert score.dropped == ["skills", "education", "soft_signals"]


@pytest.mark.fast
def test_growth_action_rejects_out_of_range_months() -> None:
    GrowthAction(
        what="x",
        time_horizon_months=12,
        mechanism="y",
        setting="capability_artifact",
        anchor=Anchor(quote="z"),
    )
    with pytest.raises(ValidationError):
        GrowthAction(
            what="x",
            time_horizon_months=0,
            mechanism="y",
            setting="capability_artifact",
            anchor=Anchor(quote="z"),
        )
    with pytest.raises(ValidationError):
        GrowthAction(
            what="x",
            time_horizon_months=25,
            mechanism="y",
            setting="capability_artifact",
            anchor=Anchor(quote="z"),
        )


@pytest.mark.fast
def test_profile_rejects_out_of_range_years_experience() -> None:
    item = ProfileItem(text="python", anchor=Anchor(quote="Python"))
    with pytest.raises(ValidationError):
        Profile(
            skills=[item],
            experience=[item],
            education=[item],
            soft_signals=[item],
            detected_role="engineer",
            detected_location=None,
            detected_years_experience=71,
        )


@pytest.mark.fast
def test_salary_estimate_rejects_inverted_range() -> None:
    with pytest.raises(ValidationError):
        SalaryEstimate(
            low=120_000,
            high=80_000,
            currency="CZK",
            period="month",
            sources=[Source(url="https://example.com", snippet="...", domain="example.com")],
            reasoning="market data",
        )


@pytest.mark.fast
def test_salary_estimate_rejects_empty_sources() -> None:
    """An empty `sources` list must fail schema validation.

    `salary.estimate_salary` would reject it downstream anyway (the
    URL-in-inputs filter on line ~255 produces `StageFailure(... model_urls=[])`),
    but enforcing the invariant at the schema layer lets
    `LLMClient.complete_json`'s ValidationError-retry loop recover the rare
    LLM sample that drops the field instead of bubbling the failure to
    the user. See `tests/test_acceptance.py::test_salary_ranges_dont_overlap`
    for the regression this guards against.
    """
    with pytest.raises(ValidationError):
        SalaryEstimate(
            low=80_000,
            high=120_000,
            currency="CZK",
            period="month",
            sources=[],
            reasoning="market data",
        )


@pytest.mark.fast
def test_salary_source_rejects_non_url() -> None:
    with pytest.raises(ValidationError):
        Source(url="not a url", snippet="...", domain="example.com")


@pytest.mark.fast
@pytest.mark.parametrize(
    "failed_field",
    ["profile", "score", "salary", "confidence", "growth"],
)
def test_report_accepts_stage_failure_in_each_block(failed_field: str) -> None:
    failure = StageFailure(stage=failed_field, user_message="boom")
    blocks: dict[str, object] = {
        "profile": _profile(),
        "score": _score(),
        "salary": _salary(),
        "confidence": _confidence(),
        "growth": _growth(),
    }
    blocks[failed_field] = failure

    report = Report(
        profile=blocks["profile"],  # type: ignore[arg-type]
        score=blocks["score"],  # type: ignore[arg-type]
        salary=blocks["salary"],  # type: ignore[arg-type]
        confidence=blocks["confidence"],  # type: ignore[arg-type]
        growth=blocks["growth"],  # type: ignore[arg-type]
        statuses=_statuses(),
        raw_cv_text="...",
    )

    assert isinstance(getattr(report, failed_field), StageFailure)
    expected_types = {
        "profile": Profile,
        "score": Score,
        "salary": SalaryEstimate,
        "confidence": Confidence,
        "growth": list,
    }
    for name, typ in expected_types.items():
        if name == failed_field:
            continue
        assert isinstance(getattr(report, name), typ)


@pytest.mark.fast
def test_report_statuses_require_known_complete_keys_and_allow_skipped() -> None:
    report = Report(
        profile=_profile(),
        score=_score(),
        salary=_salary(),
        confidence=_confidence(),
        growth=_growth(),
        statuses={
            "profile": "done",
            "score": "done",
            "salary": "failed",
            "confidence": "skipped",
            "growth": "done",
        },
        raw_cv_text="...",
    )

    assert report.statuses["confidence"] == "skipped"

    missing = _statuses()
    missing.pop("growth")
    with pytest.raises(ValidationError):
        Report(
            profile=_profile(),
            score=_score(),
            salary=_salary(),
            confidence=_confidence(),
            growth=_growth(),
            statuses=missing,
            raw_cv_text="...",
        )

    extra: dict[str, str] = {**_statuses(), "ingest": "done"}
    with pytest.raises(ValidationError):
        Report(
            profile=_profile(),
            score=_score(),
            salary=_salary(),
            confidence=_confidence(),
            growth=_growth(),
            statuses=extra,  # type: ignore[arg-type]
            raw_cv_text="...",
        )


@pytest.mark.fast
def test_report_accepts_none_blocks_for_pipeline_streaming() -> None:
    # T15 pipeline yields intermediate states where downstream blocks have not
    # run yet; None represents "pending". Schema must accept None for every block.
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
    assert report.profile is None
    assert report.score is None
    assert report.salary is None
    assert report.confidence is None
    assert report.growth is None
    # Cost/latency aggregates default to zero before any llm_call fires.
    assert report.total_cost_usd == 0.0
    assert report.total_latency_ms == 0


@pytest.mark.fast
def test_report_carries_cost_and_latency_totals() -> None:
    report = Report(
        statuses=_statuses(),
        raw_cv_text="",
        total_cost_usd=0.0123,
        total_latency_ms=4567,
    )
    assert report.total_cost_usd == pytest.approx(0.0123)
    assert report.total_latency_ms == 4567


@pytest.mark.fast
def test_stage_boundary_catches_exception_and_yields_failure() -> None:
    with stage_boundary("test_stage") as cm:
        raise RuntimeError("boom")

    assert cm.failure is not None
    assert cm.failure.stage == "test_stage"
    assert cm.failure.user_message == "Could not complete this stage reliably"
    assert cm.failure.debug_detail and "RuntimeError" in cm.failure.debug_detail
