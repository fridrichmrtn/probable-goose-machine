# CV fixture sources

Synthesized CZ data / DS / ML CVs used by the test suite and the user-facing
eval-corpus runner. T04 covers the two acceptance anchors (#1 junior, #8
senior) so the L0.5 capability spike has data. T06 will fill in #2–7, #9, #10.

All names are clearly fictional. Employers are real CZ companies or plausible
CZ-based subsidiaries. Universities are CZ. Salaries (when implied by role)
match the Czech market in CZK monthly gross.

## Rendering tools

- DOCX: `python-docx` straight to `.docx`.
- PDF: `reportlab` two-column layout with deliberate stressors (uneven column
  widths, header/footer bands, mixed serif/sans body, mid-phrase column
  breaks) so `pdfplumber`'s layout-aware fallback gets exercised in T07.
  Czech diacritics handled via DejaVu Sans / Serif TTF registration; falls
  back to Helvetica/Times-Roman if DejaVu is absent (output then drops
  diacritics — acceptable lossy mode).
- `.txt` golden text is the actual output of `pypdf.PdfReader` (PDF) and
  `python-docx Document.paragraphs` (DOCX), not the source content. Goldens
  reflect what L1 ingestion will see, so verify-against-source tests are
  honest.

Single source script: [`scripts/build_cv_fixtures.py`](../../../scripts/build_cv_fixtures.py).
Re-run with `uv run python scripts/build_cv_fixtures.py` to regenerate.

## #1 — Jan Novotný — Junior Data Analyst (DOCX)

- Files: `01_junior_da_novotny.docx`, `01_junior_da_novotny.txt`.
- Format-stress purpose: clean DOCX baseline; T07 must parse it cleanly via
  `python-docx` with no surprises.
- Role / seniority target: junior, ≤2 years total experience, narrow stack,
  no leadership signals.
- Anchors (verifiable substrings the pipeline can quote):
  1. "Junior Data Analyst" / 1 year at Mall.cz, Prague.
  2. "reducing reporting turnaround from 2 days to 4 hours" — quantified
     outcome.
  3. "18 dbt 1.7 models on PostgreSQL 15" — tech stack with versions.
  4. "column-level tests covering 92% of business-critical fields".
  5. "pandas 2.2" / "Python 3.11" stack signal.
  6. "6.4% drop in repeat purchases among the Home & Garden segment" —
     quantified analytical outcome.
  7. "11 alerts during my first rotation without escalation".
  8. "Bachelor of Economics and Management — VŠE Prague".
  9. "thesis on revenue forecasting using Prophet".
  10. Languages: Czech native + English C1 (FCE 2021).

## #8 — Tomáš Dvořák — Staff ML Engineer (PDF, two-column)

- Files: `08_staff_ml_engineer_dvorak.pdf`, `08_staff_ml_engineer_dvorak.txt`.
- Format-stress purpose: messy two-column reportlab PDF — uneven column
  widths (42% / 58%), header/footer bands, mixed serif body + sans header,
  diacritics requiring TTF embedding. Exercises pdfplumber's column-aware
  fallback when `pypdf` returns interleaved text.
- Role / seniority target: senior anchor — 13 years, 3 roles spanning Avast →
  Kiwi.com → ČSOB, leadership/staff signals (tech lead, guild founder, RFC
  author), broad+deep stack.
- Anchors (verifiable substrings):
  1. "Staff Machine Learning Engineer with 13 years of experience".
  2. "leading a team of 6 engineers and 2 data scientists" — leadership.
  3. "12M+ daily scoring calls" — scale.
  4. "cutting median inference latency from 240 ms to 38 ms" — quantified.
  5. "reducing infra cost by 41%" — quantified.
  6. "Founded the ML platform guild (8 engineers across 3 squads)" —
     leadership / org-design signal.
  7. "two-tower TensorFlow 2.8 retrieval-then-ranking architecture" — tech
     depth.
  8. "lifting click-through on the top-3 results by 17.4%" — quantified A/B.
  9. "4.2 billion file scans per month at peak" — scale at Avast.
  10. "Reduced false-positive rate from 0.32% to 0.11%".
  11. "calibrated LightGBM 2.1 model with weekly retraining".
  12. "Ing. (M.Sc.) in Computer Science — ČVUT FIT, Prague".
  13. "Bc. (B.Sc.) in Computer Science — VUT Brno".
  14. "Project Hermes (ČSOB, 2024)" — named project + outcome.
  15. "presented at MLPrague 2022" — community / external visibility.

## Calibration

The two CVs span the seniority gap T05's spike + T17's acceptance tests
require:

| # | Role | Years | Leadership | CZK/mo gross (rough) |
|---|---|---|---|---|
| 1 | Junior Data Analyst (Mall.cz) | 1 | none | 45–55k |
| 8 | Staff ML Engineer (ČSOB) | 13 | tech lead 6+2 | 160–220k |

T05 expects `score_spread ≥ 20` between these two on the same scoring rubric.
T17 expects `senior.salary.low > junior.salary.high` (no overlap).
