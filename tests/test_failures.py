"""T18 — pipeline failure-path tests (PRD §4.6 graceful degradation).

Each test drives `pipeline.run` through one realistic failure mode and asserts
the final `Report` carries the right user-facing message + status without
escaping a traceback. Where possible the test uses the real code path (random
bytes through real `extract_text`, reportlab-synthesized scanned PDF through
real ingest) so the seam against the actual library matters. The DDG and
extract-validation cases mock at the seam closest to the boundary (`DDGS`,
`LLMClient.complete_json`) so the real stage modules — including their
`stage_boundary` and cascade messages — run end-to-end.

`tests/test_pipeline_fast.py` already covers stage-worker-level monkeypatching
of every failure mode; this file deliberately drives one level deeper so the
DDG/LLM seams stay protected even as the stage workers evolve.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from gander import pipeline
from gander.confidence import Confidence
from gander.errors import StageFailure
from gander.ingest import CORRUPT_MSG, LOW_EVIDENCE_MSG, SCANNED_MSG, UNKNOWN_MSG
from gander.llm import LLMClient
from gander.schemas import (
    Anchor,
    Component,
    GrowthAction,
    Profile,
    ProfileItem,
    RedactedCV,
    Report,
    Score,
)


@pytest.fixture(autouse=True)
def _deterministic_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GANDER_INGEST_MODE", "text")


# ---------- profile / score / growth canned values ---------------------------


def _profile() -> Profile:
    item = ProfileItem(text="python", anchor=Anchor(quote="Python"))
    return Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="Senior Data Scientist",
        detected_location="Prague",
        detected_years_experience=8,
    )


def _score() -> Score:
    def _c(name: str, s: int) -> Component:
        return Component(
            name=name,  # type: ignore[arg-type]
            score_0_100=s,
            justification="ok",
            anchor=Anchor(quote="q", section="Work Experience"),
        )

    return Score(
        components=[
            _c("skills", 80),
            _c("experience", 70),
            _c("education", 60),
            _c("soft_signals", 90),
        ]
    )


def _growth() -> list[GrowthAction]:
    return [
        GrowthAction(
            what="ship a Rust CLI",
            time_horizon_months=6,
            mechanism="weekend project",
            setting="capability_artifact",
            anchor=Anchor(quote="C++ background"),
        )
    ]


def _redacted(text: str = "redacted") -> RedactedCV:
    return RedactedCV(text=text, audit_log=[])


# ---------- helpers ----------------------------------------------------------


async def _collect(it: Any) -> list[Report]:
    return [r async for r in it]


def _read_cv_fixture_bytes(name: str) -> bytes:
    fixture = Path(__file__).resolve().parent / "fixtures" / "cvs" / name
    file_bytes = fixture.read_bytes()
    if file_bytes.startswith(b"version https://git-lfs.github.com/"):
        pytest.fail(f"{fixture.name} is an unresolved LFS pointer. Run `git lfs pull`.")
    return file_bytes


def _patch_non_salary_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch every stage worker EXCEPT estimate_salary, so the real salary
    module — including its DDGS seam — runs end-to-end while the rest of the
    pipeline stays offline.
    """

    async def _ingest_ok(_bytes: bytes, _name: str) -> str:
        return "raw cv text"

    def _redact_ok(text: str) -> RedactedCV:
        return _redacted(text=text)

    async def _extract_ok(_r: RedactedCV) -> Profile:
        return _profile()

    async def _score_ok(_r: RedactedCV, _p: Profile) -> Score:
        return _score()

    async def _growth_should_not_run(*_a: Any, **_kw: Any) -> list[GrowthAction]:
        # Decision A: growth requires both score AND salary. When salary fails,
        # pipeline cascades growth without calling plan_growth — this stub is
        # safety-net, not expected path.
        return _growth()

    async def _judge_should_not_run(*_a: Any, **_kw: Any) -> Confidence:
        # Salary-failure short-circuits confidence to Low without an LLM call.
        # If this gets called the cascade contract regressed.
        raise AssertionError("judge() must not run when salary failed")

    monkeypatch.setattr(pipeline, "extract_text", _ingest_ok)
    monkeypatch.setattr(pipeline, "redact", _redact_ok)
    monkeypatch.setattr(pipeline, "extract_profile", _extract_ok)
    monkeypatch.setattr(pipeline, "score_profile", _score_ok)
    monkeypatch.setattr(pipeline, "plan_growth", _growth_should_not_run)
    monkeypatch.setattr(pipeline, "judge", _judge_should_not_run)


def _patch_ddgs(monkeypatch: pytest.MonkeyPatch, text_mock: MagicMock) -> None:
    """Replace `gander.salary.DDGS` with a context-manager-shaped mock."""
    fake_instance = MagicMock()
    fake_instance.__enter__.return_value.text = text_mock
    fake_instance.__exit__.return_value = False
    monkeypatch.setattr("gander.salary.DDGS", lambda: fake_instance)


