from __future__ import annotations

import re
import time
from io import BytesIO
from pathlib import Path

import docx
import pdfplumber
import pypdf

from gander import obs
from gander.errors import StageFailure, stage_boundary

SCANNED_MSG = "This appears to be a scanned PDF. Text-based PDFs and DOCX are required."
UNKNOWN_MSG = "Unable to read this file. Please upload a valid PDF or DOCX."
DOC_MSG = "Legacy .doc is not supported. Please convert to PDF or DOCX and re-upload."
CORRUPT_MSG = "Could not read this file. It may be corrupt or password-protected."
EMPTY_MSG = "This file appears to be empty or too short to be a CV."

SECTION_NAMES: frozenset[str] = frozenset(
    {
        "experience",
        "work experience",
        "education",
        "skills",
        "projects",
        "summary",
        "profile",
    }
)
MIN_TEXT_CHARS = 100

_ALL_CAPS_HEADER = re.compile(r"^[A-Z][A-Z &/]{6,}$")


def extract_text(file_bytes: bytes, filename: str) -> str | StageFailure:
    """Extract plain text from a CV file (PDF or DOCX).

    Returns the text on success, or a StageFailure with a user-facing message on
    controlled failure paths (unknown suffix, legacy .doc, scanned PDF, corrupt
    file). Wrapped in stage_boundary as defense-in-depth for unexpected errors.
    """
    t0 = time.perf_counter()
    suffix = Path(filename).suffix.lower()
    obs.emit("ingest", "start", filename_suffix=suffix, size_bytes=len(file_bytes))

    def _ms() -> int:
        return int((time.perf_counter() - t0) * 1000)

    with stage_boundary("ingest") as cm:
        if suffix == ".doc":
            obs.emit("ingest", "rejected", reason="doc_legacy", duration_ms=_ms())
            return StageFailure(stage="ingest", user_message=DOC_MSG)

        if suffix == ".pdf":
            try:
                text = _extract_pdf(file_bytes)
            except Exception as exc:
                obs.emit("ingest", "rejected", reason="corrupt", duration_ms=_ms())
                return StageFailure(
                    stage="ingest",
                    user_message=CORRUPT_MSG,
                    debug_detail=f"{type(exc).__name__}: {len(file_bytes)} bytes",
                )
            if len(text.strip()) < MIN_TEXT_CHARS:
                obs.emit("ingest", "rejected", reason="scanned", duration_ms=_ms())
                return StageFailure(stage="ingest", user_message=SCANNED_MSG)
        elif suffix == ".docx":
            try:
                text = _extract_docx(file_bytes)
            except Exception as exc:
                obs.emit("ingest", "rejected", reason="corrupt", duration_ms=_ms())
                return StageFailure(
                    stage="ingest",
                    user_message=CORRUPT_MSG,
                    debug_detail=f"{type(exc).__name__}: {len(file_bytes)} bytes",
                )
            if len(text.strip()) < MIN_TEXT_CHARS:
                obs.emit("ingest", "rejected", reason="empty_docx", duration_ms=_ms())
                return StageFailure(stage="ingest", user_message=EMPTY_MSG)
        else:
            obs.emit("ingest", "rejected", reason="unknown_suffix", duration_ms=_ms())
            return StageFailure(stage="ingest", user_message=UNKNOWN_MSG)

        annotated = _annotate_sections(text)
        obs.emit(
            "ingest",
            "done",
            chars=len(annotated),
            suffix=suffix,
            duration_ms=_ms(),
        )
        return annotated

    assert cm.failure is not None  # stage_boundary swallowed an unexpected exception
    return cm.failure


def _extract_pdf(file_bytes: bytes) -> str:
    reader = pypdf.PdfReader(BytesIO(file_bytes))
    pypdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    pypdf_chars = len(pypdf_text.strip())

    if pypdf_chars >= MIN_TEXT_CHARS:
        obs.emit(
            "ingest",
            "pdf_pass",
            pypdf_chars=pypdf_chars,
            pdfplumber_chars=0,
            used="pypdf",
        )
        return pypdf_text

    # pypdf produced something parseable but text-poor. If pdfplumber blows up,
    # don't reclassify the file as corrupt — fall back to pypdf's output and
    # let the caller's <100-char check yield SCANNED_MSG.
    try:
        with pdfplumber.open(BytesIO(file_bytes)) as plumber_pdf:
            plumber_text = "\n".join(page.extract_text() or "" for page in plumber_pdf.pages)
        plumber_chars = len(plumber_text.strip())
    except Exception as exc:
        obs.emit(
            "ingest",
            "pdfplumber_fallback_failed",
            pypdf_chars=pypdf_chars,
            exc_type=type(exc).__name__,
        )
        return pypdf_text

    used = "pdfplumber" if plumber_chars > pypdf_chars else "pypdf"
    obs.emit(
        "ingest",
        "pdf_pass",
        pypdf_chars=pypdf_chars,
        pdfplumber_chars=plumber_chars,
        used=used,
    )
    return plumber_text if used == "pdfplumber" else pypdf_text


def _extract_docx(file_bytes: bytes) -> str:
    document = docx.Document(BytesIO(file_bytes))
    parts: list[str] = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


def _looks_like_section_header(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _ALL_CAPS_HEADER.fullmatch(stripped):
        return True
    return stripped.lower() in SECTION_NAMES


def _annotate_sections(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    for i, line in enumerate(lines):
        if _looks_like_section_header(line):
            prev = out[-1].strip() if out else ""
            already_annotated = prev.startswith("##") and prev.lstrip("#").strip().lower() == (
                line.strip().lower()
            )
            previous_source = lines[i - 1].strip() if i > 0 else ""
            already_in_source = previous_source.startswith("##") and previous_source.lstrip(
                "#"
            ).strip().lower() == (line.strip().lower())
            if not already_annotated and not already_in_source:
                out.append(f"## {line.strip()}")
        out.append(line)
    return "\n".join(out)
