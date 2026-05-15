from __future__ import annotations

import json
from typing import Any

import pytest

import gander.growth as growth_mod
from gander.errors import StageFailure
from gander.growth import _build_user_message, _GrowthList, _jaccard_4gram, plan_growth
from gander.llm import LLMClient
from gander.obs import subscribe
from gander.schemas import (
    Anchor,
    Component,
    GrowthAction,
    Profile,
    ProfileItem,
    RedactedCV,
    Score,
)

# Long quotes (>=8 words) so verify_quote treats them as "appear at least once"
# rather than the 6-7 word "appear exactly once" rule.
_CV_TEXT = (
    "## Work Experience\n"
    "Built a fraud-detection service using PyTorch and Kafka stream processing "
    "for the European retail team.\n"
    "Owned the on-call rotation across two production squads for eighteen "
    "consecutive months without escalation.\n"
    "Migrated the recommendation pipeline from on-prem Spark to managed cloud "
    "infrastructure during a six month rollout.\n"
    "## Education\n"
    "Completed an MSc in Computer Science at an accredited Czech university "
    "with a thesis on graph algorithms.\n"
    "## Skills\n"
    "Python, PyTorch, Kafka, async pipelines, distributed systems, infrastructure "
    "as code, and observability tooling.\n"
)

_QUOTE_FRAUD = (
    "Built a fraud-detection service using PyTorch and Kafka stream processing "
    "for the European retail team"
)
_QUOTE_ONCALL = (
    "Owned the on-call rotation across two production squads for eighteen "
    "consecutive months without escalation"
)
_QUOTE_MIGRATION = (
    "Migrated the recommendation pipeline from on-prem Spark to managed cloud "
    "infrastructure during a six month rollout"
)
_QUOTE_EDUCATION = (
    "Completed an MSc in Computer Science at an accredited Czech university "
    "with a thesis on graph algorithms"
)
_QUOTE_SKILLS = (
    "Python, PyTorch, Kafka, async pipelines, distributed systems, infrastructure "
    "as code, and observability tooling"
)


def _redacted() -> RedactedCV:
    return RedactedCV(text=_CV_TEXT, audit_log=[])


def _profile() -> Profile:
    item = ProfileItem(text="x", anchor=Anchor(quote="x"))
    return Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="Senior Data Engineer",
        detected_location="Prague",
        detected_years_experience=6,
    )


def _score() -> Score:
    return Score(
        components=[
            Component(
                name="skills",
                score_0_100=72,
                justification="Strong Python and streaming stack.",
                anchor=Anchor(quote="x"),
            ),
            Component(
                name="experience",
                score_0_100=68,
                justification="Six years with production ownership.",
                anchor=Anchor(quote="x"),
            ),
            Component(
                name="education",
                score_0_100=60,
                justification="MSc in Computer Science.",
                anchor=Anchor(quote="x"),
            ),
            Component(
                name="soft_signals",
                score_0_100=55,
                justification="On-call ownership signal.",
                anchor=Anchor(quote="x"),
            ),
        ]
    )


def _action(
    *,
    what: str,
    mechanism: str,
    quote: str,
    section: str | None = "Work Experience",
    months: int = 9,
) -> GrowthAction:
    return GrowthAction(
        what=what,
        time_horizon_months=months,
        mechanism=mechanism,
        anchor=Anchor(quote=quote, section=section),
    )


@pytest.mark.fast
def test_jaccard_4gram_identical_returns_one() -> None:
    s = "alpha bravo charlie delta echo foxtrot"
    assert _jaccard_4gram(s, s) == 1.0


@pytest.mark.fast
def test_jaccard_4gram_disjoint_returns_zero() -> None:
    a = "alpha bravo charlie delta echo"
    b = "foxtrot golf hotel india juliet"
    assert _jaccard_4gram(a, b) == 0.0


@pytest.mark.fast
def test_jaccard_4gram_below_threshold_for_short_inputs() -> None:
    # Fewer than 4 tokens → no 4-grams to form → 0.0 even for identical inputs.
    assert _jaccard_4gram("alpha bravo charlie", "alpha bravo charlie") == 0.0
    assert _jaccard_4gram("alpha", "alpha") == 0.0
    assert _jaccard_4gram("", "") == 0.0


