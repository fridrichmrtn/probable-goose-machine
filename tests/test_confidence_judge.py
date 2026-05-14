from __future__ import annotations

import inspect
import os
import re
from typing import Any

import pytest

from jobfit.confidence import _STEP_B_PROMPT, _render_step_b, judge
from jobfit.errors import StageFailure
from jobfit.obs import subscribe
from jobfit.schemas import Confidence, Source

_LIVE_SKIPIF = pytest.mark.skipif(
    not os.environ.get("MINIMAX_API_KEY"),
    reason="needs MINIMAX_API_KEY",
)


def _sources_three_agreeing() -> list[Source]:
    return [
        Source(
            url="https://platy.cz/analyst",  # type: ignore[arg-type]
            snippet="Data analysts in Prague typically earn around 105000 CZK per month.",
            domain="platy.cz",
        ),
        Source(
            url="https://profesia.cz/analyst",  # type: ignore[arg-type]
            snippet="Senior analyst roles in the Czech market pay about 100000 CZK monthly.",
            domain="profesia.cz",
        ),
        Source(
            url="https://glassdoor.com/analyst-prague",  # type: ignore[arg-type]
            snippet="Analyst compensation in Prague averages 110000 CZK per month.",
            domain="glassdoor.com",
        ),
    ]


def _sources_single() -> list[Source]:
    return [
        Source(
            url="https://platy.cz/analyst",  # type: ignore[arg-type]
            snippet="Data analysts in Prague typically earn around 105000 CZK per month.",
            domain="platy.cz",
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


@pytest.mark.fast
def test_judge_signature_is_isolated() -> None:
    sig = inspect.signature(judge)
    params = set(sig.parameters.keys())
    assert params == {"sources", "low", "high", "currency", "period"}, (
        "judge() must not accept estimator reasoning, profile, or score — leakage channel"
    )
    for p in sig.parameters.values():
        assert p.kind not in (
            inspect.Parameter.VAR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        ), f"judge() must not accept **kwargs/*args — leakage channel via {p.name}"


@pytest.mark.fast
def test_step_b_does_not_see_estimator_reasoning() -> None:
    rendered = _render_step_b("Low", 100000, 200000, "CZK", "month").lower()
    for token in ("estimator", "reasoning", "profile"):
        assert token not in rendered, f"{token!r} leaked into Step B user message"
    # The system prompt is a static template; it must not name the upstream
    # leakage channels ("estimator", "profile"). "reasoning" is excluded here
    # because the prompt legitimately describes Step A as a "reasoning step"
    # (meta-reference to the prior LLM call, not estimator content).
    system = _STEP_B_PROMPT.lower()
    for token in ("estimator", "profile"):
        assert token not in system, f"{token!r} leaked into Step B system prompt"


@pytest.mark.live
@_LIVE_SKIPIF
async def test_step_a_high_with_three_agreeing_sources() -> None:
    result = await judge(
        sources=_sources_three_agreeing(),
        low=100000,
        high=110000,
        currency="CZK",
        period="month",
    )
    assert not isinstance(result, StageFailure), (
        f"judge returned StageFailure: {getattr(result, 'user_message', result)!r}"
    )
    assert isinstance(result, Confidence)
    assert result.tier == "High"


@pytest.mark.live
@_LIVE_SKIPIF
async def test_step_a_low_with_one_source() -> None:
    result = await judge(
        sources=_sources_single(),
        low=100000,
        high=110000,
        currency="CZK",
        period="month",
    )
    assert not isinstance(result, StageFailure), (
        f"judge returned StageFailure: {getattr(result, 'user_message', result)!r}"
    )
    assert isinstance(result, Confidence)
    assert result.tier == "Low"


@pytest.mark.live
@_LIVE_SKIPIF
async def test_step_a_low_with_disagreeing_sources() -> None:
    result = await judge(
        sources=_sources_three_disagreeing(),
        low=50000,
        high=200000,
        currency="CZK",
        period="month",
    )
    assert not isinstance(result, StageFailure), (
        f"judge returned StageFailure: {getattr(result, 'user_message', result)!r}"
    )
    assert isinstance(result, Confidence)
    assert result.tier == "Low"


@pytest.mark.live
@_LIVE_SKIPIF
async def test_step_b_cannot_override_step_a_low() -> None:
    # The regenerate-or-fallback path means _LOW_FALLBACK_RATIONALE also contains
    # "insufficient", so the keyword check alone cannot prove Step B actually ran.
    # We subscribe to obs events and require a `confidence_step_b` event so an
    # upstream short-circuit (Step A only) would fail this test.
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await judge(
            sources=_sources_single(),
            low=100000,
            high=110000,
            currency="CZK",
            period="month",
        )
    assert not isinstance(result, StageFailure), (
        f"judge returned StageFailure: {getattr(result, 'user_message', result)!r}"
    )
    assert isinstance(result, Confidence)
    assert result.tier == "Low"
    assert re.search(r"insufficient|disagree", result.rationale, re.I)
    step_b_events = [e for e in events if e["event"] == "confidence_step_b"]
    assert step_b_events, (
        f"expected at least one confidence_step_b event, got: {[e['event'] for e in events]}"
    )
