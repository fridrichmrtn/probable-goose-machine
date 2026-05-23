from __future__ import annotations

import os
from typing import Any

import pytest
from pydantic import BaseModel

from gander.llm import LLMClient, LogicalModel, _strip_think
from gander.obs import current_stage, subscribe


@pytest.mark.fast
def test_strip_think_handles_fences_and_thinkblocks() -> None:
    # think block + json fence
    assert _strip_think('<think>reasoning</think>\n\n```json\n{"a": 1}\n```') == '{"a": 1}'
    # fence only
    assert _strip_think('```json\n{"a": 1}\n```') == '{"a": 1}'
    # think only
    assert _strip_think('<think>reasoning</think>\n\n{"a": 1}') == '{"a": 1}'
    # bare json
    assert _strip_think('{"a": 1}') == '{"a": 1}'


class Echo(BaseModel):
    message: str


_LOGICAL_MODELS: tuple[LogicalModel, ...] = ("reasoning", "cheap", "extract", "vision")


def _clear_openrouter_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for logical in _LOGICAL_MODELS:
        suffix = logical.upper()
        monkeypatch.delenv(f"OPENROUTER_MODEL_{suffix}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_MODEL_{suffix}_FALLBACK", raising=False)


class _RetryingLLMClient(LLMClient):
    def __init__(self) -> None:
        self._provider = "openrouter"
        self.calls = 0

    def _resolve_model(self, logical: str, provider: str | None = None) -> str:
        return f"fake-{logical}"

    def _estimate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        return float(prompt_tokens + completion_tokens)

    async def _chat_json(
        self,
        model: str,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int | None = None,
        provider: str | None = None,
    ) -> tuple[str, int, int, str, float | None]:
        self.calls += 1
        if self.calls == 1:
            return "not json", 3, 5, "stop", None
        return '{"message": "pong"}', 7, 11, "stop", None


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
    assert llm_events[0]["provider"] == "openrouter"


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
    _clear_openrouter_model_env(monkeypatch)

    client = LLMClient()

    assert captured["api_key"] == "or-test"
    assert str(captured["base_url"]) == "https://openrouter.ai/api/v1"
    assert captured["default_headers"]["X-Title"] == "Gander"
    for logical in _LOGICAL_MODELS:
        assert client._resolve_model(logical) == "google/gemini-2.5-flash-lite"
        assert client._resolve_models(logical) == (
            "google/gemini-2.5-flash-lite",
            "google/gemini-2.5-flash",
        )

    monkeypatch.setenv("OPENROUTER_MODEL_REASONING", "anthropic/claude-sonnet-4.5")
    monkeypatch.setenv("OPENROUTER_MODEL_CHEAP", "google/gemini-2.5-flash-lite")
    monkeypatch.setenv("OPENROUTER_MODEL_EXTRACT", "anthropic/claude-opus-4.5")
    monkeypatch.setenv("OPENROUTER_MODEL_VISION", "qwen/qwen2.5-vl-72b-instruct")
    monkeypatch.setenv("OPENROUTER_MODEL_EXTRACT_FALLBACK", "google/gemini-2.5-flash-lite")
    monkeypatch.setenv("OPENROUTER_MODEL_VISION_FALLBACK", "google/gemini-2.5-flash")
    assert client._resolve_model("reasoning") == "anthropic/claude-sonnet-4.5"
    assert client._resolve_model("cheap") == "google/gemini-2.5-flash-lite"
    assert client._resolve_model("extract") == "anthropic/claude-opus-4.5"
    assert client._resolve_model("vision") == "qwen/qwen2.5-vl-72b-instruct"
    assert client._resolve_models("extract") == (
        "anthropic/claude-opus-4.5",
        "google/gemini-2.5-flash-lite",
    )
    assert client._resolve_models("vision") == (
        "qwen/qwen2.5-vl-72b-instruct",
        "google/gemini-2.5-flash",
    )


@pytest.mark.fast
@pytest.mark.parametrize("logical", _LOGICAL_MODELS)
def test_openrouter_default_route_for_each_slot(
    monkeypatch: pytest.MonkeyPatch,
    logical: LogicalModel,
) -> None:
    _clear_openrouter_model_env(monkeypatch)
    client = object.__new__(LLMClient)
    client._provider = "openrouter"

    assert client._resolve_model(logical) == "google/gemini-2.5-flash-lite"
    assert client._resolve_models(logical) == (
        "google/gemini-2.5-flash-lite",
        "google/gemini-2.5-flash",
    )


@pytest.mark.fast
@pytest.mark.parametrize("logical", _LOGICAL_MODELS)
def test_openrouter_route_env_override_and_duplicate_fallback_removal(
    monkeypatch: pytest.MonkeyPatch,
    logical: LogicalModel,
) -> None:
    _clear_openrouter_model_env(monkeypatch)
    suffix = logical.upper()
    monkeypatch.setenv(f"OPENROUTER_MODEL_{suffix}", "custom/primary")
    monkeypatch.setenv(
        f"OPENROUTER_MODEL_{suffix}_FALLBACK",
        "custom/primary, custom/fallback-a, custom/fallback-b",
    )
    client = object.__new__(LLMClient)
    client._provider = "openrouter"

    assert client._resolve_model(logical) == "custom/primary"
    assert client._resolve_models(logical) == (
        "custom/primary",
        "custom/fallback-a",
        "custom/fallback-b",
    )


