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


def _score_total(report: Report, label: str) -> int:
    if not isinstance(report.score, Score):
        raise RuntimeError(
            f"{label}: expected Score, got {type(report.score).__name__} — {report.score!r}"
        )
    return report.score.total


async def _main() -> int:
    with_report = await _final_report(WITH_PRESTIGE)
    redacted_report = await _final_report(REDACTED_PRESTIGE)

    with_total = _score_total(with_report, "with_prestige")
    redacted_total = _score_total(redacted_report, "redacted_prestige")
    delta = abs(with_total - redacted_total)

    print(f"Score with MFF UK / Charles University: {with_total}")
    print(f"Score with [REDACTED UNIVERSITY]:       {redacted_total}")
    print(f"Score delta with vs. without MFF UK:    {delta}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
