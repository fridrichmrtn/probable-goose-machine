from __future__ import annotations

import time
import unicodedata
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
        # English (existing + new for title-case headers seen in CZ/EN CVs)
        "experience",
        "work experience",
        "professional experience",
        "education",
        "skills",
        "projects",
        "summary",
        "profile",
        "languages",
        "certifications",
        "honors-awards",
        "awards",
        "publications",
        "contact",
        # Czech — section labels common on bilingual CZ/EN CVs
        "pracovní zkušenosti",
        "zkušenosti",
        "vzdělání",
        "dovednosti",
        "nejčastější dovednosti",
        "jazyky",
        "certifikace",
        "ocenění",
        "publikace",
        "projekty",
        "shrnutí",
        "profil",
        "kontakt",
    }
)
MIN_TEXT_CHARS = 100
# The length gate exists ONLY to keep long paragraph sentences that contain a
# section keyword (e.g. "He learned several languages…") out of the vocab-match
# branch. 40 chars covers every alias plus typical decorations (trailing colon,
# single trailing word). It does NOT apply to the all-caps branch: real CVs
# sometimes use long all-caps section headers, especially in Czech where
# diacritics make labels longer (e.g. "PRACOVNÍ ZKUŠENOSTI A PROFESNÍ KARIÉRA").
_MAX_HEADER_CHARS = 40


def _is_all_caps_header(s: str) -> bool:
    """Unicode-aware all-caps section heuristic.

    Accepts a line that is at least 7 chars long, starts with an uppercase
    letter, and contains only uppercase letters plus the decorations seen on
    real CV headers (space, ampersand, slash). Unicode-aware so Czech
    diacritics like Í/Š/É count as uppercase letters — the previous ASCII-only
    regex silently dropped every all-caps Czech header.
    """
    if len(s) < 7 or not s[0].isupper():
        return False
    has_letter = False
    for ch in s:
        if ch.isalpha():
            if not ch.isupper():
                return False
            has_letter = True
        elif ch not in " &/":
            return False
    return has_letter


def _normalize_for_section_match(s: str) -> str:
    """NFD-decompose, drop combining marks (= strip diacritics), lowercase,
    collapse internal whitespace. So `Vzdělání` and `vzdelani` and
    `  VZDĚLÁNÍ  ` all hash the same key."""
    decomposed = unicodedata.normalize("NFD", s)
    no_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return " ".join(no_marks.lower().split())


_NORMALIZED_SECTION_NAMES: frozenset[str] = frozenset(
    _normalize_for_section_match(name) for name in SECTION_NAMES
)


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
    # All-caps branch: trusted enough to bypass the length gate. The strict
    # shape (uppercase letters + space/&// only) already rules out paragraph
    # sentences. Long Czech all-caps labels live here.
    if _is_all_caps_header(stripped):
        return True
    # Vocab-match branch: the length gate applies here because this branch is
    # the one prone to false positives — paragraph sentences containing a
    # section keyword normalise to a vocab miss only because the surrounding
    # words push them past the threshold. Without the gate, "He learned
    # several languages…" risks promotion if it ever shortens.
    if len(stripped) > _MAX_HEADER_CHARS:
        return False
    return _normalize_for_section_match(stripped) in _NORMALIZED_SECTION_NAMES


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
