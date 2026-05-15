"""Opt-in arbitrary-CV live smoke.

Set ``GANDER_SMOKE_CV=/path/to/cv.pdf`` or ``.docx`` to exercise the exact
reviewer-supplied-CV path without committing private files to the repository.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from gander import pipeline
from gander.errors import StageFailure
from gander.schemas import Confidence, Profile, Report, SalaryEstimate, Score


def _missing_provider_key() -> bool:
    provider = os.environ.get("GANDER_LLM_PROVIDER", "openrouter")
    if provider == "openrouter":
        return not bool(os.environ.get("OPENROUTER_API_KEY"))
    return False


pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.xdist_group("arbitrary-cv"),
    pytest.mark.skipif(
        not os.environ.get("GANDER_SMOKE_CV"),
        reason="set GANDER_SMOKE_CV=/path/to/reviewer-cv.pdf or .docx",
    ),
    pytest.mark.skipif(
        _missing_provider_key(),
        reason="arbitrary CV smoke requires OPENROUTER_API_KEY",
    ),
]


async def _run_to_completion(path: Path) -> Report:
    final: Report | None = None
    async for snap in pipeline.run(path.read_bytes(), path.name):
        final = snap
    assert final is not None, f"pipeline.run yielded zero reports for {path.name}"
    return final


def _assert_terminal_block(block: object, expected_type: type[object], label: str) -> None:
    assert block is not None, f"final yield left {label} pending"
    if isinstance(block, StageFailure):
        assert block.user_message.strip(), f"{label} failure lacks reviewer-facing copy"
        assert "Traceback" not in block.user_message
        return
    assert isinstance(block, expected_type), (
        f"{label}: expected {expected_type.__name__} or StageFailure, got {type(block).__name__}"
    )


async def test_arbitrary_cv_smoke_from_env_path() -> None:
    raw_path = os.environ["GANDER_SMOKE_CV"]
    path = Path(raw_path).expanduser()
    assert path.exists(), f"GANDER_SMOKE_CV does not exist: {path}"
    assert path.suffix.lower() in {".pdf", ".docx"}, (
        f"GANDER_SMOKE_CV must point to a PDF or DOCX, got {path.suffix!r}"
    )

    final = await _run_to_completion(path)

    assert set(final.statuses) == {"profile", "score", "salary", "confidence", "growth"}
    assert all(status != "running" for status in final.statuses.values())

    _assert_terminal_block(final.profile, Profile, "profile")
    _assert_terminal_block(final.score, Score, "score")
    _assert_terminal_block(final.salary, SalaryEstimate, "salary")
    _assert_terminal_block(final.confidence, Confidence, "confidence")
    _assert_terminal_block(final.growth, list, "growth")
