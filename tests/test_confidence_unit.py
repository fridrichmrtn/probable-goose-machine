from __future__ import annotations

import inspect
from typing import Any

import pytest

from gander.confidence import _LOW_FALLBACK_RATIONALE, _TierOnly, judge
from gander.errors import StageFailure
from gander.llm import LLMClient
from gander.obs import subscribe
from gander.schemas import Confidence, CVQualitySignals, Source


def _sources() -> list[Source]:
    # Snippets contain NO digits so the leak-channel assertion in
    # test_step_a_user_payload_does_not_leak_range is meaningful: any digit
    # in the captured step-A user payload must have come from low/high.
    return [
        Source(
            url="https://platy.cz/x",  # type: ignore[arg-type]
            snippet="Average analyst pay in Prague is competitive.",
            domain="platy.cz",
        ),
        Source(
            url="https://profesia.cz/y",  # type: ignore[arg-type]
            snippet="Senior analyst compensation in the Czech market is solid.",
            domain="profesia.cz",
        ),
    ]


def _sources_three_disagreeing() -> list[Source]:
    return [
        Source(
            url="https://platy.cz/analyst",  # type: ignore[arg-type]
            snippet="Junior analysts in Prague earn around 50000 CZK per month.",
            domain="platy.cz",
        ),
        Source(
            url="https://profesia.cz/analyst",  # type: ignore[arg-type]
            snippet="Mid-level analyst roles pay about 100000 CZK monthly.",
            domain="profesia.cz",
        ),
        Source(
            url="https://glassdoor.com/analyst-prague",  # type: ignore[arg-type]
            snippet="Lead analyst compensation reaches 200000 CZK per month.",
            domain="glassdoor.com",
        ),
    ]


def _sources_three_agreeing() -> list[Source]:
    return [
        Source(
            url="https://platy.cz/analyst",  # type: ignore[arg-type]
            snippet="Data analysts in Prague typically earn around 100000 CZK per month.",
            domain="platy.cz",
        ),
        Source(
            url="https://profesia.cz/analyst",  # type: ignore[arg-type]
            snippet="Senior analyst roles in the Czech market pay about 105000 CZK per month.",
            domain="profesia.cz",
        ),
        Source(
            url="https://glassdoor.com/analyst-prague",  # type: ignore[arg-type]
            snippet="Analyst compensation in Prague averages 110000 CZK per month.",
            domain="glassdoor.com",
        ),
    ]


def _clean_cv_quality() -> CVQualitySignals:
    return CVQualitySignals(
        dropped_score_components=0,
        canonical_role_resolved=True,
        location_detected=True,
    )


@pytest.mark.fast
def test_judge_signature_isolation() -> None:
    # Recompute-then-compare contract: judge() may receive aggregate CV-quality
    # signals, but must NOT accept any parameter that would let Step A see the
    # estimator's reasoning or produced salary range as input.
    sig = inspect.signature(judge)
    assert set(sig.parameters.keys()) == {
        "sources",
        "low",
        "high",
        "currency",
        "period",
        "cv_quality",
    }
    assert sig.parameters["cv_quality"].kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.fast
