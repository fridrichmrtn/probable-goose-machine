# T07 — L1 ingestion (PDF/DOCX → text)

Status: todo
Owner: software-engineer
Depends on: T02, T05 (gate)
Unblocks: T15
Estimate: ~30 min

## Goal

Pure-Python file → text extractor with format detection, scanned-PDF detection, and clear user-facing failures (no tracebacks).

## Deliverables

- [ ] `src/jobfit/ingest.py`:
  - `def extract_text(file_bytes: bytes, filename: str) -> str`:
    - dispatch on suffix (`.pdf`, `.docx`, `.doc` → fail with hint to convert).
    - PDF: try `pypdf` first; if extracted text < 100 chars, retry with `pdfplumber`.
    - DOCX: `python-docx`, concatenate paragraph + table cell text.
    - If still < 100 chars after both PDF passes (or PDF has > 0 pages but no text) → raise `StageFailure("This appears to be a scanned PDF. Text-based PDFs and DOCX are required.", stage="ingest")`.
    - Unknown suffix → raise `StageFailure("Unable to read this file. Please upload a valid PDF or DOCX.", stage="ingest")`.
    - Wrap in `stage_boundary("ingest")` so any underlying exception (`pypdf.errors.PdfReadError`, etc.) becomes a clean StageFailure with the corrupt-file message.
  - Insert a markdown-style `## section` header before each detected section heading (looks like `EXPERIENCE`, `EDUCATION`, etc., heuristic) so `verify_quote` section-locality has something to anchor against. Conservative: only insert if line is all-caps OR matches a known list (`Experience`, `Education`, `Skills`, `Projects`, `Summary`).
- [ ] `tests/test_ingest.py`:
  - `@pytest.mark.fast`: corrupt bytes → StageFailure with the corrupt-file message.
  - `@pytest.mark.fast`: unknown extension → StageFailure with the format message.
  - `@pytest.mark.slow`: each of the 10 fixture CVs extracts ≥200 chars (loops over `tests/fixtures/cvs/*.pdf` and `*.docx`).
  - `@pytest.mark.slow`: `05_mlops_benes.pdf` (the messy Word→PDF) succeeds — guards the pdfplumber fallback.
  - Fixture for scanned PDF: place a tiny image-only PDF at `tests/fixtures/scanned.pdf` → assert StageFailure with "scanned PDF" message.

## Verification

```bash
uv run pytest -m fast tests/test_ingest.py -v
uv run pytest -m slow tests/test_ingest.py -v   # needs T04+T06 fixtures
```

## Reference

- tasks/PLAN.md — § "L1 — Ingestion"

## Outcome

(fill in when done — note any rendering issues with the messy PDF)
