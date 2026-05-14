"""MiniMax vision capability re-spike for T32 (corrected endpoint).

Forked from `scripts/spike_minimax_vision.py`. T32's first spike hit
`/v1/chat/completions` (MiniMax's OpenAI-compat shim) which silently drops
`image_url` content blocks. This re-spike targets the native MiniMax endpoint
`/v1/text/chatcompletion_v2` which carries vision per MiniMax's official docs
(platform.minimax.io/docs/api-reference/text-post).

Transport: raw `httpx.AsyncClient` (not `AsyncOpenAI`) because the OpenAI SDK
client only knows `/chat/completions`.

Probes performed up front (one-shot, logged to dev-report):
1. Host probe: try `https://api.minimaxi.chat` (host gander.llm uses) first
   against `chatcompletion_v2`; on connection error or 404, fall back to
   canonical `https://api.minimax.io`.
2. Model probe: against the chosen host, try `MiniMax-VL-01` (canonical),
   then `MiniMax-Text-01` (per docs example), then any newer `*-VL*` model
   discovered via `/v1/models`. Lock the first model that returns a non-empty
   transcription of a small probe image.

After probes lock (host, model): run 3 fixtures × 3 runs at T=0, evaluate the
7 hard gates, write dev-report.

Run: ``uv run python scripts/spike_minimax_vision_v2.py [--report PATH]``

Exit codes:
  0 — all 7 gates passed on all 3 PDFs (ADOPT MiniMax vision).
  1 — at least one gate failed (preceded by ``FAILED GATE: <name> on <pdf>``).
  2 — preflight env-var / fixture check failed.
  3 — host or model probe failed (vision not reachable on either host).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import statistics
import sys
import time
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz  # pymupdf
import httpx

from gander import obs
from gander.verify import verify_quote

REPO_ROOT = Path(__file__).resolve().parents[1]
ANCHORS_PATH = REPO_ROOT / "tests/fixtures/vision_anchors.json"

DPI = 200
NUM_RUNS = 3
TEMPERATURE = 0.0
MAX_TOKENS = 4096

# Endpoint + host candidates. Probe order: api.minimaxi.chat first (same host
# gander.llm authenticates against today), then canonical api.minimax.io.
ENDPOINT_PATH = "/v1/text/chatcompletion_v2"
HOST_CANDIDATES = [
    "https://api.minimaxi.chat",
    "https://api.minimax.io",
]

# Model probe order. Probes the M2.x catalog first (confirmed in this account's
# token plan per /v1/models discovery in T32), then named vision variants from
# MiniMax docs. The first model that returns a transcription containing any of
# IMAGE_PROBE_MARKERS — proving the image was actually consumed, not silently
# dropped — wins and is used for the full eval.
MODEL_PROBE_ORDER = [
    # In-plan text catalog (per T32 /v1/models): may carry vision on the native
    # chatcompletion_v2 endpoint even when the OpenAI-compat shim drops images.
    "MiniMax-M2.7",
    "MiniMax-M2.7-highspeed",
    "MiniMax-M2.5",
    "MiniMax-M2.5-highspeed",
    "MiniMax-M2.1",
    "MiniMax-M2",
    # Named vision variants from MiniMax docs (in case plan was upgraded).
    "MiniMax-VL-01",
    "abab6.5-vision",
    "abab7-chat-vision",
]

# Tokens that must appear in a probe response to prove the model consumed the
# image (probe image = page 1 of 03_ds_horak.pdf). Any one of these is enough.
# All are distinctive content from that page that cannot have leaked via the
# prompt body (which only says "Transcribe this CV page verbatim per the
# rules above.").
IMAGE_PROBE_MARKERS = [
    "Horák",
    "Horak",
    "Data Scientist",
    "Mall.cz",
    "Zboží",
    "Zbozi",
    "ČVUT",
    "Email.cz",
]

# Pricing — confirmed against MiniMax billing page post-run. Placeholders
# below; reported $/MTok is grounded against the spike's printed token counts.
VISION_PRICE_PROMPT_PER_1M = float(os.environ.get("GANDER_VISION_PRICE_PROMPT", "1.50"))
VISION_PRICE_COMPLETION_PER_1M = float(os.environ.get("GANDER_VISION_PRICE_COMPLETION", "6.00"))

# Gate thresholds (unchanged from v1 spike + plan).
GATE_ANCHOR_FLOOR = 9
GATE_JACCARD_FLOOR = 0.60
GATE_COST_CEILING_PER_PAGE = 0.05
GATE_LATENCY_P95_CEILING_S = 15.0

VISION_PROMPT_VERSION = "v0-spike"
VISION_SYSTEM_PROMPT = """You are a verbatim transcriber. Output the text of the CV page exactly as it appears. Do NOT paraphrase, summarize, translate, or correct. Preserve original language (Czech and English text both untouched). Output the transcript only — no commentary, no fences, no apologies.

