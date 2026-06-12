from __future__ import annotations

import asyncio
import base64
import functools
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from gander import obs
from gander.config import env_float

LogicalModel = Literal["reasoning", "cheap", "extract", "vision"]
ProviderName = Literal["openrouter"]

# Some reasoning models prepend a <think>...</think> block to chat output and
# can wrap JSON-mode payloads in ```json fences. Strip both before parsing.
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


def _strip_json_fence(text: str) -> str:
    m = _JSON_FENCE_RE.match(text.strip())
    return m.group(1).strip() if m else text


def _strip_think(text: str) -> str:
    text = _THINK_BLOCK_RE.sub("", text, count=1).strip()
    return _strip_json_fence(text)


def _openrouter_extra_body() -> dict[str, Any]:
    # OpenRouter routes Claude 4.x with hybrid reasoning enabled by default; the
    # OpenAI-compat shim then leaves message.content empty and counts every output
    # token as thinking, which breaks JSON-mode callers. Disable reasoning unless
    # explicitly opted in (e.g. for DeepSeek-R1 or OpenAI o-series).
    if os.environ.get("OPENROUTER_REASONING") == "1":
        return {}
    return {"reasoning": {"enabled": False}}


def _usage_tokens(usage: Any) -> tuple[int, int]:
    if usage is None:
        return 0, 0
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    return int(prompt), int(completion)