@pytest.mark.fast
def test_build_user_message_includes_current_employer_hint() -> None:
    quote = (
        "Senior Manager AI and Data Science at Stealth Startup led the model "
        "evaluation program across product analytics"
    )
    redacted = RedactedCV(
        text=(
            "## Work Experience\n"
            "Senior Manager AI and Data Science — Stealth Startup\n"
            "January [YEAR] - Present\n"
            f"{quote}.\n"
            "\n"
            "Research Engineer — Prior Lab\n"
            "January [YEAR] - December [YEAR]\n"
            "Built research prototypes for recommender systems.\n"
        ),
        audit_log=[],
    )
    profile = _profile().model_copy(
        update={
            "experience": [
                ProfileItem(
                    text="Senior Manager AI and Data Science — Stealth Startup",
                    anchor=Anchor(quote=quote, section="Work Experience"),
                )
            ]
        }
    )

    payload = json.loads(
        _build_user_message(redacted, profile, _score(), salary_midpoint=150000, currency="CZK")
    )

    assert payload["current_employer_hint"] == [
        "Senior Manager AI and Data Science — Stealth Startup"
    ]


@pytest.mark.fast
def test_current_employer_hint_uses_normalized_anchor_match() -> None:
    source_quote = (
        "Senior Manager AI and Data Science led the model\n"
        "evaluation program across product analytics"
    )
    anchor_quote = (
        "senior manager ai and data science led the model evaluation program "
        "across product analytics"
    )
    redacted = RedactedCV(
        text=(
            "## Work Experience\n"
            "Senior Manager AI and Data Science — Stealth Startup\n"
            "January [YEAR] - Present\n"
            f"{source_quote}.\n"
        ),
        audit_log=[],
    )
    profile = _profile().model_copy(
        update={
            "experience": [
                ProfileItem(
                    text="Senior Manager AI and Data Science — Stealth Startup",
                    anchor=Anchor(quote=anchor_quote, section="Work Experience"),
                )
            ]
        }
    )

    payload = json.loads(
        _build_user_message(redacted, profile, _score(), salary_midpoint=150000, currency="CZK")
    )

    assert payload["current_employer_hint"] == [
        "Senior Manager AI and Data Science — Stealth Startup"
    ]


@pytest.mark.fast
def test_current_employer_hint_does_not_bleed_present_token_to_neighbor_role() -> None:
    current_quote = "Current platform lead owns fraud scoring systems across product analytics"
    past_quote = "Past research engineer built recommender prototypes for a prior lab"
    redacted = RedactedCV(
        text=(
            "## Work Experience\n"
            "Current Platform Lead — Stealth Startup\n"
            "January [YEAR] - Present\n"
            f"{current_quote}.\n"
            "Research Engineer — Prior Lab\n"
            "January [YEAR] - December [YEAR]\n"
            f"{past_quote}.\n"
        ),
        audit_log=[],
    )
    profile = _profile().model_copy(
        update={
            "experience": [
                ProfileItem(
                    text="Current Platform Lead — Stealth Startup",
                    anchor=Anchor(quote=current_quote, section="Work Experience"),
                ),
                ProfileItem(
                    text="Research Engineer — Prior Lab",
                    anchor=Anchor(quote=past_quote, section="Work Experience"),
                ),
            ]
        }
    )

    payload = json.loads(
        _build_user_message(redacted, profile, _score(), salary_midpoint=150000, currency="CZK")
    )

    assert payload["current_employer_hint"] == ["Current Platform Lead — Stealth Startup"]


@pytest.mark.fast
def test_build_user_message_includes_dropped_components() -> None:
    score = Score(
        components=[c for c in _score().components if c.name != "education"],
        dropped=["education"],
    )

    payload = json.loads(
        _build_user_message(_redacted(), _profile(), score, salary_midpoint=120000, currency="CZK")
    )

    assert payload["dropped_components"] == ["education"]


