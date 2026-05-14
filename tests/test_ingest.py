from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from gander import ingest
from gander.errors import StageFailure
from gander.ingest import (
    CORRUPT_MSG,
    DOC_MSG,
    EMPTY_MSG,
    SCANNED_MSG,
    UNKNOWN_MSG,
    _annotate_sections,
    extract_text,
)
from gander.obs import subscribe


@pytest.mark.fast
def test_unknown_extension_returns_format_failure() -> None:
    result = extract_text(b"hello", "notes.txt")
    assert isinstance(result, StageFailure)
    assert result.stage == "ingest"
    assert result.user_message == UNKNOWN_MSG


@pytest.mark.fast
def test_doc_extension_returns_conversion_hint() -> None:
    result = extract_text(b"\xd0\xcf\x11\xe0fake-ole-bytes", "cv.doc")
    assert isinstance(result, StageFailure)
    assert result.stage == "ingest"
    assert result.user_message == DOC_MSG


@pytest.mark.fast
def test_corrupt_pdf_returns_corrupt_failure() -> None:
    result = extract_text(b"%PDF-not-a-real-pdf", "cv.pdf")
    assert isinstance(result, StageFailure)
    assert result.stage == "ingest"
    assert result.user_message == CORRUPT_MSG
    assert result.user_message != SCANNED_MSG


@pytest.mark.fast
def test_corrupt_pdf_debug_detail_does_not_leak_content() -> None:
    payload = b"%PDF-not-a-real-pdf"
    result = extract_text(payload, "cv.pdf")
    assert isinstance(result, StageFailure)
    assert result.debug_detail is not None
    assert f"{len(payload)} bytes" in result.debug_detail
    assert "not-a-real-pdf" not in result.debug_detail


@pytest.mark.fast
def test_corrupt_docx_returns_corrupt_failure() -> None:
    result = extract_text(b"PK\x03\x04junk-not-a-real-docx", "cv.docx")
    assert isinstance(result, StageFailure)
    assert result.stage == "ingest"
    assert result.user_message == CORRUPT_MSG


@pytest.mark.fast
def test_empty_docx_returns_empty_failure() -> None:
    import docx as _docx

    document = _docx.Document()
    buf = BytesIO()
    document.save(buf)
    result = extract_text(buf.getvalue(), "empty.docx")
    assert isinstance(result, StageFailure)
    assert result.stage == "ingest"
    assert result.user_message == EMPTY_MSG


@pytest.mark.fast
def test_tiny_docx_returns_empty_failure() -> None:
    import docx as _docx

    document = _docx.Document()
    document.add_paragraph("Hi")
    buf = BytesIO()
    document.save(buf)
    result = extract_text(buf.getvalue(), "tiny.docx")
    assert isinstance(result, StageFailure)
    assert result.stage == "ingest"
    assert result.user_message == EMPTY_MSG