def _emit_truncation(
    *,
    finish_reason: str,
    max_tokens: int | None,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    # Silent quality regression: the cap clipped the response (finish_reason
    # "length") but JSON parsing may still succeed downstream. Surface a
    # dedicated obs signal so operators can see cap hits and raise the cap.
    if finish_reason != "length" or max_tokens is None:
        return
    obs.emit(
        obs.current_stage.get(),
        "llm_truncated",
        model=model,
        max_tokens=max_tokens,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def _usage_cost_usd(usage: Any) -> float | None:
    """Return provider-reported USD cost when the response includes it."""
    if usage is None:
        return None
    cost = getattr(usage, "cost", None)
    if cost is None and isinstance(usage, dict):
        cost = usage.get("cost")
    if cost is None:
        model_extra = getattr(usage, "model_extra", None)
        if isinstance(model_extra, dict):
            cost = model_extra.get("cost")
    if cost is None:
        return None
    try:
        return float(cost)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class _OpenRouterRoute:
    primary: str
    fallbacks: tuple[str, ...]


# Re-verify on OpenRouter catalog change; slugs drift faster than SDK APIs.
# `reasoning` is the growth-stage slot; Flash-Lite hit its capability boundary on
# adversarial CZ fixtures (PRD §4.4 anchor-verified actions), so this slot keeps
# full Flash as primary. The cheap/extract/vision slots default to Flash-Lite.
#
# Slug pinning (P1.4): these are FLOATING tags, not pinned snapshots. OpenRouter
# publishes no dated/snapshot variant for the Gemini 2.5 Flash family — there is
# no `google/gemini-2.5-flash-...-MM-YYYY` to pin to — so "pin to a dated slug"
# is not an available option here; the bare slug is the only id the API accepts.
# Known risk, verified 2026-06-12 against https://openrouter.ai/api/v1/models:
# the live catalog had already rotated to `google/gemini-3.5-flash` /
# `google/gemini-3.1-flash-lite` and no longer lists the 2.5 ids at all. These
# routes are therefore time-sensitive: when a 2.5 slug stops resolving, the
# fallback chain still points at the sibling 2.5 slug (same vintage), so both
# can fail together. Re-pin to the current Gemini flash-tier ids — or to the
# `~google/gemini-flash-latest` router alias — when refreshing this table.
_OPENROUTER_SLOTS: tuple[LogicalModel, ...] = ("reasoning", "cheap", "extract", "vision")
_OPENROUTER_ROUTES: dict[LogicalModel, _OpenRouterRoute] = {
    "reasoning": _OpenRouterRoute(
        primary="google/gemini-2.5-flash",
        fallbacks=("google/gemini-2.5-flash-lite",),
    ),
    "cheap": _OpenRouterRoute(
        primary="google/gemini-2.5-flash-lite",
        fallbacks=("google/gemini-2.5-flash",),
    ),
    "extract": _OpenRouterRoute(
        primary="google/gemini-2.5-flash-lite",
        fallbacks=("google/gemini-2.5-flash",),
    ),
    "vision": _OpenRouterRoute(
        primary="google/gemini-2.5-flash-lite",
        fallbacks=("google/gemini-2.5-flash",),
    ),
}

# USD per 1M tokens, (prompt, completion).
# OpenRouter normally reports usage.cost; this table is only a local fallback.
MODEL_PRICES: dict[str, tuple[float, float]] = {}
_DEFAULT_LLM_TIMEOUT_S = 60.0
_DEFAULT_VISION_TIMEOUT_S = 120.0

_MISSING_KEY_MESSAGE = "OPENROUTER_API_KEY not set — add it to .env or export it"


def check_env() -> None:
    """Fail fast at boot if required runtime env is missing.

    Called once at app startup (app.py) so the process dies with a clear
    message instead of a confusing auth error on the first real LLM call.
    `LLMClient` construction itself stays cheap and does not raise, so tests
    that stub LLM methods need no fake key.
    """
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise RuntimeError(_MISSING_KEY_MESSAGE)


def _llm_timeout_s() -> float:
    return env_float("GANDER_LLM_TIMEOUT_S", _DEFAULT_LLM_TIMEOUT_S)


def _vision_timeout_s() -> float:
    return env_float("GANDER_VISION_TIMEOUT_S", _DEFAULT_VISION_TIMEOUT_S)


def _deadline_after(timeout_s: float) -> float:
    return time.perf_counter() + timeout_s


def _remaining_timeout_s(deadline: float) -> float:
    remaining = deadline - time.perf_counter()
    if remaining <= 0:
        raise TimeoutError("LLM call timed out")
    return remaining


class LLMClient:
    """Async chat client over OpenRouter.

    Provider selected via GANDER_LLM_PROVIDER env, which must be `openrouter`.
    A logical model may still set GANDER_LLM_PROVIDER_<LOGICAL_MODEL>, but it
    must also be `openrouter`; legacy providers fail at startup/call time.
    Every call emits an `llm_call` telemetry event (success or failure).
    """

    def __init__(self) -> None:
        self._provider = self._validate_provider(
            os.environ.get("GANDER_LLM_PROVIDER", "openrouter"),
            "GANDER_LLM_PROVIDER",
        )
        self._client: AsyncOpenAI
        self._clients: dict[ProviderName, AsyncOpenAI] = {}
        self._client = self._build_client(self._provider)
        self._clients[self._provider] = self._client

    @staticmethod
    def _validate_provider(raw: str, env_name: str) -> ProviderName:
        provider = raw.strip().lower()
        if provider == "openrouter":
            return "openrouter"
        raise RuntimeError(f"Unknown {env_name}={raw!r}; expected 'openrouter'")

    def _build_client(self, provider: ProviderName) -> AsyncOpenAI:
        # Construction stays cheap and never raises on a missing key — boot-time
        # check_env() is the early-fail gate (app.py). The OpenAI SDK rejects an
        # empty api_key at construction, so fall back to a placeholder when the
        # key is absent; a real missing-key run surfaces as a 401 on the first
        # call, which stage_boundary converts to a user-facing StageFailure.
        api_key = os.environ.get("OPENROUTER_API_KEY") or "missing-openrouter-key"
        return AsyncOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": os.environ.get(
                    "OPENROUTER_HTTP_REFERER",
                    "https://huggingface.co/spaces/fridrichmrtn/probable-goose-machine",
                ),
                "X-Title": os.environ.get("OPENROUTER_APP_TITLE", "Gander"),
            },
        )

    def _client_for_provider(self, provider: ProviderName) -> AsyncOpenAI:
        if provider == self._provider:
            return self._client
        if provider not in self._clients:
            self._clients[provider] = self._build_client(provider)
        return self._clients[provider]

    def _resolve_provider(self, logical: LogicalModel) -> ProviderName:
        env_key = f"GANDER_LLM_PROVIDER_{logical.upper()}"
        raw = os.environ.get(env_key)
        if raw is None:
            return self._provider
        return self._validate_provider(raw, env_key)

    def _resolve_model(self, logical: LogicalModel) -> str:
        env_key = f"OPENROUTER_MODEL_{logical.upper()}"
        return os.environ.get(env_key, _OPENROUTER_ROUTES[logical].primary)

    def _resolve_models(
        self, logical: LogicalModel, provider: ProviderName | None = None
    ) -> tuple[str, ...]:
        provider = provider or self._resolve_provider(logical)
        primary = self._resolve_model(logical)
        env_key = f"OPENROUTER_MODEL_{logical.upper()}_FALLBACK"
        fallback_raw = os.environ.get(env_key)
        if fallback_raw is None:
            fallbacks = _OPENROUTER_ROUTES[logical].fallbacks
        else:
            fallbacks = tuple(model.strip() for model in fallback_raw.split(",") if model.strip())
        return (primary, *(model for model in fallbacks if model != primary))

    def _estimate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        price = MODEL_PRICES.get(model)
        if price is None:
            return 0.0
        return (prompt_tokens / 1e6) * price[0] + (completion_tokens / 1e6) * price[1]

    def _cost_usd(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        provider_cost_usd: float | None,
        provider: ProviderName | None = None,
    ) -> float:
        provider = provider or self._provider
        if provider == "openrouter" and provider_cost_usd is not None:
            return provider_cost_usd
        return self._estimate_cost(model, prompt_tokens, completion_tokens)

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        model: LogicalModel = "reasoning",
        temperature: float = 0.0,
        max_retries: int = 1,
        max_tokens: int | None = None,
    ) -> BaseModel:
        provider = self._resolve_provider(model)
        resolved_models = self._resolve_models(model, provider)
        t0 = time.perf_counter()
        deadline = _deadline_after(_llm_timeout_s())
        prompt_tokens = 0
        completion_tokens = 0
        provider_cost_usd: float | None = None
        finish_reason = ""
        attempted_models: list[str] = []
        try:
            last_err: Exception | None = None
            for model_i, resolved in enumerate(resolved_models):
                current_user = user
                validation_err: ValidationError | json.JSONDecodeError | None = None
                try:
                    for attempt in range(max_retries + 1):
                        if attempt > 0 and validation_err is not None:
                            current_user = (
                                user
                                + f"\n\nYour previous output failed validation: {validation_err}"
                                + "\n\nReturn corrected JSON only."
                            )
                        attempt_timeout_s = _remaining_timeout_s(deadline)
                        attempted_models.append(resolved)
                        (
                            text,
                            attempt_prompt,
                            attempt_completion,
                            finish_reason,
                            attempt_cost_usd,
                        ) = await asyncio.wait_for(
                            self._chat_json(
                                resolved,
                                system,
                                current_user,
                                temperature,
                                max_tokens=max_tokens,
                                timeout_s=attempt_timeout_s,
                                provider=provider,
                            ),
                            timeout=attempt_timeout_s,
                        )
                        prompt_tokens += attempt_prompt
                        completion_tokens += attempt_completion
                        if attempt_cost_usd is not None:
                            provider_cost_usd = (provider_cost_usd or 0.0) + attempt_cost_usd
                        try:
                            parsed = json.loads(text)
                            return schema.model_validate(parsed)
                        except (ValidationError, json.JSONDecodeError) as err:
                            validation_err = err
                            last_err = err
                            if attempt >= max_retries:
                                break
                    if validation_err is not None:
                        last_err = validation_err
                except Exception as err:
                    last_err = err

                if model_i < len(resolved_models) - 1:
                    obs.emit(
                        obs.current_stage.get(),
                        "llm_model_fallback",
                        provider=provider,
                        logical_model=model,
                        from_model=resolved,
                        to_model=resolved_models[model_i + 1],
                        reason=type(last_err).__name__ if last_err is not None else "unknown",
                    )
                    continue
                if last_err is not None:
                    raise last_err
            raise RuntimeError("unreachable: complete_json exhausted models without return")
        finally:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            obs.emit(
                obs.current_stage.get(),
                "llm_call",
                provider=provider,
                model=attempted_models[-1] if attempted_models else resolved_models[0],
                models_attempted=attempted_models,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usd_cost=self._cost_usd(
                    attempted_models[-1] if attempted_models else resolved_models[0],
                    prompt_tokens,
                    completion_tokens,
                    provider_cost_usd,
                    provider,
                ),
                duration_ms=duration_ms,
                finish_reason=finish_reason,
            )

    async def complete_text(
        self,
        *,
        system: str,
        user: str,
        model: LogicalModel = "cheap",
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        provider = self._resolve_provider(model)
        resolved_models = self._resolve_models(model, provider)
        t0 = time.perf_counter()
        deadline = _deadline_after(_llm_timeout_s())
        prompt_tokens = 0
        completion_tokens = 0
        provider_cost_usd: float | None = None
        finish_reason = ""
        attempted_models: list[str] = []
        try:
            last_err: Exception | None = None
            for model_i, resolved in enumerate(resolved_models):
                try:
                    attempt_timeout_s = _remaining_timeout_s(deadline)
                    attempted_models.append(resolved)
                    (
                        text,
                        attempt_prompt,
                        attempt_completion,
                        finish_reason,
                        attempt_cost_usd,
                    ) = await asyncio.wait_for(
                        self._chat_text(
                            resolved,
                            system,
                            user,
                            temperature,
                            max_tokens=max_tokens,
                            timeout_s=attempt_timeout_s,
                            provider=provider,
                        ),
                        timeout=attempt_timeout_s,
                    )
                    prompt_tokens += attempt_prompt
                    completion_tokens += attempt_completion
                    if attempt_cost_usd is not None:
                        provider_cost_usd = (provider_cost_usd or 0.0) + attempt_cost_usd
                    return text
                except Exception as err:
                    last_err = err
                    if model_i < len(resolved_models) - 1:
                        obs.emit(
                            obs.current_stage.get(),
                            "llm_model_fallback",
                            provider=provider,
                            logical_model=model,
                            from_model=resolved,
                            to_model=resolved_models[model_i + 1],
                            reason=type(err).__name__,
                        )
                        continue
                    raise
            if last_err is not None:
                raise last_err
            raise RuntimeError("unreachable: complete_text exhausted models without return")
        finally:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            obs.emit(
                obs.current_stage.get(),
                "llm_call",
                provider=provider,
                model=attempted_models[-1] if attempted_models else resolved_models[0],
                models_attempted=attempted_models,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usd_cost=self._cost_usd(
                    attempted_models[-1] if attempted_models else resolved_models[0],
                    prompt_tokens,
                    completion_tokens,
                    provider_cost_usd,
                    provider,
                ),
                duration_ms=duration_ms,
                finish_reason=finish_reason,
            )

    async def complete_vision_text(
        self,
        *,
        image_bytes: bytes,
        prompt: str,
        mime_type: str = "image/png",
        timeout_s: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Transcribe one rendered page through OpenRouter vision."""
        self._resolve_provider("vision")
        resolved_timeout_s = _vision_timeout_s() if timeout_s is None else timeout_s
        return await self._complete_openrouter_vision_text(
            image_bytes=image_bytes,
            prompt=prompt,
            mime_type=mime_type,
            timeout_s=resolved_timeout_s,
            max_tokens=max_tokens,
        )

    async def _complete_openrouter_vision_text(
        self,
        *,
        image_bytes: bytes,
        prompt: str,
        mime_type: str,
        timeout_s: float,
        max_tokens: int | None = None,
    ) -> str:
        provider: ProviderName = "openrouter"
        resolved_models = self._resolve_models("vision", provider)
        t0 = time.perf_counter()
        prompt_tokens = 0
        completion_tokens = 0
        provider_cost_usd: float | None = None
        finish_reason = ""
        attempted_models: list[str] = []
        try:
            for model_i, resolved in enumerate(resolved_models):
                try:
                    attempted_models.append(resolved)
                    (
                        text,
                        attempt_prompt,
                        attempt_completion,
                        finish_reason,
                        attempt_cost_usd,
                    ) = await self._chat_vision_text(
                        resolved,
                        image_bytes,
                        prompt,
                        mime_type,
                        timeout_s,
                        max_tokens,
                    )
                    prompt_tokens += attempt_prompt
                    completion_tokens += attempt_completion
                    if attempt_cost_usd is not None:
                        provider_cost_usd = (provider_cost_usd or 0.0) + attempt_cost_usd
                    return text
                except Exception as err:
                    if model_i < len(resolved_models) - 1:
                        obs.emit(
                            obs.current_stage.get(),
                            "llm_model_fallback",
                            provider=provider,
                            logical_model="vision",
                            from_model=resolved,
                            to_model=resolved_models[model_i + 1],
                            reason=type(err).__name__,
                        )
                        continue
                    raise
            raise RuntimeError("unreachable: complete_vision_text exhausted models without return")
        finally:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            obs.emit(
                obs.current_stage.get(),
                "llm_call",
                provider=provider,
                model=attempted_models[-1] if attempted_models else resolved_models[0],
                models_attempted=attempted_models,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usd_cost=self._cost_usd(
                    attempted_models[-1] if attempted_models else resolved_models[0],
                    prompt_tokens,
                    completion_tokens,
                    provider_cost_usd,
                    provider,
                ),
                duration_ms=duration_ms,
                finish_reason=finish_reason,
            )

    async def _chat_json(
        self,
        model: str,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int | None = None,
        timeout_s: float | None = None,
        provider: ProviderName | None = None,
    ) -> tuple[str, int, int, str, float | None]:
        provider = provider or self._provider
        client_o: Any = self._client_for_provider(provider)
        openrouter_kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system + "\n\nReturn JSON only, no prose."},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": temperature,
            "extra_body": _openrouter_extra_body(),
        }
        if max_tokens is not None:
            openrouter_kwargs["max_tokens"] = max_tokens
        if timeout_s is not None:
            openrouter_kwargs["timeout"] = timeout_s
        response_o = await client_o.chat.completions.create(**openrouter_kwargs)
        choice_o = response_o.choices[0]
        text_o = choice_o.message.content or ""
        if os.environ.get("OPENROUTER_STRIP_THINK") == "1":
            text_o = _strip_think(text_o)
        else:
            text_o = _strip_json_fence(text_o)
        usage_o = response_o.usage
        prompt_tokens_o, completion_tokens_o = _usage_tokens(usage_o)
        finish_reason_o = choice_o.finish_reason or ""
        _emit_truncation(
            finish_reason=finish_reason_o,
            max_tokens=max_tokens,
            model=model,
            prompt_tokens=prompt_tokens_o,
            completion_tokens=completion_tokens_o,
        )
        return (
            text_o,
            prompt_tokens_o,
            completion_tokens_o,
            finish_reason_o,
            _usage_cost_usd(usage_o),
        )

    async def _chat_text(
        self,
        model: str,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int | None = None,
        timeout_s: float | None = None,
        provider: ProviderName | None = None,
    ) -> tuple[str, int, int, str, float | None]:
        provider = provider or self._provider
        client_o: Any = self._client_for_provider(provider)
        openrouter_kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "extra_body": _openrouter_extra_body(),
        }
        if max_tokens is not None:
            openrouter_kwargs["max_tokens"] = max_tokens
        if timeout_s is not None:
            openrouter_kwargs["timeout"] = timeout_s
        response_o = await client_o.chat.completions.create(**openrouter_kwargs)
        choice_o = response_o.choices[0]
        text_o = choice_o.message.content or ""
        if os.environ.get("OPENROUTER_STRIP_THINK") == "1":
            text_o = _strip_think(text_o)
        usage_o = response_o.usage
        prompt_tokens_o, completion_tokens_o = _usage_tokens(usage_o)
        finish_reason_o = choice_o.finish_reason or ""
        _emit_truncation(
            finish_reason=finish_reason_o,
            max_tokens=max_tokens,
            model=model,
            prompt_tokens=prompt_tokens_o,
            completion_tokens=completion_tokens_o,
        )
        return (
            text_o,
            prompt_tokens_o,
            completion_tokens_o,
            finish_reason_o,
            _usage_cost_usd(usage_o),
        )

    async def _chat_vision_text(
        self,
        model: str,
        image_bytes: bytes,
        prompt: str,
        mime_type: str,
        timeout_s: float,
        max_tokens: int | None = None,
    ) -> tuple[str, int, int, str, float | None]:
        client_o: Any = self._client_for_provider("openrouter")
        image_url = f"data:{mime_type};base64," + base64.b64encode(image_bytes).decode("ascii")
        openrouter_kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            "temperature": 0.0,
            "extra_body": _openrouter_extra_body(),
            "timeout": timeout_s,
        }
        if max_tokens is not None:
            openrouter_kwargs["max_tokens"] = max_tokens
        response_o = await client_o.chat.completions.create(**openrouter_kwargs)
        choice_o = response_o.choices[0]
        text_o = choice_o.message.content or ""
        if os.environ.get("OPENROUTER_STRIP_THINK") == "1":
            text_o = _strip_think(text_o)
        usage_o = response_o.usage
        prompt_tokens_o, completion_tokens_o = _usage_tokens(usage_o)
        finish_reason_o = choice_o.finish_reason or ""
        _emit_truncation(
            finish_reason=finish_reason_o,
            max_tokens=max_tokens,
            model=model,
            prompt_tokens=prompt_tokens_o,
            completion_tokens=completion_tokens_o,
        )
        return (
            text_o,
            prompt_tokens_o,
            completion_tokens_o,
            finish_reason_o,
            _usage_cost_usd(usage_o),
        )


@functools.lru_cache(maxsize=1)
def get_client() -> LLMClient:
    """Process-wide shared client; tests isolate via get_client.cache_clear()."""
    return LLMClient()