@pytest.mark.fast
def test_openrouter_missing_key_and_removed_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GANDER_LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        LLMClient()

    monkeypatch.setenv("GANDER_LLM_PROVIDER", "anthropic")
    with pytest.raises(RuntimeError, match="'openrouter'"):
        LLMClient()

    monkeypatch.setenv("GANDER_LLM_PROVIDER", "legacy")
    with pytest.raises(RuntimeError, match="'openrouter'"):
        LLMClient()


class _FakeChatCompletions:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None
        self.all_kwargs: list[dict[str, Any]] = []
        self.content = '{"message": "pong"}'
        self.finish_reason = "stop"
        self.usage: Any = type(
            "Usage", (), {"prompt_tokens": 3, "completion_tokens": 4, "cost": 0.00042}
        )()
        self.fail_models: set[str] = set()

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        self.all_kwargs.append(kwargs)
        if kwargs["model"] in self.fail_models:
            raise RuntimeError(f"synthetic outage for {kwargs['model']}")
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
                            "finish_reason": self.finish_reason,
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
def test_provider_overrides_accept_only_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GANDER_LLM_PROVIDER_EXTRACT", "openrouter")
    client = object.__new__(LLMClient)
    client._provider = "openrouter"

    assert client._resolve_provider("cheap") == "openrouter"
    assert client._resolve_provider("extract") == "openrouter"

    monkeypatch.setenv("GANDER_LLM_PROVIDER_EXTRACT", "legacy")
    with pytest.raises(RuntimeError, match="'openrouter'"):
        client._resolve_provider("extract")


@pytest.mark.fast
async def test_openrouter_chat_json_uses_openrouter_request_shape(
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
async def test_openrouter_extract_falls_back_from_lite_to_flash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_MODEL_EXTRACT", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_EXTRACT_FALLBACK", raising=False)
    events: list[dict[str, Any]] = []
    client, fake_completions = _client_with_fake_chat("openrouter")
    fake_completions.fail_models = {"google/gemini-2.5-flash-lite"}

    with subscribe(events.append):
        echo = await client.complete_json(
            system='You echo. Return JSON {"message": "..."}.',
            user="Echo back the word pong.",
            schema=Echo,
            model="extract",
        )

    assert echo == Echo(message="pong")
    assert [call["model"] for call in fake_completions.all_kwargs] == [
        "google/gemini-2.5-flash-lite",
        "google/gemini-2.5-flash",
    ]
    fallback = next(e for e in events if e["event"] == "llm_model_fallback")
    assert fallback["logical_model"] == "extract"
    assert fallback["from_model"] == "google/gemini-2.5-flash-lite"
    assert fallback["to_model"] == "google/gemini-2.5-flash"
    llm_event = next(e for e in events if e["event"] == "llm_call")
    assert llm_event["model"] == "google/gemini-2.5-flash"
    assert llm_event["models_attempted"] == [
        "google/gemini-2.5-flash-lite",
        "google/gemini-2.5-flash",
    ]