@pytest.mark.fast
async def test_plan_growth_returns_stage_failure_when_complete_json_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pydantic rejection of out-of-range time_horizon_months at the LLM-client
    # boundary surfaces here as RuntimeError. We test the post-Pydantic failure
    # branch, not an in-growth filter.
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        raise RuntimeError("validation failure: time_horizon_months out of range")

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await plan_growth(
            _redacted(), _profile(), _score(), salary_midpoint=110000, currency="CZK"
        )

    assert isinstance(result, StageFailure)
    assert result.stage == "growth"
    assert result.user_message == "Could not generate this section reliably"

    failure_evt = next(e for e in events if e["event"] == "stage_failure")
    assert failure_evt["stage"] == "growth"
    assert failure_evt["reason"] == "llm_error"
    assert failure_evt["exc_type"] == "RuntimeError"


@pytest.mark.fast
async def test_plan_growth_drops_ban_phrase_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    banned_what = "Complete a PhD in machine learning to qualify for senior research roles"
    payload = _GrowthList(
        actions=[
            _action(
                what=banned_what,
                mechanism="moves you into the research-band salary range",
                quote=_QUOTE_FRAUD,
            ),
            _action(
                what="Lead the on-prem to cloud migration of the recommendation pipeline you own",
                mechanism="owning a production migration unlocks +20% in the CZ tech-lead band",
                quote=_QUOTE_MIGRATION,
            ),
            _action(
                what="Take the principal engineer on-call rotation across both production squads",
                mechanism="on-call ownership at scale lifts base by ~15% plus uplift in CZ",
                quote=_QUOTE_ONCALL,
                section="Work Experience",
            ),
            _action(
                what="Publish a Kafka stream-processing case study from the European retail team",
                mechanism="external visibility shifts you into the staff-IC band, +25% in CZ",
                quote=_QUOTE_FRAUD,
            ),
            _action(
                what="Mentor two MSc Computer Science graduates through a Czech university scheme",
                mechanism="formal mentorship is the tech-lead promotion signal, +30k CZK/mo",
                quote=_QUOTE_EDUCATION,
                section="Education",
            ),
        ]
    )

    captured: dict[str, Any] = {}

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await plan_growth(
            _redacted(), _profile(), _score(), salary_midpoint=110000, currency="CZK"
        )

    assert isinstance(result, list)
    assert len(result) == 4
    assert all(banned_what != a.what for a in result)
    assert captured["max_tokens"] == 1536

    drop_evt = next(
        e for e in events if e["event"] == "growth_action_dropped" and e["reason"] == "ban_phrase"
    )
    assert drop_evt["phrase"] == "phd"

    anti_slop_evt = next(e for e in events if e["event"] == "growth_anti_slop_check")
    assert anti_slop_evt["returned"] == 5
    assert anti_slop_evt["dropped"] == 1
    assert anti_slop_evt["survived"] == 4


