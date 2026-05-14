"""T20 — bias-smoke runner (no pytest).

Runs CV #9 in two versions (with and without the "MFF UK / Charles
University" prestige token) through the full pipeline and prints the score
delta. Used to fill in the README §Limitations number outside the test
infrastructure.

Usage:
    uv run python scripts/run_bias_smoke.py

Exit codes:
  0 — both sides scored; delta printed.
  2 — at least one side gracefully degraded (PRD §4.6); the failing stage's
      ``user_message`` is printed and the delta is unmeasurable for this run.

Provider exceptions (auth, network, rate-limit, 5xx) bubble as tracebacks.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from gander import pipeline
from gander.errors import StageFailure
from gander.schemas import Report, Score

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "cvs"

WITH_PRESTIGE = "09_research_phd_marek.pdf"
REDACTED_PRESTIGE = "09b_research_phd_marek_anon.pdf"

EXIT_OK = 0
EXIT_STAGE_FAILURE = 2


async def _final_report(fname: str) -> Report:
    path = FIXTURE_DIR / fname
    file_bytes = path.read_bytes()
    final: Report | None = None
    async for snap in pipeline.run(file_bytes, fname):
        final = snap
    if final is None:
        raise RuntimeError(f"pipeline.run yielded zero reports for {fname}")
    return final


def _describe(report: Report) -> str:
    if isinstance(report.score, Score):
        return f"{report.score.total}"
    if isinstance(report.score, StageFailure):
        return f"<degraded: {report.score.user_message}>"
    return f"<degraded: {type(report.score).__name__}>"


async def _main() -> int:
    with_report = await _final_report(WITH_PRESTIGE)
    redacted_report = await _final_report(REDACTED_PRESTIGE)

    print(f"Score with MFF UK / Charles University: {_describe(with_report)}")
    print(f"Score with [REDACTED UNIVERSITY]:       {_describe(redacted_report)}")

    if isinstance(with_report.score, Score) and isinstance(redacted_report.score, Score):
        delta = abs(with_report.score.total - redacted_report.score.total)
        print(f"Score delta with vs. without MFF UK:    {delta}")
        return EXIT_OK

    print("Score delta with vs. without MFF UK:    <unmeasurable — graceful degradation>")
    for label, score in (("with_prestige", with_report.score), ("redacted", redacted_report.score)):
        if isinstance(score, StageFailure):
            print(f"  {label}: score stage failed — {score.user_message}")
    return EXIT_STAGE_FAILURE


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the school-prestige bias smoke (CV #9 with vs. without "
            "MFF UK / Charles University) and print the score delta."
        )
    )
    return parser.parse_args()


if __name__ == "__main__":
    _parse_args()
    sys.exit(asyncio.run(_main()))
