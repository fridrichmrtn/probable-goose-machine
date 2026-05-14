"""T30 Phase 1 — renderer contract test: stage failures degrade gracefully.

PRD §4.6 promises "rest-of-report-renders" when a single downstream stage
fails. `tests/test_render.py` covers each-stage-fails-alone permutations;
this file owns the multi-failure case (every non-profile stage fails) and
asserts the renderer still emits the other sections' callouts rather than
short-circuiting on the first failure.
"""

from __future__ import annotations

import pytest

from gander.errors import StageFailure
from gander.report import render_body
from gander.schemas import (
    Anchor,
    Profile,
    ProfileItem,
    Report,
    StageName,
    StageStatus,
)


def _profile() -> Profile:
    item = ProfileItem(text="python", anchor=Anchor(quote="Python"))
    return Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="engineer",
        detected_location=None,
        detected_years_experience=5,
    )


def _failed_statuses() -> dict[StageName, StageStatus]:
    return {
        "profile": "done",
        "score": "failed",
        "salary": "failed",
        "confidence": "failed",
        "growth": "failed",
    }


@pytest.mark.fast
def test_stage_failure_does_not_block_other_stages() -> None:
    """Every downstream stage fails with a distinct message; renderer surfaces every callout.

    Without the rest-of-report-renders promise from PRD §4.6, a renderer that
    short-circuits on the first StageFailure would emit only one of these
    four messages. The test asserts all four reach the body.
    """
    report = Report(
        profile=_profile(),
        score=StageFailure(stage="score", user_message="Score stage hit a wall"),
        salary=StageFailure(stage="salary", user_message="Insufficient market data"),
        confidence=StageFailure(stage="confidence", user_message="Confidence judge offline"),
        growth=StageFailure(stage="growth", user_message="Plan generation failed"),
        statuses=_failed_statuses(),
        raw_cv_text="raw text",
    )
    out = render_body(report)

    # All four sections render their failure callouts.
    assert "## Score" in out
    assert "Score stage hit a wall" in out

    assert "## Salary" in out
    assert "Insufficient market data" in out

    assert "## Confidence" in out
    assert "Confidence judge offline" in out

    assert "## Plan" in out
    assert "Plan generation failed" in out

    # Footer still renders — it always does for a populated profile.
    assert "How is this scored?" in out
