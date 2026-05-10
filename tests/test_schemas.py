import pytest
from pydantic import ValidationError

from jobfit.errors import StageFailure, stage_boundary
from jobfit.schemas import (
    Anchor,
    Component,
    Confidence,
    GrowthAction,
    Profile,
    ProfileItem,
    Report,
    SalaryEstimate,
    Score,
    Source,
)


def _component(name: str, score: int) -> Component:
    return Component(
        name=name,  # type: ignore[arg-type]
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
            anchor=Anchor(quote="C++ background"),
        )
    ]


def _statuses() -> dict[str, str]:
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
def test_growth_action_rejects_out_of_range_months() -> None:
    GrowthAction(
        what="x",
        time_horizon_months=12,
        mechanism="y",
        anchor=Anchor(quote="z"),
    )
    with pytest.raises(ValidationError):
        GrowthAction(
            what="x",
            time_horizon_months=0,
            mechanism="y",
            anchor=Anchor(quote="z"),
        )
    with pytest.raises(ValidationError):
        GrowthAction(
            what="x",
            time_horizon_months=25,
            mechanism="y",
            anchor=Anchor(quote="z"),
        )


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
        statuses=_statuses(),  # type: ignore[arg-type]
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
def test_stage_boundary_catches_exception_and_yields_failure() -> None:
    with stage_boundary("test_stage") as cm:
        raise RuntimeError("boom")

    assert cm.failure is not None
    assert cm.failure.stage == "test_stage"
    assert cm.failure.user_message == "boom"
    assert cm.failure.debug_detail and "RuntimeError" in cm.failure.debug_detail
