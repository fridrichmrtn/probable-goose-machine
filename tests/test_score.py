from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from gander.errors import StageFailure
from gander.llm import LLMClient
from gander.obs import subscribe
from gander.schemas import (
    Anchor,
    Component,
    Profile,
    ProfileItem,
    RedactedCV,
    Score,
)
from gander.score import _ComponentList, score_profile

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "cvs"
JUNIOR_FIXTURE = FIXTURE_DIR / "01_junior_da_novotny.txt"
SENIOR_FIXTURE = FIXTURE_DIR / "08_staff_ml_engineer_dvorak.txt"


@pytest.mark.fast
def test_score_total_is_deterministic_weighted_sum() -> None:
    score = Score(
        components=[
            Component(name="skills", score_0_100=80, justification=".", anchor=Anchor(quote="x")),
            Component(
                name="experience", score_0_100=60, justification=".", anchor=Anchor(quote="x")
            ),
            Component(
                name="education", score_0_100=40, justification=".", anchor=Anchor(quote="x")
            ),
            Component(
                name="soft_signals", score_0_100=100, justification=".", anchor=Anchor(quote="x")
            ),
        ]
    )
    # 80*0.35 + 60*0.30 + 40*0.20 + 100*0.15 = 28 + 18 + 8 + 15 = 69
    assert score.total == 69


@pytest.mark.fast
async def test_score_returns_stage_failure_when_anchor_unverifiable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cv_text = (
        "## Work Experience\n"
        "Built a recommendation system that reduced churn by eighteen percent.\n"
        "Mentored four junior engineers across two squads in the platform team.\n"
        "## Education\n"
        "MSc in Computer Science, accredited university, two thousand eighteen.\n"
        "## Skills\n"
        "Python, PyTorch, async pipelines, vector databases, distributed systems work.\n"
    )
    redacted = RedactedCV(text=cv_text, audit_log=[])
    item = ProfileItem(text="x", anchor=Anchor(quote="recommendation system that reduced churn by"))
    profile = Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="engineer",
        detected_location=None,
        detected_years_experience=5,
    )

    payload = _ComponentList(
        components=[
            Component(
                name="skills",
                score_0_100=70,
                justification=".",
                anchor=Anchor(
                    quote="python, pytorch, async pipelines, vector databases",
                    section="Skills",
                ),
            ),
            Component(
                name="experience",
                score_0_100=65,
                justification=".",
                anchor=Anchor(
                    quote="recommendation system that reduced churn by",
                    section="Work Experience",
                ),
            ),
            # This one is unverifiable: paraphrased, not a substring of cv_text.
            Component(
                name="education",
                score_0_100=55,
                justification=".",
                anchor=Anchor(
                    quote="masters degree in computer science earned in twenty eighteen",
                    section="Education",
                ),
            ),
            Component(
                name="soft_signals",
                score_0_100=60,
                justification=".",
                anchor=Anchor(
                    quote="mentored four junior engineers across two squads",
                    section="Work Experience",
                ),
            ),
        ]
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-stub")

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await score_profile(redacted, profile)
    assert isinstance(result, StageFailure)
    assert result.stage == "score"
    assert "scoring components" in result.user_message.lower()

    # Observability: the failure path must emit both the components counter
    # and an explicit stage_failure event (PRD §4.8 — every stage failure
    # carries stage + reason in the log stream).
    components_evt = next(e for e in events if e["event"] == "score_components")
    assert components_evt["stage"] == "score"
    assert components_evt["dropped"] >= 1
    assert components_evt["verified"] == 3
    failure_evt = next(e for e in events if e["event"] == "stage_failure")
    assert failure_evt["stage"] == "score"
    assert failure_evt["reason"] == "missing_categories"
    assert failure_evt["missing"] == ["education"]


@pytest.mark.fast
async def test_score_returns_stage_failure_when_llm_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redacted = RedactedCV(text="## Skills\nPython, PyTorch, async pipelines.\n", audit_log=[])
    item = ProfileItem(text="x", anchor=Anchor(quote="x"))
    profile = Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="engineer",
        detected_location=None,
        detected_years_experience=5,
    )

    async def raising_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        raise RuntimeError("minimax 429 throttled")

    monkeypatch.setattr(LLMClient, "complete_json", raising_complete_json)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-stub")

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await score_profile(redacted, profile)

    # PRD §4.6 verbatim copy for generation failures — the bare `assert isinstance`
    # used to smuggle the LLM's exception text into the user_message via
    # stage_boundary's `str(exc)` default. Closes Copilot finding on score.py:51.
    assert isinstance(result, StageFailure)
    assert result.stage == "score"
    assert result.user_message == "Could not generate this section reliably"

    failure_evt = next(e for e in events if e["event"] == "stage_failure")
    assert failure_evt["stage"] == "score"
    assert failure_evt["reason"] == "llm_error"
    assert failure_evt["exc_type"] == "RuntimeError"