async def test_step_a_user_payload_does_not_leak_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    captured: dict[str, Any] = {}
    text_kwargs: dict[str, Any] = {}

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return _TierOnly(tier="Medium", rationale_short="two distinct domains overlap")

    async def fake_complete_text(self: LLMClient, **kwargs: Any) -> str:
        text_kwargs.update(kwargs)
        return (
            "Confidence in this estimate is Medium. "
            "The 100000-200000 CZK/month band is well-supported."
        )

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setattr(LLMClient, "complete_text", fake_complete_text)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await judge(
            sources=_sources(),
            low=100000,
            high=200000,
            currency="CZK",
            period="month",
            cv_quality=_clean_cv_quality(),
        )

    assert isinstance(result, Confidence)
    assert result.tier == "Medium"
    assert captured["max_tokens"] == 128
    assert text_kwargs["max_tokens"] == 256

    payload = captured["user"]
    lowered = payload.lower()
    # Numeric and unit leakage from low/high/currency/period must be impossible
    # by construction. These assertions are the regression guard.
    assert "100000" not in payload
    assert "200000" not in payload
    assert "czk" not in lowered
    assert "month" not in lowered
    assert "currency" not in lowered
    assert "period" not in lowered
    assert "low" not in lowered
    assert "high" not in lowered

    # §4.8: every stage emits its structured signals. Step A and Step B carry
    # tier + counts so the run log is auditable without re-running the model.
    step_a_evt = next(e for e in events if e["event"] == "confidence_step_a")
    assert step_a_evt["stage"] == "confidence"
    assert step_a_evt["tier"] == "Medium"
    assert step_a_evt["sources_count"] == 2

    step_b_evt = next(e for e in events if e["event"] == "confidence_step_b")
    assert step_b_evt["stage"] == "confidence"
    assert step_b_evt["regenerated"] is False
    assert step_b_evt["rationale_len"] == len(result.rationale)

    decision_evt = next(e for e in events if e["event"] == "confidence_decision")
    assert decision_evt["stage"] == "confidence"
    assert decision_evt["tier"] == "Medium"
    assert decision_evt["rationale_len"] == len(result.rationale)

    done_evt = next(e for e in events if e["event"] == "done" and e["stage"] == "confidence")
    assert isinstance(done_evt["duration_ms"], int)
    assert done_evt["duration_ms"] >= 0
    assert done_evt["tier"] == "Medium"


