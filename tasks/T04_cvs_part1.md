# T04 — CV corpus part 1: junior + senior

Status: todo
Owner: software-engineer
Depends on: T00
Unblocks: T05
Estimate: ~30 min

## Goal

Synthesize and render 2 of the 10 CVs (the junior and senior endpoints) so the L0.5 capability spike (T05) has data to validate MiniMax against.

## Deliverables

- [ ] `tests/fixtures/cvs/01_junior_da_novotny.docx` — Jan Novotný, Junior Data Analyst, 1 yr at a CZ company (e.g., Mall.cz or Productboard CZ subsidiary). DOCX format. Includes 5–10 verifiable specifics: tech stack with versions, project name, one quantified outcome ("reduced reporting turnaround from 2 days to 4 hours"). All in English.
- [ ] `tests/fixtures/cvs/08_staff_ml_engineer_dvorak.pdf` — Tomáš Dvořák, Staff ML Engineer, 13 yrs spanning roles at Avast → Kiwi.com → ČSOB or similar. **PDF rendered from a two-column layout** (use a Word→PDF path, not LaTeX) so it stresses pdfplumber. Includes 10–15 verifiable specifics: project names, tech versions, quantified outcomes, leadership signals.
- [ ] `tests/fixtures/cvs/01_junior_da_novotny.txt` — extracted text version (for golden-quote diffing).
- [ ] `tests/fixtures/cvs/08_staff_ml_engineer_dvorak.txt` — same.
- [ ] Stub entry in `tests/fixtures/cvs/SOURCES.md` for these two (full file lands in T06).

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

(fill in when done — note the rendering tool you used so T06 stays consistent)
