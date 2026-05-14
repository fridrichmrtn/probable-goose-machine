# T06 — CV corpus part 2: remaining 8 CVs + SOURCES.md

Status: done
Owner: software-engineer
Depends on: T04
Unblocks: T17, T20, T21
Estimate: ~2h

Can run in parallel with the stage-worker tasks (T07–T13).

## Goal

Round out the 10-CV corpus per the PLAN.md composition table. Author the synthesis-provenance log so the §1.4 "creativity in sourcing data" lens is visible.

## Deliverables

- [x] Synthesize CVs #2–7, #9, #10 per the composition table in `tasks/PLAN.md` § "CV Corpus":
  - 02_da_svoboda (3y, marketing→DA, PDF clean LaTeX)
  - 03_ds_horak (5y, mid DS, PDF clean) — **acceptance: mid**
  - 04_mle_kralova (6y, ML eng, DOCX)
  - 05_mlops_benes (7y, MLOps, **PDF messy Word→PDF with footer cruft**)
  - 06_nlp_ds_pokorna (8y, NLP DS, DOCX)
  - 07_senior_ds_holub (10y, senior DS, PDF clean)
  - 09_research_phd_marek (12y, PhD academia→industry, PDF clean) — **needed for T20 bias smoke test (CZ school prestige signal)**
  - 09b_research_phd_marek_anon — bias-pair variant of #9 (generic school string); identical to #9 except the one school line, for the T20 bias smoke test.
  - 10_head_of_data_zemanova (15y, leadership-heavy, DOCX)
- [x] `.txt` extraction for each.
- [x] `tests/fixtures/cvs/SOURCES.md` — per-CV entry:
  ```md
  ## 03 — Data Scientist (mid)
  - **Persona**: Lukáš Horák, 5 yrs, Prague.
  - **Format**: PDF clean (LaTeX-rendered).
  - **Role / seniority targets**: data scientist, mid level (40–70 score band, 70–110k CZK/mo expected).
  - **Verifiable anchors** (what later stages can quote):
    - "led the customer churn model retraining for Mall.cz, reducing 30-day churn by 11%"
    - "Python 3.11, scikit-learn 1.4, MLflow 2.7"
    - …
  - **Format-stress purpose**: standard happy path; baseline.
  ```

## Verification

```bash
# 10 canonical personas (NN_*) + 1 bias variant (09b_*) = 11 fixture pairs.
ls tests/fixtures/cvs/[0-9][0-9]_*.{pdf,docx} | wc -l    # 10 canonical
ls tests/fixtures/cvs/[0-9][0-9]*_*.{pdf,docx} | wc -l   # 11 (canonical + 09b)
ls tests/fixtures/cvs/[0-9][0-9]*_*.txt | wc -l           # 11
# every PDF + DOCX must extract:
for f in tests/fixtures/cvs/*.pdf tests/fixtures/cvs/*.docx; do
  uv run python -c "from gander.ingest import extract_text; import sys; t = extract_text(open('$f','rb').read(), '$f'); assert len(t) > 200, '$f too short'"
done
# salary expectations are monotonically increasing across acceptance triplet (manual review)
```

## Reference

- tasks/PLAN.md — § "CV Corpus (Track E)"

## Outcome

Extended `scripts/build_cv_fixtures.py` in place with three additions on top of the T04 scaffold: a new `_build_clean_pdf()` helper (single-frame `BaseDocTemplate`, full-width Frame, header band drawn in `onPage`, same DejaVu fonts and serif body / sans heading as the messy template); a shared `_build_docx()` for the three new DOCX personas; and 9 persona block factories (`_svoboda_blocks`, `_horak_blocks`, `_kralova_blocks`, `_benes_blocks`, `_pokorna_blocks`, `_holub_blocks`, `_marek_blocks`, `_zemanova_blocks`). `_build_messy_pdf` gained an optional `footer_cruft` keyword (default `None`, so #08 renders byte-identical) used by #05 to draw a chrome line into the bottom of the body — the worst-case extraction CV. `_marek_blocks(school: str)` takes the school as a parameter so #09 and #09b call the same factory with different strings and diverge at exactly one point.

Rendering choices and deltas from the plan: the `_build_docx` shared helper is slightly more compact than the per-CV DOCX shape the plan offered as an alternative — three DOCX personas share a single function rather than three near-duplicate builders. The `main()` rendering loop is data-driven (a single `builds: list[tuple[stem, format, builder]]`), so adding/removing fixtures touches one list. Salary numbers stay in SOURCES.md only; CV bodies convey level via title, scope, team size, and seniority signals.

Verification evidence:
- `ls tests/fixtures/cvs/*.pdf tests/fixtures/cvs/*.docx | wc -l` → 11; `ls tests/fixtures/cvs/*.txt | wc -l` → 11.
- Every golden `.txt` is well above the 200-char floor (smallest is #01 at 1515 chars).
- `diff 09_research_phd_marek.txt 09b_research_phd_marek_anon.txt` returns one hunk on line 29 — the school line — and nothing else.
- `uv run pytest -m fast -q` → 40 passed, 1 deselected.
- `uv run ruff format --check scripts/ src/ tests/` → 14 files already formatted.
- `uv run ruff check scripts/ src/ tests/` → all checks passed.
- `uv run mypy src/gander` → no issues found in 6 source files (T06 didn't touch `src/`).
- `uv run pre-commit run --all-files` → clean (one one-time EOF auto-fix on `08_staff_ml_engineer_dvorak.txt`; re-run after the fix is fully green).

Known limitation: the plan's per-fixture extraction sanity step uses `gander.ingest.extract_text`, which lives in T07's scope and does not exist yet. The corresponding sanity gate was satisfied via `wc -c` on the gold `.txt` files (>200 chars on all 11) — substantively equivalent for this stage since the `.txt` files are written by the same `extract_pdf_text` / `extract_docx_text` helpers the pipeline will later wrap.
