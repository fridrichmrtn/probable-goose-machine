"""Synthetic MiniMax Token Plan VLM smoke/eval for Gander.

This is deliberately a testing-only spike:
- no production imports from gander,
- no private or fixture CV pages,
- no secret printing,
- synthetic CV-like pages rendered in memory and sent to MiniMax API-vlm.

Run:
    UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/spike_minimax_token_plan_vlm.py

The script writes a short Markdown report by default to:
    tasks/minimax_token_plan_vlm_report.md
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from textwrap import shorten
from typing import Any

import fitz
import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / "tasks" / "minimax_token_plan_vlm_report.md"
DEFAULT_ENDPOINT = "https://api.minimax.io/v1/coding_plan/vlm"
PAYGO_USD_PER_REQUEST = 0.06
TOKEN_PLAN_M2_REQUESTS_PER_VLM = 3
ANCHOR_NEAR_THRESHOLD = 0.88

FONT_REGULAR = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
FONT_BOLD = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

PROMPT = """Transcribe this synthetic CV page verbatim.

Rules:
- Return only visible text, no commentary.
- Preserve Czech diacritics and original language.
- Do not summarize or rewrite bullets.
- For a two-column page, output the left sidebar first, then the right body.
"""


@dataclass(frozen=True)
class SyntheticCase:
    name: str
    description: str
    layout: str
    anchors: tuple[str, ...]
    czech_tokens: tuple[str, ...] = ()
    sidebar_tokens: tuple[str, ...] = ()
    body_tokens: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnchorHit:
    anchor: str
    matched: bool
    exact: bool
    score: float


@dataclass
class CaseResult:
    case: SyntheticCase
    status_code: int
    latency_s: float
    response_text: str
    raw_body_prefix: str
    error: str | None = None

    @property
    def ok_http(self) -> bool:
        return self.status_code == 200 and self.error is None and bool(self.response_text.strip())


CASES: tuple[SyntheticCase, ...] = (
    SyntheticCase(
        name="single_column_en",
        description="Single-column English CV text",
        layout="single_en",
        anchors=(
            "Data Scientist with 5 years building churn models for retail teams",
            "Led customer churn model for Mall.cz pilot reducing cancellations by 11 percent",
            "Built basket demand forecasting model with Python SQL and LightGBM",
            "Owned weekly model monitoring notes for the synthetic analytics team",
            "CVUT FIT Prague - MSc Informatics 2021",
        ),
    ),
    SyntheticCase(
        name="bilingual_czech",
        description="Bilingual/Czech CV text with diacritics",
        layout="czech",
        anchors=(
            "Pracovní zkušenosti",
            "Vedla model odchodu zákazníků pro Praha Retail Lab v října 2024",
            "Navrhla dashboard pro Česko a Slovensko s přesností 93 procent",
            "ČVUT FIT - Datová věda, září 2019 - června 2021",
            "čeština, angličtina",
        ),
        czech_tokens=("Pracovní zkušenosti", "Vzdělání", "října", "Česko", "ČVUT"),
    ),
    SyntheticCase(
        name="two_column_sidebar",
        description="Two-column CV layout with sidebar-first ordering",
        layout="two_column",
        anchors=(
            "Kontakt",
            "Praha, Česko",
            "Nejčastější dovednosti",
            "Mini Badge 2026",
            "Pracovní zkušenosti",
            "Founded data quality program for synthetic finance team",
            "Improved forecast review cycle from 9 days to 3 days",
            "Vzdělání",
        ),
        czech_tokens=(
            "Kontakt",
            "Česko",
            "Nejčastější dovednosti",
            "Pracovní zkušenosti",
            "Vzdělání",
        ),
        sidebar_tokens=("Kontakt", "Praha, Česko", "Nejčastější dovednosti", "Mini Badge 2026"),
        body_tokens=("Pracovní zkušenosti", "Founded data quality program", "Vzdělání"),
    ),
)


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader for this script only; avoids adding python-dotenv."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _require_key() -> str:
    _load_dotenv(REPO_ROOT / ".env")
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY not set; add it to .env or export it")
    return api_key


def _font_paths() -> tuple[Path, Path]:
    if not FONT_REGULAR.exists() or not FONT_BOLD.exists():
        raise RuntimeError("DejaVu fonts not found; cannot render Czech diacritics reliably")
    return FONT_REGULAR, FONT_BOLD


def _insert_fonts(page: fitz.Page) -> None:
    regular, bold = _font_paths()
    page.insert_font(fontname="dejavu", fontfile=str(regular))
    page.insert_font(fontname="dejavub", fontfile=str(bold))


def _draw_lines(
    page: fitz.Page,
    lines: list[tuple[str, float, str]],
    *,
    x: float,
    y: float,
    line_gap: float = 31,
    color: tuple[float, float, float] = (0, 0, 0),
) -> None:
    for text, size, font in lines:
        page.insert_text((x, y), text, fontsize=size, fontname=font, color=color)
        y += line_gap


def _render_case(case: SyntheticCase, dpi: int) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=900, height=1100)
    _insert_fonts(page)

    if case.layout == "single_en":
        _draw_lines(
            page,
            [
                ("GANDER SYNTHETIC CV 001", 26, "dejavub"),
                ("Summary", 22, "dejavub"),
                (
                    "Data Scientist with 5 years building churn models for retail teams",
                    18,
                    "dejavu",
                ),
                ("Experience", 22, "dejavub"),
                (
                    "- Led customer churn model for Mall.cz pilot reducing cancellations "
                    "by 11 percent",
                    17,
                    "dejavu",
                ),
                (
                    "- Built basket demand forecasting model with Python SQL and LightGBM",
                    17,
                    "dejavu",
                ),
                (
                    "- Owned weekly model monitoring notes for the synthetic analytics team",
                    17,
                    "dejavu",
                ),
                ("Education", 22, "dejavub"),
                ("CVUT FIT Prague - MSc Informatics 2021", 17, "dejavu"),
            ],
            x=72,
            y=86,
            line_gap=44,
        )
    elif case.layout == "czech":
        _draw_lines(
            page,
            [
                ("Jana Testovací", 28, "dejavub"),
                ("Pracovní zkušenosti", 23, "dejavub"),
                (
                    "- Vedla model odchodu zákazníků pro Praha Retail Lab v října 2024",
                    17,
                    "dejavu",
                ),
                ("- Navrhla dashboard pro Česko a Slovensko s přesností 93 procent", 17, "dejavu"),
                ("Vzdělání", 23, "dejavub"),
                ("ČVUT FIT - Datová věda, září 2019 - června 2021", 17, "dejavu"),
                ("Jazyky", 23, "dejavub"),
                ("čeština, angličtina", 17, "dejavu"),
            ],
            x=72,
            y=86,
            line_gap=46,
        )
    elif case.layout == "two_column":
        page.draw_rect(fitz.Rect(0, 0, 285, 1100), fill=(0.92, 0.94, 0.96), color=None)
        _draw_lines(
            page,
            [
                ("Kontakt", 22, "dejavub"),
                ("Praha, Česko", 17, "dejavu"),
                ("Nejčastější dovednosti", 19, "dejavub"),
                ("Python", 16, "dejavu"),
                ("SQL", 16, "dejavu"),
                ("Certifikace", 19, "dejavub"),
                ("Mini Badge 2026", 16, "dejavu"),
            ],
            x=36,
            y=72,
            line_gap=42,
        )
        _draw_lines(
            page,
            [
                ("Alex Synthetic", 29, "dejavub"),
                ("Pracovní zkušenosti", 23, "dejavub"),
                ("Senior Analytics Lead", 18, "dejavub"),
                ("- Founded data quality program for synthetic finance team", 17, "dejavu"),
                ("- Improved forecast review cycle from 9 days to 3 days", 17, "dejavu"),
                ("Vzdělání", 23, "dejavub"),
                ("Test University - Applied Statistics 2018", 17, "dejavu"),
            ],
            x=330,
            y=72,
            line_gap=46,
        )
    else:
        raise ValueError(f"unknown layout: {case.layout}")

    pix = page.get_pixmap(dpi=dpi)
    png = pix.tobytes("png")
    doc.close()
    return png


def _extract_response_text(data: dict[str, Any]) -> str:
    content = data.get("content", "")
    if isinstance(content, str):
        return content.strip()
    return str(content).strip()


def _call_vlm(
    endpoint: str, api_key: str, png: bytes, timeout: float
) -> tuple[int, float, str, str]:
    image_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "MM-API-Source": "Gander-Synthetic-VLM-Spike",
    }
    payload = {"prompt": PROMPT, "image_url": image_url}
    start = time.perf_counter()
    response = httpx.post(endpoint, headers=headers, json=payload, timeout=timeout)
    latency_s = time.perf_counter() - start
    body_prefix = response.text[:1400]
    if response.status_code != 200:
        return response.status_code, latency_s, "", body_prefix
    data = response.json()
    return response.status_code, latency_s, _extract_response_text(data), body_prefix


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _score_anchor(anchor: str, transcript: str) -> AnchorHit:
    norm_anchor = _norm(anchor)
    norm_text = _norm(transcript)
    if norm_anchor in norm_text:
        return AnchorHit(anchor=anchor, matched=True, exact=True, score=1.0)

    lines = [line.strip() for line in transcript.splitlines() if line.strip()]
    best = 0.0
    for line in lines + [transcript]:
        best = max(best, SequenceMatcher(None, norm_anchor, _norm(line)).ratio())
    return AnchorHit(
        anchor=anchor,
        matched=best >= ANCHOR_NEAR_THRESHOLD,
        exact=False,
        score=best,
    )


def _anchor_hits(case: SyntheticCase, transcript: str) -> list[AnchorHit]:
    return [_score_anchor(anchor, transcript) for anchor in case.anchors]


def _contains_token(transcript: str, token: str) -> bool:
    return _norm(token) in _norm(transcript)


def _czech_ok(case: SyntheticCase, transcript: str) -> bool:
    return all(_contains_token(transcript, token) for token in case.czech_tokens)


def _layout_ok(case: SyntheticCase, transcript: str) -> bool | None:
    if not case.sidebar_tokens:
        return None
    norm_text = _norm(transcript)
    sidebar_positions = [norm_text.find(_norm(token)) for token in case.sidebar_tokens]
    body_positions = [norm_text.find(_norm(token)) for token in case.body_tokens]
    if any(pos < 0 for pos in sidebar_positions + body_positions):
        return False
    return max(sidebar_positions) < min(body_positions)


def _result_row(result: CaseResult) -> tuple[int, int, bool, bool | None, str]:
    hits = _anchor_hits(result.case, result.response_text)
    matched = sum(hit.matched for hit in hits)
    czech_ok = _czech_ok(result.case, result.response_text)
    layout_ok = _layout_ok(result.case, result.response_text)
    verdict = (
        "PASS"
        if result.ok_http and matched == len(hits) and czech_ok and layout_ok is not False
        else "FAIL"
    )
    return matched, len(hits), czech_ok, layout_ok, verdict


def _overall_recommendation(results: list[CaseResult]) -> str:
    total = 0
    matched = 0
    all_http = all(result.ok_http for result in results)
    czech_pass = True
    layout_pass = True
    for result in results:
        hits = _anchor_hits(result.case, result.response_text)
        total += len(hits)
        matched += sum(hit.matched for hit in hits)
        czech_pass = czech_pass and _czech_ok(result.case, result.response_text)
        layout = _layout_ok(result.case, result.response_text)
        layout_pass = layout_pass and layout is not False

    anchor_rate = matched / total if total else 0.0
    if all_http and anchor_rate >= 0.9 and czech_pass and layout_pass:
        return "usable"
    if all_http and anchor_rate >= 0.7:
        return "usable with guardrails"
    return "not usable"


def _snippet(text: str, limit: int = 900) -> str:
    text = text.strip()
    return shorten(text, width=limit, placeholder="\n...[truncated]")


def _write_report(endpoint: str, results: list[CaseResult], report_path: Path) -> None:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    total_requests = len(results)
    total_cost = total_requests * PAYGO_USD_PER_REQUEST
    total_m2_requests = total_requests * TOKEN_PLAN_M2_REQUESTS_PER_VLM
    recommendation = _overall_recommendation(results)

    total_anchors = sum(len(result.case.anchors) for result in results)
    matched_anchors = sum(
        sum(hit.matched for hit in _anchor_hits(result.case, result.response_text))
        for result in results
    )
    anchor_rate = matched_anchors / total_anchors if total_anchors else 0.0

    lines: list[str] = [
        "# MiniMax Token Plan VLM synthetic test report",
        "",
        f"Generated: {now}",
        "",
        "## Scope",
        "",
        "- Synthetic CV-like pages only; no private CVs or repo CV fixtures were sent.",
        "- Endpoint tested: `POST " + endpoint + "`.",
        f"- Requests: {total_requests}; pay-as-you-go equivalent: ${total_cost:.2f}; "
        f"Token Plan quota equivalent: {total_m2_requests} M2.7 requests.",
        "",
        "## Results",
        "",
        "| Case | HTTP | Latency | Anchors | Czech | Layout | Verdict |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for result in results:
        matched, total, czech_ok, layout_ok, verdict = _result_row(result)
        layout_text = "n/a" if layout_ok is None else ("PASS" if layout_ok else "FAIL")
        czech_text = "PASS" if czech_ok else "FAIL"
        http_text = "PASS" if result.ok_http else f"FAIL {result.status_code}"
        lines.append(
            "| "
            f"`{result.case.name}` | {http_text} | {result.latency_s:.2f}s | "
            f"{matched}/{total} | {czech_text} | {layout_text} | {verdict} |"
        )

    lines.extend(
        [
            "",
            f"Anchor survival: {matched_anchors}/{total_anchors} ({anchor_rate:.0%}).",
            "",
            "## Raw Response Snippets",
            "",
        ]
    )
    for result in results:
        lines.extend(
            [
                f"### `{result.case.name}`",
                "",
                "```text",
                _snippet(result.response_text or result.raw_body_prefix),
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "## Recommendation",
            "",
            f"**{recommendation}**",
            "",
            "Real CV/Profile.pdf testing remains a separate approval because it sends document "
            "content to MiniMax.",
            "",
        ]
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def run(endpoint: str, report_path: Path, dpi: int, timeout: float) -> int:
    api_key = _require_key()
    results: list[CaseResult] = []
    for case in CASES:
        png = _render_case(case, dpi=dpi)
        try:
            status_code, latency_s, text, raw_prefix = _call_vlm(endpoint, api_key, png, timeout)
            results.append(
                CaseResult(
                    case=case,
                    status_code=status_code,
                    latency_s=latency_s,
                    response_text=text,
                    raw_body_prefix=raw_prefix,
                )
            )
        except Exception as exc:
            results.append(
                CaseResult(
                    case=case,
                    status_code=0,
                    latency_s=0.0,
                    response_text="",
                    raw_body_prefix="",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    _write_report(endpoint, results, report_path)
    recommendation = _overall_recommendation(results)
    for result in results:
        matched, total, czech_ok, layout_ok, verdict = _result_row(result)
        layout_text = "n/a" if layout_ok is None else ("pass" if layout_ok else "fail")
        print(
            f"{result.case.name}: {verdict.lower()} "
            f"http={result.status_code} latency={result.latency_s:.2f}s "
            f"anchors={matched}/{total} czech={'pass' if czech_ok else 'fail'} "
            f"layout={layout_text}"
        )
        if result.error:
            print(f"  error={result.error}")
    print(f"report={report_path}")
    print(f"recommendation={recommendation}")
    return 0 if recommendation in {"usable", "usable with guardrails"} else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--dpi", type=int, default=120)
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return run(args.endpoint, args.report, args.dpi, args.timeout)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
