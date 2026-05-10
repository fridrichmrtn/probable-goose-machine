from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING, Any, Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from jobfit import obs

if TYPE_CHECKING:
    # Optional fallback dep — not installed by default.
    from anthropic import AsyncAnthropic  # type: ignore[import-not-found]

LogicalModel = Literal["reasoning", "cheap"]

# Pricing as of 2026-05-10 — re-check minimaxi.chat/pricing if cost reports drift.
# USD per 1M tokens, (prompt, completion).
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "MiniMax-M1": (1.10, 4.40),
    "abab6.5s-chat": (0.20, 0.20),
}

_PROFILE_MODELS: dict[str, dict[str, str]] = {
    "local": {"reasoning": "MiniMax-M1", "cheap": "abab6.5s-chat"},
    "ci": {"reasoning": "abab6.5s-chat", "cheap": "abab6.5s-chat"},
}

_ANTHROPIC_MODEL = "claude-sonnet-4-6"


class LLMClient:
    """Async chat client over MiniMax (default) or Anthropic (fallback).

    Provider selected via JOBFIT_LLM_PROVIDER env (`minimax` | `anthropic`).
    Model resolution for MiniMax via JOBFIT_MODEL_PROFILE env (`local` | `ci`).
    Every call emits an `llm_call` telemetry event (success or failure).
    """

    def __init__(self) -> None:
        self._provider = os.environ.get("JOBFIT_LLM_PROVIDER", "minimax")
        self._client: AsyncOpenAI | AsyncAnthropic
        if self._provider == "minimax":
            api_key = os.environ.get("MINIMAX_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "MINIMAX_API_KEY not set — add it to .env or export it"
                )
            self._client = AsyncOpenAI(
                api_key=api_key, base_url="https://api.minimaxi.chat/v1"
            )
        elif self._provider == "anthropic":
            try:
                import anthropic
            except ImportError as e:
                raise RuntimeError(
                    "JOBFIT_LLM_PROVIDER=anthropic but `anthropic` package not "
                    "installed — `uv add anthropic`"
                ) from e
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY not set — add it to .env or export it"
                )
            self._client = anthropic.AsyncAnthropic(api_key=api_key)
        else:
            raise RuntimeError(
                f"Unknown JOBFIT_LLM_PROVIDER={self._provider!r}; "
                "expected 'minimax' or 'anthropic'"
            )

    def _resolve_model(self, logical: LogicalModel) -> str:
        if self._provider == "anthropic":
            return _ANTHROPIC_MODEL
        profile = os.environ.get("JOBFIT_MODEL_PROFILE", "local")
        if profile not in _PROFILE_MODELS:
            raise RuntimeError(
                f"Unknown JOBFIT_MODEL_PROFILE={profile!r}; "
                f"expected one of {sorted(_PROFILE_MODELS)}"
            )
        return _PROFILE_MODELS[profile][logical]

    def _estimate_cost(
        self, model: str, prompt_tokens: int, completion_tokens: int
    ) -> float:
        # Cost only modeled for MiniMax; Anthropic fallback returns 0.0 for now.
        price = MODEL_PRICES.get(model)
        if price is None:
            return 0.0
        return (prompt_tokens / 1e6) * price[0] + (completion_tokens / 1e6) * price[1]

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        model: LogicalModel = "reasoning",
        temperature: float = 0.0,
        max_retries: int = 1,
    ) -> BaseModel:
        resolved = self._resolve_model(model)
        t0 = time.perf_counter()
        prompt_tokens = 0
        completion_tokens = 0
        usd_cost = 0.0
        try:
            current_user = user
            last_err: ValidationError | json.JSONDecodeError | None = None
            for attempt in range(max_retries + 1):
                if attempt > 0 and last_err is not None:
                    current_user = (
                        user
                        + f"\n\nYour previous output failed validation: {last_err}"
                        + "\n\nReturn corrected JSON only."
                    )
                text, prompt_tokens, completion_tokens = await self._chat_json(
                    resolved, system, current_user, temperature
                )
                try:
                    parsed = json.loads(text)
                    return schema.model_validate(parsed)
                except (ValidationError, json.JSONDecodeError) as err:
                    last_err = err
                    if attempt >= max_retries:
                        raise
            raise RuntimeError("unreachable: complete_json loop exited without return")
        finally:
            usd_cost = self._estimate_cost(resolved, prompt_tokens, completion_tokens)
            duration_ms = int((time.perf_counter() - t0) * 1000)
            obs.emit(
                obs.current_stage.get(),
                "llm_call",
                model=resolved,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usd_cost=usd_cost,
                duration_ms=duration_ms,
            )

    async def complete_text(
        self,
        *,
        system: str,
        user: str,
        model: LogicalModel = "cheap",
        temperature: float = 0.0,
    ) -> str:
        resolved = self._resolve_model(model)
        t0 = time.perf_counter()
        prompt_tokens = 0
        completion_tokens = 0
        usd_cost = 0.0
        try:
            text, prompt_tokens, completion_tokens = await self._chat_text(
                resolved, system, user, temperature
            )
            return text
        finally:
            usd_cost = self._estimate_cost(resolved, prompt_tokens, completion_tokens)
            duration_ms = int((time.perf_counter() - t0) * 1000)
            obs.emit(
                obs.current_stage.get(),
                "llm_call",
                model=resolved,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usd_cost=usd_cost,
                duration_ms=duration_ms,
            )

    async def _chat_json(
        self, model: str, system: str, user: str, temperature: float
    ) -> tuple[str, int, int]:
        if self._provider == "minimax":
            client: Any = self._client
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=temperature,
            )
            text = response.choices[0].message.content or ""
            usage = response.usage
            return text, usage.prompt_tokens, usage.completion_tokens
        client_a: Any = self._client
        response_a = await client_a.messages.create(
            model=model,
            system=system + "\n\nReturn JSON only, no prose.",
            messages=[{"role": "user", "content": user}],
            max_tokens=2048,
            temperature=temperature,
        )
        text = response_a.content[0].text
        usage_a = response_a.usage
        return text, usage_a.input_tokens, usage_a.output_tokens

    async def _chat_text(
        self, model: str, system: str, user: str, temperature: float
    ) -> tuple[str, int, int]:
        if self._provider == "minimax":
            client: Any = self._client
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
            )
            text = response.choices[0].message.content or ""
            usage = response.usage
            return text, usage.prompt_tokens, usage.completion_tokens
        client_a: Any = self._client
        response_a = await client_a.messages.create(
            model=model,
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=2048,
            temperature=temperature,
        )
        text = response_a.content[0].text
        usage_a = response_a.usage
        return text, usage_a.input_tokens, usage_a.output_tokens
