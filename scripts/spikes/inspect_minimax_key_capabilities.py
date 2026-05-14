"""Diagnostic: probe what THIS MINIMAX_API_KEY is actually authorized for.

Splits the 2061 mystery: is MiniMax-Text-01 fully plan-gated (any request type
returns 2061), or only vision-gated (text-only succeeds, image fails)?

Run: ``uv run python scripts/inspect_minimax_key_capabilities.py``
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx

HOST = "https://api.minimaxi.chat"


async def text_only_call(client: httpx.AsyncClient, model: str) -> tuple[int, str]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Say hi in 5 words."}],
        "temperature": 0.0,
        "max_tokens": 50,
    }
    r = await client.post(HOST + "/v1/text/chatcompletion_v2", json=payload, timeout=60.0)
    if r.status_code != 200:
        return r.status_code, r.text[:300]
    data = r.json()
    base = data.get("base_resp") or {}
    if base.get("status_code", 0) not in (0, 200):
        return -1, str(base)
    choices = data.get("choices") or []
    if not choices:
        return -2, str(data)[:300]
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        text = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    else:
        text = str(content)
    return 200, text


async def list_models(client: httpx.AsyncClient) -> tuple[int, str]:
    """Try /v1/models to enumerate what this key can hit."""
    r = await client.get(HOST + "/v1/models", timeout=30.0)
    return r.status_code, r.text[:2000]


async def main() -> int:
    if not os.environ.get("MINIMAX_API_KEY"):
        print("Set MINIMAX_API_KEY", file=sys.stderr)
        return 2

    headers = {
        "Authorization": f"Bearer {os.environ['MINIMAX_API_KEY']}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(headers=headers, timeout=60.0) as client:
        print("=" * 70)
        print("/v1/models discovery (text-only — what does this key see?)")
        print("=" * 70)
        status, body = await list_models(client)
        print(f"status={status}")
        print(body)
        print()

        for model in [
            "MiniMax-Text-01",
            "MiniMax-VL-01",
            "MiniMax-M2.7",
            "MiniMax-M2.5",
            "abab6.5s-chat",
        ]:
            print("=" * 70)
            print(f"TEXT-ONLY call: model={model}")
            print("=" * 70)
            try:
                status, text = await text_only_call(client, model)
                print(f"status={status} response={text[:200]!r}")
            except Exception as e:
                print(f"EXC: {type(e).__name__}: {e}")
            print()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
