"""T20 — bias-smoke runner (no pytest).

Runs CV #9 in two versions (with and without the "MFF UK / Charles
University" prestige token) through the full pipeline and prints the score
delta. Used to fill in the README §Limitations number outside the test
infrastructure.

Usage:
    uv run python scripts/run_bias_smoke.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from gander import pipeline
from gander.schemas import Report, Score

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "cvs"

WITH_PRESTIGE = "09_research_phd_marek.pdf"
REDACTED_PRESTIGE = "09b_research_phd_marek_anon.pdf"


async def _final_report(fname: str) -> Report:
    path = FIXTURE_DIR / fname
    file_bytes = path.read_bytes()
    final: Report | None = None
    async for snap in pipeline.run(file_bytes, fname):
        final = snap
    if final is None:
        raise RuntimeError(f"pipeline.run yielded zero reports for {fname}")
    return final


def _describe(report: Report, label: str) -> str:
    if isinstance(report.score, Score):
        return f"{report.score.total}"
    return f"<degraded: {type(report.score).__name__}>"


async def _main() -> int:
    with_report = await _final_report(WITH_PRESTIGE)
    redacted_report = await _final_report(REDACTED_PRESTIGE)

    with_desc = _describe(with_report, "with_prestige")
    redacted_desc = _describe(redacted_report, "redacted_prestige")

    print(f"Score with MFF UK / Charles University: {with_desc}")
    print(f"Score with [REDACTED UNIVERSITY]:       {redacted_desc}")

    if isinstance(with_report.score, Score) and isinstance(redacted_report.score, Score):
        delta = abs(with_report.score.total - redacted_report.score.total)
        print(f"Score delta with vs. without MFF UK:    {delta}")
        return 0

    print("Score delta with vs. without MFF UK:    <unmeasurable — graceful degradation>")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