@pytest.mark.fast
async def test_score_returns_stage_failure_on_invalid_llm_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redacted = RedactedCV(text="## Skills\nPython, PyTorch.\n", audit_log=[])
    item = ProfileItem(text="x", anchor=Anchor(quote="x"))
    profile = Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="engineer",
        detected_location=None,
        detected_years_experience=5,
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return {"components": []}  # plain dict, not a `_ComponentList`

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-stub")

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await score_profile(redacted, profile)

    assert isinstance(result, StageFailure)
    assert result.stage == "score"
    assert result.user_message == "Could not generate this section reliably"
    failure_evt = next(e for e in events if e["event"] == "stage_failure")
    assert failure_evt["reason"] == "invalid_llm_output"
    assert failure_evt["got_type"] == "dict"


@pytest.mark.live
@pytest.mark.xfail(
    strict=False,
    reason=(
        "T10 Outcome defers calibration to T17 acceptance — MiniMax-M2.7 currently "
        "paraphrases anchors, so verify_quote drops all 4 components and the stage "
        "fails closed. Tracked in tasks/T10_score.md §Outcome and T17_acceptance.md. "
        "Once T17 lands the prompt-or-verify calibration, this will XPASS and the "
        "marker can come off."
    ),
)
async def test_junior_fixture_scores_below_40() -> None:
    cv_text = JUNIOR_FIXTURE.read_text(encoding="utf-8")
    redacted = RedactedCV(text=cv_text, audit_log=[])
    item = ProfileItem(text="placeholder", anchor=Anchor(quote="placeholder"))
    profile = Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="Junior Data Analyst",
        detected_location="Prague",
        detected_years_experience=1,
    )
    result = await score_profile(redacted, profile)
    assert isinstance(result, Score), f"expected Score, got {type(result).__name__}: {result}"
    assert result.total < 40, f"junior fixture scored {result.total}, expected <40"


@pytest.mark.live
@pytest.mark.xfail(
    strict=False,
    reason=(
        "T10 Outcome defers calibration to T17 acceptance — MiniMax-M2.7 currently "
        "paraphrases anchors, so verify_quote drops all 4 components and the stage "
        "fails closed. Tracked in tasks/T10_score.md §Outcome and T17_acceptance.md. "
        "Once T17 lands the prompt-or-verify calibration, this will XPASS and the "
        "marker can come off."
    ),
)
async def test_senior_fixture_scores_above_70() -> None:
    cv_text = SENIOR_FIXTURE.read_text(encoding="utf-8")
    redacted = RedactedCV(text=cv_text, audit_log=[])
    item = ProfileItem(text="placeholder", anchor=Anchor(quote="placeholder"))
    profile = Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="Staff Machine Learning Engineer",
        detected_location="Prague",
        detected_years_experience=13,
    )
    result = await score_profile(redacted, profile)
    assert isinstance(result, Score), f"expected Score, got {type(result).__name__}: {result}"
    assert result.total > 70, f"senior fixture scored {result.total}, expected >70"


@pytest.mark.live
@pytest.mark.slow
async def test_score_calibration_variance_on_mid_fixture() -> None:
    pytest.skip("no mid fixture authored yet — covered by T17 acceptance once T06 lands")
