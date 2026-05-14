"""MiniMax vision capability spike for T32.

Renders the three fixture PDFs page-by-page via pymupdf, calls the MiniMax
vision endpoint per page with a verbatim-transcription prompt, runs each PDF 3
times at temperature=0, then evaluates the 7 hard gates and prints a results
table. Mirrors the structure of `scripts/spike_minimax.py` (T05).

Run: ``uv run python scripts/spike_minimax_vision.py [--report PATH]``

Exit codes:
  0 — all 7 gates passed on all 3 PDFs.
  1 — at least one gate failed (preceded by ``FAILED GATE: <name> on <pdf>``).
  2 — preflight env-var / fixture check failed.

The 7 gates:
  G1 anchor_survival     ≥9/10 verify_quote hits per PDF (run-1 transcript).
  G2 column_order        sidebar tokens precede body tokens (multi-col PDF only).
  G3 translation_drift   every cz_only_token appears literally (no EN translation).
  G4 drift_jaccard       length-≥6 word n-gram Jaccard vs text-tier transcript
                         ≥0.6 on single-column fixtures (where text-tier is good).
  G5 cost_per_page       per-page USD cost ≤ $0.05.
  G6 latency_p95         per-page p95 latency ≤ 15s.
  G7 determinism         3 runs at T=0 → whitespace-normalised identical per page.

The image-input shape (`image_url` vs `input_image`) is locked into a
module-level constant the script prints — T34 reuses it.
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

from gander import obs
from gander.verify import verify_quote

REPO_ROOT = Path(__file__).resolve().parents[1]
ANCHORS_PATH = REPO_ROOT / "tests/fixtures/vision_anchors.json"

# DPI for page rendering. The plan ([plan §"Files to add / modify"]) clamps to
# [120, 300]; spike uses the production default.
DPI = 200

# Image-input shape for MiniMax OpenAI-compatible chat.completions. Per the
# plan, try `image_url` (OpenAI canonical) first; if it 400s, the spike will
# log + retry with `input_image`. The shape that worked is printed at the
# end of the run so T34 can pin it as a constant in `gander.llm`.
IMAGE_INPUT_SHAPE_PREFERRED = "image_url"
IMAGE_INPUT_SHAPE_FALLBACK = "input_image"

# Vision model identifier. MiniMax doc nomenclature has shifted across releases;
# `MiniMax-VL-01` and `abab6.5-vision` have both been valid at different points.
# Override at the CLI via env if needed. The script prints the resolved model
# in the report so the post-spike default is explicit.
DEFAULT_VISION_MODEL = os.environ.get("GANDER_VISION_MODEL", "MiniMax-VL-01")

# Per-1M-token pricing for the vision model. MiniMax does not publish vision
# prices in their public console without auth — these are placeholders that
# get re-grounded from the printed token counts in the dev-report.
# (prompt_usd_per_1m, completion_usd_per_1m) — image input is billed as
# prompt tokens with a per-image surcharge that we approximate via the
# `usage.prompt_tokens` returned by the API.
VISION_PRICE_PROMPT_PER_1M = float(os.environ.get("GANDER_VISION_PRICE_PROMPT", "1.50"))
VISION_PRICE_COMPLETION_PER_1M = float(os.environ.get("GANDER_VISION_PRICE_COMPLETION", "6.00"))

NUM_RUNS = 3
TEMPERATURE = 0.0
MAX_TOKENS = 4096

# Gate thresholds — pinned in the plan.
GATE_ANCHOR_FLOOR = 9  # ≥9/10 verify-anchors must hit per PDF
GATE_JACCARD_FLOOR = 0.60
GATE_COST_CEILING_PER_PAGE = 0.05
GATE_LATENCY_P95_CEILING_S = 15.0

# Verbatim-transcription prompt (v0 — T34 extracts to prompts/ingest_vision.md).
# Per the plan §"Transcription prompt".
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
    text_tier_transcript: str = ""  # for Jaccard gate
    expects_column_check: bool = False
    gate_results: dict[str, tuple[bool, str]] = field(default_factory=dict)

    @property
    def first_run(self) -> RunResult:
        return self.runs[0]


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
    """Whitespace-normalise for determinism check (trailing WS stripped per line)."""
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def _render_pages(pdf_path: Path, dpi: int = DPI) -> list[bytes]:
    doc = fitz.open(pdf_path)
    try:
        return [doc[i].get_pixmap(dpi=dpi).tobytes("png") for i in range(doc.page_count)]
    finally:
        doc.close()


def _text_tier_transcript(pdf_path: Path) -> str:
    """Best-effort text-tier extraction for the Jaccard baseline. Uses
    pdfplumber.extract_text() — matches what the current L1 ingest does on
    PDFs after the pypdf fast-path."""
    import pdfplumber  # noqa: PLC0415 — heavy import isolated to spike

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
# Vision call
# ---------------------------------------------------------------------------


async def _call_vision_page(
    client: Any,
    model: str,
    png_bytes: bytes,
    shape: str,
) -> tuple[str, int, int, str]:
    """Single vision call. Returns (text, prompt_tokens, completion_tokens, shape_used).

    Tries the supplied `shape` first; on a 400-style error, retries with the
    fallback shape. Raises on other errors so they bubble to the caller.
    """
    b64 = base64.b64encode(png_bytes).decode("ascii")
    data_url = f"data:image/png;base64,{b64}"

    def _build_content(s: str) -> list[dict[str, Any]]:
        if s == "image_url":
            return [
                {"type": "text", "text": VISION_USER_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
        return [
            {"type": "text", "text": VISION_USER_PROMPT},
            {"type": "input_image", "image_url": data_url},
        ]

    for attempt_shape in (shape, IMAGE_INPUT_SHAPE_FALLBACK if shape != IMAGE_INPUT_SHAPE_FALLBACK else IMAGE_INPUT_SHAPE_PREFERRED):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": VISION_SYSTEM_PROMPT},
                    {"role": "user", "content": _build_content(attempt_shape)},
                ],
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
            )
            text = (response.choices[0].message.content or "").strip()
            usage = response.usage
            return text, usage.prompt_tokens, usage.completion_tokens, attempt_shape
        except Exception as e:
            msg = str(e).lower()
            # Retry on shape-shaped errors only (invalid request / bad param).
            if "400" in msg or "invalid" in msg or "unsupported" in msg or "image" in msg:
                continue
            raise
    raise RuntimeError("Both image-input shapes failed; check MiniMax vision API docs")


# ---------------------------------------------------------------------------
# Main spike orchestration
# ---------------------------------------------------------------------------


async def _run_fixture(
    client: Any,
    model: str,
    name: str,
    pdf_path: Path,
    shape: str,
) -> tuple[FixtureResult, str]:
    """Returns (FixtureResult with NUM_RUNS runs, image-shape that worked)."""
    pages_png = _render_pages(pdf_path, dpi=DPI)
    result = FixtureResult(name=name, pdf_path=pdf_path)
    shape_used = shape
    for run_index in range(NUM_RUNS):
        run = RunResult(run_index=run_index)
        for page_index, png in enumerate(pages_png):
            t0 = time.perf_counter()
            try:
                with _stage(f"spike.vision.{name}.run{run_index}.page{page_index}"):
                    text, pt, ct, shape_used = await _call_vision_page(client, model, png, shape_used)
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
        result.runs.append(run)
    return result, shape_used


def _evaluate_gates(fixture: FixtureResult, fixture_spec: dict[str, Any]) -> None:
    """Populate fixture.gate_results with (passed, detail) per gate."""

    # G1 anchor_survival — uses run-0 (first) transcript via verify_quote
    anchors = fixture_spec["verify_anchors"]
    transcript = fixture.first_run.transcript
    hits = sum(1 for a in anchors if verify_quote(a["text"], transcript))
    fixture.gate_results["G1_anchor_survival"] = (
        hits >= GATE_ANCHOR_FLOOR,
        f"{hits}/{len(anchors)} (floor ≥{GATE_ANCHOR_FLOOR})",
    )

    # G2 column_order — only for multi-column fixtures
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

    # G3 translation_drift — every cz_only_token appears literally
    cz_tokens = fixture_spec.get("cz_only_tokens", [])
    if cz_tokens:
        misses = [t["text"] for t in cz_tokens if t["text"] not in transcript]
        fixture.gate_results["G3_translation_drift"] = (
            not misses,
            f"missing={misses}" if misses else f"all {len(cz_tokens)} CZ tokens survived literally",
        )
    else:
        fixture.gate_results["G3_translation_drift"] = (True, "n/a (no CZ-only tokens)")

    # G4 drift_jaccard — only for single-column fixtures (where text-tier is reliable)
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

    # G5 cost_per_page — across all runs / all pages
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

    # G6 latency_p95 — across all runs / all pages
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

    # G7 determinism — N=3 runs, whitespace-normalised identical per page
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


async def main() -> int:
    pre = _preflight()
    if pre is not None:
        return pre

    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=REPO_ROOT / "tasks/T32_dev-report.md")
    parser.add_argument("--model", type=str, default=DEFAULT_VISION_MODEL)
    parser.add_argument(
        "--profile-pdf",
        type=Path,
        default=Path("/home/mf/Downloads/Profile.pdf"),
        help="Path to Profile.pdf (user-local, gitignored).",
    )
    args = parser.parse_args()

    anchors = json.loads(ANCHORS_PATH.read_text())
    fixtures = anchors["fixtures"]

    # Map fixture name -> path. profile_pdf is user-local; others are corpus.
    fixture_paths: dict[str, Path] = {
        "profile_pdf": args.profile_pdf,
        "07_senior_ds_holub": REPO_ROOT / "tests/fixtures/cvs/07_senior_ds_holub.pdf",
        "03_ds_horak": REPO_ROOT / "tests/fixtures/cvs/03_ds_horak.pdf",
    }
    for name, path in fixture_paths.items():
        if not path.exists():
            print(f"Missing fixture PDF: {path} (fixture: {name})", file=sys.stderr)
            return 2

    # Lazy AsyncOpenAI import — keeps the script importable even if openai not
    # installed (it is, but be defensive).
    from openai import AsyncOpenAI  # noqa: PLC0415

    api_key = os.environ["MINIMAX_API_KEY"]
    client = AsyncOpenAI(api_key=api_key, base_url="https://api.minimaxi.chat/v1")

    print(f"Spike start: model={args.model} dpi={DPI} runs={NUM_RUNS} temp={TEMPERATURE}")
    print(f"Image shape preference: {IMAGE_INPUT_SHAPE_PREFERRED} (fallback: {IMAGE_INPUT_SHAPE_FALLBACK})")
    print(f"Fixtures: {list(fixtures.keys())}")
    print()

    results: list[FixtureResult] = []
    shape_locked: str = IMAGE_INPUT_SHAPE_PREFERRED
    for name, fixture_spec in fixtures.items():
        pdf_path = fixture_paths[name]
        print(f"[{name}] rendering + transcribing {pdf_path.name}...")
        try:
            fixture, shape_used = await _run_fixture(client, args.model, name, pdf_path, shape_locked)
        except Exception as e:
            print(f"FATAL: spike crashed on {name}: {type(e).__name__}: {e}", file=sys.stderr)
            raise
        shape_locked = shape_used
        # Compute text-tier baseline for single-column fixtures (G4 Jaccard).
        if not fixture_spec.get("column_tokens"):
            try:
                fixture.text_tier_transcript = _text_tier_transcript(pdf_path)
            except Exception as e:  # noqa: BLE001
                print(f"  text-tier baseline failed: {e}", file=sys.stderr)
        _evaluate_gates(fixture, fixture_spec)
        results.append(fixture)
        print(_format_fixture_report(fixture))
        print()

    # Aggregate verdict
    any_failed = False
    failed_lines: list[str] = []
    for fixture in results:
        for gate, (ok, _) in fixture.gate_results.items():
            if not ok:
                any_failed = True
                failed_lines.append(f"FAILED GATE: {gate} on {fixture.name}")

    # Write dev-report
    report_lines = [
        "# T32 dev-report — MiniMax vision capability spike",
        "",
        f"- Model: `{args.model}`",
        f"- DPI: {DPI}",
        f"- Runs per PDF: {NUM_RUNS}",
        f"- Temperature: {TEMPERATURE}",
        f"- Image-input shape used: `{shape_locked}` (preferred: `{IMAGE_INPUT_SHAPE_PREFERRED}`, fallback: `{IMAGE_INPUT_SHAPE_FALLBACK}`)",
        f"- Vision prompt version: `{VISION_PROMPT_VERSION}`",
        f"- Pricing assumed: prompt ${VISION_PRICE_PROMPT_PER_1M}/1M, completion ${VISION_PRICE_COMPLETION_PER_1M}/1M (recheck post-run)",
        "",
        "## Per-fixture gate results",
        "",
    ]
    for fixture in results:
        report_lines.append(_format_fixture_report(fixture))
        report_lines.append("")

    total_calls = sum(len(r.runs) * r.first_run.page_count for r in results)
    total_usd = sum(sum(r.total_usd for r in f.runs) for f in results)
    report_lines.extend(
        [
            "## Aggregate",
            "",
            f"- Total vision calls: {total_calls}",
            f"- Total cost: ${total_usd:.4f}",
            "",
            "## Recommendation",
            "",
            "**" + ("ADOPT MiniMax vision — all gates passed." if not any_failed
                    else "DO NOT ADOPT MiniMax vision yet — see failed gates above. "
                    "Next step: run Anthropic mini-spike or halt.") + "**",
            "",
        ]
    )
    args.report.write_text("\n".join(report_lines))
    print(f"Wrote {args.report}")

    # Print final verdict on stdout
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
