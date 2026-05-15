from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from gander.errors import StageFailure
from gander.llm import LLMClient
from gander.obs import subscribe
from gander.schemas import (
    COMPONENT_WEIGHTS,
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
PHD_FIXTURE = FIXTURE_DIR / "09_research_phd_marek.txt"


def _missing_provider_key() -> bool:
    provider = os.environ.get("GANDER_LLM_PROVIDER", "openrouter")
    if provider == "openrouter":
        return not bool(os.environ.get("OPENROUTER_API_KEY"))
    return False


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
def test_score_prompt_pins_education_credential_bands() -> None:
    body = (REPO_ROOT / "src" / "gander" / "prompts" / "score.md").read_text(encoding="utf-8")

    assert "86–100 Doctorate completed" in body
    assert "Multiple advanced degrees" in body
    assert "Score on the HIGHEST credential" in body
    assert "Do not score this component on prestige" in body


# Shared CV body for the T25 partial-score scenarios. Each section header is
# present so verify_quote's section-restricted path hits cleanly (no fallback,
# no section_miss events) — the partial behaviour comes purely from which
# anchor quotes verify, not from header misalignment.
_T25_CV = (
    "## Work Experience\n"
    "Built a recommendation system that reduced churn by eighteen percent.\n"
    "Mentored four junior engineers across two squads in the platform team.\n"
    "## Education\n"
    "MSc in Computer Science, accredited university, two thousand eighteen.\n"
    "## Skills\n"
    "Python, PyTorch, async pipelines, vector databases, distributed systems work.\n"
)


def _t25_profile() -> Profile:
    item = ProfileItem(text="x", anchor=Anchor(quote="recommendation system that reduced churn by"))
    return Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="engineer",
        detected_location=None,
        detected_years_experience=5,
    )


# Anchor quotes that DO substring-match _T25_CV under their respective sections.
_VERIFIES_SKILLS = Anchor(
    quote="python, pytorch, async pipelines, vector databases", section="Skills"
)
_VERIFIES_EXPERIENCE = Anchor(
    quote="recommendation system that reduced churn by", section="Work Experience"
)
_VERIFIES_EDUCATION = Anchor(
    quote="msc in computer science, accredited university", section="Education"
)
_VERIFIES_SOFT = Anchor(
    quote="mentored four junior engineers across two squads", section="Work Experience"
)


@pytest.mark.fast
async def test_score_no_partial_when_all_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # T25 regression: 4-of-4 verify path must NOT take the partial branch.
    # `score_partial` must NOT fire; `Score.dropped` must be empty.
    payload = _ComponentList(
        components=[
            Component(name="skills", score_0_100=70, justification=".", anchor=_VERIFIES_SKILLS),
            Component(
                name="experience", score_0_100=65, justification=".", anchor=_VERIFIES_EXPERIENCE
            ),
            Component(
                name="education", score_0_100=55, justification=".", anchor=_VERIFIES_EDUCATION
            ),
            Component(
                name="soft_signals", score_0_100=60, justification=".", anchor=_VERIFIES_SOFT
            ),
        ]
    )

    captured: dict[str, Any] = {}

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    redacted = RedactedCV(text=_T25_CV, audit_log=[])
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await score_profile(redacted, _t25_profile())

    assert isinstance(result, Score)
    assert result.dropped == []
    assert {c.name for c in result.components} == set(
        ("skills", "experience", "education", "soft_signals")
    )
    assert not any(e["event"] == "score_partial" for e in events)
    assert captured["max_tokens"] == 1024
    components_evt = next(e for e in events if e["event"] == "score_components")
    assert components_evt["verified"] == 4
    assert components_evt["dropped"] == 0
    done_evt = next(e for e in events if e["event"] == "done" and e["stage"] == "score")
    assert isinstance(done_evt["duration_ms"], int)
    assert done_evt["duration_ms"] >= 0
    assert done_evt["total"] == result.total


