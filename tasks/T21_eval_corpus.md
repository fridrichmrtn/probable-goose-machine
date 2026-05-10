# T21 — scripts/eval_corpus.py — 10-CV live runner

Status: todo
Owner: software-engineer
Depends on: T15, T06
Unblocks: T23 (README quotes outcomes from this)
Estimate: ~45 min

## Goal

The user's manual gauging surface. Runs all 10 CVs through the live pipeline end-to-end and writes inspectable per-CV reports + a summary table. Doubles as a reliability smoke test (exits non-zero on any pipeline failure).

## Deliverables

- [ ] `scripts/eval_corpus.py`:
  - Iterates over `sorted(tests/fixtures/cvs/*.{pdf,docx})`.
  - For each: read bytes, time the pipeline, collect the final `Report`.
  - Writes `reports/<cv_basename>.md` containing:
    - Header: filename, format, total latency, total cost.
    - The same markdown the Gradio UI would render (`render_body(report)`).
  - Writes `reports/SUMMARY.md`:
    ```md
    # Eval corpus run — <ISO timestamp>

    Profile: local (M1) | CI (abab6.5s) [whichever was active]

    | # | CV | Format | Score | Salary (CZK/mo) | Confidence | Top growth action | Cost (USD) | Latency (s) |
    |---|---|---|---|---|---|---|---|---|
    | 01 | junior_da_novotny | DOCX | 28 | 38,000 – 52,000 | High | Lead the customer-segmentation project end-to-end | $0.018 | 27.4 |
    | ...

    **Totals**: 10 reports, $X.XX total spend, average latency Ys, max Ys.
    ```
  - Exits non-zero if any CV produced a top-level `StageFailure` (ingest/redact failures) — those are bugs, not graceful degradation.
  - Concurrency: serial (avoid hammering DDG with 10 parallel queries from the same IP).
  - Adds a `--profile {local,ci}` flag that just sets `JOBFIT_MODEL_PROFILE` env var for this run.
- [ ] `reports/.gitkeep` + `.gitignore` covers `reports/*.md`.

## Verification

```bash
uv run python scripts/eval_corpus.py
ls reports/                      # 10 .md files + SUMMARY.md
cat reports/SUMMARY.md           # eyeball — totals look sane
echo $?                               # 0 unless there were ingest failures
```

After running once, manually scan SUMMARY.md and 2–3 individual reports. This is the user's gauging step — record observations in `tasks/lessons.md` if the outputs look off (and use those observations to revise prompts in the relevant T0X file).

## Reference

- tasks/PLAN.md — § "Eval corpus runner — `scripts/eval_corpus.py`"

## Outcome

(fill in when done — paste the SUMMARY table or a screenshot link)
