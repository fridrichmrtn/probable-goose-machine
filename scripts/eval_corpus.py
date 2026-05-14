"""T21 — 10-CV live corpus runner.

The user's manual gauging surface. Runs every fixture under
`tests/fixtures/cvs/*.{pdf,docx}` through the live L1→L5 pipeline,
writes per-CV markdown reports + a SUMMARY.md table, and exits
non-zero on any top-level pipeline failure (ingest / redact / extract).

Usage:
    uv run python scripts/eval_corpus.py
    uv run python scripts/eval_corpus.py --profile ci
    uv run python scripts/eval_corpus.py --output-dir reports/ci-run

The `--profile` flag sets `GANDER_MODEL_PROFILE` for the run (see
`gander.llm` for what it picks). Local profile uses the reasoning-heavy
MiniMax model; CI uses the cheap one.

Execution is serial — DDG queries are rate-sensitive and 10 parallel
pipelines from one IP would draw throttles.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "cvs"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "reports"
SUPPORTED_SUFFIXES = (".pdf", ".docx")


def _iter_fixture_paths(fixture_dir: Path) -> Iterable[Path]:
    for path in sorted(fixture_dir.iterdir()):
        if path.suffix.lower() in SUPPORTED_SUFFIXES:
            yield path


def _format_salary(report: object) -> str:
    from gander.errors import StageFailure
    from gander.schemas import SalaryEstimate

    salary = getattr(report, "salary", None)
    if isinstance(salary, SalaryEstimate):
        return f"{salary.low:,} – {salary.high:,} {salary.currency}/{salary.period}"
    if isinstance(salary, StageFailure):
        return f"failed: {salary.user_message[:60]}"
    return "—"


def _format_score(report: object) -> str:
    from gander.errors import StageFailure
    from gander.schemas import Score

    score = getattr(report, "score", None)
    if isinstance(score, Score):
        return str(score.total)
    if isinstance(score, StageFailure):
        return "failed"
    return "—"


def _format_confidence(report: object) -> str:
    from gander.errors import StageFailure
    from gander.schemas import Confidence

    confidence = getattr(report, "confidence", None)
    if isinstance(confidence, Confidence):
        return confidence.tier
    if isinstance(confidence, StageFailure):
        return "failed"
    return "—"


def _top_growth_action(report: object) -> str:
    from gander.errors import StageFailure

    growth = getattr(report, "growth", None)
    if isinstance(growth, StageFailure):
        return f"failed: {growth.user_message[:60]}"
    if isinstance(growth, list) and growth:
        what = getattr(growth[0], "what", "")
        return what[:80]
    return "—"


async def _run_one(file_bytes: bytes, filename: str) -> object:
    from gander import pipeline

    final: object = None
    async for snap in pipeline.run(file_bytes, filename):
        final = snap
    if final is None:
        raise RuntimeError(f"pipeline.run yielded zero reports for {filename}")
    return final


def _has_top_level_failure(report: object) -> bool:
    """Return True if profile/score is StageFailure — those mean the pipeline
    could not produce a meaningful report, vs. a graceful-degradation failure
    in salary/growth/confidence which is expected behaviour for some inputs."""
    from gander.errors import StageFailure

    return isinstance(getattr(report, "profile", None), StageFailure) or isinstance(
        getattr(report, "score", None), StageFailure
    )


def _write_individual_report(
    output_dir: Path,
    cv_path: Path,
    report: object,
    latency_s: float,
) -> Path:
    from gander.report import render_body

    cost_usd = float(getattr(report, "total_cost_usd", 0.0) or 0.0)
    header = "\n".join(
        [
            f"# {cv_path.name}",
            "",
            f"- Format: `{cv_path.suffix.lstrip('.').upper()}`",
            f"- Latency: {latency_s:.1f}s",
            f"- Cost: ${cost_usd:.4f}",
            "",
            "---",
            "",
        ]
    )
    body = render_body(report)  # type: ignore[arg-type]
    out_path = output_dir / f"{cv_path.stem}.md"
    out_path.write_text(header + body, encoding="utf-8")
    return out_path


def _write_summary(
    output_dir: Path,
    rows: list[dict[str, object]],
    profile: str,
    total_cost_usd: float,
    latencies_s: list[float],
) -> Path:
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    avg_latency = sum(latencies_s) / len(latencies_s) if latencies_s else 0.0
    max_latency = max(latencies_s) if latencies_s else 0.0

    header_cols = (
        "| # | CV | Format | Score | Salary | Confidence "
        "| Top growth action | Cost (USD) | Latency (s) |"
    )
    header_lines = [
        f"# Eval corpus run — {timestamp}",
        "",
        f"Profile: `{profile}` (GANDER_MODEL_PROFILE)",
        "",
        header_cols,
        "|---|---|---|---|---|---|---|---|---|",
    ]
    table_lines = []
    for i, row in enumerate(rows, start=1):
        table_lines.append(
            f"| {i:02d} | {row['cv']} | {row['format']} | {row['score']} "
            f"| {row['salary']} | {row['confidence']} | {row['growth']} "
            f"| ${float(row['cost']):.4f} | {float(row['latency']):.1f} |"  # type: ignore[arg-type]
        )
    totals_lines = [
        "",
        f"**Totals**: {len(rows)} reports, ${total_cost_usd:.4f} total spend, "
        f"avg latency {avg_latency:.1f}s, max latency {max_latency:.1f}s.",
        "",
    ]

    summary_path = output_dir / "SUMMARY.md"
    summary_path.write_text("\n".join(header_lines + table_lines + totals_lines), encoding="utf-8")
    return summary_path


async def _run_corpus(fixture_dir: Path, output_dir: Path, profile: str) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = list(_iter_fixture_paths(fixture_dir))
    if not paths:
        print(f"No fixtures matched {fixture_dir}/*{SUPPORTED_SUFFIXES}", file=sys.stderr)
        return 2

    rows: list[dict[str, object]] = []
    latencies: list[float] = []
    total_cost = 0.0
    top_level_failures: list[str] = []

    for path in paths:
        print(f"→ {path.name}", flush=True)
        file_bytes = path.read_bytes()
        t0 = time.perf_counter()
        report = await _run_one(file_bytes, path.name)
        latency_s = time.perf_counter() - t0

        cost_usd = float(getattr(report, "total_cost_usd", 0.0) or 0.0)
        latencies.append(latency_s)
        total_cost += cost_usd

        _write_individual_report(output_dir, path, report, latency_s)
        rows.append(
            {
                "cv": path.stem,
                "format": path.suffix.lstrip(".").upper(),
                "score": _format_score(report),
                "salary": _format_salary(report),
                "confidence": _format_confidence(report),
                "growth": _top_growth_action(report),
                "cost": cost_usd,
                "latency": latency_s,
            }
        )

        if _has_top_level_failure(report):
            top_level_failures.append(path.name)

    summary_path = _write_summary(output_dir, rows, profile, total_cost, latencies)
    print(f"Wrote {summary_path.relative_to(REPO_ROOT)}")

    if top_level_failures:
        print(
            "Top-level failures (profile/score) in: " + ", ".join(top_level_failures),
            file=sys.stderr,
        )
        return 1
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=("local", "ci"),
        default=os.environ.get("GANDER_MODEL_PROFILE", "local"),
        help="GANDER_MODEL_PROFILE for this run (default: env or 'local').",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=FIXTURE_DIR,
        help="Directory of CV fixtures (default: tests/fixtures/cvs).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Where to write per-CV reports + SUMMARY.md (default: reports/).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    os.environ["GANDER_MODEL_PROFILE"] = args.profile
    return asyncio.run(
        _run_corpus(args.fixture_dir.resolve(), args.output_dir.resolve(), args.profile)
    )


if __name__ == "__main__":
    sys.exit(main())