Rules:

1. Character preservation: preserve every character as-is — diacritics, capitalization, punctuation (incl. en-dash `–` vs hyphen `-`, smart vs straight quotes, ampersand `&`, slash `/`), internal whitespace within a line, abbreviations (do not expand `sr.` → `senior`, `&` → `and`), and any visible typos. Do not normalize Unicode (no NFC↔NFD changes).
2. Language lock: if text is in Czech, output Czech. If text is in English, output English. Never translate, transliterate, or mix languages within a token. Czech month genitives (`října`, `ledna`, `prosince`) must survive verbatim.
3. Column order: this page may have a narrow dark-background column on the left and a wide light-background column on the right. Transcribe the entire dark-background column first, top to bottom, then the entire light-background column, top to bottom. Insert exactly one blank line between the two columns. If the page is single-column, transcribe top to bottom.
4. Section headings → emit as `## <heading text>` on their own line.
5. Bulleted lists → use `- ` markers, one item per line.
6. Date ranges → reproduce verbatim, including Czech month names (`října 2015 – Present`).
7. URLs, emails, phone numbers → reproduce verbatim.
8. Decorative suppression — bounded: skip only page numbers, "Page X of Y" artifacts, and decorative horizontal rules. Never skip a line that contains letters forming a word in the section vocabulary. When in doubt, include.
9. Unreadable regions: if a region is obscured, faded, or genuinely illegible, output the literal token `[UNREADABLE]` in that position. Do not guess.

Few-shot examples (✗ = wrong, ✓ = correct):

Page text: `Pracovní zkušenosti`
✗ `Work Experience`
✓ `## Pracovní zkušenosti`

Page text: `Built churn model with SHAP`
✗ `Built a churn model using SHAP values`
✓ `Built churn model with SHAP`

Page text: `Machine Learning Scientist w/ Python`
✗ `Machine Learning Scientist with Python`
✓ `Machine Learning Scientist w/ Python`

Page text: `March 2021 – present`
✗ `March 2021 - present`
✓ `March 2021 – present`

