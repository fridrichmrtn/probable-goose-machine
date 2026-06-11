"""T21 — live corpus runner.

The user's manual gauging surface. Runs every fixture under
`tests/fixtures/cvs/*.{pdf,docx}` through the live L1→L5 pipeline,
writes per-CV markdown reports + a SUMMARY.md table.

Exit codes:
    0 = all fixtures produced a meaningful report.
    1 = at least one fixture had a top-level pipeline failure
        (profile or score returned StageFailure — the report
        cannot be judged meaningfully without them), OR the growth
        stage failed outright on more than GROWTH_FAILURE_RATE_MAX
        of the corpus (degraded partial lists do not count as failed).
    2 = setup error: fixture dir missing, no fixtures matched,
        provider API key missing, provider upload not explicitly allowed,
        or an unresolved Git LFS pointer was found.

Usage:
    uv run python scripts/eval_corpus.py --allow-provider-upload
    uv run python scripts/eval_corpus.py --profile ci --allow-provider-upload
    uv run python scripts/eval_corpus.py --output-dir reports/ci-run --allow-provider-upload
    GANDER_LLM_PROVIDER=openrouter OPENROUTER_API_KEY=... \
        uv run python scripts/eval_corpus.py --allow-provider-upload

The `--profile` flag labels the generated SUMMARY.md and sets
`GANDER_MODEL_PROFILE` for compatibility with older runbooks. Current model
selection is OpenRouter-only and controlled by `OPENROUTER_MODEL_*` env vars
or the defaults in `gander.llm`.

Execution is serial — DDG queries are rate-sensitive and many parallel
pipelines from one IP would draw throttles.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "cvs"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "reports"
SUPPORTED_SUFFIXES = (".pdf", ".docx")
PROFILE_CHOICES = ("local", "ci")
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/"
GROWTH_FAILURE_RATE_MAX = 0.25
_GROWTH_EVENT_NAMES = (
    "growth_action_dropped",
    "growth_retry",
    "growth_degraded",
    "growth_attempt_error",
    "stage_failure",
)
PROVIDER_KEYS = {
    "openrouter": "OPENROUTER_API_KEY",
}
LOGICAL_PROVIDER_ENV_KEYS = (
    "GANDER_LLM_PROVIDER_REASONING",
    "GANDER_LLM_PROVIDER_CHEAP",
    "GANDER_LLM_PROVIDER_EXTRACT",
    "GANDER_LLM_PROVIDER_VISION",
)


def _iter_fixture_paths(fixture_dir: Path) -> Iterable[Path]:
    for path in sorted(fixture_dir.iterdir()):
        if path.suffix.lower() in SUPPORTED_SUFFIXES:
            yield path


def _display_path(path: Path) -> str:
    """Repo-relative if possible, otherwise absolute. `--output-dir` may point
    outside the repo, in which case `relative_to(REPO_ROOT)` would raise."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _provider_key_error() -> str | None:
    provider_sources = {
        "GANDER_LLM_PROVIDER": os.environ.get("GANDER_LLM_PROVIDER", "openrouter"),
    }
    for env_key in LOGICAL_PROVIDER_ENV_KEYS:
        raw = os.environ.get(env_key)
        if raw is not None:
            provider_sources[env_key] = raw

    missing: dict[str, list[str]] = {}
    for env_key, raw_provider in provider_sources.items():
        provider = raw_provider.strip().lower()
        api_key_env = PROVIDER_KEYS.get(provider)
        if api_key_env is None:
            expected = " or ".join(f"{name!r}" for name in PROVIDER_KEYS)
            return f"Unknown {env_key}={raw_provider!r}; expected {expected}."
        if not os.environ.get(api_key_env):
            missing.setdefault(api_key_env, []).append(f"{env_key}={provider}")

    if missing:
        details = "; ".join(
            f"{api_key_env} ({', '.join(sources)})"
            for api_key_env, sources in sorted(missing.items())
        )
        return (
            f"Missing provider credential(s): {details}. "
            "Set the env var(s) and retry; .env is not auto-loaded by this script."
        )
    return None


def _provider_upload_consent_error(allow_provider_upload: bool) -> str | None:
    if allow_provider_upload:
        return None
    return (
        "Live corpus evaluation sends committed fixture CV content to the "
        "configured LLM provider. Pass --allow-provider-upload only after "
        "confirming this is acceptable for the current run."
    )


