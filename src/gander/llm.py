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
ProviderName = Literal["openrouter", "local"]

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
# Slug pinning (P1.4 → re-pinned 2026-06-12): OpenRouter publishes no dated
# snapshot for the Gemini flash family (no `...-MM-YYYY` id), so the bare slug is
# the only id the API accepts. The 2.5 family was DELISTED from the live catalog
# (verified against https://openrouter.ai/api/v1/models): both 2.5 ids 404, so
# the prior routes had primary AND fallback failing together. Re-pinned to the
# current generation — `google/gemini-3.5-flash` (reasoning) / `-3.1-flash-lite`
# (cheap/extract/vision), each falling back to its sibling tier. We pin explicit
# generation ids (not the `~google/gemini-flash-latest` auto-track alias) to keep
# the eval baseline reproducible — a silently-rotating model would drift scores
# and cost under us. The `live`-marked test_configured_slugs_present_in_catalog
# guard fails CI if any configured primary stops resolving, so this can't rot
# silently again.
_OPENROUTER_SLOTS: tuple[LogicalModel, ...] = ("reasoning", "cheap", "extract", "vision")
_OPENROUTER_ROUTES: dict[LogicalModel, _OpenRouterRoute] = {
    "reasoning": _OpenRouterRoute(
        primary="google/gemini-3.5-flash",
        fallbacks=("google/gemini-3.1-flash-lite",),
    ),
    "cheap": _OpenRouterRoute(
        primary="google/gemini-3.1-flash-lite",
        fallbacks=("google/gemini-3.5-flash",),
    ),
    "extract": _OpenRouterRoute(
        primary="google/gemini-3.1-flash-lite",
        fallbacks=("google/gemini-3.5-flash",),
    ),
    "vision": _OpenRouterRoute(
        primary="google/gemini-3.1-flash-lite",
        fallbacks=("google/gemini-3.5-flash",),
    ),
}

# Opt-in local provider (Ollama / self-hosted, OpenAI-compatible). Default OFF —
# enabled per slot via GANDER_LLM_PROVIDER_<SLOT>=local. No `:free` hosted variants
# here: those are prohibited for CV content by the provider data-use policy. These
# are sensible Ollama model tags; the operator pulls them (or overrides per slot via
# OPENROUTER_MODEL_<SLOT>) on their own box. Vision never resolves here — it stays
# OpenRouter-only (local models often lack vision) — but the slot is kept for table
# totality.
_LOCAL_ROUTES: dict[LogicalModel, _OpenRouterRoute] = {
    "reasoning": _OpenRouterRoute(primary="qwen2.5", fallbacks=("llama3.1",)),
    "cheap": _OpenRouterRoute(primary="llama3.2", fallbacks=("qwen2.5",)),
    "extract": _OpenRouterRoute(primary="llama3.2", fallbacks=("qwen2.5",)),
    "vision": _OpenRouterRoute(primary="llama3.2-vision", fallbacks=()),
}

_ROUTES_BY_PROVIDER: dict[ProviderName, dict[LogicalModel, _OpenRouterRoute]] = {
    "openrouter": _OPENROUTER_ROUTES,
    "local": _LOCAL_ROUTES,
}

# USD per 1M tokens, (prompt, completion). OpenRouter normally reports usage.cost;
# this table is only the local fallback for _estimate_cost when usage.cost is absent.
# Figures are OpenRouter's published per-model prices, read 2026-06-13 from the model
# pages cited below (page-reported; a fallback estimate, not billing). Self-hosted
# `local` models are free, so they intentionally have no entry and estimate to ~0.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    # https://openrouter.ai/google/gemini-3.5-flash — $1.50 in / $9.00 out per 1M.
    "google/gemini-3.5-flash": (1.50, 9.00),
    # https://openrouter.ai/google/gemini-3.1-flash-lite — $0.25 in / $1.50 out per 1M.
    "google/gemini-3.1-flash-lite": (0.25, 1.50),
}
_DEFAULT_LLM_TIMEOUT_S = 60.0
_DEFAULT_VISION_TIMEOUT_S = 120.0

_MISSING_KEY_MESSAGE = (
    "OPENROUTER_API_KEY not set — add it to .env or export it "
    "(or set GANDER_LLM_PROVIDER=local to run text slots fully self-hosted)"
)

# Slots whose provider decides whether an OpenRouter key is required at boot.
# Vision is deliberately excluded: it is pinned to OpenRouter but degrades to
# the text-ingest fallback when the key is absent (GANDER_PDF_INGEST_MODE=text),
# so it must not force the boot gate on its own.
_TEXT_SLOTS: tuple[LogicalModel, ...] = ("reasoning", "cheap", "extract")


def _slot_provider(logical: LogicalModel) -> str:
    """Provider a slot resolves to from env, mirroring `_resolve_provider`.

    Module-level (no `LLMClient` instance) so the boot gate can ask the
    question before any client is built: per-slot `GANDER_LLM_PROVIDER_<SLOT>`
    wins, else the global `GANDER_LLM_PROVIDER` (default `openrouter`).
    """
    raw = os.environ.get(f"GANDER_LLM_PROVIDER_{logical.upper()}")
    if raw is None:
        raw = os.environ.get("GANDER_LLM_PROVIDER", "openrouter")
    return raw.strip().lower()