@pytest.mark.fast
async def test_plan_growth_drops_unverified_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    payload = _GrowthList(
        actions=[
            _action(
                what="Drive the Snowflake adoption rollout for the analytics platform",
                mechanism="owning the warehouse migration lifts you into the staff-data band",
                quote="this exact substring does not appear in the cv text anywhere at all",
                section=None,
            ),
            _action(
                what="Lead the on-prem to cloud migration of the recommendation pipeline",
                mechanism="production migration ownership unlocks +20% in CZ tech-lead band",
                quote=_QUOTE_MIGRATION,
            ),
            _action(
                what="Own the principal engineer on-call rotation across both production squads",
                mechanism="on-call ownership lifts base by ~15% plus uplift in CZ market",
                quote=_QUOTE_ONCALL,
            ),
            _action(
                what="Publish a Kafka stream-processing case study from the retail engagement",
                mechanism="external visibility shifts you into staff-IC band, +25% in CZ",
                quote=_QUOTE_FRAUD,
            ),
        ]
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await plan_growth(
            _redacted(), _profile(), _score(), salary_midpoint=110000, currency="CZK"
        )

    assert isinstance(result, list)
    assert len(result) == 3
    drop_evt = next(
        e
        for e in events
        if e["event"] == "growth_action_dropped" and e["reason"] == "unverified_anchor"
    )
    assert drop_evt["stage"] == "growth"


@pytest.mark.fast
async def test_plan_growth_returns_stage_failure_when_fewer_than_three_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    payload = _GrowthList(
        actions=[
            # ban phrase
            _action(
                what="Complete a PhD program at a top-tier institution",
                mechanism="moves into research band",
                quote=_QUOTE_FRAUD,
            ),
            # unverified anchor
            _action(
                what="Drive the Snowflake adoption rollout for the analytics platform",
                mechanism="owning the warehouse migration lifts you into the staff-data band",
                quote="this quote does not appear anywhere inside the source cv text body",
                section=None,
            ),
            # unverified anchor
            _action(
                what="Publish an OSS contribution to a streaming framework you maintain",
                mechanism="external signal shifts you to staff-IC band in CZ market",
                quote="another fabricated quote that the verifier will not find anywhere here",
                section=None,
            ),
            # verified
            _action(
                what="Lead the on-prem to cloud migration of the recommendation pipeline",
                mechanism="production migration ownership unlocks +20% in CZ tech-lead band",
                quote=_QUOTE_MIGRATION,
            ),
        ]
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await plan_growth(
            _redacted(), _profile(), _score(), salary_midpoint=110000, currency="CZK"
        )

    assert isinstance(result, StageFailure)
    assert result.stage == "growth"
    assert result.user_message == "Could not generate this section reliably"

    failure_evt = next(
        e
        for e in events
        if e["event"] == "stage_failure" and e["reason"] == "insufficient_verified_actions"
    )
    assert failure_evt["survived"] == 1


@pytest.mark.fast
async def test_plan_growth_truncates_to_five_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    # Seven valid actions, all anchors verified, none banned. Quotes reused
    # across actions are fine — verify_quote accepts repeated >=8-word
    # substrings (count >= 1 rule).
    payload = _GrowthList(
        actions=[
            _action(
                what="Lead the on-prem to cloud migration of the recommendation pipeline",
                mechanism="production migration ownership unlocks +20% in CZ tech-lead band",
                quote=_QUOTE_MIGRATION,
            ),
            _action(
                what="Own the principal engineer on-call rotation across both production squads",
                mechanism="on-call ownership lifts base by ~15% plus uplift in CZ market",
                quote=_QUOTE_ONCALL,
            ),
            _action(
                what="Publish a Kafka stream-processing case study from the retail engagement",
                mechanism="external visibility shifts you into staff-IC band, +25% in CZ",
                quote=_QUOTE_FRAUD,
            ),
            _action(
                what="Mentor two graduates through the Czech MSc programme you completed",
                mechanism="formal mentorship is the tech-lead promotion signal, +30k CZK/mo",
                quote=_QUOTE_EDUCATION,
                section="Education",
            ),
            _action(
                what="Drive an internal observability rollout for the fraud-detection service",
                mechanism="platform ownership signal shifts you into senior-platform band",
                quote=_QUOTE_SKILLS,
                section="Skills",
            ),
            _action(
                what="Take the staff-engineer interview loop for the Kafka platform team",
                mechanism="staff title shift adds +35% to base in CZ senior-IC ladder",
                quote=_QUOTE_FRAUD,
            ),
            _action(
                what="Own a quarterly cost-model report for the migrated recommendation pipeline",
                mechanism="finance-facing reporting unlocks the principal-IC band, +40k CZK/mo",
                quote=_QUOTE_MIGRATION,
            ),
        ]
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    result = await plan_growth(
        _redacted(), _profile(), _score(), salary_midpoint=110000, currency="CZK"
    )

    assert isinstance(result, list)
    assert len(result) == 5


@pytest.mark.fast
async def test_plan_growth_user_message_includes_salary_midpoint_and_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    captured: dict[str, str] = {}

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        captured["user"] = kwargs["user"]
        # Return a minimal valid payload so the stage exits cleanly via the
        # < 3 verified path; we only care about the captured user payload.
        return _GrowthList(actions=[])

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    await plan_growth(_redacted(), _profile(), _score(), salary_midpoint=137000, currency="CZK")

    user_payload = captured["user"]
    assert "137000" in user_payload
    assert "CZK" in user_payload
    assert "skills" in user_payload
    assert "Strong Python and streaming stack." in user_payload
    # Pin the redacted CV and profile metadata flow into the prompt — proves
    # the user payload carries the CV body and detected_role/location, not
    # only the salary fields.
    assert "fraud-detection service" in user_payload
    assert "Senior Data Engineer" in user_payload
    assert "Prague" in user_payload


@pytest.mark.fast
async def test_plan_growth_drops_ban_phrase_phd_dotted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`Ph.D.` lowercases to `ph.d.` which has no literal `phd` substring;
    only after punctuation-stripping normalization does the ban match."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    banned_what = "Complete a Ph.D. in ML"
    payload = _GrowthList(
        actions=[
            _action(
                what=banned_what,
                mechanism="moves you into the research-band salary range",
                quote=_QUOTE_FRAUD,
            ),
            _action(
                what="Lead the on-prem to cloud migration of the recommendation pipeline you own",
                mechanism="production migration ownership unlocks +20% in CZ tech-lead band",
                quote=_QUOTE_MIGRATION,
            ),
            _action(
                what="Own the principal engineer on-call rotation across both production squads",
                mechanism="on-call ownership lifts base by ~15% plus uplift in CZ market",
                quote=_QUOTE_ONCALL,
            ),
            _action(
                what="Publish a Kafka stream-processing case study from the European retail team",
                mechanism="external visibility shifts you into the staff-IC band, +25% in CZ",
                quote=_QUOTE_FRAUD,
            ),
        ]
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await plan_growth(
            _redacted(), _profile(), _score(), salary_midpoint=110000, currency="CZK"
        )

    assert isinstance(result, list)
    assert all(a.what != banned_what for a in result)
    drop_evt = next(
        e for e in events if e["event"] == "growth_action_dropped" and e["reason"] == "ban_phrase"
    )
    assert drop_evt["phrase"] == "phd"


@pytest.mark.fast
async def test_plan_growth_drops_ban_phrase_split_by_newline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`learn\\nmore` must still match the `learn more` ban after whitespace collapse."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    banned_what = "Learn\nmore about distributed systems beyond the recommendation pipeline"
    payload = _GrowthList(
        actions=[
            _action(
                what=banned_what,
                mechanism="general upskilling without a clear band ladder",
                quote=_QUOTE_FRAUD,
            ),
            _action(
                what="Lead the on-prem to cloud migration of the recommendation pipeline you own",
                mechanism="production migration ownership unlocks +20% in CZ tech-lead band",
                quote=_QUOTE_MIGRATION,
            ),
            _action(
                what="Own the principal engineer on-call rotation across both production squads",
                mechanism="on-call ownership lifts base by ~15% plus uplift in CZ market",
                quote=_QUOTE_ONCALL,
            ),
            _action(
                what="Publish a Kafka stream-processing case study from the European retail team",
                mechanism="external visibility shifts you into the staff-IC band, +25% in CZ",
                quote=_QUOTE_FRAUD,
            ),
        ]
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await plan_growth(
            _redacted(), _profile(), _score(), salary_midpoint=110000, currency="CZK"
        )

    assert isinstance(result, list)
    assert all(a.what != banned_what for a in result)
    drop_evt = next(
        e for e in events if e["event"] == "growth_action_dropped" and e["reason"] == "ban_phrase"
    )
    assert drop_evt["phrase"] == "learn more"


@pytest.mark.fast
@pytest.mark.parametrize(
    ("banned_what", "expected_phrase"),
    [
        (
            "Found a startup with two cofounders to spin out the fraud-detection service",
            "found a startup",
        ),
        (
            "Improve communication with the product team during the recommendation migration",
            "improve communication",
        ),
        (
            "Learn more about Kafka stream processing internals beyond the European retail team",
            "learn more",
        ),
        (
            "Network more aggressively at Czech engineering meetups to surface staff-IC offers",
            "network more",
        ),
    ],
)
async def test_plan_growth_drops_each_ban_phrase(
    monkeypatch: pytest.MonkeyPatch,
    banned_what: str,
    expected_phrase: str,
) -> None:
    """Every ban phrase besides `phd` must drop the offending action and emit
    the structured `growth_action_dropped` event with the matched phrase."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    payload = _GrowthList(
        actions=[
            _action(
                what=banned_what,
                mechanism="claims a market-band shift in CZ engineering ladder of +25%",
                quote=_QUOTE_FRAUD,
            ),
            _action(
                what="Lead the on-prem to cloud migration of the recommendation pipeline you own",
                mechanism="production migration ownership unlocks +20% in CZ tech-lead band",
                quote=_QUOTE_MIGRATION,
            ),
            _action(
                what="Own the principal engineer on-call rotation across both production squads",
                mechanism="on-call ownership lifts base by ~15% plus uplift in CZ market",
                quote=_QUOTE_ONCALL,
            ),
            _action(
                what="Publish a Kafka stream-processing case study from the European retail team",
                mechanism="external visibility shifts you into the staff-IC band, +25% in CZ",
                quote=_QUOTE_FRAUD,
            ),
        ]
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await plan_growth(
            _redacted(), _profile(), _score(), salary_midpoint=110000, currency="CZK"
        )

    assert isinstance(result, list)
    assert all(a.what != banned_what for a in result)
    drop_evt = next(
        e for e in events if e["event"] == "growth_action_dropped" and e["reason"] == "ban_phrase"
    )
    assert drop_evt["phrase"] == expected_phrase


def _five_verified_actions() -> list[GrowthAction]:
    return [
        _action(
            what="Lead the on-prem to cloud migration of the recommendation pipeline",
            mechanism="production migration ownership unlocks +20% in CZ tech-lead band",
            quote=_QUOTE_MIGRATION,
        ),
        _action(
            what="Own the principal engineer on-call rotation across both production squads",
            mechanism="on-call ownership lifts base by ~15% plus uplift in CZ market",
            quote=_QUOTE_ONCALL,
        ),
        _action(
            what="Publish a Kafka stream-processing case study from the retail engagement",
            mechanism="external visibility shifts you into staff-IC band, +25% in CZ",
            quote=_QUOTE_FRAUD,
        ),
        _action(
            what="Mentor two graduates through the Czech MSc programme you completed",
            mechanism="formal mentorship is the tech-lead promotion signal, +30k CZK/mo",
            quote=_QUOTE_EDUCATION,
            section="Education",
        ),
        _action(
            what="Drive an internal observability rollout for the fraud-detection service",
            mechanism="platform ownership signal shifts you into senior-platform band",
            quote=_QUOTE_SKILLS,
            section="Skills",
        ),
    ]


@pytest.mark.fast
async def test_plan_growth_returns_exactly_three_when_three_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    payload = _GrowthList(actions=_five_verified_actions()[:3])

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await plan_growth(
            _redacted(), _profile(), _score(), salary_midpoint=110000, currency="CZK"
        )

    assert isinstance(result, list)
    assert len(result) == 3
    returned_evt = next(e for e in events if e["event"] == "growth_actions_returned")
    assert returned_evt["count"] == 3
    assert not any(e["event"] == "growth_actions_truncated" for e in events)


@pytest.mark.fast
async def test_plan_growth_keeps_five_when_five_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    payload = _GrowthList(actions=_five_verified_actions())

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await plan_growth(
            _redacted(), _profile(), _score(), salary_midpoint=110000, currency="CZK"
        )

    assert isinstance(result, list)
    assert len(result) == 5
    returned_evt = next(e for e in events if e["event"] == "growth_actions_returned")
    assert returned_evt["count"] == 5
    assert not any(e["event"] == "growth_actions_truncated" for e in events)


@pytest.mark.fast
async def test_plan_growth_emits_truncated_event_when_more_than_five_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The truncation path (7→5) must emit `growth_actions_truncated` once
    with the correct before/after/dropped counts."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    seven = _five_verified_actions() + [
        _action(
            what="Take the staff-engineer interview loop for the Kafka platform team",
            mechanism="staff title shift adds +35% to base in CZ senior-IC ladder",
            quote=_QUOTE_FRAUD,
        ),
        _action(
            what="Own a quarterly cost-model report for the migrated recommendation pipeline",
            mechanism="finance-facing reporting unlocks the principal-IC band, +40k CZK/mo",
            quote=_QUOTE_MIGRATION,
        ),
    ]
    payload = _GrowthList(actions=seven)

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await plan_growth(
            _redacted(), _profile(), _score(), salary_midpoint=110000, currency="CZK"
        )

    assert isinstance(result, list)
    assert len(result) == 5
    truncated_evt = next(e for e in events if e["event"] == "growth_actions_truncated")
    assert truncated_evt["count_before"] == 7
    assert truncated_evt["count_after"] == 5
    assert truncated_evt["dropped"] == 2


@pytest.mark.fast
async def test_plan_growth_emits_baseline_missing_when_no_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")
    # Point baseline at a non-existent path so `_load_baseline` returns []
    # and the else branch fires.
    monkeypatch.setattr(growth_mod, "_BASELINE_PATH", tmp_path / "missing.json")

    payload = _GrowthList(actions=_five_verified_actions()[:3])

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await plan_growth(
            _redacted(), _profile(), _score(), salary_midpoint=110000, currency="CZK"
        )

    assert isinstance(result, list)
    assert any(e["event"] == "growth_baseline_missing" for e in events)


@pytest.mark.fast
async def test_plan_growth_emits_possible_boilerplate_on_baseline_overlap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")
    # Baseline phrase fully matches one survivor's `what` → Jaccard = 1.0 > 0.6.
    overlap = "Lead the on-prem to cloud migration of the recommendation pipeline"
    baseline_path = tmp_path / "growth_baseline.json"
    baseline_path.write_text(f'["{overlap}"]', encoding="utf-8")
    monkeypatch.setattr(growth_mod, "_BASELINE_PATH", baseline_path)

    payload = _GrowthList(actions=_five_verified_actions()[:3])

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await plan_growth(
            _redacted(), _profile(), _score(), salary_midpoint=110000, currency="CZK"
        )

    assert isinstance(result, list)
    boilerplate_evt = next(e for e in events if e["event"] == "growth_possible_boilerplate")
    assert boilerplate_evt["max_overlap"] == 1.0


@pytest.mark.fast
async def test_plan_growth_returns_stage_failure_on_invalid_llm_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If `complete_json` returns the wrong type, the stage must surface PRD
    §4.6 user copy and emit `stage_failure` with `reason='invalid_llm_output'`."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return {"actions": []}  # plain dict, not a _GrowthList

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await plan_growth(
            _redacted(), _profile(), _score(), salary_midpoint=110000, currency="CZK"
        )

    assert isinstance(result, StageFailure)
    assert result.user_message == "Could not generate this section reliably"
    failure_evt = next(e for e in events if e["event"] == "stage_failure")
    assert failure_evt["reason"] == "invalid_llm_output"


@pytest.mark.fast
async def test_plan_growth_returns_stage_failure_on_unexpected_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure outside the `complete_json` try/except (here: `verify_quote`
    raising) must still surface PRD §4.6 copy and emit `stage_failure` with
    `reason='unexpected_error'` rather than leak `str(exc)` to the user."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    payload = _GrowthList(actions=_five_verified_actions()[:3])

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    def boom(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("simulated verify failure")

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setattr(growth_mod, "verify_quote", boom)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await plan_growth(
            _redacted(), _profile(), _score(), salary_midpoint=110000, currency="CZK"
        )

    assert isinstance(result, StageFailure)
    assert result.user_message == "Could not generate this section reliably"
    failure_evt = next(e for e in events if e["event"] == "stage_failure")
    assert failure_evt["reason"] == "unexpected_error"


@pytest.mark.fast
def test_baseline_path_lives_inside_package() -> None:
    """The smoke-check baseline must live inside `src/gander/` so a packaged
    wheel install keeps the path resolvable. Pointing at `tests/fixtures/...`
    would silently lose the boilerplate check on any non-source distribution.
    Closes Copilot finding on growth.py:53.
    """
    baseline = growth_mod._BASELINE_PATH
    assert baseline.name == "growth_baseline.json"
    assert baseline.parent.name == "data"
    assert baseline.parent.parent.name == "gander"
    # tests/ directory must NOT appear anywhere in the runtime path.
    assert "tests" not in baseline.parts