def _cell(value: object) -> str:
    """Escape an LLM-produced string for a markdown table cell. Newlines
    break the row; literal `|` breaks the column boundary."""
    text = str(value)
    return text.replace("\n", " ").replace("\r", " ").replace("|", r"\|")


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


@dataclass(frozen=True)
class GrowthStats:
    # "ok" (>=3 actions) | "degraded" (1-2) | "skipped" (upstream cascade,
    # growth never ran) | "failed" (genuine growth StageFailure)
    status: str
    drops_by_reason: dict[str, int]
    retries: int
    attempt_errors: dict[str, int]
    failure_reason: str | None = None


async def _run_one(file_bytes: bytes, filename: str) -> tuple[object, list[dict[str, object]]]:
    from gander import obs, pipeline

    growth_events: list[dict[str, object]] = []

    def _on_event(rec: dict[str, object]) -> None:
        if rec.get("stage") == "growth" and rec.get("event") in _GROWTH_EVENT_NAMES:
            growth_events.append(rec)

    final: object = None
    with obs.subscribe(_on_event):
        async for snap in pipeline.run(file_bytes, filename):
            final = snap
    if final is None:
        raise RuntimeError(f"pipeline.run yielded zero reports for {filename}")
    return final, growth_events


# Prefix shared by pipeline._CASCADE_PROFILE_FAILED["growth"] and the
# _GROWTH_NO_BASELINE/_GROWTH_NEEDS_* constants — a StageFailure carrying it
# means growth never ran, vs. the §4.6 copy a genuine growth failure carries.
_GROWTH_CASCADE_PREFIX = "Cannot generate growth plan without"


def _summarize_growth(report: object, growth_events: list[dict[str, object]]) -> GrowthStats:
    growth = getattr(report, "growth", None)
    if isinstance(growth, list) and len(growth) >= 3:
        status = "ok"
    elif isinstance(growth, list) and growth:
        status = "degraded"
    elif str(getattr(growth, "user_message", "")).startswith(_GROWTH_CASCADE_PREFIX):
        status = "skipped"
    else:
        status = "failed"

    drops_by_reason: dict[str, int] = {}
    attempt_errors: dict[str, int] = {}
    retries = 0
    failure_reason: str | None = None
    for rec in growth_events:
        event = rec.get("event")
        if event == "growth_action_dropped":
            reason = str(rec.get("reason", "unknown"))
            drops_by_reason[reason] = drops_by_reason.get(reason, 0) + 1
        elif event == "growth_retry":
            retries += 1
        elif event == "growth_attempt_error":
            reason = str(rec.get("reason", "unknown"))
            attempt_errors[reason] = attempt_errors.get(reason, 0) + 1
        elif event == "stage_failure":
            failure_reason = str(rec.get("reason", "unknown"))
    return GrowthStats(
        status=status,
        drops_by_reason=drops_by_reason,
        retries=retries,
        attempt_errors=attempt_errors,
        failure_reason=failure_reason,
    )


def _format_growth_drops(stats: GrowthStats) -> str:
    parts = [f"{reason}:{count}" for reason, count in sorted(stats.drops_by_reason.items())]
    parts.extend(
        f"attempt_error[{reason}]:{count}" for reason, count in sorted(stats.attempt_errors.items())
    )
    if stats.retries:
        parts.append(f"retries:{stats.retries}")
    if stats.status == "failed" and stats.failure_reason is not None:
        parts.append(f"failure:{stats.failure_reason}")
    return ", ".join(parts) if parts else "-"


