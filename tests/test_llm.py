from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from gander.llm import (
    _LOCAL_ROUTES,
    _OPENROUTER_ROUTES,
    MODEL_PRICES,
    LLMClient,
    LogicalModel,
    _strip_think,
    check_env,
)
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

_EXPECTED_DEFAULT_ROUTE: dict[LogicalModel, tuple[str, tuple[str, ...]]] = {
    "reasoning": (
        "google/gemini-3.5-flash",
        ("google/gemini-3.5-flash", "google/gemini-3.1-flash-lite"),
    ),
    "cheap": (
        "google/gemini-3.1-flash-lite",
        ("google/gemini-3.1-flash-lite", "google/gemini-3.5-flash"),
    ),
    "extract": (
        "google/gemini-3.1-flash-lite",
        ("google/gemini-3.1-flash-lite", "google/gemini-3.5-flash"),
    ),
    "vision": (
        "google/gemini-3.1-flash-lite",
        ("google/gemini-3.1-flash-lite", "google/gemini-3.5-flash"),
    ),
}


def _clear_openrouter_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for logical in _LOGICAL_MODELS:
        suffix = logical.upper()
        monkeypatch.delenv(f"OPENROUTER_MODEL_{suffix}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_MODEL_{suffix}_FALLBACK", raising=False)


