# T07 — L1 ingestion: implementation checklist

Source of truth: `tasks/T07_ingest.md`. PLAN reference: §"L1 — Ingestion".

## Files to create / modify

- **Create** `src/jobfit/ingest.py` — public `extract_text` + private helpers.
- **Create** `tests/test_ingest.py` — fast + slow pytest cases.
- **No new dependencies.** `pypdf`, `pdfplumber`, `python-docx` are runtime; `reportlab` is dev. Confirmed in `pyproject.toml`.
- **No edits** to `errors.py`, `schemas.py`, `obs.py`, `pyproject.toml`.

## Function signatures + return-type contracts

```python
def extract_text(file_bytes: bytes, filename: str) -> str | StageFailure: ...
```

### Failure-shape decision (call-out)

`StageFailure` is a `pydantic.BaseModel`, not a `BaseException` — it cannot be raised. Two viable patterns; we pick **(B)**:

- (A) Raise a custom exception whose `str(exc)` is the user_message; rely on `stage_boundary` to translate. Clean, but `stage_boundary` puts `repr(exc)` in `debug_detail` — fine — and forces the function signature to return only via the boundary.
- **(B) Return `str | StageFailure` directly.** The function dispatches itself, builds a `StageFailure` for the *controlled* failure modes (unknown suffix, `.doc` hint, scanned-PDF after both passes), and uses `stage_boundary` ONLY around the parser calls so corrupt-file exceptions become a generic StageFailure. Reasoning: each controlled failure has a distinct `user_message` per T07 spec; constructing them in-place is one line and keeps the messages out of exception strings (where they don't belong semantically). The corrupt-file path delegates message-shaping to `stage_boundary` since the exception text from `pypdf`/`python-docx` is fine for `debug_detail` but we want a stable user-facing message — so we wrap that call in our own `try/except` returning a hand-built `StageFailure` with `user_message="Could not read this file. It may be corrupt or password-protected."` and `debug_detail=repr(exc)`. `stage_boundary` is then redundant for the parsers; we drop it for the parser path and use it once at the *outer* function scope to catch genuinely unexpected failures (defense-in-depth, single-line cost).

Concrete control flow:

```
extract_text(file_bytes, filename):
  with obs-emit "ingest.start" (size, suffix)
  with stage_boundary("ingest") as cm:
      suffix = Path(filename).suffix.lower()
      if suffix == ".doc": return StageFailure(..., "...convert to PDF or DOCX.")
      if suffix == ".pdf":
          text = _extract_pdf(file_bytes)        # may raise; caught below
          if len(text.strip()) < 100:
              return StageFailure(..., SCANNED_MSG)
      elif suffix == ".docx":
          text = _extract_docx(file_bytes)
      else:
          return StageFailure(..., UNKNOWN_MSG)
      annotated = _annotate_sections(text)
      obs.emit("ingest", "done", chars=len(annotated), suffix=suffix)
      return annotated
  return cm.failure  # only reached if an unexpected exception bubbled
```

Private helpers (all `-> str`, raise on parser failure):

- `_extract_pdf(file_bytes: bytes) -> str` — pypdf first; if `len(result.strip()) < 100`, retry with pdfplumber and return whichever is longer. Counter `obs.emit("ingest", "pdf_pass", pypdf_chars=..., pdfplumber_chars=..., used=...)`.
- `_extract_docx(file_bytes: bytes) -> str` — `docx.Document(BytesIO(file_bytes))`; concatenate `[p.text for p in doc.paragraphs]` then table cell text (`for table in doc.tables: for row in table.rows: for cell in row.cells: cell.text`). Join with `\n`.
- `_annotate_sections(text: str) -> str` — line-by-line; if a line matches the heading heuristic AND is not already preceded by `## `, emit `## <line>\n<line>`. Heuristic:
  - `re.fullmatch(r"[A-Z][A-Z &/]{2,}", stripped)` (all-caps, length ≥ 3, allow space/`&`/`/`) — rejects single tokens, `2024`, `C++17`, `1.0`.
  - OR case-insensitive exact match against `{"experience", "work experience", "education", "skills", "projects", "summary", "profile"}`.
  - Skip lines containing digits to avoid eating "EXPERIENCE 2024" — actually allow them only if they pass the closed list (closed list is exact-match, no digits). Simpler: regex anchor `^[A-Z][A-Z &/]{2,}$` rejects digits naturally.

Module-level constants:
- `SCANNED_MSG = "This appears to be a scanned PDF. Text-based PDFs and DOCX are required."`
- `UNKNOWN_MSG = "Unable to read this file. Please upload a valid PDF or DOCX."`
- `DOC_MSG = "Legacy .doc is not supported. Please convert to PDF or DOCX and re-upload."`
- `CORRUPT_MSG = "Could not read this file. It may be corrupt or password-protected."`
- `SECTION_NAMES = frozenset({"experience", "work experience", "education", "skills", "projects", "summary", "profile"})`
- `MIN_TEXT_CHARS = 100`

### Observability

- Start: `obs.emit("ingest", "start", filename_suffix=suffix, size_bytes=len(file_bytes))` — never log filename or content.
- PDF passes: `obs.emit("ingest", "pdf_pass", pypdf_chars=..., pdfplumber_chars=..., used="pypdf"|"pdfplumber")`.
- Done: `obs.emit("ingest", "done", chars=..., suffix=...)`.
- Failure paths: rely on `stage_boundary` for unexpected errors; for controlled `StageFailure` returns, emit `obs.emit("ingest", "rejected", reason="scanned"|"unknown_suffix"|"doc_legacy"|"corrupt")`.

## Test cases — `tests/test_ingest.py`

Module header: `from __future__ import annotations`, `pytestmark = pytest.mark.fast` for the fast group; mark slow tests individually with `@pytest.mark.slow`.

### Fast (no IO beyond in-memory bytes)

1. `test_unknown_extension_returns_format_failure` — `extract_text(b"hello", "notes.txt")` → `StageFailure`, `user_message == UNKNOWN_MSG`, `stage == "ingest"`.
2. `test_doc_extension_returns_conversion_hint` — `extract_text(b"...", "cv.doc")` → `StageFailure`, `user_message == DOC_MSG`.
3. `test_corrupt_pdf_returns_corrupt_failure` — `extract_text(b"%PDF-not-a-real-pdf", "cv.pdf")` → `StageFailure`, `user_message == CORRUPT_MSG` (NOT `SCANNED_MSG`).
4. `test_corrupt_docx_returns_corrupt_failure` — `extract_text(b"PK\x03\x04junk", "cv.docx")` → `StageFailure`, `user_message == CORRUPT_MSG`.
5. `test_annotate_inserts_header_for_all_caps_line` — `_annotate_sections("EXPERIENCE\nLed migration.\n")` contains `"## EXPERIENCE"` exactly once.
6. `test_annotate_inserts_header_for_closed_list_match_case_insensitive` — input `"Work Experience\nFoo\n"` → contains `"## Work Experience"`.
7. `test_annotate_does_not_eat_year_line` — input `"2024\nFoo\n"` → no `## 2024` injected.
8. `test_annotate_does_not_eat_version_token` — inputs `"C++17\nFoo\n"` and `"Python 3.10\nFoo\n"` → no `##` injection.
9. `test_annotate_does_not_double_annotate` — input that already contains `"## Experience\nFoo\n"` produces no second `## Experience`.

### Slow (loops fixtures)

10. `@pytest.mark.slow test_real_fixtures_extract_minimum_chars` — iterate `Path("tests/fixtures/cvs").glob("*.pdf")` + `glob("*.docx")`, assert `isinstance(result, str)` and `len(result) >= 200` for each. Currently covers `01_junior_da_novotny.docx` and `08_staff_ml_engineer_dvorak.pdf`; will pick up additional fixtures as T04/T06 land.
11. `@pytest.mark.slow test_scanned_pdf_returns_scanned_failure` — synthesize an image-only PDF using `reportlab.pdfgen.canvas.Canvas` drawing a filled rectangle (`canvas.rect(...)` + `canvas.setFillColorRGB(...)` + `canvas.fill()`) to a `BytesIO`. No `drawString`, so `pypdf` and `pdfplumber` both extract `< 100` chars. Assert `StageFailure` with `user_message == SCANNED_MSG`. If reportlab's text-stream output still contains stray dictionary chars that push past 100, fall back to `pytest.skip("scanned-pdf synthesis produced extractable text; defer to T07-followup")` rather than fight it. (PIL is NOT in deps — do not import it.)

## Risks

- **Heading heuristic over-eager.** Real CVs have section banners like `EXPERIENCE` but also stray `JAVA` / `AWS` skill words on their own line. The `^[A-Z][A-Z &/]{2,}$` regex with `len ≥ 3` mitigates but does not eliminate. Acceptable for v1: verify_quote tolerates extra `## X` headers (they only narrow section search). Will revisit if T15 sees real false positives.
- **pdfplumber fallback latency.** pdfplumber is slow on large PDFs. Mitigation: only run when pypdf returns `< 100` chars. Not adding a hard timeout — out of scope for T07; pipeline-level deadline (T15) handles this.
- **scanned-PDF synthesis fragility.** If reportlab's no-text PDF still extracts > 100 chars on some pypdf version, the slow test skips. Recorded as deferral, not a blocker — fast-path scanned detection is exercised indirectly by the `MIN_TEXT_CHARS` branch; an explicit fixture is best-effort.
- **`.doc` files** are not just bytes — the suffix dispatch happens before parsing, so we never feed legacy binary into `pypdf`/`docx`. Safe.
- **Encrypted PDFs** raise `pypdf.errors.PdfReadError` or similar — `stage_boundary` catches, message becomes `CORRUPT_MSG`. Acceptable: the user sees "may be corrupt or password-protected". No separate code path.

## Acceptance gate

All four must pass before declaring T07 done:

```bash
uv run ruff format --check src/jobfit/ingest.py tests/test_ingest.py
uv run ruff check src/jobfit/ingest.py tests/test_ingest.py
uv run mypy --strict src/jobfit
uv run pytest -m fast tests/test_ingest.py -v
uv run pytest -m slow tests/test_ingest.py -v
```

Plus:
- All 9 fast tests green.
- Slow fixture loop green for the 2 currently-present fixtures.
- Scanned-PDF slow test green OR explicitly skipped with a recorded reason.
- No new entries in `pyproject.toml` `dependencies` or `dependency-groups.dev`.
- `tasks/T07_ingest.md` "Outcome" section filled in with what was verified, what was deferred (extra fixtures, scanned-PDF if skipped).