def _growth_failure_rate_exceeded(statuses: list[str]) -> bool:
    # "skipped" rows never ran growth (upstream cascade) — exclude them from
    # both sides so a salary shortfall cannot fail CI blaming the growth stage.
    ran = [s for s in statuses if s != "skipped"]
    if not ran:
        return False
    failed = sum(1 for s in ran if s == "failed")
    return failed / len(ran) > GROWTH_FAILURE_RATE_MAX


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
        "| Top growth action | Growth status | Growth drops | Cost (USD) | Latency (s) |"
    )
    header_lines = [
        f"# Eval corpus run — {timestamp}",
        "",
        f"Profile: `{profile}` (GANDER_MODEL_PROFILE)",
        "",
        header_cols,
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    table_lines = []
    for i, row in enumerate(rows, start=1):
        table_lines.append(
            f"| {i:02d} | {_cell(row['cv'])} | {_cell(row['format'])} "
            f"| {_cell(row['score'])} | {_cell(row['salary'])} "
            f"| {_cell(row['confidence'])} | {_cell(row['growth'])} "
            f"| {_cell(row['growth_status'])} | {_cell(row['growth_drops'])} "
            f"| ${float(row['cost']):.4f} | {float(row['latency']):.1f} |"  # type: ignore[arg-type]
        )
    statuses = [str(row["growth_status"]) for row in rows]
    growth_counts = {s: statuses.count(s) for s in ("ok", "degraded", "skipped", "failed")}
    totals_lines = [
        "",
        f"**Totals**: {len(rows)} reports, ${total_cost_usd:.4f} total spend, "
        f"avg latency {avg_latency:.1f}s, max latency {max_latency:.1f}s.",
        "",
        f"**Growth**: {growth_counts['ok']} ok, {growth_counts['degraded']} degraded, "
        f"{growth_counts['skipped']} skipped, {growth_counts['failed']} failed "
        f"(failure threshold {GROWTH_FAILURE_RATE_MAX:.0%} of non-skipped).",
        "",
    ]

    summary_path = output_dir / "SUMMARY.md"
    summary_path.write_text("\n".join(header_lines + table_lines + totals_lines), encoding="utf-8")
    return summary_path


async def _run_corpus(
    fixture_dir: Path,
    output_dir: Path,
    profile: str,
    *,
    allow_provider_upload: bool,
) -> int:
    consent_error = _provider_upload_consent_error(allow_provider_upload)
    if consent_error is not None:
        print(consent_error, file=sys.stderr)
        return 2

    provider_error = _provider_key_error()
    if provider_error is not None:
        print(provider_error, file=sys.stderr)
        return 2

    if not fixture_dir.exists() or not fixture_dir.is_dir():
        print(
            f"Fixture directory not found or not a directory: {fixture_dir}",
            file=sys.stderr,
        )
        return 2
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
        if file_bytes.startswith(LFS_POINTER_PREFIX):
            print(
                f"{path.name} is an unresolved Git LFS pointer. "
                "Run `git lfs pull` (CI uses actions/checkout@v4 with lfs: true).",
                file=sys.stderr,
            )
            return 2
        t0 = time.perf_counter()
        report, growth_events = await _run_one(file_bytes, path.name)
        latency_s = time.perf_counter() - t0

        cost_usd = float(getattr(report, "total_cost_usd", 0.0) or 0.0)
        latencies.append(latency_s)
        total_cost += cost_usd

        growth_stats = _summarize_growth(report, growth_events)
        _write_individual_report(output_dir, path, report, latency_s)
        rows.append(
            {
                "cv": path.stem,
                "format": path.suffix.lstrip(".").upper(),
                "score": _format_score(report),
                "salary": _format_salary(report),
                "confidence": _format_confidence(report),
                "growth": _top_growth_action(report),
                "growth_status": growth_stats.status,
                "growth_drops": _format_growth_drops(growth_stats),
                "cost": cost_usd,
                "latency": latency_s,
            }
        )

        if _has_top_level_failure(report):
            top_level_failures.append(path.name)

    summary_path = _write_summary(output_dir, rows, profile, total_cost, latencies)
    print(f"Wrote {_display_path(summary_path)}")

    if top_level_failures:
        print(
            "Top-level failures (profile/score) in: " + ", ".join(top_level_failures),
            file=sys.stderr,
        )
        return 1

    statuses = [str(row["growth_status"]) for row in rows]
    if _growth_failure_rate_exceeded(statuses):
        ran = [s for s in statuses if s != "skipped"]
        failed = sum(1 for s in ran if s == "failed")
        print(
            f"Growth stage failed on {failed}/{len(ran)} fixtures that ran it, "
            f"above the {GROWTH_FAILURE_RATE_MAX:.0%} threshold.",
            file=sys.stderr,
        )
        return 1
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    env_profile = os.environ.get("GANDER_MODEL_PROFILE", "local")
    if env_profile not in PROFILE_CHOICES:
        raise SystemExit(
            f"GANDER_MODEL_PROFILE={env_profile!r} is not one of {PROFILE_CHOICES}. "
            "Unset it or pass --profile explicitly."
        )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES,
        default=env_profile,
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
    parser.add_argument(
        "--allow-provider-upload",
        action="store_true",
        help=(
            "Confirm that sending committed fixture CV content to the configured "
            "LLM provider is acceptable for this run."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    os.environ["GANDER_MODEL_PROFILE"] = args.profile
    return asyncio.run(
        _run_corpus(
            args.fixture_dir.resolve(),
            args.output_dir.resolve(),
            args.profile,
            allow_provider_upload=args.allow_provider_upload,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
