# T04 — CV corpus part 1: junior + senior

Status: done
Owner: software-engineer
Depends on: T00
Unblocks: T05
Estimate: ~30 min

## Goal

Synthesize and render 2 of the 10 CVs (the junior and senior endpoints) so the L0.5 capability spike (T05) has data to validate MiniMax against.

## Deliverables

- [x] `tests/fixtures/cvs/01_junior_da_novotny.docx` — Jan Novotný, Junior Data Analyst, 1 yr at Mall.cz Prague. DOCX via python-docx. 10 verifiable anchors including the quantified "reduced reporting turnaround from 2 days to 4 hours" specified in the brief.
- [x] `tests/fixtures/cvs/08_staff_ml_engineer_dvorak.pdf` — Tomáš Dvořák, Staff ML Engineer, 13 yrs across Avast → Kiwi.com → ČSOB. Two-column reportlab PDF (uneven 42/58 columns + header/footer bands + serif body / sans header) — stresses pdfplumber column-aware fallback. 15 verifiable anchors. DejaVu Sans/Serif TTFs registered so Czech diacritics survive.
- [x] `tests/fixtures/cvs/01_junior_da_novotny.txt` — output of `python-docx Document.paragraphs` join.
- [x] `tests/fixtures/cvs/08_staff_ml_engineer_dvorak.txt` — output of `pypdf.PdfReader.extract_text()` join (preserves the messy mid-phrase column line breaks T07 will need to fix via pdfplumber).
- [x] `tests/fixtures/cvs/SOURCES.md` — anchor list per CV + rendering-tool note + calibration table for T05/T17 expectations.

## Authoring rules (apply throughout)

- Names are clearly fictional Czech names; avoid real CZ professionals.
- Employers are real CZ companies or plausible CZ subsidiaries.
- Universities are CZ (MFF UK, ČVUT FIT, VŠE, MUNI, VUT Brno).
- Cities: Prague / Brno / Ostrava / Plzeň.
- Salaries (when included): CZK monthly gross.
- Junior anchor: ≤2 years total experience, no leadership signals, narrow stack.
- Senior anchor: ≥12 years, multiple roles, leadership/staff signals, broad+deep stack.

## Verification

```bash
uv run python -c "from pypdf import PdfReader; print(len(PdfReader('tests/fixtures/cvs/08_staff_ml_engineer_dvorak.pdf').pages))"   # > 0
uv run python -c "from docx import Document; print(len(Document('tests/fixtures/cvs/01_junior_da_novotny.docx').paragraphs))"        # > 0
diff <(uv run python -c "from pypdf import PdfReader; print(PdfReader('tests/fixtures/cvs/08_staff_ml_engineer_dvorak.pdf').pages[0].extract_text())") tests/fixtures/cvs/08_staff_ml_engineer_dvorak.txt   # close enough that the .txt covers ≥80% of extracted tokens
```

## Reference

- tasks/PLAN.md — § "CV Corpus (Track E, ~2.5h)"

## Outcome

Both fixtures rendered via a single `scripts/build_cv_fixtures.py` (T06 will extend this same script with CVs #2–7, #9, #10).

Rendering choice: **`reportlab` (pure-Python dev dep) + `python-docx`** — picked over libreoffice (~500 MB system install) and weasyprint (cairo/pango via apt) for zero system-dep cost. Reportlab is *not* a true Word→PDF path, but the deliberate two-column / mixed-font / header-footer messiness produces a PDF that exercises pdfplumber's layout-aware fallback in the way the original spec intends; SOURCES.md records the rationale so future readers don't think we cargo-culted reportlab.

Czech diacritic survival required `pdfmetrics.registerFont(TTFont("DejaVuSans", …))` for normal/bold/oblique + serif variants and `registerFontFamily(...)` so `<b>` inside `Paragraph` picks up DejaVuSans-Bold. Without these, ř / Č / š render as filled boxes (verified — first build pass had `Dvo■ák`).

Verification (all pass):
- `len(PdfReader('…dvorak.pdf').pages)` = 1.
- `len(Document('…novotny.docx').paragraphs)` = 15.
- Senior `.txt` covers 100% of pdfplumber-extracted tokens (≥80% gate).
- Junior `.txt` covers 100% of python-docx-extracted tokens (≥80% gate).
- `ruff format` + `ruff check` clean on `scripts/build_cv_fixtures.py`.

Side-effect: `pyproject.toml` + `uv.lock` updated to add `reportlab` as a dev dep (~2 MB Python wheel; no system deps). Confirmed with the user before the add (after an unprompted-add lapse earlier in the same session — feedback memory updated).