@pytest.mark.fast
async def test_openrouter_chat_text_uses_openrouter_request_shape_and_handles_missing_usage(
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
async def test_openrouter_complete_text_falls_back_from_lite_to_flash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_MODEL_CHEAP", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_CHEAP_FALLBACK", raising=False)
    events: list[dict[str, Any]] = []
    client, fake_completions = _client_with_fake_chat("openrouter")
    fake_completions.content = "Normalized transcript."
    fake_completions.fail_models = {"google/gemini-2.5-flash-lite"}

    with subscribe(events.append):
        text = await client.complete_text(
            system="Normalize source text.",
            user="Raw transcript",
            model="cheap",
        )

    assert text == "Normalized transcript."
    assert [call["model"] for call in fake_completions.all_kwargs] == [
        "google/gemini-2.5-flash-lite",
        "google/gemini-2.5-flash",
    ]
    fallback = next(e for e in events if e["event"] == "llm_model_fallback")
    assert fallback["logical_model"] == "cheap"
    assert fallback["from_model"] == "google/gemini-2.5-flash-lite"
    assert fallback["to_model"] == "google/gemini-2.5-flash"
    llm_event = next(e for e in events if e["event"] == "llm_call")
    assert llm_event["model"] == "google/gemini-2.5-flash"
    assert llm_event["models_attempted"] == [
        "google/gemini-2.5-flash-lite",
        "google/gemini-2.5-flash",
    ]


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
async def test_openrouter_complete_vision_text_uses_image_url_and_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_MODEL_VISION", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_VISION_FALLBACK", raising=False)
    client, fake_completions = _client_with_fake_chat("openrouter")
    fake_completions.content = "Visible CV transcript"
    events: list[dict[str, Any]] = []

    with subscribe(events.append):
        text = await client.complete_vision_text(
            image_bytes=b"\x89PNG\r\n\x1a\nfake",
            prompt="Transcribe this page.",
            timeout_s=9.0,
        )

    assert text == "Visible CV transcript"
    assert fake_completions.kwargs is not None
    assert fake_completions.kwargs["model"] == "google/gemini-2.5-flash-lite"
    assert fake_completions.kwargs["timeout"] == 9.0
    content = fake_completions.kwargs["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "Transcribe this page."}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert fake_completions.kwargs["extra_body"] == {"reasoning": {"enabled": False}}
    llm_event = next(e for e in events if e["event"] == "llm_call")
    assert llm_event["provider"] == "openrouter"
    assert llm_event["model"] == "google/gemini-2.5-flash-lite"
    assert llm_event["usd_cost"] == 0.00042


@pytest.mark.fast
async def test_openrouter_complete_vision_text_falls_back_to_flash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_MODEL_VISION", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_VISION_FALLBACK", raising=False)
    events: list[dict[str, Any]] = []
    client, fake_completions = _client_with_fake_chat("openrouter")
    fake_completions.content = "Fallback vision transcript"
    fake_completions.fail_models = {"google/gemini-2.5-flash-lite"}

    with subscribe(events.append):
        text = await client.complete_vision_text(
            image_bytes=b"\x89PNG\r\n\x1a\nfake",
            prompt="Transcribe this page.",
        )

    assert text == "Fallback vision transcript"
    assert [call["model"] for call in fake_completions.all_kwargs] == [
        "google/gemini-2.5-flash-lite",
        "google/gemini-2.5-flash",
    ]
    fallback = next(e for e in events if e["event"] == "llm_model_fallback")
    assert fallback["logical_model"] == "vision"
    assert fallback["from_model"] == "google/gemini-2.5-flash-lite"
    assert fallback["to_model"] == "google/gemini-2.5-flash"
    llm_event = next(e for e in events if e["event"] == "llm_call")
    assert llm_event["model"] == "google/gemini-2.5-flash"
    assert llm_event["models_attempted"] == [
        "google/gemini-2.5-flash-lite",
        "google/gemini-2.5-flash",
    ]


@pytest.mark.fast
async def test_openrouter_complete_json_forwards_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_MODEL_CHEAP", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_CHEAP_FALLBACK", raising=False)
    client, fake_completions = _client_with_fake_chat("openrouter")

    await client.complete_json(
        system='You echo. Return JSON {"message": "..."}.',
        user="Echo back the word pong.",
        schema=Echo,
        model="cheap",
        max_tokens=512,
    )

    assert fake_completions.kwargs is not None
    assert fake_completions.kwargs["max_tokens"] == 512


@pytest.mark.fast
async def test_openrouter_complete_text_forwards_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_MODEL_CHEAP", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_CHEAP_FALLBACK", raising=False)
    client, fake_completions = _client_with_fake_chat("openrouter")
    fake_completions.content = "Plain rationale."

    await client.complete_text(
        system="Be concise.",
        user="Summarize the year.",
        model="cheap",
        max_tokens=200,
    )

    assert fake_completions.kwargs is not None
    assert fake_completions.kwargs["max_tokens"] == 200


@pytest.mark.fast
async def test_openrouter_complete_vision_text_forwards_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_MODEL_VISION", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_VISION_FALLBACK", raising=False)
    client, fake_completions = _client_with_fake_chat("openrouter")
    fake_completions.content = "Page transcript"

    await client.complete_vision_text(
        image_bytes=b"\x89PNG\r\n\x1a\nfake",
        prompt="Transcribe this page.",
        max_tokens=1500,
    )

    assert fake_completions.kwargs is not None
    assert fake_completions.kwargs["max_tokens"] == 1500


@pytest.mark.fast
async def test_chat_json_emits_llm_truncated_when_finish_reason_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_MODEL_CHEAP", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_CHEAP_FALLBACK", raising=False)
    client, fake_completions = _client_with_fake_chat("openrouter")
    fake_completions.finish_reason = "length"
    events: list[dict[str, Any]] = []

    token = current_stage.set("test_stage")
    try:
        with subscribe(events.append):
            echo = await client.complete_json(
                system='You echo. Return JSON {"message": "..."}.',
                user="Echo back the word pong.",
                schema=Echo,
                model="cheap",
                max_tokens=512,
            )
    finally:
        current_stage.reset(token)

    assert echo == Echo(message="pong")
    truncations = [e for e in events if e["event"] == "llm_truncated"]
    assert len(truncations) == 1
    truncation = truncations[0]
    assert truncation["stage"] == "test_stage"
    assert truncation["model"] == "google/gemini-2.5-flash-lite"
    assert truncation["max_tokens"] == 512
    assert truncation["prompt_tokens"] == 3
    assert truncation["completion_tokens"] == 4


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