# ---------- ingest-layer failures (real code path, no mocking) ---------------


@pytest.mark.fast
async def test_corrupt_pdf_full_pipeline_emits_corrupt_message() -> None:
    """Random bytes with a `.pdf` suffix → ingest fails, profile carries
    CORRUPT_MSG, every downstream stage cascades, no exception escapes."""
    garbage = b"\x00\x01not a pdf\xff\xfe" * 16
    reports = await _collect(pipeline.run(garbage, "broken.pdf"))
    final = reports[-1]

    assert isinstance(final.profile, StageFailure)
    assert final.profile.user_message == CORRUPT_MSG
    assert final.statuses["profile"] == "failed"
    for stage in ("score", "salary", "confidence", "growth"):
        assert final.statuses[stage] == "failed"  # type: ignore[index]
        assert isinstance(getattr(final, stage), StageFailure)


@pytest.mark.fast
async def test_image_only_pdf_full_pipeline_emits_scanned_message() -> None:
    """Reportlab-synthesized image-only PDF → ingest fails with SCANNED_MSG.

    Pre-condition check mirrors `tests/test_ingest.py::test_scanned_pdf_*`
    so a future reportlab change that silently produces extractable text
    fails loudly instead of bypassing the detector.
    """
    reportlab_canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    buf = BytesIO()
    c = reportlab_canvas.Canvas(buf)
    c.setFillColorRGB(0.2, 0.2, 0.2)
    c.rect(50, 50, 200, 200, fill=1, stroke=0)
    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()

    reports = await _collect(pipeline.run(pdf_bytes, "scanned.pdf"))
    final = reports[-1]

    assert isinstance(final.profile, StageFailure)
    assert final.profile.user_message == SCANNED_MSG
    for stage in ("score", "salary", "confidence", "growth"):
        assert final.statuses[stage] == "failed"  # type: ignore[index]


@pytest.mark.fast
async def test_unknown_extension_full_pipeline_emits_unknown_message() -> None:
    """Any non-pdf/docx suffix → UNKNOWN_MSG before any LLM call."""
    reports = await _collect(pipeline.run(b"plain text content", "notes.txt"))
    final = reports[-1]

    assert isinstance(final.profile, StageFailure)
    assert final.profile.user_message == UNKNOWN_MSG
    for stage in ("score", "salary", "confidence", "growth"):
        assert final.statuses[stage] == "failed"  # type: ignore[index]


# ---------- salary-layer failures (real salary code, mocked DDGS) ------------


@pytest.mark.fast
async def test_ddg_returns_empty_short_circuits_salary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DDG returns no results → real salary code returns StageFailure
    ("Insufficient market data"); confidence short-circuits to a Low
    Confidence object without ever calling judge().
    """
    _patch_non_salary_stages(monkeypatch)
    _patch_ddgs(monkeypatch, MagicMock(return_value=[]))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    reports = await _collect(pipeline.run(b"x", "cv.pdf"))
    final = reports[-1]

    assert isinstance(final.salary, StageFailure)
    assert "Insufficient market data" in final.salary.user_message
    assert final.statuses["salary"] == "failed"

    # Confidence short-circuits to a Low *Confidence object* (not a
    # StageFailure) per the pipeline contract — the rationale points back to
    # the salary block so the reviewer sees the chain.
    assert isinstance(final.confidence, Confidence)
    assert final.confidence.tier == "Low"
    assert "salary" in final.confidence.rationale.lower()

    # Growth cascades because Decision A requires both score AND salary.
    assert isinstance(final.growth, StageFailure)


@pytest.mark.fast
async def test_ddg_raises_connection_error_short_circuits_salary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DDG raises a ConnectionError-class exception on every attempt → salary
    returns the same canonical StageFailure as the empty-results path; the
    transport detail stays in `debug_detail`, not in the user message.
    """
    _patch_non_salary_stages(monkeypatch)
    _patch_ddgs(monkeypatch, MagicMock(side_effect=ConnectionError("ddg unreachable")))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    reports = await _collect(pipeline.run(b"x", "cv.pdf"))
    final = reports[-1]

    assert isinstance(final.salary, StageFailure)
    assert "Insufficient market data" in final.salary.user_message
    # The transport exception name belongs in debug_detail, not in user copy.
    assert "ddg unreachable" not in final.salary.user_message
    assert final.salary.debug_detail is not None
    assert "ConnectionError" in final.salary.debug_detail

    assert isinstance(final.confidence, Confidence)
    assert final.confidence.tier == "Low"


