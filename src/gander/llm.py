from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Any, Literal

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from gander import obs

LogicalModel = Literal["reasoning", "cheap", "extract"]

# MiniMax-M2.x models prepend a <think>...</think> reasoning block to chat output
# regardless of response_format, and often wrap JSON-mode payloads in ```json fences.
# Strip both before JSON-parsing or returning text.
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


# USD per 1M tokens, (prompt, completion).
# TODO(T05): re-verify model identifiers and re-cost from MiniMax pricing console;
# zeroed because public docs no longer expose per-model pricing without auth.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "MiniMax-M2.7-highspeed": (0.0, 0.0),
}

_PROFILE_MODELS: dict[str, dict[str, str]] = {
    "local": {
        "reasoning": "MiniMax-M2.7-highspeed",
        "cheap": "MiniMax-M2.7-highspeed",
        "extract": "MiniMax-M2.7-highspeed",
    },
    "ci": {
        "reasoning": "MiniMax-M2.7-highspeed",
        "cheap": "MiniMax-M2.7-highspeed",
        "extract": "MiniMax-M2.7-highspeed",
    },
}

_OPENROUTER_MODELS: dict[LogicalModel, str] = {
    # Re-verify on OpenRouter catalog change; slugs drift faster than SDK APIs.
    "reasoning": "google/gemini-2.5-flash",
    "cheap": "google/gemini-2.5-flash",
    "extract": "anthropic/claude-haiku-4.5",
}
_API_VLM_MODEL = "api-vlm"
_API_VLM_ENDPOINT = "https://api.minimax.io/v1/coding_plan/vlm"
_API_VLM_USD_PER_REQUEST = 0.06
_API_VLM_TOKEN_PLAN_M2_REQUESTS = 3


