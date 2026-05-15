from __future__ import annotations

import os
from typing import Any

import pytest
from pydantic import BaseModel

from gander.llm import LLMClient, _strip_think
from gander.obs import subscribe


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
        self._provider = "test"
        self.calls = 0

    def _resolve_model(self, logical: str) -> str:
        return f"fake-{logical}"

    def _estimate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        return float(prompt_tokens + completion_tokens)

    async def _chat_json(
        self, model: str, system: str, user: str, temperature: float
    ) -> tuple[str, int, int, str, float | None]:
        self.calls += 1
        if self.calls == 1:
            return "not json", 3, 5, "stop", None
        return '{"message": "pong"}', 7, 11, "stop", None


@pytest.mark.fast
async def test_complete_vision_text_posts_api_vlm_payload_and_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"content": "Summary\nSynthetic transcript", "base_resp": {"status_code": 0}}

    class _FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(
            self, endpoint: str, *, headers: dict[str, str], json: dict[str, str]
        ) -> _FakeResponse:
            captured["endpoint"] = endpoint
            captured["headers"] = headers
            captured["json"] = json
            return _FakeResponse()

    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setattr("gander.llm.httpx.AsyncClient", _FakeAsyncClient)
    client = object.__new__(LLMClient)
    events: list[dict[str, Any]] = []

    with subscribe(events.append):
        text = await client.complete_vision_text(
            image_bytes=b"\x89PNG\r\n\x1a\nfake", prompt="Transcribe this page."
        )

    assert text == "Summary\nSynthetic transcript"
    assert captured["endpoint"] == "https://api.minimax.io/v1/coding_plan/vlm"
    assert captured["timeout"] == 120.0
    payload = captured["json"]
    assert payload["prompt"] == "Transcribe this page."
    assert payload["image_url"].startswith("data:image/png;base64,")
    assert captured["headers"]["Authorization"] == "Bearer test-key"

    llm_events = [e for e in events if e["event"] == "llm_call"]
    assert len(llm_events) == 1
    assert llm_events[0]["model"] == "api-vlm"
    assert llm_events[0]["usd_cost"] == 0.06
    assert llm_events[0]["token_plan_m2_requests"] == 3


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
    assert llm_events[0]["provider"] == "test"


@pytest.mark.fast
def test_openrouter_constructs_with_defaults_and_model_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("gander.llm.AsyncOpenAI", _FakeAsyncOpenAI)
    monkeypatch.setenv("GANDER_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.delenv("OPENROUTER_MODEL_REASONING", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_CHEAP", raising=False)

    client = LLMClient()

    assert captured["api_key"] == "or-test"
    assert str(captured["base_url"]) == "https://openrouter.ai/api/v1"
    assert captured["default_headers"]["X-Title"] == "Gander"
    assert client._resolve_model("reasoning") == "anthropic/claude-haiku-4.5"
    assert client._resolve_model("cheap") == "google/gemini-2.5-flash"

    monkeypatch.setenv("OPENROUTER_MODEL_REASONING", "anthropic/claude-sonnet-4.5")
    monkeypatch.setenv("OPENROUTER_MODEL_CHEAP", "google/gemini-2.5-flash-lite")
    assert client._resolve_model("reasoning") == "anthropic/claude-sonnet-4.5"
    assert client._resolve_model("cheap") == "google/gemini-2.5-flash-lite"


@pytest.mark.fast
def test_openrouter_missing_key_and_removed_anthropic_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GANDER_LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        LLMClient()

    monkeypatch.setenv("GANDER_LLM_PROVIDER", "anthropic")
    with pytest.raises(RuntimeError, match="'minimax' or 'openrouter'"):
        LLMClient()


class _FakeChatCompletions:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None
        self.content = '{"message": "pong"}'
        self.usage: Any = type(
            "Usage", (), {"prompt_tokens": 3, "completion_tokens": 4, "cost": 0.00042}
        )()

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return type(
            "Response",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {
                            "message": type("Message", (), {"content": self.content})(),
                            "finish_reason": "stop",
                        },
                    )()
                ],
                "usage": self.usage,
            },
        )()


def _client_with_fake_chat(provider: str) -> tuple[LLMClient, _FakeChatCompletions]:
    fake_completions = _FakeChatCompletions()
    fake_chat = type("Chat", (), {"completions": fake_completions})()
    fake_client = type("Client", (), {"chat": fake_chat})()
    client = object.__new__(LLMClient)
    client._provider = provider
    client._client = fake_client
    return client, fake_completions