Page text: `recieved Rector's Award` (typo)
✗ `received Rector's Award`
✓ `recieved Rector's Award`
"""

VISION_USER_PROMPT = "Transcribe this CV page verbatim per the rules above."


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class PageCall:
    page_index: int
    transcript: str
    duration_s: float
    prompt_tokens: int
    completion_tokens: int
    usd_cost: float
    error: str | None = None


@dataclass
class RunResult:
    run_index: int
    pages: list[PageCall] = field(default_factory=list)

    @property
    def transcript(self) -> str:
        return "\n\n[PAGE_BREAK]\n\n".join(p.transcript for p in self.pages)

    @property
    def total_usd(self) -> float:
        return sum(p.usd_cost for p in self.pages)

    @property
    def page_count(self) -> int:
        return len(self.pages)


@dataclass
class FixtureResult:
    name: str
    pdf_path: Path
    runs: list[RunResult] = field(default_factory=list)
    text_tier_transcript: str = ""
    gate_results: dict[str, tuple[bool, str]] = field(default_factory=dict)

    @property
    def first_run(self) -> RunResult:
        return self.runs[0]


@dataclass
class ProbeRecord:
    """One row in the probe table for the dev-report."""

    host: str
    model: str
    http_status: int | str
    response_snippet: str
    note: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _stage(name: str) -> Iterator[None]:
    token = obs.current_stage.set(name)
    try:
        yield
    finally:
        obs.current_stage.reset(token)


def _normalize_ws(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def _render_pages(pdf_path: Path, dpi: int = DPI) -> list[bytes]:
    doc = fitz.open(pdf_path)
    try:
        return [doc[i].get_pixmap(dpi=dpi).tobytes("png") for i in range(doc.page_count)]
    finally:
        doc.close()


def _text_tier_transcript(pdf_path: Path) -> str:
    import pdfplumber  # noqa: PLC0415

    with pdfplumber.open(pdf_path) as pdf:
        parts = [page.extract_text() or "" for page in pdf.pages]
    return "\n\n".join(parts)


def _word_ngrams(text: str, n: int = 6) -> set[str]:
    words = re.findall(r"\S+", text.lower())
    if len(words) < n:
        return set()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _preflight() -> int | None:
    if not os.environ.get("MINIMAX_API_KEY"):
        print("Set MINIMAX_API_KEY in the environment (.env is not auto-loaded)", file=sys.stderr)
        return 2
    if not ANCHORS_PATH.exists():
        print(f"Missing fixture file: {ANCHORS_PATH}", file=sys.stderr)
        return 2
    return None


# ---------------------------------------------------------------------------
# Vision call (chatcompletion_v2)
# ---------------------------------------------------------------------------


def _build_payload(model: str, png_bytes: bytes) -> dict[str, Any]:
    """MiniMax chatcompletion_v2 payload with `image_url` content block.

    Per MiniMax docs verbatim:
        {"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}
    The `url` field accepts a public HTTPS URL or a base64 data URI.
    """
    b64 = base64.b64encode(png_bytes).decode("ascii")
    data_url = f"data:image/png;base64,{b64}"
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_USER_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }


async def _call_vision_page(
    client: httpx.AsyncClient,
    host: str,
    model: str,
    png_bytes: bytes,
) -> tuple[str, int, int]:
    """One vision call. Returns (text, prompt_tokens, completion_tokens).

    Raises on non-200 with the response body included in the message so the
    caller can record it.
    """
    payload = _build_payload(model, png_bytes)
    response = await client.post(host + ENDPOINT_PATH, json=payload, timeout=60.0)
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
    data = response.json()
    base_resp = data.get("base_resp") or {}
    if base_resp.get("status_code", 0) not in (0, 200):
        raise RuntimeError(f"base_resp error: {base_resp}")
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"empty choices in response: {str(data)[:300]}")
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        # MiniMax may return content as a list of content blocks; concatenate
        # text-type parts.
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        text = "".join(parts).strip()
    else:
        text = str(content).strip()
    usage = data.get("usage") or {}
    pt = int(usage.get("prompt_tokens") or usage.get("total_tokens", 0) or 0)
    ct = int(usage.get("completion_tokens") or 0)
    return text, pt, ct


# ---------------------------------------------------------------------------
# Probes (one-shot up front, logged to dev-report)
# ---------------------------------------------------------------------------


def _image_consumed(text: str) -> bool:
    """True if response contains any IMAGE_PROBE_MARKERS — proves the model
    actually transcribed the image and didn't just hallucinate or silently
    drop it ("there's no image attached" style)."""
    return any(marker in text for marker in IMAGE_PROBE_MARKERS)


async def _probe_host_and_model(
    client: httpx.AsyncClient,
    probe_png: bytes,
) -> tuple[str | None, str | None, list[ProbeRecord]]:
    """Try (host × model) combinations. Returns (host, model, probe_records).

    A combo "wins" only if the response contains evidence the image was
    actually consumed (IMAGE_PROBE_MARKERS). Silent-drop responses (200 OK
    with text that has no markers) are recorded and probing continues.

    Returns (None, None, records) if no combo proved image consumption.
    """
    records: list[ProbeRecord] = []
    for host in HOST_CANDIDATES:
        for model in MODEL_PROBE_ORDER:
            try:
                text, pt, ct = await _call_vision_page(client, host, model, probe_png)
                if not text:
                    records.append(
                        ProbeRecord(
                            host=host,
                            model=model,
                            http_status=200,
                            response_snippet="",
                            note="empty response (200 OK)",
                        )
                    )
                    continue
                if _image_consumed(text):
                    records.append(
                        ProbeRecord(
                            host=host,
                            model=model,
                            http_status=200,
                            response_snippet=text[:200],
                            note=f"PASS — image consumed. tokens: prompt={pt}, completion={ct}",
                        )
                    )
                    return host, model, records
                records.append(
                    ProbeRecord(
                        host=host,
                        model=model,
                        http_status=200,
                        response_snippet=text[:200],
                        note="SILENT DROP — 200 OK but no IMAGE_PROBE_MARKERS in response",
                    )
                )
            except Exception as e:
                msg = str(e)
                records.append(
                    ProbeRecord(
                        host=host,
                        model=model,
                        http_status=msg.split(":")[0] if "HTTP" in msg else "error",
                        response_snippet=msg[:300],
                    )
                )
    return None, None, records


# ---------------------------------------------------------------------------
# Main spike orchestration
# ---------------------------------------------------------------------------


async def _run_fixture(
    client: httpx.AsyncClient,
    host: str,
    model: str,
    name: str,
    pdf_path: Path,
) -> FixtureResult:
    pages_png = _render_pages(pdf_path, dpi=DPI)
    result = FixtureResult(name=name, pdf_path=pdf_path)
    for run_index in range(NUM_RUNS):
        run = RunResult(run_index=run_index)
        for page_index, png in enumerate(pages_png):
            t0 = time.perf_counter()
            try:
                with _stage(f"spike.vision.{name}.run{run_index}.page{page_index}"):
                    text, pt, ct = await _call_vision_page(client, host, model, png)
                err: str | None = None
            except Exception as e:
                text, pt, ct, err = "", 0, 0, f"{type(e).__name__}: {e}"
            dur = time.perf_counter() - t0
            usd = (pt / 1e6) * VISION_PRICE_PROMPT_PER_1M + (ct / 1e6) * VISION_PRICE_COMPLETION_PER_1M
            run.pages.append(
                PageCall(
                    page_index=page_index,
                    transcript=text,
                    duration_s=dur,
                    prompt_tokens=pt,
                    completion_tokens=ct,
                    usd_cost=usd,
                    error=err,
                )
            )
            print(
                f"  [{name} r{run_index} p{page_index}] "
                f"{dur:.2f}s tokens={pt}+{ct} ${usd:.4f} "
                f"{'OK' if err is None else err[:80]}"
            )
        result.runs.append(run)
    return result


def _evaluate_gates(fixture: FixtureResult, fixture_spec: dict[str, Any]) -> None:
    anchors = fixture_spec["verify_anchors"]
    transcript = fixture.first_run.transcript
    hits = sum(1 for a in anchors if verify_quote(a["text"], transcript))
    fixture.gate_results["G1_anchor_survival"] = (
        hits >= GATE_ANCHOR_FLOOR,
        f"{hits}/{len(anchors)} (floor ≥{GATE_ANCHOR_FLOOR})",
    )

    column = fixture_spec.get("column_tokens")
    if column:
        norm_transcript = unicodedata.normalize("NFC", transcript)
        sidebar_positions = [
            norm_transcript.find(unicodedata.normalize("NFC", tok))
            for tok in column["sidebar_first"]
        ]
        body_positions = [
            norm_transcript.find(unicodedata.normalize("NFC", tok))
            for tok in column["body_after"]
        ]
        sidebar_found = [p for p in sidebar_positions if p >= 0]
        body_found = [p for p in body_positions if p >= 0]
        if not sidebar_found or not body_found:
            fixture.gate_results["G2_column_order"] = (
                False,
                f"sidebar_found={len(sidebar_found)} body_found={len(body_found)} (need both)",
            )
        else:
            max_sidebar = max(sidebar_found)
            min_body = min(body_found)
            passed = max_sidebar < min_body
            fixture.gate_results["G2_column_order"] = (
                passed,
                f"last_sidebar_pos={max_sidebar} first_body_pos={min_body}",
            )
    else:
        fixture.gate_results["G2_column_order"] = (True, "n/a (single-column fixture)")

    cz_tokens = fixture_spec.get("cz_only_tokens", [])
    if cz_tokens:
        misses = [t["text"] for t in cz_tokens if t["text"] not in transcript]
        fixture.gate_results["G3_translation_drift"] = (
            not misses,
            f"missing={misses}" if misses else f"all {len(cz_tokens)} CZ tokens survived literally",
        )
    else:
        fixture.gate_results["G3_translation_drift"] = (True, "n/a (no CZ-only tokens)")

    is_single_column = column is None
    if is_single_column and fixture.text_tier_transcript:
        ng_vision = _word_ngrams(transcript, n=6)
        ng_text = _word_ngrams(fixture.text_tier_transcript, n=6)
        j = _jaccard(ng_vision, ng_text)
        fixture.gate_results["G4_drift_jaccard"] = (
            j >= GATE_JACCARD_FLOOR,
            f"jaccard={j:.3f} (floor ≥{GATE_JACCARD_FLOOR})",
        )
    else:
        fixture.gate_results["G4_drift_jaccard"] = (True, "n/a (multi-column or no text-tier)")

    all_pages = [p for r in fixture.runs for p in r.pages]
    if all_pages:
        max_cost = max(p.usd_cost for p in all_pages)
        avg_cost = statistics.mean(p.usd_cost for p in all_pages)
        passed = max_cost <= GATE_COST_CEILING_PER_PAGE
        fixture.gate_results["G5_cost_per_page"] = (
            passed,
            f"max=${max_cost:.4f} avg=${avg_cost:.4f} (ceiling ≤${GATE_COST_CEILING_PER_PAGE})",
        )
    else:
        fixture.gate_results["G5_cost_per_page"] = (False, "no page calls completed")

    latencies = [p.duration_s for p in all_pages if p.error is None]
    if latencies:
        p95 = _percentile(latencies, 0.95)
        passed = p95 <= GATE_LATENCY_P95_CEILING_S
        fixture.gate_results["G6_latency_p95"] = (
            passed,
            f"p95={p95:.2f}s p50={_percentile(latencies, 0.5):.2f}s (ceiling ≤{GATE_LATENCY_P95_CEILING_S}s)",
        )
    else:
        fixture.gate_results["G6_latency_p95"] = (False, "no successful page calls")

    page_count = fixture.first_run.page_count
    deterministic = True
    diffs: list[str] = []
    for page_index in range(page_count):
        normalised = {_normalize_ws(r.pages[page_index].transcript) for r in fixture.runs}
        if len(normalised) > 1:
            deterministic = False
            diffs.append(f"page {page_index}: {len(normalised)} distinct normalised outputs")
    fixture.gate_results["G7_determinism"] = (
        deterministic,
        "all 3 runs identical (whitespace-normalised)" if deterministic else "; ".join(diffs),
    )


def _format_fixture_report(fixture: FixtureResult) -> str:
    lines = [f"### {fixture.name} ({fixture.pdf_path.name})", ""]
    for gate, (ok, detail) in fixture.gate_results.items():
        marker = "PASS" if ok else "FAIL"
        lines.append(f"- **{gate}**: {marker} — {detail}")
    page_count = fixture.first_run.page_count
    total_usd = sum(r.total_usd for r in fixture.runs)
    lines.append("")
    lines.append(
        f"  Runs: {len(fixture.runs)} × {page_count} pages = "
        f"{len(fixture.runs) * page_count} vision calls. Total: ${total_usd:.4f}"
    )
    return "\n".join(lines)


def _format_probe_table(records: list[ProbeRecord]) -> str:
    lines = ["| Host | Model | Status | Note / Snippet |", "|---|---|---|---|"]
    for r in records:
        snippet = (r.note or r.response_snippet or "").replace("\n", " ").replace("|", "\\|")[:160]
        lines.append(f"| `{r.host}` | `{r.model}` | `{r.http_status}` | {snippet} |")
    return "\n".join(lines)


async def main() -> int:
    pre = _preflight()
    if pre is not None:
        return pre

    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=REPO_ROOT / "tasks/T32_dev-report.md")
    parser.add_argument(
        "--profile-pdf",
        type=Path,
        default=Path("/home/mf/Downloads/Profile.pdf"),
    )
    args = parser.parse_args()

    anchors = json.loads(ANCHORS_PATH.read_text())
    fixtures = anchors["fixtures"]

    fixture_paths: dict[str, Path] = {
        "profile_pdf": args.profile_pdf,
        "07_senior_ds_holub": REPO_ROOT / "tests/fixtures/cvs/07_senior_ds_holub.pdf",
        "03_ds_horak": REPO_ROOT / "tests/fixtures/cvs/03_ds_horak.pdf",
    }
    for name, path in fixture_paths.items():
        if not path.exists():
            print(f"Missing fixture PDF: {path} (fixture: {name})", file=sys.stderr)
            return 2

    api_key = os.environ["MINIMAX_API_KEY"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(headers=headers, timeout=60.0) as client:
        # Probe with page 1 of the smallest single-column fixture
        probe_pdf = fixture_paths["03_ds_horak"]
        probe_pages = _render_pages(probe_pdf, dpi=DPI)
        probe_png = probe_pages[0]

        print(f"Probing (host × model) — endpoint {ENDPOINT_PATH}, dpi {DPI}")
        host, model, probe_records = await _probe_host_and_model(client, probe_png)

        for rec in probe_records:
            print(f"  [{rec.host}] [{rec.model}] {rec.http_status}: {rec.note or rec.response_snippet[:120]}")

        if host is None or model is None:
            print("\nFATAL: no (host, model) combo accepted a vision call.", file=sys.stderr)
            # Write a partial dev-report so the user has the forensic table
            report_lines = [
                "# T32 dev-report — MiniMax vision capability spike (re-run)",
                "",
                "**Verdict: PROBE FAILED — no host/model combination accepted a vision call.**",
                "",
                "## Probe table",
                "",
                _format_probe_table(probe_records),
                "",
            ]
            args.report.write_text("\n".join(report_lines))
            print(f"Wrote partial dev-report: {args.report}")
            return 3

        print(f"\nLocked: host={host} model={model}\n")

        # Full eval
        print(f"Running 3 fixtures × {NUM_RUNS} runs × per-page calls...")
        results: list[FixtureResult] = []
        for name, fixture_spec in fixtures.items():
            pdf_path = fixture_paths[name]
            print(f"\n[{name}] {pdf_path.name}")
            fixture = await _run_fixture(client, host, model, name, pdf_path)
            if not fixture_spec.get("column_tokens"):
                try:
                    fixture.text_tier_transcript = _text_tier_transcript(pdf_path)
                except Exception as e:  # noqa: BLE001
                    print(f"  text-tier baseline failed: {e}", file=sys.stderr)
            _evaluate_gates(fixture, fixture_spec)
            results.append(fixture)
            print(_format_fixture_report(fixture))

    # Aggregate verdict
    any_failed = False
    failed_lines: list[str] = []
    for fixture in results:
        for gate, (ok, _) in fixture.gate_results.items():
            if not ok:
                any_failed = True
                failed_lines.append(f"FAILED GATE: {gate} on {fixture.name}")

    total_calls = sum(len(r.runs) * r.first_run.page_count for r in results)
    total_usd = sum(sum(r.total_usd for r in f.runs) for f in results)

    report_lines = [
        "# T32 dev-report — MiniMax vision capability spike (re-run)",
        "",
        f"**Verdict: {'ADOPT MiniMax vision — all gates passed.' if not any_failed else 'NOT YET — see failed gates below.'}**",
        "",
        f"- Host (locked): `{host}`",
        f"- Endpoint: `{ENDPOINT_PATH}`",
        f"- Model (locked): `{model}`",
        f"- DPI: {DPI}",
        f"- Runs per PDF: {NUM_RUNS}",
        f"- Temperature: {TEMPERATURE}",
        f"- Vision prompt version: `{VISION_PROMPT_VERSION}`",
        f"- Pricing assumed: prompt ${VISION_PRICE_PROMPT_PER_1M}/1M, completion ${VISION_PRICE_COMPLETION_PER_1M}/1M (recheck post-run)",
        "",
        "## Probe table",
        "",
        _format_probe_table(probe_records),
        "",
        "## Per-fixture gate results",
        "",
    ]
    for fixture in results:
        report_lines.append(_format_fixture_report(fixture))
        report_lines.append("")

    report_lines.extend(
        [
            "## Aggregate",
            "",
            f"- Total vision calls: {total_calls}",
            f"- Total cost: ${total_usd:.4f}",
            "",
            "## Verdict",
            "",
            "**" + ("ADOPT MiniMax vision — all gates passed. T34 wires the path."
                    if not any_failed
                    else "DO NOT ADOPT YET — see failed gates above.") + "**",
            "",
        ]
    )
    args.report.write_text("\n".join(report_lines))
    print(f"\nWrote {args.report}")

    print()
    print(f"=== Spike verdict: {'PASS' if not any_failed else 'FAIL'} ===")
    if any_failed:
        for line in failed_lines:
            print(line)
        return 1
    print("All 7 gates passed on all 3 fixtures.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
