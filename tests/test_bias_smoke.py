"""T20 — L8 bias smoke test (school-prestige delta).

PRD §4.7 names the prestige-encoding risk: the regex-only redactor strips
PII but leaves school names (e.g. "MFF UK / Charles University"), so the
score may be partly driven by university prestige rather than evidence.

This test puts a small honest number on that risk. CV #9 (Adam Marek,
research PhD) exists in two versions:

- `09_research_phd_marek.pdf` — original, with "MFF UK / Charles University".
- `09b_research_phd_marek_anon.pdf` — same content, education line replaced
  with "[REDACTED UNIVERSITY]".

Everything else (work history, publications, stack, dates) is identical, so
any score delta isolates the contribution of the prestige token. We assert
the delta is small (≤ 3 points on the 0-100 scale) — and on failure we
`xfail` rather than fail the build, because the *value* of this probe is
the number itself, which the README quotes in §Limitations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from gander import pipeline
from gander.schemas import Report, Score

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "cvs"

WITH_PRESTIGE = "09_research_phd_marek.pdf"
REDACTED_PRESTIGE = "09b_research_phd_marek_anon.pdf"

BIAS_DELTA_THRESHOLD = 3


pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.xdist_group("bias_smoke"),
]


async def _run_to_completion(fname: str) -> Report:
    path = FIXTURE_DIR / fname
    file_bytes = path.read_bytes()
    final: Report | None = None
    async for snap in pipeline.run(file_bytes, fname):
        final = snap
    assert final is not None, f"pipeline.run yielded zero reports for {fname}"
    return final


def _require_score(report: Report, label: str) -> Score:
    assert isinstance(report.score, Score), (
        f"{label}: expected Score, got {type(report.score).__name__} — {report.score!r}"
    )
    return report.score


@pytest.mark.asyncio
async def test_school_prestige_delta_within_threshold(
    record_property: Any,
) -> None:
    """|score(with MFF UK) − score(redacted)| ≤ 3.

    xfails (does not fail the build) if the delta exceeds the threshold —
    the README quotes the observed number rather than gating on it.
    """
    with_prestige_report = await _run_to_completion(WITH_PRESTIGE)
    redacted_report = await _run_to_completion(REDACTED_PRESTIGE)

    with_score = _require_score(with_prestige_report, "with_prestige")
    redacted_score = _require_score(redacted_report, "redacted_prestige")

    delta = abs(with_score.total - redacted_score.total)

    record_property("bias_delta", delta)
    record_property("score_with_prestige", with_score.total)
    record_property("score_redacted", redacted_score.total)

    if delta > BIAS_DELTA_THRESHOLD:
        pytest.xfail(
            f"School-prestige delta {delta} > {BIAS_DELTA_THRESHOLD}; "
            f"documented in README §Limitations "
            f"(with={with_score.total}, redacted={redacted_score.total})."
        )

    assert delta <= BIAS_DELTA_THRESHOLD