@pytest.mark.fast
async def test_source_rubric_caps_overconfident_step_a(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return _TierOnly(tier="High", rationale_short="three domains present")

    async def fake_complete_text(self: LLMClient, **kwargs: Any) -> str:
        return "Confidence in this estimate is Low because the source snippets disagree."

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setattr(LLMClient, "complete_text", fake_complete_text)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await judge(
            sources=_sources_three_disagreeing(),
            low=50000,
            high=200000,
            currency="CZK",
            period="month",
            cv_quality=_clean_cv_quality(),
        )

    assert isinstance(result, Confidence)
    assert result.tier == "Low"
    cap_evt = next(e for e in events if e["event"] == "confidence_source_rubric_applied")
    assert cap_evt["model_tier"] == "High"
    assert cap_evt["source_tier"] == "Low"
    assert cap_evt["final_salary_tier"] == "Low"
    assert cap_evt["distinct_domains"] == 3
    assert cap_evt["comparable_values"] == 3
    assert cap_evt["spread"] > 0.50
    assert cap_evt["spread_known"] is True
    assert cap_evt["reason"] == "source_disagreement"
    step_a_evt = next(e for e in events if e["event"] == "confidence_step_a")
    assert step_a_evt["salary_tier"] == "Low"
    assert step_a_evt["tier"] == "Low"


@pytest.mark.fast
async def test_source_rubric_cap_emits_spread_known_false_when_spread_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # When the cap is driven by fewer_than_two_domains, the rubric never
    # computes a spread. The emitted event must still expose a typed
    # spread_known field so downstream consumers can gate cleanly.
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return _TierOnly(tier="High", rationale_short="one decent source")

    async def fake_complete_text(self: LLMClient, **kwargs: Any) -> str:
        return "Confidence in this estimate is Low because evidence is thin."

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setattr(LLMClient, "complete_text", fake_complete_text)

    one_source = [
        Source(
            url="https://platy.cz/analyst",  # type: ignore[arg-type]
            snippet="Analysts in Prague earn around 100000 CZK per month.",
            domain="platy.cz",
        ),
    ]

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await judge(
            sources=one_source,
            low=80000,
            high=120000,
            currency="CZK",
            period="month",
            cv_quality=_clean_cv_quality(),
        )

    assert isinstance(result, Confidence)
    assert result.tier == "Low"
    cap_evt = next(e for e in events if e["event"] == "confidence_source_rubric_applied")
    assert cap_evt["reason"] == "fewer_than_two_domains"
    assert cap_evt["spread"] is None
    assert cap_evt["spread_known"] is False
    assert cap_evt["distinct_domains"] == 1
    assert cap_evt["comparable_values"] == 1


@pytest.mark.fast
async def test_source_rubric_never_upgrades_low_step_a(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return _TierOnly(tier="Low", rationale_short="model judged evidence insufficient")

    async def fake_complete_text(self: LLMClient, **kwargs: Any) -> str:
        return "Confidence in this estimate is Low because evidence is insufficient."

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setattr(LLMClient, "complete_text", fake_complete_text)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await judge(
            sources=_sources_three_agreeing(),
            low=100000,
            high=110000,
            currency="CZK",
            period="month",
            cv_quality=_clean_cv_quality(),
        )

    assert isinstance(result, Confidence)
    assert result.tier == "Low"
    assert not [e for e in events if e["event"] == "confidence_source_rubric_applied"]
    step_a_evt = next(e for e in events if e["event"] == "confidence_step_a")
    assert step_a_evt["salary_tier"] == "Low"
    assert step_a_evt["tier"] == "Low"


@pytest.mark.fast
async def test_step_b_cannot_override_step_a_and_regenerates_on_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return _TierOnly(tier="Low", rationale_short="only one source")

    # Both drafts lack the lexical marker — the second one also tries to claim
    # confidence inconsistent with tier="Low". The pipeline MUST refuse to ship
    # either prose alongside a Low tier and fall back to the honest sentence.
    text_responses = iter(
        [
            "High confidence pending market check.",
            "Strong signal from limited data.",
        ]
    )
    call_count = {"n": 0}

    async def fake_complete_text(self: LLMClient, **kwargs: Any) -> str:
        call_count["n"] += 1
        return next(text_responses)

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setattr(LLMClient, "complete_text", fake_complete_text)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await judge(
            sources=_sources(),
            low=100000,
            high=200000,
            currency="CZK",
            period="month",
            cv_quality=_clean_cv_quality(),
        )

    assert isinstance(result, Confidence)
    # Step A is authoritative; Step B prose claiming "High confidence ..."
    # cannot flip the tier.
    assert result.tier == "Low"
    # Regenerate fires exactly once. Both drafts still lack the marker, so
    # the rationale becomes the hardcoded fallback — pairing tier="Low" with
    # honest copy by construction.
    assert call_count["n"] == 2
    assert result.rationale == _LOW_FALLBACK_RATIONALE

    regen_evt = next(
        (e for e in events if e["event"] == "confidence_step_b_regenerated"),
        None,
    )
    assert regen_evt is not None
    assert regen_evt["stage"] == "confidence"
    assert regen_evt["reason"] == "missing_low_marker"

    fallback_evt = next(
        (e for e in events if e["event"] == "confidence_low_fallback_used"),
        None,
    )
    assert fallback_evt is not None
    assert fallback_evt["stage"] == "confidence"
    assert fallback_evt["reason"] == "regenerate_failed"


@pytest.mark.fast
async def test_step_b_regenerate_recovers_on_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return _TierOnly(tier="Low", rationale_short="single domain only")

    second = (
        "Confidence in this estimate is Low. The market data here is insufficient "
        "to corroborate the 100000-200000 CZK/month band, so treat the figure "
        "as provisional."
    )
    text_responses = iter(["High confidence pending market check.", second])
    call_count = {"n": 0}

    async def fake_complete_text(self: LLMClient, **kwargs: Any) -> str:
        call_count["n"] += 1
        return next(text_responses)

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setattr(LLMClient, "complete_text", fake_complete_text)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await judge(
            sources=_sources(),
            low=100000,
            high=200000,
            currency="CZK",
            period="month",
            cv_quality=_clean_cv_quality(),
        )

    assert isinstance(result, Confidence)
    assert result.tier == "Low"
    assert call_count["n"] == 2
    assert result.rationale == second

    regen_evt = next(
        (e for e in events if e["event"] == "confidence_step_b_regenerated"),
        None,
    )
    assert regen_evt is not None

    # No fallback event when the regenerate succeeds.
    fallback_evt = next(
        (e for e in events if e["event"] == "confidence_low_fallback_used"),
        None,
    )
    assert fallback_evt is None


@pytest.mark.fast
async def test_judge_does_not_regenerate_when_low_marker_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return _TierOnly(tier="Low", rationale_short="single domain only")

    first = (
        "Confidence in this estimate is Low. The market evidence is insufficient "
        "to confirm the 100000-200000 CZK/month band, so the figure is provisional."
    )
    call_count = {"n": 0}

    async def fake_complete_text(self: LLMClient, **kwargs: Any) -> str:
        call_count["n"] += 1
        return first

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setattr(LLMClient, "complete_text", fake_complete_text)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await judge(
            sources=_sources(),
            low=100000,
            high=200000,
            currency="CZK",
            period="month",
            cv_quality=_clean_cv_quality(),
        )

    assert isinstance(result, Confidence)
    assert result.tier == "Low"
    assert result.rationale == first
    assert call_count["n"] == 1

    regen_evt = next(
        (e for e in events if e["event"] == "confidence_step_b_regenerated"),
        None,
    )
    assert regen_evt is None

    step_b_evt = next(e for e in events if e["event"] == "confidence_step_b")
    assert step_b_evt["regenerated"] is False


@pytest.mark.fast
async def test_cv_floor_caps_high_to_low_when_two_components_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return _TierOnly(tier="High", rationale_short="three domains agree")

    async def fake_complete_text(self: LLMClient, **kwargs: Any) -> str:
        return "Confidence in this estimate is Low because extraction is insufficient."

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setattr(LLMClient, "complete_text", fake_complete_text)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await judge(
            sources=_sources(),
            low=100000,
            high=200000,
            currency="CZK",
            period="month",
            cv_quality=CVQualitySignals(
                dropped_score_components=2,
                canonical_role_resolved=True,
                location_detected=True,
            ),
        )

    assert isinstance(result, Confidence)
    assert result.tier == "Low"
    floor_evt = next(e for e in events if e["event"] == "confidence_cv_floor_applied")
    assert floor_evt["salary_tier"] == "High"
    assert floor_evt["cv_floor"] == "Low"
    assert floor_evt["final_tier"] == "Low"


@pytest.mark.fast
async def test_cv_floor_low_uses_cv_quality_fallback_not_market_data_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return _TierOnly(tier="High", rationale_short="three domains agree")

    text_responses = iter(
        [
            "Confidence in this estimate is Low. The range remains provisional.",
            "Confidence in this estimate is Low. The sources still look usable.",
        ]
    )
    call_count = {"n": 0}

    async def fake_complete_text(self: LLMClient, **kwargs: Any) -> str:
        call_count["n"] += 1
        return next(text_responses)

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setattr(LLMClient, "complete_text", fake_complete_text)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await judge(
            sources=_sources(),
            low=100000,
            high=200000,
            currency="CZK",
            period="month",
            cv_quality=CVQualitySignals(
                dropped_score_components=2,
                canonical_role_resolved=True,
                location_detected=True,
            ),
        )

    assert isinstance(result, Confidence)
    assert result.tier == "Low"
    assert call_count["n"] == 2
    assert result.rationale != _LOW_FALLBACK_RATIONALE
    assert "CV extraction is thin" in result.rationale
    assert "insufficient or in disagreement" not in result.rationale
    fallback_evt = next(e for e in events if e["event"] == "confidence_low_fallback_used")
    assert fallback_evt["reason"] == "regenerate_failed"


@pytest.mark.fast
async def test_cv_floor_caps_high_to_medium_when_canonical_role_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return _TierOnly(tier="High", rationale_short="three domains agree")

    async def fake_complete_text(self: LLMClient, **kwargs: Any) -> str:
        return "Confidence in this estimate is Medium because role resolution is thin."

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setattr(LLMClient, "complete_text", fake_complete_text)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await judge(
            sources=_sources(),
            low=100000,
            high=200000,
            currency="CZK",
            period="month",
            cv_quality=CVQualitySignals(
                dropped_score_components=0,
                canonical_role_resolved=False,
                location_detected=True,
            ),
        )

    assert isinstance(result, Confidence)
    assert result.tier == "Medium"
    floor_evt = next(e for e in events if e["event"] == "confidence_cv_floor_applied")
    assert floor_evt["salary_tier"] == "High"
    assert floor_evt["cv_floor"] == "Medium"
    assert floor_evt["final_tier"] == "Medium"


@pytest.mark.fast
async def test_cv_floor_caps_high_to_medium_when_location_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return _TierOnly(tier="High", rationale_short="three domains agree")

    async def fake_complete_text(self: LLMClient, **kwargs: Any) -> str:
        return "Confidence in this estimate is Medium because location evidence is thin."

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setattr(LLMClient, "complete_text", fake_complete_text)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await judge(
            sources=_sources(),
            low=100000,
            high=200000,
            currency="CZK",
            period="month",
            cv_quality=CVQualitySignals(
                dropped_score_components=0,
                canonical_role_resolved=True,
                location_detected=False,
            ),
        )

    assert isinstance(result, Confidence)
    assert result.tier == "Medium"
    floor_evt = next(e for e in events if e["event"] == "confidence_cv_floor_applied")
    assert floor_evt["salary_tier"] == "High"
    assert floor_evt["cv_floor"] == "Medium"
    assert floor_evt["final_tier"] == "Medium"


@pytest.mark.fast
async def test_cv_floor_caps_high_to_medium_when_market_provenance_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return _TierOnly(tier="High", rationale_short="three domains agree")

    async def fake_complete_text(self: LLMClient, **kwargs: Any) -> str:
        return "Confidence in this estimate is Medium because the market is unresolved."

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setattr(LLMClient, "complete_text", fake_complete_text)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await judge(
            sources=_sources(),
            low=100000,
            high=200000,
            currency="USD",
            period="year",
            cv_quality=CVQualitySignals(
                dropped_score_components=0,
                canonical_role_resolved=True,
                location_detected=True,
                market_provenance="default",
            ),
        )

    assert isinstance(result, Confidence)
    assert result.tier == "Medium"
    floor_evt = next(e for e in events if e["event"] == "confidence_cv_floor_applied")
    assert floor_evt["salary_tier"] == "High"
    assert floor_evt["cv_floor"] == "Medium"
    assert floor_evt["final_tier"] == "Medium"
    assert floor_evt["market_provenance"] == "default"


@pytest.mark.fast
async def test_cv_floor_does_not_upgrade_low_to_medium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return _TierOnly(tier="Low", rationale_short="single domain only")

    async def fake_complete_text(self: LLMClient, **kwargs: Any) -> str:
        return "Confidence in this estimate is Low because evidence is insufficient."

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setattr(LLMClient, "complete_text", fake_complete_text)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await judge(
            sources=_sources(),
            low=100000,
            high=200000,
            currency="CZK",
            period="month",
            cv_quality=_clean_cv_quality(),
        )

    assert isinstance(result, Confidence)
    assert result.tier == "Low"
    assert not [e for e in events if e["event"] == "confidence_cv_floor_applied"]


@pytest.mark.fast
async def test_judge_returns_stage_failure_when_llm_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        raise RuntimeError("simulated LLM failure")

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await judge(
            sources=_sources(),
            low=100000,
            high=200000,
            currency="CZK",
            period="month",
            cv_quality=_clean_cv_quality(),
        )

    assert isinstance(result, StageFailure)
    assert result.stage == "confidence"
    # PRD §4.6: user-facing copy is pinned, not str(exc).
    assert result.user_message == "Could not generate this section reliably"

    failure_evt = next(e for e in events if e["event"] == "stage_failure")
    assert failure_evt["stage"] == "confidence"
    assert failure_evt["reason"] == "step_a_llm_error"
    assert failure_evt["exc_type"] == "RuntimeError"