def _openrouter_required() -> bool:
    """True when any text slot still routes to OpenRouter.

    A value other than `local` (including a typo) is treated as needing the
    key — conservative, and the actual provider validation surfaces when
    `LLMClient` is built. When every text slot is opted into `local`, Gander
    runs fully self-hosted and needs no OpenRouter key.
    """
    return any(_slot_provider(slot) != "local" for slot in _TEXT_SLOTS)


def check_env() -> None:
    """Fail fast at boot if required runtime env is missing.

    Called once at app startup (app.py) so the process dies with a clear
    message instead of a confusing auth error on the first real LLM call.
    `LLMClient` construction itself stays cheap and does not raise, so tests
    that stub LLM methods need no fake key.

    The OpenRouter key is required only when at least one text slot routes to
    OpenRouter; an all-`local` text config boots keyless (vision still needs
    the key or `GANDER_PDF_INGEST_MODE=text` for PDFs — see `_TEXT_SLOTS`).
    """
    if _openrouter_required() and not os.environ.get("OPENROUTER_API_KEY"):
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
    """Async chat client over an OpenAI-compatible provider.

    Provider selected via GANDER_LLM_PROVIDER env (`openrouter`, the default, or
    `local`). A logical model may override per slot via
    GANDER_LLM_PROVIDER_<LOGICAL_MODEL>; an unknown value fails at startup/call
    time. `local` targets a self-hosted OpenAI-compatible endpoint
    (GANDER_LOCAL_BASE_URL, default Ollama) and is OFF unless explicitly opted in;
    vision always uses OpenRouter regardless of the slot override. Every call
    emits an `llm_call` telemetry event (success or failure).
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
        if provider in ("openrouter", "local"):
            return provider  # type: ignore[return-value]
        raise RuntimeError(f"Unknown {env_name}={raw!r}; expected 'openrouter' or 'local'")

    def _build_client(self, provider: ProviderName) -> AsyncOpenAI:
        # Construction stays cheap and never raises on a missing key — boot-time
        # check_env() is the early-fail gate (app.py). The OpenAI SDK rejects an
        # empty api_key at construction, so fall back to a placeholder when the
        # key is absent; a real missing-key run surfaces as a 401 on the first
        # call, which stage_boundary converts to a user-facing StageFailure.
        if provider == "local":
            # Opt-in self-hosted OpenAI-compatible endpoint (Ollama default port).
            # Ollama ignores the api_key but the SDK requires a non-empty one.
            return AsyncOpenAI(
                api_key=os.environ.get("GANDER_LOCAL_API_KEY") or "local",
                base_url=os.environ.get("GANDER_LOCAL_BASE_URL", "http://localhost:11434/v1"),
            )
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

    def _resolve_model(self, logical: LogicalModel, provider: ProviderName) -> str:
        # The OPENROUTER_MODEL_<SLOT> override is the single per-slot model knob
        # for both providers; the default falls to the provider's route table.
        env_key = f"OPENROUTER_MODEL_{logical.upper()}"
        return os.environ.get(env_key, _ROUTES_BY_PROVIDER[provider][logical].primary)

    def _resolve_models(
        self, logical: LogicalModel, provider: ProviderName | None = None
    ) -> tuple[str, ...]:
        provider = provider or self._resolve_provider(logical)
        primary = self._resolve_model(logical, provider)
        env_key = f"OPENROUTER_MODEL_{logical.upper()}_FALLBACK"
        fallback_raw = os.environ.get(env_key)
        if fallback_raw is None:
            fallbacks = _ROUTES_BY_PROVIDER[provider][logical].fallbacks
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
        """Transcribe one rendered page through OpenRouter vision.

        Vision is pinned to OpenRouter: local models often lack a vision head, so a
        `GANDER_LLM_PROVIDER_VISION=local` override intentionally degrades back to
        OpenRouter rather than failing. The _resolve_provider call still validates
        the env value (an unknown provider raises) before we discard it.
        """
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
        # `reasoning` is an OpenRouter routing directive; it means nothing to a
        # local server, so only send extra_body on the openrouter path.
        extra_body = _openrouter_extra_body() if provider == "openrouter" else {}
        openrouter_kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system + "\n\nReturn JSON only, no prose."},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": temperature,
            "extra_body": extra_body,
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
        # See _chat_json: extra_body carries an OpenRouter-only routing directive.
        extra_body = _openrouter_extra_body() if provider == "openrouter" else {}
        openrouter_kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "extra_body": extra_body,
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
    """Process-wide shared client; tests isolate via get_client.cache_clear().

    Boot-checks the environment on first construction (`check_env`) so a caller
    that bypasses app.py's startup gate fails with an actionable message instead
    of an opaque 401 from sending the `missing-openrouter-key` sentinel. Direct
    `LLMClient()` construction stays key-free for tests that stub the LLM methods.
    """
    check_env()
    return LLMClient()
