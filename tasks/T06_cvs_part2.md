# T06 — CV corpus part 2: remaining 8 CVs + SOURCES.md

Status: todo
Owner: software-engineer
Depends on: T04
Unblocks: T17, T20, T21
Estimate: ~2h

Can run in parallel with the stage-worker tasks (T07–T13).

## Goal

Round out the 10-CV corpus per the PLAN.md composition table. Author the synthesis-provenance log so the §1.4 "creativity in sourcing data" lens is visible.

## Deliverables

- [ ] Synthesize CVs #2–7, #9, #10 per the composition table in `tasks/PLAN.md` § "CV Corpus":
  - 02_da_svoboda (3y, marketing→DA, PDF clean LaTeX)
  - 03_ds_horak (5y, mid DS, PDF clean) — **acceptance: mid**
  - 04_mle_kralova (6y, ML eng, DOCX)
  - 05_mlops_benes (7y, MLOps, **PDF messy Word→PDF with footer cruft**)
  - 06_nlp_ds_pokorna (8y, NLP DS, DOCX)
  - 07_senior_ds_holub (10y, senior DS, PDF clean)
  - 09_research_phd_marek (12y, PhD academia→industry, PDF clean) — **needed for T20 bias smoke test (CZ school prestige signal)**
  - 10_head_of_data_zemanova (15y, leadership-heavy, DOCX)
- [ ] `.txt` extraction for each.
- [ ] `tests/fixtures/cvs/SOURCES.md` — per-CV entry:
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
ls tests/fixtures/cvs/*.{pdf,docx} | wc -l    # 10
ls tests/fixtures/cvs/*.txt | wc -l            # 10
# every PDF + DOCX must extract:
for f in tests/fixtures/cvs/*.pdf tests/fixtures/cvs/*.docx; do
  uv run python -c "from jobfit.ingest import extract_text; import sys; t = extract_text(open('$f','rb').read(), '$f'); assert len(t) > 200, '$f too short'"
done
# salary expectations are monotonically increasing across acceptance triplet (manual review)
```

## Reference

- tasks/PLAN.md — § "CV Corpus (Track E)"

## Outcome

(fill in when done — esp. any messy-PDF rendering tooling notes)