class _RetryingLLMClient(LLMClient):
    def __init__(self) -> None:
        self._provider = "openrouter"
        self.calls = 0

    def _resolve_model(self, logical: str, provider: str = "openrouter") -> str:
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
        timeout_s: float | None = None,
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
        expected_primary, expected_models = _EXPECTED_DEFAULT_ROUTE[logical]
        assert client._resolve_model(logical, "openrouter") == expected_primary
        assert client._resolve_models(logical) == expected_models

    monkeypatch.setenv("OPENROUTER_MODEL_REASONING", "anthropic/claude-sonnet-4.5")
    monkeypatch.setenv("OPENROUTER_MODEL_CHEAP", "anthropic/claude-haiku-4.5")
    monkeypatch.setenv("OPENROUTER_MODEL_EXTRACT", "anthropic/claude-opus-4.5")
    monkeypatch.setenv("OPENROUTER_MODEL_VISION", "qwen/qwen2.5-vl-72b-instruct")
    monkeypatch.setenv("OPENROUTER_MODEL_EXTRACT_FALLBACK", "google/gemini-3.1-flash-lite")
    monkeypatch.setenv("OPENROUTER_MODEL_VISION_FALLBACK", "google/gemini-3.5-flash")
    assert client._resolve_model("reasoning", "openrouter") == "anthropic/claude-sonnet-4.5"
    assert client._resolve_model("cheap", "openrouter") == "anthropic/claude-haiku-4.5"
    assert client._resolve_model("extract", "openrouter") == "anthropic/claude-opus-4.5"
    assert client._resolve_model("vision", "openrouter") == "qwen/qwen2.5-vl-72b-instruct"
    assert client._resolve_models("extract") == (
        "anthropic/claude-opus-4.5",
        "google/gemini-3.1-flash-lite",
    )
    assert client._resolve_models("vision") == (
        "qwen/qwen2.5-vl-72b-instruct",
        "google/gemini-3.5-flash",
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

    expected_primary, expected_models = _EXPECTED_DEFAULT_ROUTE[logical]
    assert client._resolve_model(logical, "openrouter") == expected_primary
    assert client._resolve_models(logical) == expected_models


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

    assert client._resolve_model(logical, "openrouter") == "custom/primary"
    assert client._resolve_models(logical) == (
        "custom/primary",
        "custom/fallback-a",
        "custom/fallback-b",
    )


@pytest.mark.fast
def test_check_env_raises_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Boot-time gate: check_env() is where a missing key fails fast. Construction
    # itself stays cheap (see test_llmclient_construction_is_cheap_without_key).
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        check_env()


@pytest.mark.fast
def test_check_env_passes_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    check_env()  # must not raise


@pytest.mark.fast
def test_llmclient_construction_is_cheap_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The T47 wart: tests had to stub OPENROUTER_API_KEY purely because the
    # constructor raised. After the move to check_env(), construction succeeds
    # with no key and the first real call is the failure point instead.
    monkeypatch.setenv("GANDER_LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    LLMClient()  # must not raise


@pytest.mark.fast
def test_removed_providers_still_rejected_at_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

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
        self.delay_s = 0.0

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        self.all_kwargs.append(kwargs)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
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
def test_provider_overrides_validate_known_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GANDER_LLM_PROVIDER_EXTRACT", "openrouter")
    client = object.__new__(LLMClient)
    client._provider = "openrouter"

    assert client._resolve_provider("cheap") == "openrouter"
    assert client._resolve_provider("extract") == "openrouter"

    # `local` is a valid per-slot override (opt-in, default OFF).
    monkeypatch.setenv("GANDER_LLM_PROVIDER_EXTRACT", "local")
    assert client._resolve_provider("extract") == "local"

    monkeypatch.setenv("GANDER_LLM_PROVIDER_EXTRACT", "legacy")
    with pytest.raises(RuntimeError, match="expected 'openrouter' or 'local'"):
        client._resolve_provider("extract")


@pytest.mark.fast
def test_local_provider_builds_client_against_default_local_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("gander.llm.AsyncOpenAI", _FakeAsyncOpenAI)
    monkeypatch.setenv("GANDER_LLM_PROVIDER", "local")
    monkeypatch.delenv("GANDER_LOCAL_BASE_URL", raising=False)
    monkeypatch.delenv("GANDER_LOCAL_API_KEY", raising=False)

    client = LLMClient()

    assert client._provider == "local"
    assert str(captured["base_url"]) == "http://localhost:11434/v1"
    assert captured["api_key"] == "local"
    # The OpenRouter referer/title headers don't apply to a local endpoint.
    assert "default_headers" not in captured


@pytest.mark.fast
def test_local_provider_honours_base_url_and_key_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("gander.llm.AsyncOpenAI", _FakeAsyncOpenAI)
    monkeypatch.setenv("GANDER_LLM_PROVIDER", "local")
    monkeypatch.setenv("GANDER_LOCAL_BASE_URL", "http://gpu-box:8000/v1")
    monkeypatch.setenv("GANDER_LOCAL_API_KEY", "secret-token")

    LLMClient()

    assert str(captured["base_url"]) == "http://gpu-box:8000/v1"
    assert captured["api_key"] == "secret-token"


@pytest.mark.fast
def test_local_per_slot_override_resolves_local_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_openrouter_model_env(monkeypatch)
    monkeypatch.setenv("GANDER_LLM_PROVIDER_CHEAP", "local")
    client = object.__new__(LLMClient)
    client._provider = "openrouter"

    assert client._resolve_provider("cheap") == "local"
    # The local cheap slot resolves from _LOCAL_ROUTES, not the OpenRouter table.
    assert client._resolve_models("cheap") == (
        _LOCAL_ROUTES["cheap"].primary,
        *_LOCAL_ROUTES["cheap"].fallbacks,
    )
    # A slot without an override still resolves OpenRouter (default unchanged).
    assert client._resolve_provider("extract") == "openrouter"
    assert client._resolve_models("extract")[0] == _OPENROUTER_ROUTES["extract"].primary


@pytest.mark.fast
def test_cost_usd_falls_back_to_model_prices_when_provider_cost_absent() -> None:
    client = object.__new__(LLMClient)
    client._provider = "openrouter"
    prompt_price, completion_price = MODEL_PRICES["google/gemini-3.5-flash"]
    # 1M prompt + 1M completion tokens ⇒ exactly (prompt_price + completion_price).
    cost = client._cost_usd("google/gemini-3.5-flash", 1_000_000, 1_000_000, None, "openrouter")
    assert cost == pytest.approx(prompt_price + completion_price)


@pytest.mark.fast
def test_cost_usd_prefers_provider_reported_cost() -> None:
    client = object.__new__(LLMClient)
    client._provider = "openrouter"
    # Provider-reported cost wins over the local estimate when present.
    cost = client._cost_usd("google/gemini-3.5-flash", 1_000, 2_000, 0.0042, "openrouter")
    assert cost == 0.0042


@pytest.mark.fast
def test_cost_usd_local_provider_estimates_zero() -> None:
    client = object.__new__(LLMClient)
    client._provider = "openrouter"
    # A self-hosted model isn't in MODEL_PRICES, so even large token counts
    # estimate to 0 — local inference is free.
    cost = client._cost_usd("llama3.2", 5_000_000, 5_000_000, None, "local")
    assert cost == 0.0


@pytest.mark.fast
async def test_vision_ignores_local_override_and_uses_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_MODEL_VISION", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_VISION_FALLBACK", raising=False)
    monkeypatch.delenv("OPENROUTER_REASONING", raising=False)
    # A local override on the vision slot must degrade back to OpenRouter rather
    # than route to a (often vision-less) local model.
    monkeypatch.setenv("GANDER_LLM_PROVIDER_VISION", "local")
    client, fake_completions = _client_with_fake_chat("openrouter")
    fake_completions.content = "Transcript"
    events: list[dict[str, Any]] = []

    with subscribe(events.append):
        text = await client.complete_vision_text(
            image_bytes=b"\x89PNG\r\n\x1a\nfake",
            prompt="Transcribe this page.",
            timeout_s=5.0,
        )

    assert text == "Transcript"
    assert fake_completions.kwargs is not None
    # Routed through the OpenRouter vision model + its routing directive.
    assert fake_completions.kwargs["model"] == _OPENROUTER_ROUTES["vision"].primary
    assert fake_completions.kwargs["extra_body"] == {"reasoning": {"enabled": False}}
    llm_event = next(e for e in events if e["event"] == "llm_call")
    assert llm_event["provider"] == "openrouter"


@pytest.mark.fast
async def test_openrouter_chat_json_uses_openrouter_request_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_STRIP_THINK", raising=False)
    client, fake_completions = _client_with_fake_chat("openrouter")

    text, prompt_tokens, completion_tokens, finish_reason, cost_usd = await client._chat_json(
        "google/gemini-3.5-flash",
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
        "google/gemini-3.5-flash",
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
    fake_completions.fail_models = {"google/gemini-3.1-flash-lite"}

    with subscribe(events.append):
        echo = await client.complete_json(
            system='You echo. Return JSON {"message": "..."}.',
            user="Echo back the word pong.",
            schema=Echo,
            model="extract",
        )

    assert echo == Echo(message="pong")
    assert [call["model"] for call in fake_completions.all_kwargs] == [
        "google/gemini-3.1-flash-lite",
        "google/gemini-3.5-flash",
    ]
    fallback = next(e for e in events if e["event"] == "llm_model_fallback")
    assert fallback["logical_model"] == "extract"
    assert fallback["from_model"] == "google/gemini-3.1-flash-lite"
    assert fallback["to_model"] == "google/gemini-3.5-flash"
    llm_event = next(e for e in events if e["event"] == "llm_call")
    assert llm_event["model"] == "google/gemini-3.5-flash"
    assert llm_event["models_attempted"] == [
        "google/gemini-3.1-flash-lite",
        "google/gemini-3.5-flash",
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
        "google/gemini-3.5-flash",
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
    fake_completions.fail_models = {"google/gemini-3.1-flash-lite"}

    with subscribe(events.append):
        text = await client.complete_text(
            system="Normalize source text.",
            user="Raw transcript",
            model="cheap",
        )

    assert text == "Normalized transcript."
    assert [call["model"] for call in fake_completions.all_kwargs] == [
        "google/gemini-3.1-flash-lite",
        "google/gemini-3.5-flash",
    ]
    fallback = next(e for e in events if e["event"] == "llm_model_fallback")
    assert fallback["logical_model"] == "cheap"
    assert fallback["from_model"] == "google/gemini-3.1-flash-lite"
    assert fallback["to_model"] == "google/gemini-3.5-flash"
    llm_event = next(e for e in events if e["event"] == "llm_call")
    assert llm_event["model"] == "google/gemini-3.5-flash"
    assert llm_event["models_attempted"] == [
        "google/gemini-3.1-flash-lite",
        "google/gemini-3.5-flash",
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
    assert fake_completions.kwargs["model"] == "google/gemini-3.1-flash-lite"
    assert fake_completions.kwargs["timeout"] == 9.0
    content = fake_completions.kwargs["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "Transcribe this page."}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert fake_completions.kwargs["extra_body"] == {"reasoning": {"enabled": False}}
    llm_event = next(e for e in events if e["event"] == "llm_call")
    assert llm_event["provider"] == "openrouter"
    assert llm_event["model"] == "google/gemini-3.1-flash-lite"
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
    fake_completions.fail_models = {"google/gemini-3.1-flash-lite"}

    with subscribe(events.append):
        text = await client.complete_vision_text(
            image_bytes=b"\x89PNG\r\n\x1a\nfake",
            prompt="Transcribe this page.",
        )

    assert text == "Fallback vision transcript"
    assert [call["model"] for call in fake_completions.all_kwargs] == [
        "google/gemini-3.1-flash-lite",
        "google/gemini-3.5-flash",
    ]
    fallback = next(e for e in events if e["event"] == "llm_model_fallback")
    assert fallback["logical_model"] == "vision"
    assert fallback["from_model"] == "google/gemini-3.1-flash-lite"
    assert fallback["to_model"] == "google/gemini-3.5-flash"
    llm_event = next(e for e in events if e["event"] == "llm_call")
    assert llm_event["model"] == "google/gemini-3.5-flash"
    assert llm_event["models_attempted"] == [
        "google/gemini-3.1-flash-lite",
        "google/gemini-3.5-flash",
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
async def test_openrouter_complete_json_forwards_timeout_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_MODEL_CHEAP", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_CHEAP_FALLBACK", raising=False)
    monkeypatch.setenv("GANDER_LLM_TIMEOUT_S", "12.5")
    client, fake_completions = _client_with_fake_chat("openrouter")

    await client.complete_json(
        system='You echo. Return JSON {"message": "..."}.',
        user="Echo back the word pong.",
        schema=Echo,
        model="cheap",
    )

    assert fake_completions.kwargs is not None
    assert fake_completions.kwargs["timeout"] == pytest.approx(12.5, abs=0.05)


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
async def test_openrouter_complete_text_forwards_timeout_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_MODEL_CHEAP", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_CHEAP_FALLBACK", raising=False)
    monkeypatch.setenv("GANDER_LLM_TIMEOUT_S", "13")
    client, fake_completions = _client_with_fake_chat("openrouter")
    fake_completions.content = "Plain rationale."

    await client.complete_text(
        system="Be concise.",
        user="Summarize the year.",
        model="cheap",
    )

    assert fake_completions.kwargs is not None
    assert fake_completions.kwargs["timeout"] == pytest.approx(13.0, abs=0.05)


@pytest.mark.fast
async def test_complete_json_timeout_is_wall_budget_across_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_MODEL_CHEAP", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_CHEAP_FALLBACK", raising=False)
    monkeypatch.setenv("GANDER_LLM_TIMEOUT_S", "0")
    client, fake_completions = _client_with_fake_chat("openrouter")
    fake_completions.delay_s = 1.0

    t0 = time.perf_counter()
    with pytest.raises(TimeoutError):
        await client.complete_json(
            system='You echo. Return JSON {"message": "..."}.',
            user="Echo back the word pong.",
            schema=Echo,
            model="cheap",
        )

    assert time.perf_counter() - t0 < 0.5
    assert len(fake_completions.all_kwargs) <= 2
    assert fake_completions.all_kwargs[0]["timeout"] == pytest.approx(0.1, abs=0.05)


@pytest.mark.fast
async def test_complete_text_timeout_is_wall_budget_across_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_MODEL_CHEAP", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_CHEAP_FALLBACK", raising=False)
    monkeypatch.setenv("GANDER_LLM_TIMEOUT_S", "0")
    client, fake_completions = _client_with_fake_chat("openrouter")
    fake_completions.delay_s = 1.0
    fake_completions.content = "Plain rationale."

    t0 = time.perf_counter()
    with pytest.raises(TimeoutError):
        await client.complete_text(
            system="Be concise.",
            user="Summarize the year.",
            model="cheap",
        )

    assert time.perf_counter() - t0 < 0.5
    assert len(fake_completions.all_kwargs) <= 2
    assert fake_completions.all_kwargs[0]["timeout"] == pytest.approx(0.1, abs=0.05)


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
async def test_openrouter_complete_vision_text_uses_timeout_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_MODEL_VISION", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL_VISION_FALLBACK", raising=False)
    monkeypatch.setenv("GANDER_VISION_TIMEOUT_S", "8.5")
    client, fake_completions = _client_with_fake_chat("openrouter")
    fake_completions.content = "Page transcript"

    await client.complete_vision_text(
        image_bytes=b"\x89PNG\r\n\x1a\nfake",
        prompt="Transcribe this page.",
    )

    assert fake_completions.kwargs is not None
    assert fake_completions.kwargs["timeout"] == 8.5


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
    assert truncation["model"] == "google/gemini-3.1-flash-lite"
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


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY not set")
async def test_configured_slugs_present_in_catalog() -> None:
    """Catalog guard — fail CI if any configured slug is delisted from OpenRouter.

    The 2.5 family was silently delisted (both primary AND fallback 404'd
    together), so this asserts every route's primary and fallbacks still resolve
    against the live `/models` catalog. Covers fallbacks too: a rotted fallback
    is invisible until the primary also fails, which is exactly how the 2.5
    outage stayed hidden.
    """
    configured: set[str] = set()
    for route in _OPENROUTER_ROUTES.values():
        configured.add(route.primary)
        configured.update(route.fallbacks)

    key = os.environ["OPENROUTER_API_KEY"]
    # Mirror the production request shape (gander.llm._make_client): OpenRouter
    # ranks and, on some plans, gates requests by the HTTP-Referer / X-Title
    # attribution headers, so probing without them can resolve differently than
    # the app's real calls — a CI-only catalog mismatch. Same env keys/defaults.
    headers = {
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": os.environ.get(
            "OPENROUTER_HTTP_REFERER",
            "https://huggingface.co/spaces/fridrichmrtn/probable-goose-machine",
        ),
        "X-Title": os.environ.get("OPENROUTER_APP_TITLE", "Gander"),
    }
    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.get(
            "https://openrouter.ai/api/v1/models",
            headers=headers,
        )
        resp.raise_for_status()
        catalog = {entry["id"] for entry in resp.json()["data"]}

    missing = sorted(slug for slug in configured if slug not in catalog)
    assert not missing, (
        f"Configured OpenRouter slugs absent from the live catalog: {missing}. "
        "Re-pin _OPENROUTER_ROUTES in gander.llm (and the CLAUDE.md / .env.example "
        "model policy) to currently-listed ids."
    )
