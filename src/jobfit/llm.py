from __future__ import annotations

import json
import os
import re
import time
from typing import TYPE_CHECKING, Any, Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from jobfit import obs

if TYPE_CHECKING:
    # Optional fallback dep — not installed by default.
    from anthropic import AsyncAnthropic  # type: ignore[import-not-found]

LogicalModel = Literal["reasoning", "cheap"]

# MiniMax-M2.x models prepend a <think>...</think> reasoning block to chat output
# regardless of response_format, and often wrap JSON-mode payloads in ```json fences.
# Strip both before JSON-parsing or returning text.
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


def _strip_think(text: str) -> str:
    text = _THINK_BLOCK_RE.sub("", text, count=1).strip()
    m = _JSON_FENCE_RE.match(text)
    return m.group(1).strip() if m else text


# USD per 1M tokens, (prompt, completion).
# TODO(T05): re-verify model identifiers and re-cost from MiniMax pricing console;
# zeroed because public docs no longer expose per-model pricing without auth.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "MiniMax-M2.7-highspeed": (0.0, 0.0),
}

_PROFILE_MODELS: dict[str, dict[str, str]] = {
    "local": {"reasoning": "MiniMax-M2.7-highspeed", "cheap": "MiniMax-M2.7-highspeed"},
    "ci": {"reasoning": "MiniMax-M2.7-highspeed", "cheap": "MiniMax-M2.7-highspeed"},
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
                raise RuntimeError("MINIMAX_API_KEY not set — add it to .env or export it")
            self._client = AsyncOpenAI(api_key=api_key, base_url="https://api.minimaxi.chat/v1")
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
                raise RuntimeError("ANTHROPIC_API_KEY not set — add it to .env or export it")
            self._client = anthropic.AsyncAnthropic(api_key=api_key)
        else:
            raise RuntimeError(
                f"Unknown JOBFIT_LLM_PROVIDER={self._provider!r}; expected 'minimax' or 'anthropic'"
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

    def _estimate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
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
        finish_reason = ""
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
                text, attempt_prompt, attempt_completion, finish_reason = await self._chat_json(
                    resolved,
                    system,
                    current_user,
                    temperature,
                )
                prompt_tokens += attempt_prompt
                completion_tokens += attempt_completion
                try:
                    parsed = json.loads(text)
                    return schema.model_validate(parsed)
                except (ValidationError, json.JSONDecodeError) as err:
                    last_err = err
                    if attempt >= max_retries:
                        raise
            raise RuntimeError("unreachable: complete_json loop exited without return")
        finally:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            obs.emit(
                obs.current_stage.get(),
                "llm_call",
                model=resolved,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usd_cost=self._estimate_cost(resolved, prompt_tokens, completion_tokens),
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
    ) -> str:
        resolved = self._resolve_model(model)
        t0 = time.perf_counter()
        prompt_tokens = 0
        completion_tokens = 0
        usd_cost = 0.0
        finish_reason = ""
        try:
            text, prompt_tokens, completion_tokens, finish_reason = await self._chat_text(
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
                finish_reason=finish_reason,
            )

    async def _chat_json(
        self, model: str, system: str, user: str, temperature: float
    ) -> tuple[str, int, int, str]:
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
                max_tokens=4096,
                extra_body={"reasoning_split": True},
            )
            choice = response.choices[0]
            text = choice.message.content or ""
            usage = response.usage
            return (
                _strip_think(text),
                usage.prompt_tokens,
                usage.completion_tokens,
                choice.finish_reason or "",
            )
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
        return text, usage_a.input_tokens, usage_a.output_tokens, response_a.stop_reason or ""

    async def _chat_text(
        self, model: str, system: str, user: str, temperature: float
    ) -> tuple[str, int, int, str]:
        if self._provider == "minimax":
            client: Any = self._client
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                extra_body={"reasoning_split": True},
            )
            choice = response.choices[0]
            text = choice.message.content or ""
            usage = response.usage
            return (
                _strip_think(text),
                usage.prompt_tokens,
                usage.completion_tokens,
                choice.finish_reason or "",
            )
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
        return text, usage_a.input_tokens, usage_a.output_tokens, response_a.stop_reason or ""