# ---------- extract-layer failure (real extract, mocked LLM seam) ------------


@pytest.mark.fast
async def test_extract_validation_error_cascades_to_every_downstream_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLMClient.complete_json raises (simulating retry-exhausted parse
    failure) → real extract.extract_profile catches it via stage_boundary and
    returns a StageFailure; pipeline cascades the "without profile" message
    to score / salary / confidence / growth without invoking any of them.
    """

    # Use a real-ish parser-style error after `max_retries=1` is exhausted.
    # `complete_json` catches ValidationError/JSONDecodeError internally and
    # re-raises after the retry budget — we simulate the "after retry" state
    # by raising directly, which is what callers see.
    async def _always_raise(self: LLMClient, **_kw: Any) -> Any:
        raise RuntimeError("invalid JSON after retries")

    monkeypatch.setattr(LLMClient, "complete_json", _always_raise)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    # Use a real CV docx so ingest succeeds and we actually reach extract.
    fixture_name = "01_junior_da_novotny.docx"
    file_bytes = _read_cv_fixture_bytes(fixture_name)
    reports = await _collect(pipeline.run(file_bytes, fixture_name))
    final = reports[-1]

    assert isinstance(final.profile, StageFailure)
    assert final.profile.stage == "extract"  # stage_boundary uses its own tag
    assert final.statuses["profile"] == "failed"

    for stage in ("score", "salary", "confidence", "growth"):
        block = getattr(final, stage)
        assert isinstance(block, StageFailure), f"{stage} should cascade as StageFailure"
        assert "without" in block.user_message.lower(), (
            f"{stage} cascade message should explain the upstream gap, got {block.user_message!r}"
        )
        assert final.statuses[stage] == "failed"  # type: ignore[index]


# ---------- low-evidence gate (T38) — non-CV upload cascades --------------


@pytest.mark.fast
async def test_low_evidence_profile_cascades_to_every_downstream_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T38: non-CV upload (or CV whose anchors all drop) → extract returns
    StageFailure(LOW_EVIDENCE_MSG); pipeline cascades to score/salary/
    confidence/growth without invoking them; no stage left in `running`."""

    # LLM "extracts" a profile from a non-CV — anchors won't substring-verify
    # against the real CV docx, so post-verification composite score = 0.
    hallucinated = Profile(
        skills=[
            ProfileItem(
                text="Python",
                anchor=Anchor(quote="Wrote scalable Python pipelines for niche ETL workloads"),
            ),
        ],
        experience=[
            ProfileItem(
                text="Engineer",
                anchor=Anchor(quote="Led a small team to ship quarterly product milestones."),
            ),
        ],
        education=[],
        soft_signals=[],
        detected_role="Senior Engineer",
        detected_location=None,
        detected_years_experience=5,
    )

    async def _fake_complete_json(self: LLMClient, **_kw: Any) -> Any:
        return hallucinated

    monkeypatch.setattr(LLMClient, "complete_json", _fake_complete_json)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    # Real docx so ingest+redact actually run; the anchors above won't appear
    # in the redacted text, so drop_unverified strips every item.
    fixture_name = "01_junior_da_novotny.docx"
    file_bytes = _read_cv_fixture_bytes(fixture_name)
    reports = await _collect(pipeline.run(file_bytes, fixture_name))
    final = reports[-1]

    assert isinstance(final.profile, StageFailure)
    assert final.profile.user_message == LOW_EVIDENCE_MSG
    assert final.statuses["profile"] == "failed"

    for stage in ("score", "salary", "confidence", "growth"):
        block = getattr(final, stage)
        assert isinstance(block, StageFailure), f"{stage} should cascade as StageFailure"
        assert final.statuses[stage] == "failed"  # type: ignore[index]

    assert all(v != "running" for v in final.statuses.values())


# ---------- liveness assertion (every test in this file shares it) -----------


@pytest.mark.fast
async def test_no_failure_path_leaves_running_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity meta-test: across a representative spread of failure modes, the
    final yield never leaves a stage in `running`. Pairs with
    `tests/test_partial_failure_streaming.py` which makes the same assertion
    on every intermediate yield."""
    # Spot-check with the corrupt-PDF and DDG-empty paths (covered above);
    # if either changes its final-status shape this guards against the
    # silent regression where statuses["X"] = "running" leaks out.
    corrupt_final = (await _collect(pipeline.run(b"\x00bad", "x.pdf")))[-1]
    assert all(v != "running" for v in corrupt_final.statuses.values())

    _patch_non_salary_stages(monkeypatch)
    _patch_ddgs(monkeypatch, MagicMock(return_value=[]))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")
    ddg_final = (await _collect(pipeline.run(b"x", "cv.pdf")))[-1]
    assert all(v != "running" for v in ddg_final.statuses.values())