@pytest.mark.fast
def test_pdfplumber_failure_falls_back_to_scanned_not_corrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When pypdf parses a valid PDF but extracts <100 chars, and pdfplumber
    then raises during fallback, classify as SCANNED (text-poor), not CORRUPT.
    """
    reportlab_canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    buf = BytesIO()
    c = reportlab_canvas.Canvas(buf)
    c.drawString(100, 100, "hi")  # tiny but pypdf-parseable text
    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("synthetic pdfplumber failure")

    monkeypatch.setattr(ingest.pdfplumber, "open", _boom)

    result = extract_text(pdf_bytes, "tiny.pdf")
    assert isinstance(result, StageFailure)
    assert result.stage == "ingest"
    assert result.user_message == SCANNED_MSG


@pytest.mark.fast
def test_annotate_inserts_header_for_all_caps_line() -> None:
    out = _annotate_sections("EXPERIENCE\nLed migration.\n")
    assert out.count("## EXPERIENCE") == 1


@pytest.mark.fast
def test_annotate_inserts_header_for_work_experience() -> None:
    out = _annotate_sections("WORK EXPERIENCE\nLed migration.\n")
    assert "## WORK EXPERIENCE" in out


@pytest.mark.fast
def test_annotate_inserts_header_for_closed_list_match_case_insensitive() -> None:
    out = _annotate_sections("Work Experience\nFoo\n")
    assert "## Work Experience" in out


@pytest.mark.fast
def test_annotate_does_not_eat_year_line() -> None:
    out = _annotate_sections("2024\nFoo\n")
    assert "## 2024" not in out


@pytest.mark.fast
def test_annotate_does_not_eat_version_token() -> None:
    out_cpp = _annotate_sections("C++17\nFoo\n")
    out_py = _annotate_sections("Python 3.10\nFoo\n")
    assert "##" not in out_cpp
    assert "##" not in out_py


@pytest.mark.fast
def test_annotate_does_not_eat_short_acronyms() -> None:
    """Short skill/tooling tokens on their own line must not become section headers."""
    for token in ("AWS S3", "CI/CD", "R&D", "IT/OPS"):
        out = _annotate_sections(f"{token}\nFoo\n")
        assert f"## {token}" not in out, f"{token!r} should not be promoted to ## header"


@pytest.mark.fast
def test_annotate_does_not_double_annotate() -> None:
    out = _annotate_sections("## Experience\nExperience\nFoo\n")
    assert out.count("## Experience") == 1


@pytest.mark.fast
def test_observability_emits_start_and_done_for_docx_fixture() -> None:
    fixture = _FIXTURE_DIR / "01_junior_da_novotny.docx"
    data = fixture.read_bytes()
    # Fail loudly on unresolved LFS pointers (fresh checkout w/o `git lfs pull`
    # or CI without `lfs: true`). Otherwise the test would surface as a cryptic
    # zip-parse failure inside extract_text. — Copilot PR #2 finding.
    if data.startswith(b"version https://git-lfs.github.com/"):
        pytest.fail(
            f"{fixture.name} is an unresolved LFS pointer. "
            "Run `git lfs pull` (CI uses `actions/checkout@v4` with `lfs: true`)."
        )
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = extract_text(data, fixture.name)
    assert isinstance(result, str)

    starts = [e for e in events if e["event"] == "start" and e["stage"] == "ingest"]
    dones = [e for e in events if e["event"] == "done" and e["stage"] == "ingest"]
    assert starts, f"expected a start event, got {events!r}"
    assert dones, f"expected a done event, got {events!r}"

    done = dones[0]
    assert done["chars"] >= 200
    assert "duration_ms" in done
    assert isinstance(done["duration_ms"], int)
    assert done["duration_ms"] >= 0
    assert "duration_ms" not in starts[0]


@pytest.mark.fast
def test_observability_emits_rejected_for_unknown_suffix() -> None:
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = extract_text(b"hello", "notes.txt")
    assert isinstance(result, StageFailure)

    rejected = [
        e
        for e in events
        if e["event"] == "rejected"
        and e["stage"] == "ingest"
        and e.get("reason") == "unknown_suffix"
    ]
    assert rejected, f"expected rejected/unknown_suffix event, got {events!r}"
    assert "duration_ms" in rejected[0]
    assert isinstance(rejected[0]["duration_ms"], int)


_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cvs"


@pytest.mark.slow
def test_cv_fixtures_corpus_not_empty() -> None:
    """Guard: empty parametrize silently auto-skips. Make corpus regression loud."""
    pdfs = list(_FIXTURE_DIR.glob("*.pdf"))
    docxs = list(_FIXTURE_DIR.glob("*.docx"))
    if not pdfs and not docxs:
        pytest.fail("no CV fixtures found in tests/fixtures/cvs/ — corpus regression")


@pytest.mark.slow
@pytest.mark.parametrize(
    "fixture_path",
    sorted(list(_FIXTURE_DIR.glob("*.pdf")) + list(_FIXTURE_DIR.glob("*.docx"))),
    ids=lambda p: p.name,
)
def test_real_fixtures_extract_minimum_chars(fixture_path: Path) -> None:
    result = extract_text(fixture_path.read_bytes(), fixture_path.name)
    assert isinstance(result, str), f"expected str, got {result!r}"
    assert len(result) >= 200


@pytest.mark.slow
def test_scanned_pdf_returns_scanned_failure() -> None:
    reportlab_canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    buf = BytesIO()
    c = reportlab_canvas.Canvas(buf)
    c.setFillColorRGB(0.2, 0.2, 0.2)
    c.rect(50, 50, 200, 200, fill=1, stroke=0)
    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()

    # Precondition: the synthesized PDF must actually be text-poor on both
    # parsers; otherwise the detector is being silently bypassed.
    import pdfplumber as _pdfplumber
    import pypdf as _pypdf

    reader = _pypdf.PdfReader(BytesIO(pdf_bytes))
    pypdf_chars = len("\n".join(p.extract_text() or "" for p in reader.pages).strip())
    with _pdfplumber.open(BytesIO(pdf_bytes)) as plumber_pdf:
        plumber_chars = len("\n".join(p.extract_text() or "" for p in plumber_pdf.pages).strip())
    if pypdf_chars >= 100 or plumber_chars >= 100:
        pytest.fail(
            "scanned-pdf fixture synthesis produced extractable text "
            f"(pypdf={pypdf_chars}, pdfplumber={plumber_chars}) — "
            "fix the synthesis or commit a real fixture"
        )

    result = extract_text(pdf_bytes, "scanned.pdf")
    assert isinstance(result, StageFailure)
    assert result.stage == "ingest"
    assert result.user_message == SCANNED_MSG
