"""Diagnostic v3: try the exact MiniMax docs canonical vision example.

Two corrections vs v2:
1. Use a public HTTPS URL for the image_url (the docs canonical example),
   not a base64 data URI. The docs say both work, but plan-gating /
   silent-drop may be specific to data URIs.
2. Try the Anthropic-compatible endpoint `/anthropic/v1/messages` alongside
   `chatcompletion_v2` — third-party reports say MiniMax vision works there
   when chatcompletion_v2 silently drops.

Run: ``uv run python scripts/inspect_minimax_vision_v3.py``
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
from pathlib import Path

import fitz
import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests/fixtures/cvs/07_senior_ds_holub.pdf"

# Canonical public image from MiniMax docs example.
DOCS_EXAMPLE_IMAGE_URL = (
    "https://cdn.hailuoai.com/prod/2024-09-18-16/user/multi_chat_file/"
    "9c0b5c14-ee88-4a5b-b503-4f626f018639.jpeg"
)

HOST = "https://api.minimaxi.chat"  # host the rest of gander uses
HOST_ALT = "https://api.minimax.io"  # canonical


def render_512px(pdf_path: Path, page_index: int = 0) -> bytes:
    """Render a page downsized to fit within 512px on the longest edge."""
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_index]
        rect = page.rect
        longest = max(rect.width, rect.height)
        zoom = 512.0 / longest
        matrix = fitz.Matrix(zoom, zoom)
        return page.get_pixmap(matrix=matrix).tobytes("png")
    finally:
        doc.close()


async def try_chatcompletion_v2(
    client: httpx.AsyncClient,
    host: str,
    model: str,
    content_block: dict,
    user_text: str,
) -> tuple[int, str]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    content_block,
                ],
            },
        ],
        "temperature": 0.0,
        "max_tokens": 2048,
    }
    r = await client.post(host + "/v1/text/chatcompletion_v2", json=payload, timeout=120.0)
    if r.status_code != 200:
        return r.status_code, r.text[:500]
    data = r.json()
    base = data.get("base_resp") or {}
    if base.get("status_code", 0) not in (0, 200):
        return -1, str(base)
    choices = data.get("choices") or []
    if not choices:
        return -2, str(data)[:500]
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        text = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    else:
        text = str(content)
    return 200, text


async def try_anthropic_messages(
    client: httpx.AsyncClient,
    host: str,
    model: str,
    png_bytes: bytes,
    user_text: str,
) -> tuple[int, str]:
    """Try the /anthropic/v1/messages endpoint with Anthropic image format."""
    b64 = base64.b64encode(png_bytes).decode("ascii")
    payload = {
        "model": model,
        "max_tokens": 2048,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": user_text},
                ],
            }
        ],
    }
    r = await client.post(host + "/anthropic/v1/messages", json=payload, timeout=120.0)
    if r.status_code != 200:
        return r.status_code, r.text[:500]
    data = r.json()
    content = data.get("content") or []
    parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return 200, "".join(parts) or str(data)[:300]


async def main() -> int:
    if not os.environ.get("MINIMAX_API_KEY"):
        print("Set MINIMAX_API_KEY", file=sys.stderr)
        return 2

    png_512 = render_512px(FIXTURE)
    b64_512 = base64.b64encode(png_512).decode("ascii")
    print(f"512px-resized fixture page: {len(png_512)} bytes PNG, {len(b64_512)} chars base64\n")

    headers = {
        "Authorization": f"Bearer {os.environ['MINIMAX_API_KEY']}",
        "Content-Type": "application/json",
    }

    public_block = {
        "type": "image_url",
        "image_url": {"url": DOCS_EXAMPLE_IMAGE_URL},
    }
    data_uri_block = {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{b64_512}"},
    }

    async with httpx.AsyncClient(headers=headers, timeout=120.0) as client:
        # Probe 1: chatcompletion_v2 with PUBLIC HTTPS URL (docs example image) on Text-01
        print("=" * 80)
        print("PROBE 1: chatcompletion_v2 + MiniMax-Text-01 + DOCS-EXAMPLE-PUBLIC-URL")
        print("=" * 80)
        status, text = await try_chatcompletion_v2(
            client, HOST, "MiniMax-Text-01", public_block,
            "What does this picture represent?",
        )
        print(f"status={status}")
        print(text[:1500])
        print()

        # Probe 2: chatcompletion_v2 + M2.5 + public URL
        print("=" * 80)
        print("PROBE 2: chatcompletion_v2 + MiniMax-M2.5 + DOCS-EXAMPLE-PUBLIC-URL")
        print("=" * 80)
        status, text = await try_chatcompletion_v2(
            client, HOST, "MiniMax-M2.5", public_block,
            "What does this picture represent?",
        )
        print(f"status={status}")
        print(text[:1500])
        print()

        # Probe 3: chatcompletion_v2 + M2.5 + 512px BASE64 of our fixture
        print("=" * 80)
        print("PROBE 3: chatcompletion_v2 + MiniMax-M2.5 + 512px-base64 of fixture CV")
        print("=" * 80)
        status, text = await try_chatcompletion_v2(
            client, HOST, "MiniMax-M2.5", data_uri_block,
            "Transcribe this CV page verbatim.",
        )
        print(f"status={status}")
        print(text[:1500])
        print()

        # Probe 4: /anthropic/v1/messages on Text-01 with 512px base64
        print("=" * 80)
        print("PROBE 4: /anthropic/v1/messages + MiniMax-Text-01 + 512px-base64")
        print("=" * 80)
        try:
            status, text = await try_anthropic_messages(
                client, HOST, "MiniMax-Text-01", png_512,
                "Transcribe this CV page verbatim.",
            )
        except Exception as e:
            status, text = -99, f"{type(e).__name__}: {e}"
        print(f"status={status}")
        print(text[:1500])
        print()

        # Probe 5: /anthropic/v1/messages on M2.5 with 512px base64
        print("=" * 80)
        print("PROBE 5: /anthropic/v1/messages + MiniMax-M2.5 + 512px-base64")
        print("=" * 80)
        try:
            status, text = await try_anthropic_messages(
                client, HOST, "MiniMax-M2.5", png_512,
                "Transcribe this CV page verbatim.",
            )
        except Exception as e:
            status, text = -99, f"{type(e).__name__}: {e}"
        print(f"status={status}")
        print(text[:1500])
        print()

        # Probe 6: try alt host for docs-example
        print("=" * 80)
        print("PROBE 6: chatcompletion_v2 + MiniMax-Text-01 + public URL on api.minimax.io")
        print("=" * 80)
        status, text = await try_chatcompletion_v2(
            client, HOST_ALT, "MiniMax-Text-01", public_block,
            "What does this picture represent?",
        )
        print(f"status={status}")
        print(text[:1500])
        print()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