@pytest.mark.fast
async def test_openrouter_chat_json_omits_minimax_quirks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_STRIP_THINK", raising=False)
    client, fake_completions = _client_with_fake_chat("openrouter")

    text, prompt_tokens, completion_tokens, finish_reason, cost_usd = await client._chat_json(
        "google/gemini-2.5-flash",
        "System",
        "User",
        0.0,
    )

    assert text == '{"message": "pong"}'
    assert (prompt_tokens, completion_tokens, finish_reason) == (3, 4, "stop")
    assert cost_usd == 0.00042
    assert fake_completions.kwargs is not None
    assert fake_completions.kwargs["response_format"] == {"type": "json_object"}
    assert fake_completions.kwargs["extra_body"] == {"reasoning": {"enabled": False}}
    assert "max_tokens" not in fake_completions.kwargs


@pytest.mark.fast
async def test_openrouter_chat_json_handles_missing_usage() -> None:
    client, fake_completions = _client_with_fake_chat("openrouter")
    fake_completions.usage = None

    text, prompt_tokens, completion_tokens, finish_reason, cost_usd = await client._chat_json(
        "google/gemini-2.5-flash",
        "System",
        "User",
        0.0,
    )

    assert text == '{"message": "pong"}'
    assert (prompt_tokens, completion_tokens, finish_reason) == (0, 0, "stop")
    assert cost_usd is None


@pytest.mark.fast
async def test_openrouter_chat_json_strips_json_fence_without_think_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_STRIP_THINK", raising=False)
    client, fake_completions = _client_with_fake_chat("openrouter")
    fake_completions.content = '```json\n{"message": "pong"}\n```'

    text, prompt_tokens, completion_tokens, finish_reason, cost_usd = await client._chat_json(
        "anthropic/claude-haiku-4.5",
        "System",
        "User",
        0.0,
    )

    assert text == '{"message": "pong"}'
    assert (prompt_tokens, completion_tokens, finish_reason) == (3, 4, "stop")
    assert cost_usd == 0.00042


@pytest.mark.fast
async def test_openrouter_complete_json_uses_provider_usage_cost() -> None:
    events: list[dict[str, Any]] = []
    client, fake_completions = _client_with_fake_chat("openrouter")
    fake_completions.usage = type(
        "Usage", (), {"prompt_tokens": 3, "completion_tokens": 4, "cost": 0.0123}
    )()

    with subscribe(events.append):
        echo = await client.complete_json(
            system='You echo. Return JSON {"message": "..."}.',
            user="Echo back the word pong.",
            schema=Echo,
            model="cheap",
        )

    assert echo == Echo(message="pong")
    llm_event = next(e for e in events if e["event"] == "llm_call")
    assert llm_event["provider"] == "openrouter"
    assert llm_event["prompt_tokens"] == 3
    assert llm_event["completion_tokens"] == 4
    assert llm_event["usd_cost"] == 0.0123


@pytest.mark.fast
async def test_openrouter_chat_text_omits_minimax_quirks_and_handles_missing_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_STRIP_THINK", raising=False)
    client, fake_completions = _client_with_fake_chat("openrouter")
    fake_completions.content = "Plain rationale."
    fake_completions.usage = None

    text, prompt_tokens, completion_tokens, finish_reason, cost_usd = await client._chat_text(
        "google/gemini-2.5-flash",
        "System",
        "User",
        0.0,
    )

    assert text == "Plain rationale."
    assert (prompt_tokens, completion_tokens, finish_reason) == (0, 0, "stop")
    assert cost_usd is None
    assert fake_completions.kwargs is not None
    assert fake_completions.kwargs["extra_body"] == {"reasoning": {"enabled": False}}
    assert "max_tokens" not in fake_completions.kwargs
    assert "response_format" not in fake_completions.kwargs


@pytest.mark.fast
async def test_openrouter_reasoning_opt_in_drops_disable_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_REASONING", "1")
    client, fake_completions = _client_with_fake_chat("openrouter")

    await client._chat_json("anthropic/claude-haiku-4.5", "System", "User", 0.0)

    assert fake_completions.kwargs is not None
    assert fake_completions.kwargs["extra_body"] == {}


@pytest.mark.fast
async def test_minimax_chat_json_retains_reasoning_split_and_token_cap() -> None:
    client, fake_completions = _client_with_fake_chat("minimax")

    await client._chat_json("MiniMax-M2.7-highspeed", "System", "User", 0.0)

    assert fake_completions.kwargs is not None
    assert fake_completions.kwargs["extra_body"] == {"reasoning_split": True}
    assert fake_completions.kwargs["max_tokens"] == 4096


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


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY not set")
async def test_openrouter_complete_json_roundtrip_emits_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GANDER_LLM_PROVIDER", "openrouter")
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
    assert e["provider"] == "openrouter"
    assert e["prompt_tokens"] >= 0
    assert e["completion_tokens"] >= 0
    assert e["duration_ms"] >= 0
    assert e["usd_cost"] > 0.0
