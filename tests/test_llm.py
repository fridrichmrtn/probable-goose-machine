from __future__ import annotations

import os
from typing import Any

import pytest
from pydantic import BaseModel

from jobfit.llm import LLMClient
from jobfit.obs import subscribe

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("MINIMAX_API_KEY"), reason="MINIMAX_API_KEY not set"),
]


class Echo(BaseModel):
    message: str


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
