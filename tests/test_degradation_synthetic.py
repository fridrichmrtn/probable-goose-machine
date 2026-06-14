"""P1.4 — graceful degradation across out-of-corpus CV shapes (PRD §4.6).

The committed fixture corpus is entirely CZ-context data/ML roles. A reviewer
will upload CVs the corpus never represented: a non-technical role, a
career-changer, a non-CZ candidate. These tests assert the pipeline *degrades
gracefully* on those shapes — a clean per-block failure message and a settled
final report — rather than asserting any happy-path score, which would require
live model judgment we cannot run offline.

Mechanism mirrors `tests/test_failures.py`: real ingest + redact + verify run
on a `.docx` synthesized from each fixture's text; only the LLM seam
(`LLMClient.complete_json`) is mocked. The model is made to return a plausible
profile whose anchors are paraphrased rather than verbatim — exactly what an
out-of-distribution CV provokes — so `drop_unverified` strips every item and
the low-evidence gate fires. That is the realistic offline degradation: the
extractor "works" but nothing survives anchor verification.

Scope: these tests exercise ONLY the low-evidence cascade (hallucinated anchors
→ all dropped → extract returns StageFailure(LOW_EVIDENCE_MSG) → score/salary/
confidence/growth cascade). They do NOT drive the salary-failure or
confidence-tier paths — those live in `tests/test_failures.py`. The `low_evidence`
obs guard below pins that the cascade is reached through the evidence gate, so
the test can't silently start passing through a happy path if anchor
verification ever stops dropping these quotes.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from gander import obs, pipeline
from gander.errors import StageFailure
from gander.ingest import LOW_EVIDENCE_MSG
from gander.llm import LLMClient
from gander.schemas import Anchor, Profile, ProfileItem, Report

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cvs"
_BREADTH_FIXTURES = (
    "14_nontech_marketing_fialova.txt",
    "15_career_changer_nurse_to_data_prochazkova.txt",
    "16_noncz_berlin_logistics_neumann.txt",
)


@pytest.fixture(autouse=True)
def _text_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GANDER_INGEST_MODE", "text")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")


def _docx_bytes_from_text(text: str) -> bytes:
    import docx as _docx

    document = _docx.Document()
    for line in text.splitlines():
        document.add_paragraph(line)
    buf = BytesIO()
    document.save(buf)
    return buf.getvalue()


def _hallucinated_profile() -> Profile:
    """A profile whose anchors paraphrase rather than quote the CV.

    None of these quotes appear verbatim in any fixture, so every item drops at
    anchor verification regardless of which fixture is loaded — the
    fixture-independent way to drive the low-evidence path."""
    item = ProfileItem(
        text="Generalist",
        anchor=Anchor(quote="Delivered broad cross-functional impact across many teams"),
    )
    return Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="Senior Specialist",
        detected_location=None,
        detected_years_experience=7,
    )


async def _collect(it: Any) -> list[Report]:
    return [r async for r in it]


@pytest.mark.fast
@pytest.mark.parametrize("fixture_name", _BREADTH_FIXTURES)
async def test_out_of_corpus_cv_degrades_gracefully(
    fixture_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each out-of-corpus shape cascades to a clean low-evidence failure with
    no stage left running and no traceback-style copy leaking to the user."""

    async def _fake_complete_json(self: LLMClient, **_kw: Any) -> Any:
        return _hallucinated_profile()

    monkeypatch.setattr(LLMClient, "complete_json", _fake_complete_json)

    cv_text = (_FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")
    events: list[dict[str, Any]] = []
    with obs.subscribe(events.append):
        reports = await _collect(pipeline.run(_docx_bytes_from_text(cv_text), "cv.docx"))
    final = reports[-1]

    # Guard: prove the cascade was reached through the evidence gate, not a
    # happy path that incidentally produced a failure elsewhere.
    assert any(e["event"] == "low_evidence" for e in events), (
        "expected a low_evidence obs event; cascade may not be going through the gate"
    )

    assert isinstance(final.profile, StageFailure)
    assert final.profile.user_message == LOW_EVIDENCE_MSG
    assert "Traceback" not in final.profile.user_message

    for stage in ("score", "salary", "confidence", "growth"):
        block = getattr(final, stage)
        assert isinstance(block, StageFailure), f"{stage} should cascade as StageFailure"
        assert block.user_message.strip(), f"{stage} cascade lacks reviewer-facing copy"

    assert all(v != "running" for v in final.statuses.values())
    assert set(final.statuses) == {"profile", "score", "salary", "confidence", "growth"}


@pytest.mark.fast
@pytest.mark.parametrize("fixture_name", _BREADTH_FIXTURES)
async def test_out_of_corpus_cv_every_yield_renders(
    fixture_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every intermediate yield round-trips through the renderer without
    raising — the Gradio re-render loop must never stall on these shapes."""
    from gander.report import render_html

    async def _fake_complete_json(self: LLMClient, **_kw: Any) -> Any:
        return _hallucinated_profile()

    monkeypatch.setattr(LLMClient, "complete_json", _fake_complete_json)

    cv_text = (_FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")
    reports = await _collect(pipeline.run(_docx_bytes_from_text(cv_text), "cv.docx"))

    assert len(reports) >= 2
    for i, report in enumerate(reports):
        out = render_html(report)
        assert isinstance(out, str), f"render_html returned non-str on yield #{i}"
