"""Diagnostic: dump full transcripts from each MiniMax M2.x model on one page.

The v2 spike confirms M2.5 consumes images but fails every quality gate. This
script probes M2.7, M2.7-highspeed, M2.5, M2.5-highspeed against page 1 of
07_senior_ds_holub.pdf (single-column EN, known-correct text-tier baseline) so
we can eyeball whether *any* M2.x model produces a verbatim transcript or
whether they all produce summaries/paraphrases.

Run: ``uv run python scripts/inspect_minimax_vision_transcripts.py``
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

HOST = "https://api.minimaxi.chat"
ENDPOINT = "/v1/text/chatcompletion_v2"

MODELS = [
    "abab6.5-vision",
    "abab6.5s-vision",
    "abab7-chat-vision",
    "MiniMax-VL-01",
    "MiniMax-VL",
    "minimax-vl-01",
    "MiniMax-Vision-01",
    "MM-Vision-01",
]

SYSTEM_PROMPT = (
    "You are a verbatim OCR. Output the text of the image exactly as printed, "
    "character-for-character. Do not summarize, paraphrase, translate, or add "
    "any commentary. Output only the transcribed text."
)
USER_PROMPT = "Transcribe this page verbatim."


def render_page(pdf_path: Path, page_index: int = 0, dpi: int = 200) -> bytes:
    doc = fitz.open(pdf_path)
    try:
        return doc[page_index].get_pixmap(dpi=dpi).tobytes("png")
    finally:
        doc.close()


async def call(client: httpx.AsyncClient, model: str, png: bytes) -> tuple[int, str]:
    b64 = base64.b64encode(png).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": USER_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            },
        ],
        "temperature": 0.0,
        "max_tokens": 4096,
    }
    r = await client.post(HOST + ENDPOINT, json=payload, timeout=120.0)
    if r.status_code != 200:
        return r.status_code, r.text[:400]
    data = r.json()
    base = data.get("base_resp") or {}
    if base.get("status_code", 0) not in (0, 200):
        return -1, str(base)
    choices = data.get("choices") or []
    if not choices:
        return -2, str(data)[:400]
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        text = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    else:
        text = str(content)
    return 200, text


async def main() -> int:
    if not os.environ.get("MINIMAX_API_KEY"):
        print("Set MINIMAX_API_KEY", file=sys.stderr)
        return 2
    png = render_page(FIXTURE, page_index=0)
    headers = {
        "Authorization": f"Bearer {os.environ['MINIMAX_API_KEY']}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(headers=headers, timeout=120.0) as client:
        for model in MODELS:
            print("=" * 80)
            print(f"MODEL: {model}")
            print("=" * 80)
            try:
                status, text = await call(client, model, png)
            except Exception as e:
                print(f"  EXC: {type(e).__name__}: {e}")
                continue
            if status != 200:
                print(f"  status={status} body={text[:300]}")
                continue
            print(text[:2000])
            print()
            print(f"  [len={len(text)} chars]")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