class LLMClient:
    """Async chat client over MiniMax (default) or OpenRouter.

    Provider selected via GANDER_LLM_PROVIDER env (`minimax` | `openrouter`).
    Model resolution for MiniMax via GANDER_MODEL_PROFILE env (`local` | `ci`).
    Every call emits an `llm_call` telemetry event (success or failure).
    """

    def __init__(self) -> None:
        self._provider = os.environ.get("GANDER_LLM_PROVIDER", "minimax")
        self._client: AsyncOpenAI
        if self._provider == "minimax":
            api_key = os.environ.get("MINIMAX_API_KEY")
            if not api_key:
                raise RuntimeError("MINIMAX_API_KEY not set — add it to .env or export it")
            self._client = AsyncOpenAI(api_key=api_key, base_url="https://api.minimaxi.chat/v1")
        elif self._provider == "openrouter":
            api_key = os.environ.get("OPENROUTER_API_KEY")
            if not api_key:
                raise RuntimeError("OPENROUTER_API_KEY not set — add it to .env or export it")
            self._client = AsyncOpenAI(
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
        else:
            raise RuntimeError(
                f"Unknown GANDER_LLM_PROVIDER={self._provider!r}; "
                "expected 'minimax' or 'openrouter'"
            )

    def _resolve_model(self, logical: LogicalModel) -> str:
        if self._provider == "openrouter":
            env_key = f"OPENROUTER_MODEL_{logical.upper()}"
            return os.environ.get(env_key, _OPENROUTER_MODELS[logical])
        profile = os.environ.get("GANDER_MODEL_PROFILE", "local")
        if profile not in _PROFILE_MODELS:
            raise RuntimeError(
                f"Unknown GANDER_MODEL_PROFILE={profile!r}; "
                f"expected one of {sorted(_PROFILE_MODELS)}"
            )
        return _PROFILE_MODELS[profile][logical]

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
    ) -> float:
        if self._provider == "openrouter" and provider_cost_usd is not None:
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
    ) -> BaseModel:
        resolved = self._resolve_model(model)
        t0 = time.perf_counter()
        prompt_tokens = 0
        completion_tokens = 0
        provider_cost_usd: float | None = None
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
                (
                    text,
                    attempt_prompt,
                    attempt_completion,
                    finish_reason,
                    attempt_cost_usd,
                ) = await self._chat_json(resolved, system, current_user, temperature)
                prompt_tokens += attempt_prompt
                completion_tokens += attempt_completion
                if attempt_cost_usd is not None:
                    provider_cost_usd = (provider_cost_usd or 0.0) + attempt_cost_usd
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
                provider=self._provider,
                model=resolved,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usd_cost=self._cost_usd(
                    resolved, prompt_tokens, completion_tokens, provider_cost_usd
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
    ) -> str:
        resolved = self._resolve_model(model)
        t0 = time.perf_counter()
        prompt_tokens = 0
        completion_tokens = 0
        provider_cost_usd: float | None = None
        finish_reason = ""
        try:
            (
                text,
                prompt_tokens,
                completion_tokens,
                finish_reason,
                provider_cost_usd,
            ) = await self._chat_text(resolved, system, user, temperature)
            return text
        finally:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            obs.emit(
                obs.current_stage.get(),
                "llm_call",
                provider=self._provider,
                model=resolved,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usd_cost=self._cost_usd(
                    resolved, prompt_tokens, completion_tokens, provider_cost_usd
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
        timeout_s: float = 120.0,
    ) -> str:
        """Transcribe one rendered page through MiniMax Token Plan API-vlm.

        Chat/text provider selection does not apply here: no OpenRouter vision
        route is wired for the Token Plan ingest tier yet.
        """
        api_key = os.environ.get("MINIMAX_API_KEY")
        if not api_key:
            raise RuntimeError("MINIMAX_API_KEY not set — add it to .env or export it")

        endpoint = os.environ.get("GANDER_VLM_ENDPOINT", _API_VLM_ENDPOINT)
        image_url = f"data:{mime_type};base64," + base64.b64encode(image_bytes).decode("ascii")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "MM-API-Source": "Gander-Ingest",
        }
        payload = {"prompt": prompt, "image_url": image_url}
        t0 = time.perf_counter()
        sent = False
        finish_reason = ""
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                sent = True
                response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            base_resp = data.get("base_resp")
            if isinstance(base_resp, dict):
                status_code = base_resp.get("status_code")
                if status_code not in (None, 0, 200):
                    status_msg = str(base_resp.get("status_msg", "unknown MiniMax error"))
                    raise RuntimeError(f"MiniMax API-vlm error {status_code}: {status_msg}")
            content = data.get("content", "")
            text = content.strip() if isinstance(content, str) else str(content).strip()
            if not text:
                raise RuntimeError("MiniMax API-vlm returned empty content")
            finish_reason = "success"
            return text
        finally:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            obs.emit(
                obs.current_stage.get(),
                "llm_call",
                provider="minimax",
                model=_API_VLM_MODEL,
                prompt_tokens=0,
                completion_tokens=0,
                usd_cost=_API_VLM_USD_PER_REQUEST if sent else 0.0,
                duration_ms=duration_ms,
                finish_reason=finish_reason,
                token_plan_m2_requests=_API_VLM_TOKEN_PLAN_M2_REQUESTS if sent else 0,
            )

    async def _chat_json(
        self, model: str, system: str, user: str, temperature: float
    ) -> tuple[str, int, int, str, float | None]:
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
            prompt_tokens, completion_tokens = _usage_tokens(usage)
            return (
                _strip_think(text),
                prompt_tokens,
                completion_tokens,
                choice.finish_reason or "",
                None,
            )
        client_o: Any = self._client
        response_o = await client_o.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system + "\n\nReturn JSON only, no prose."},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
            extra_body=_openrouter_extra_body(),
        )
        choice_o = response_o.choices[0]
        text_o = choice_o.message.content or ""
        if os.environ.get("OPENROUTER_STRIP_THINK") == "1":
            text_o = _strip_think(text_o)
        else:
            text_o = _strip_json_fence(text_o)
        usage_o = response_o.usage
        prompt_tokens_o, completion_tokens_o = _usage_tokens(usage_o)
        return (
            text_o,
            prompt_tokens_o,
            completion_tokens_o,
            choice_o.finish_reason or "",
            _usage_cost_usd(usage_o),
        )

    async def _chat_text(
        self, model: str, system: str, user: str, temperature: float
    ) -> tuple[str, int, int, str, float | None]:
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
            prompt_tokens, completion_tokens = _usage_tokens(usage)
            return (
                _strip_think(text),
                prompt_tokens,
                completion_tokens,
                choice.finish_reason or "",
                None,
            )
        client_o: Any = self._client
        response_o = await client_o.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            extra_body=_openrouter_extra_body(),
        )
        choice_o = response_o.choices[0]
        text_o = choice_o.message.content or ""
        if os.environ.get("OPENROUTER_STRIP_THINK") == "1":
            text_o = _strip_think(text_o)
        usage_o = response_o.usage
        prompt_tokens_o, completion_tokens_o = _usage_tokens(usage_o)
        return (
            text_o,
            prompt_tokens_o,
            completion_tokens_o,
            choice_o.finish_reason or "",
            _usage_cost_usd(usage_o),
        )
