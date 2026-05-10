# T07 — L1 ingestion (PDF/DOCX → text)

Status: done
Owner: software-engineer
Depends on: T02, T05 (gate)
Unblocks: T15
Estimate: ~30 min

## Goal

Pure-Python file → text extractor with format detection, scanned-PDF detection, and clear user-facing failures (no tracebacks).

## Deliverables

- [ ] `src/jobfit/ingest.py`:
  - `def extract_text(file_bytes: bytes, filename: str) -> str | StageFailure`:
    - dispatch on suffix (`.pdf`, `.docx`, `.doc` → fail with hint to convert).
    - PDF: try `pypdf` first; if extracted text < 100 chars, retry with `pdfplumber`.
    - DOCX: `python-docx`, concatenate paragraph + table cell text.
    - If still < 100 chars after both PDF passes (or PDF has > 0 pages but no text) → `return StageFailure("This appears to be a scanned PDF. Text-based PDFs and DOCX are required.", stage="ingest")`.
    - Unknown suffix → `return StageFailure("Unable to read this file. Please upload a valid PDF or DOCX.", stage="ingest")`.
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

Signature changed from `-> str` (raise) to `-> str | StageFailure` (return) so the L6 orchestrator can branch on `isinstance(result, StageFailure)` without try/except — `stage_boundary` remains as defense-in-depth for unexpected exceptions. Implemented `extract_text` per dev-plan option B — returns `str | StageFailure`, never raises. Suffix dispatch handles `.pdf`, `.docx`, `.doc` (legacy hint), and unknown extensions; corrupt PDFs/DOCX become `CORRUPT_MSG` via narrow try/except around the parser calls. PDF path tries `pypdf` first and only invokes `pdfplumber` when the first pass returns < 100 chars; pdfplumber failure is caught locally and falls back to pypdf's output (so a plumber crash on a text-poor PDF yields `SCANNED_MSG`, not `CORRUPT_MSG`), emitting `pdf_pass` or `pdfplumber_fallback_failed` counters. DOCX path applies a post-extract `< 100` char check that returns `EMPTY_MSG` for empty / near-empty documents. Section-header insertion uses a conservative regex `^[A-Z][A-Z &/]{6,}$` plus a case-insensitive closed list, naturally rejecting digits, version tokens (`C++17`, `Python 3.10`, `2024`), and short skill/tooling acronyms (`AWS S3`, `R&D`, `CI/CD`, `IT/OPS`); duplicate-prefix detection skips re-annotation when a `## Header` already precedes the line in either the input or the running output. Observability: `start` carries `filename_suffix` + `size_bytes`; `done` and `rejected` carry `duration_ms`; `debug_detail` on corrupt paths is `"{ExcType}: {len(file_bytes)} bytes"` (no parser-exception text). The scanned-PDF slow test was synthesized via `reportlab.pdfgen.canvas.Canvas` drawing only a filled rectangle (no `drawString`); the test now fails loudly (`pytest.fail`) instead of skipping if synthesis produces extractable text. Slow fixture loop is guarded by `test_cv_fixtures_corpus_not_empty` so a future empty-corpus regression is loud, not silent.

Deferred to T06: `05_mlops_benes.pdf` — the messy Word→PDF fixture that exercises the pdfplumber fallback guard called out in the original spec. The parametrize glob will pick it up automatically once T06 commits it.