@pytest.mark.fast
async def test_score_partial_missing_skills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # T25: skills anchor paraphrased → only 3-of-4 verify. Result is a Score
    # with dropped=["skills"], total reflects the weighted sum of survivors
    # with skills contributing 0 (no re-normalization).
    payload = _ComponentList(
        components=[
            # Paraphrase — won't match _T25_CV under the Skills section.
            Component(
                name="skills",
                score_0_100=70,
                justification=".",
                anchor=Anchor(
                    quote="rust, kafka, redis, distributed cache, message bus",
                    section="Skills",
                ),
            ),
            Component(
                name="experience", score_0_100=65, justification=".", anchor=_VERIFIES_EXPERIENCE
            ),
            Component(
                name="education", score_0_100=55, justification=".", anchor=_VERIFIES_EDUCATION
            ),
            Component(
                name="soft_signals", score_0_100=60, justification=".", anchor=_VERIFIES_SOFT
            ),
        ]
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    redacted = RedactedCV(text=_T25_CV, audit_log=[])
    result = await score_profile(redacted, _t25_profile())

    assert isinstance(result, Score)
    assert result.dropped == ["skills"]
    assert {c.name for c in result.components} == {"experience", "education", "soft_signals"}
    # Drop-as-zero: 65*0.30 + 55*0.20 + 60*0.15 = 19.5 + 11.0 + 9.0 = 39.5 → 40.
    assert result.total == 40


@pytest.mark.fast
async def test_score_partial_missing_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # T25: skills + education both paraphrased; experience + soft_signals verify.
    payload = _ComponentList(
        components=[
            Component(
                name="skills",
                score_0_100=70,
                justification=".",
                anchor=Anchor(
                    quote="rust, kafka, redis, distributed cache, message bus",
                    section="Skills",
                ),
            ),
            Component(
                name="experience", score_0_100=65, justification=".", anchor=_VERIFIES_EXPERIENCE
            ),
            Component(
                name="education",
                score_0_100=55,
                justification=".",
                anchor=Anchor(
                    quote="doctorate degree from a prestigious overseas institution finally",
                    section="Education",
                ),
            ),
            Component(
                name="soft_signals", score_0_100=60, justification=".", anchor=_VERIFIES_SOFT
            ),
        ]
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    redacted = RedactedCV(text=_T25_CV, audit_log=[])
    result = await score_profile(redacted, _t25_profile())

    assert isinstance(result, Score)
    assert result.dropped == ["education", "skills"]
    assert {c.name for c in result.components} == {"experience", "soft_signals"}


@pytest.mark.fast
async def test_score_experience_missing_still_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # T25: experience is the only mandatory component. Dropping it must keep
    # the existing fail-closed StageFailure path; the partial branch must NOT
    # activate even though 3 other components verify.
    payload = _ComponentList(
        components=[
            Component(name="skills", score_0_100=70, justification=".", anchor=_VERIFIES_SKILLS),
            Component(
                name="experience",
                score_0_100=65,
                justification=".",
                anchor=Anchor(
                    quote="led a transformational programme across six business units",
                    section="Work Experience",
                ),
            ),
            Component(
                name="education", score_0_100=55, justification=".", anchor=_VERIFIES_EDUCATION
            ),
            Component(
                name="soft_signals", score_0_100=60, justification=".", anchor=_VERIFIES_SOFT
            ),
        ]
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    redacted = RedactedCV(text=_T25_CV, audit_log=[])
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await score_profile(redacted, _t25_profile())

    assert isinstance(result, StageFailure)
    assert result.stage == "score"
    assert "scoring components" in result.user_message.lower()
    failure_evt = next(e for e in events if e["event"] == "stage_failure")
    assert failure_evt["reason"] == "missing_categories"
    assert "experience" in failure_evt["missing"]
    assert not any(e["event"] == "score_partial" for e in events)


@pytest.mark.fast
async def test_score_retries_when_experience_anchor_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_payload = _ComponentList(
        components=[
            Component(name="skills", score_0_100=70, justification=".", anchor=_VERIFIES_SKILLS),
            Component(
                name="experience",
                score_0_100=65,
                justification=".",
                anchor=Anchor(
                    quote="led a transformational programme across six business units",
                    section="Work Experience",
                ),
            ),
            Component(
                name="education", score_0_100=55, justification=".", anchor=_VERIFIES_EDUCATION
            ),
            Component(
                name="soft_signals", score_0_100=60, justification=".", anchor=_VERIFIES_SOFT
            ),
        ]
    )
    second_payload = _ComponentList(
        components=[
            Component(name="skills", score_0_100=70, justification=".", anchor=_VERIFIES_SKILLS),
            Component(
                name="experience", score_0_100=65, justification=".", anchor=_VERIFIES_EXPERIENCE
            ),
            Component(
                name="education", score_0_100=55, justification=".", anchor=_VERIFIES_EDUCATION
            ),
            Component(
                name="soft_signals", score_0_100=60, justification=".", anchor=_VERIFIES_SOFT
            ),
        ]
    )
    payloads = [first_payload, second_payload]
    seen_users: list[str] = []
    seen_max_retries: list[int | None] = []

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        seen_users.append(kwargs["user"])
        seen_max_retries.append(kwargs.get("max_retries"))
        return payloads.pop(0)

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await score_profile(RedactedCV(text=_T25_CV, audit_log=[]), _t25_profile())

    assert isinstance(result, Score)
    assert result.dropped == []
    assert {c.name for c in result.components} == set(COMPONENT_WEIGHTS.keys())
    assert seen_max_retries == [2, 2]
    assert len(seen_users) == 2
    assert "previous score output failed downstream verification" in seen_users[1]
    retry_evt = next(e for e in events if e["event"] == "score_retry")
    assert retry_evt["reason"] == "missing_experience"
    assert retry_evt["missing"] == ["experience"]


@pytest.mark.fast
async def test_score_retries_when_skills_or_soft_signals_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_payload = _ComponentList(
        components=[
            Component(
                name="skills",
                score_0_100=70,
                justification=".",
                anchor=Anchor(
                    quote="rust, kafka, redis, distributed cache, message bus",
                    section="Skills",
                ),
            ),
            Component(
                name="experience", score_0_100=65, justification=".", anchor=_VERIFIES_EXPERIENCE
            ),
            Component(
                name="education", score_0_100=55, justification=".", anchor=_VERIFIES_EDUCATION
            ),
            Component(
                name="soft_signals",
                score_0_100=60,
                justification=".",
                anchor=Anchor(
                    quote="coached principal engineers during an executive roadshow",
                    section="Work Experience",
                ),
            ),
        ]
    )
    second_payload = _ComponentList(
        components=[
            Component(name="skills", score_0_100=70, justification=".", anchor=_VERIFIES_SKILLS),
            Component(
                name="experience", score_0_100=65, justification=".", anchor=_VERIFIES_EXPERIENCE
            ),
            Component(
                name="education", score_0_100=55, justification=".", anchor=_VERIFIES_EDUCATION
            ),
            Component(
                name="soft_signals", score_0_100=60, justification=".", anchor=_VERIFIES_SOFT
            ),
        ]
    )
    payloads = [first_payload, second_payload]
    seen_users: list[str] = []

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        seen_users.append(kwargs["user"])
        return payloads.pop(0)

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await score_profile(RedactedCV(text=_T25_CV, audit_log=[]), _t25_profile())

    assert isinstance(result, Score)
    assert result.dropped == []
    assert {c.name for c in result.components} == set(COMPONENT_WEIGHTS.keys())
    assert len(seen_users) == 2
    assert "compact Skills/Soft sections" in seen_users[1]
    retry_evt = next(e for e in events if e["event"] == "score_retry")
    assert retry_evt["reason"] == "missing_skills_or_soft_signals"
    assert retry_evt["missing"] == ["skills", "soft_signals"]


@pytest.mark.fast
async def test_score_retries_when_education_anchor_drops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_payload = _ComponentList(
        components=[
            Component(name="skills", score_0_100=70, justification=".", anchor=_VERIFIES_SKILLS),
            Component(
                name="experience", score_0_100=65, justification=".", anchor=_VERIFIES_EXPERIENCE
            ),
            Component(
                name="education",
                score_0_100=55,
                justification=".",
                anchor=Anchor(
                    quote="masters degree from an elite technical university overseas",
                    section="Education",
                ),
            ),
            Component(
                name="soft_signals", score_0_100=60, justification=".", anchor=_VERIFIES_SOFT
            ),
        ]
    )
    second_payload = _ComponentList(
        components=[
            Component(name="skills", score_0_100=70, justification=".", anchor=_VERIFIES_SKILLS),
            Component(
                name="experience", score_0_100=65, justification=".", anchor=_VERIFIES_EXPERIENCE
            ),
            Component(
                name="education", score_0_100=55, justification=".", anchor=_VERIFIES_EDUCATION
            ),
            Component(
                name="soft_signals", score_0_100=60, justification=".", anchor=_VERIFIES_SOFT
            ),
        ]
    )
    payloads = [first_payload, second_payload]
    seen_users: list[str] = []

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        seen_users.append(kwargs["user"])
        return payloads.pop(0)

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await score_profile(RedactedCV(text=_T25_CV, audit_log=[]), _t25_profile())

    assert isinstance(result, Score)
    assert result.dropped == []
    assert {c.name for c in result.components} == set(COMPONENT_WEIGHTS.keys())
    assert len(seen_users) == 2
    assert "exact literal degree/institution line" in seen_users[1]
    assert "compact Skills/Soft sections" not in seen_users[1]
    retry_evt = next(e for e in events if e["event"] == "score_retry")
    assert retry_evt["reason"] == "missing_education"
    assert retry_evt["missing"] == ["education"]


@pytest.mark.fast
async def test_score_retry_preserves_previously_verified_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # PR #28 review (Copilot): the salvage retry must not regress a
    # previously-valid partial score. Attempt 0 verifies experience+education
    # but drops skills+soft_signals → retry fires. Attempt 1 lands skills+
    # soft_signals but paraphrases the experience anchor. With per-attempt
    # `verified`, the second response would collapse into a "missing_experience"
    # StageFailure; with best-of merge, all four components survive.
    first_payload = _ComponentList(
        components=[
            Component(
                name="skills",
                score_0_100=70,
                justification=".",
                anchor=Anchor(
                    quote="rust, kafka, redis, distributed cache, message bus",
                    section="Skills",
                ),
            ),
            Component(
                name="experience", score_0_100=65, justification=".", anchor=_VERIFIES_EXPERIENCE
            ),
            Component(
                name="education", score_0_100=55, justification=".", anchor=_VERIFIES_EDUCATION
            ),
            Component(
                name="soft_signals",
                score_0_100=60,
                justification=".",
                anchor=Anchor(
                    quote="coached principal engineers during an executive roadshow",
                    section="Work Experience",
                ),
            ),
        ]
    )
    second_payload = _ComponentList(
        components=[
            Component(name="skills", score_0_100=70, justification=".", anchor=_VERIFIES_SKILLS),
            Component(
                name="experience",
                score_0_100=65,
                justification=".",
                anchor=Anchor(
                    quote="led a transformational programme across six business units",
                    section="Work Experience",
                ),
            ),
            Component(
                name="education",
                score_0_100=55,
                justification=".",
                anchor=Anchor(
                    quote="doctorate degree from a prestigious overseas institution finally",
                    section="Education",
                ),
            ),
            Component(
                name="soft_signals", score_0_100=60, justification=".", anchor=_VERIFIES_SOFT
            ),
        ]
    )
    payloads = [first_payload, second_payload]

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payloads.pop(0)

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await score_profile(RedactedCV(text=_T25_CV, audit_log=[]), _t25_profile())

    assert isinstance(result, Score)
    assert result.dropped == []
    assert {c.name for c in result.components} == set(COMPONENT_WEIGHTS.keys())
    # Components must come from whichever attempt verified them.
    components_by_name = {c.name: c for c in result.components}
    assert components_by_name["experience"].anchor.quote == _VERIFIES_EXPERIENCE.quote
    assert components_by_name["education"].anchor.quote == _VERIFIES_EDUCATION.quote
    assert components_by_name["skills"].anchor.quote == _VERIFIES_SKILLS.quote
    assert components_by_name["soft_signals"].anchor.quote == _VERIFIES_SOFT.quote
    assert not any(e["event"] == "stage_failure" for e in events)
    assert not any(e["event"] == "score_partial" for e in events)


@pytest.mark.fast
def test_score_total_arithmetic_drop_as_zero() -> None:
    # Concrete arithmetic per T25_score_partial.md §Deliverables:
    # partial (exp:80, edu:60, soft:40; skills dropped) → 80*0.30 + 60*0.20 +
    # 40*0.15 = 24 + 12 + 6 = 42 → int(42.0 + 0.5) = 42.
    # full-4 baseline same + skills:50 → 42 + 0.35*50 = 59.5 → int(60.0) = 60.
    # Same CV, fewer verified anchors → strictly lower total: the dropped
    # component cannot be a net positive contributor.
    partial = Score(
        components=[
            Component(
                name="experience", score_0_100=80, justification=".", anchor=Anchor(quote="x")
            ),
            Component(
                name="education", score_0_100=60, justification=".", anchor=Anchor(quote="x")
            ),
            Component(
                name="soft_signals", score_0_100=40, justification=".", anchor=Anchor(quote="x")
            ),
        ],
        dropped=["skills"],
    )
    full = Score(
        components=[
            Component(name="skills", score_0_100=50, justification=".", anchor=Anchor(quote="x")),
            Component(
                name="experience", score_0_100=80, justification=".", anchor=Anchor(quote="x")
            ),
            Component(
                name="education", score_0_100=60, justification=".", anchor=Anchor(quote="x")
            ),
            Component(
                name="soft_signals", score_0_100=40, justification=".", anchor=Anchor(quote="x")
            ),
        ],
    )
    assert partial.total == 42
    assert full.total == 60
    assert partial.total < full.total


@pytest.mark.fast
def test_score_partial_no_inflation_vs_full_verification() -> None:
    # Regression guard against accidental re-normalization: a partial Score's
    # total must equal a full Score whose dropped component contributes 0, and
    # must be strictly less than a full Score whose dropped component has any
    # positive score. If anyone re-introduces re-normalization, this test fails
    # immediately because the partial total inflates above the score=0 baseline.
    surviving = [
        Component(name="experience", score_0_100=70, justification=".", anchor=Anchor(quote="x")),
        Component(name="education", score_0_100=60, justification=".", anchor=Anchor(quote="x")),
        Component(name="soft_signals", score_0_100=50, justification=".", anchor=Anchor(quote="x")),
    ]
    partial = Score(components=surviving, dropped=["skills"])
    full_zero = Score(
        components=surviving
        + [Component(name="skills", score_0_100=0, justification=".", anchor=Anchor(quote="x"))]
    )
    full_low = Score(
        components=surviving
        + [Component(name="skills", score_0_100=1, justification=".", anchor=Anchor(quote="x"))]
    )
    full_high = Score(
        components=surviving
        + [Component(name="skills", score_0_100=100, justification=".", anchor=Anchor(quote="x"))]
    )
    # The equality with full_zero is the load-bearing regression guard: under
    # re-normalization, partial would compute ~62 (40.5 / 0.65) and this line
    # immediately reds. The bracket against full_high confirms the cap holds
    # even when the dropped component carries maximum weight.
    assert partial.total == full_zero.total
    # full_low (score_0_100=1) adds 0.35 to the weighted sum — small enough
    # that int(x+0.5) rounding can leave the total unchanged, so the bound is
    # `<=` not `<`. The strict inequality is reserved for full_high below.
    assert partial.total <= full_low.total
    assert partial.total < full_high.total


@pytest.mark.fast
async def test_score_partial_emits_obs_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # PRD §4.8: every emitted event must be CI-protected. This test exists so
    # the `score_partial` event cannot be silently removed or renamed without
    # turning the suite red. Asserts both the dropped/surviving payload shape
    # and the stage attribution.
    payload = _ComponentList(
        components=[
            Component(
                name="skills",
                score_0_100=70,
                justification=".",
                anchor=Anchor(
                    quote="rust, kafka, redis, distributed cache, message bus",
                    section="Skills",
                ),
            ),
            Component(
                name="experience", score_0_100=65, justification=".", anchor=_VERIFIES_EXPERIENCE
            ),
            Component(
                name="education", score_0_100=55, justification=".", anchor=_VERIFIES_EDUCATION
            ),
            Component(
                name="soft_signals", score_0_100=60, justification=".", anchor=_VERIFIES_SOFT
            ),
        ]
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    redacted = RedactedCV(text=_T25_CV, audit_log=[])
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await score_profile(redacted, _t25_profile())

    assert isinstance(result, Score)
    partial_evt = next(e for e in events if e["event"] == "score_partial")
    assert partial_evt["stage"] == "score"
    assert partial_evt["dropped"] == ["skills"]
    assert partial_evt["surviving"] == ["education", "experience", "soft_signals"]


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
        raise RuntimeError("openrouter 429 throttled")

    monkeypatch.setattr(LLMClient, "complete_json", raising_complete_json)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

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
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

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
        "T10 Outcome defers calibration to T17 acceptance — OpenRouter currently "
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
        "T10 Outcome defers calibration to T17 acceptance — OpenRouter currently "
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
@pytest.mark.skipif(
    _missing_provider_key(),
    reason="live score regression requires OPENROUTER_API_KEY",
)
async def test_phd_fixture_education_lands_in_doctorate_band() -> None:
    # T47: the score.md education rubric maps a completed doctorate to 86–100
    # and pushes multi-degree CVs (here: Bc. + Mgr./M.Sc. + Ph.D.) toward the
    # top of that band. The Marek research fixture lists exactly that ladder
    # in its Education section, so a passing run must produce an education
    # component ≥ 85. The score stage may drop the component on anchor-verify
    # — in that case the test fails closed rather than silently passing.
    cv_text = PHD_FIXTURE.read_text(encoding="utf-8")
    redacted = RedactedCV(text=cv_text, audit_log=[])
    item = ProfileItem(text="placeholder", anchor=Anchor(quote="placeholder"))
    profile = Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="Research Scientist",
        detected_location="Prague",
        detected_years_experience=12,
    )
    result = await score_profile(redacted, profile)
    assert isinstance(result, Score), f"expected Score, got {type(result).__name__}: {result}"
    education = next((c for c in result.components if c.name == "education"), None)
    assert education is not None, (
        f"education component missing from PhD fixture score; "
        f"dropped={result.dropped}, components={[c.name for c in result.components]}"
    )
    assert education.score_0_100 >= 85, (
        f"PhD + Master's + Bachelor's fixture scored education "
        f"{education.score_0_100}/100, expected >=85 per T47 rubric. "
        f"Anchor: {education.anchor.quote!r}"
    )


@pytest.mark.fast
async def test_score_section_blind_fail_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # CV body has all 4 anchorable phrases but NO `## SectionName` headers.
    # Each component anchor is section-tagged → every verify_quote call hits
    # the whole-CV fallback. 4 misses > cap of 2 → stage fails closed with
    # section_blind_fail rather than silently letting fallback carry it.
    cv_text = (
        "Built a recommendation system that reduced churn by eighteen percent.\n"
        "Mentored four junior engineers across two squads in the platform team.\n"
        "Holds a masters degree in computer science from a top university.\n"
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
            Component(
                name="education",
                score_0_100=55,
                justification=".",
                anchor=Anchor(
                    quote="masters degree in computer science from",
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
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await score_profile(redacted, profile)

    assert isinstance(result, StageFailure)
    assert result.stage == "score"
    assert "section anchors unavailable" in result.user_message.lower()

    blind_evt = next(e for e in events if e["event"] == "section_blind_fail")
    assert blind_evt["stage"] == "score"
    assert blind_evt["miss_count"] == 4

    miss_events = [e for e in events if e["event"] == "verify_section_miss"]
    assert len(miss_events) == 4


@pytest.mark.fast
async def test_score_section_miss_under_cap_does_not_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Two of four anchors miss their section header. 2 ≤ cap=2 → stage still
    # completes; the fallback rescues the anchors and verified components ship.
    cv_text = (
        "## Skills\n"
        "Python, PyTorch, async pipelines, vector databases, distributed systems work.\n"
        "## Work Experience\n"
        "Built a recommendation system that reduced churn by eighteen percent.\n"
        "Mentored four junior engineers across two squads in the platform team.\n"
        "Holds a masters degree in computer science from a top university.\n"
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
            # Section "Education" not in CV → falls back, quote present → verified.
            Component(
                name="education",
                score_0_100=55,
                justification=".",
                anchor=Anchor(
                    quote="masters degree in computer science from",
                    section="Education",
                ),
            ),
            # Section "Soft Signals" not in CV → falls back, quote present → verified.
            Component(
                name="soft_signals",
                score_0_100=60,
                justification=".",
                anchor=Anchor(
                    quote="mentored four junior engineers across two squads",
                    section="Soft Signals",
                ),
            ),
        ]
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await score_profile(redacted, profile)

    assert isinstance(result, Score), f"expected Score, got {type(result).__name__}: {result}"
    miss_events = [e for e in events if e["event"] == "verify_section_miss"]
    assert len(miss_events) == 2
    assert not any(e["event"] == "section_blind_fail" for e in events)


@pytest.mark.live
@pytest.mark.slow
async def test_score_calibration_variance_on_mid_fixture() -> None:
    pytest.skip("no mid fixture authored yet — covered by T17 acceptance once T06 lands")
