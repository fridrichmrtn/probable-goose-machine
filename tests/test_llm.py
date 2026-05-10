from __future__ import annotations

import os
from typing import Any

import pytest
from pydantic import BaseModel

from jobfit.llm import LLMClient, _strip_think
from jobfit.obs import subscribe


@pytest.mark.fast
def test_strip_think_handles_fences_and_thinkblocks() -> None:
    # think block + json fence (the real M2.7 shape that broke the spike)
    assert _strip_think('<think>reasoning</think>\n\n```json\n{"a": 1}\n```') == '{"a": 1}'
    # fence only
    assert _strip_think('```json\n{"a": 1}\n```') == '{"a": 1}'
    # think only
    assert _strip_think('<think>reasoning</think>\n\n{"a": 1}') == '{"a": 1}'
    # bare json
    assert _strip_think('{"a": 1}') == '{"a": 1}'


class Echo(BaseModel):
    message: str


class _RetryingLLMClient(LLMClient):
    def __init__(self) -> None:
        self.calls = 0

    def _resolve_model(self, logical: str) -> str:
        return f"fake-{logical}"

    def _estimate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        return float(prompt_tokens + completion_tokens)

    async def _chat_json(
        self, model: str, system: str, user: str, temperature: float
    ) -> tuple[str, int, int, str]:
        self.calls += 1
        if self.calls == 1:
            return "not json", 3, 5, "stop"
        return '{"message": "pong"}', 7, 11, "stop"


@pytest.mark.fast
async def test_complete_json_retry_telemetry_accumulates_tokens() -> None:
    events: list[dict[str, Any]] = []
    client = _RetryingLLMClient()

    with subscribe(events.append):
        echo = await client.complete_json(
            system="Return JSON.",
            user="Echo pong.",
            schema=Echo,
            model="cheap",
            max_retries=1,
        )

    assert echo == Echo(message="pong")
    assert client.calls == 2
    llm_events = [e for e in events if e["event"] == "llm_call"]
    assert len(llm_events) == 1
    assert llm_events[0]["prompt_tokens"] == 10
    assert llm_events[0]["completion_tokens"] == 16
    assert llm_events[0]["usd_cost"] == 26.0


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("MINIMAX_API_KEY"), reason="MINIMAX_API_KEY not set")
async def test_complete_json_roundtrip_emits_telemetry() -> None:
    events: list[dict[str, Any]] = []
    client = LLMClient()
    with subscribe(events.append):
        echo = await client.complete_json(
            system='You echo. Return JSON {"message": "..."}.',
            user="Echo back the word pong.",
            schema=Echo,
            model="cheap",
        )
    assert isinstance(echo, Echo)
    assert "pong" in echo.message.lower()

    llm_events = [e for e in events if e["event"] == "llm_call"]
    assert len(llm_events) == 1
    e = llm_events[0]
    assert e["prompt_tokens"] > 0
    assert e["completion_tokens"] >= 0
    assert e["duration_ms"] >= 0
    assert e["usd_cost"] >= 0.0
