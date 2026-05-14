# T21 — scripts/eval_corpus.py — 10-CV live runner

Status: done
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
  - Adds a `--profile {local,ci}` flag that just sets `GANDER_MODEL_PROFILE` env var for this run.
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

Implemented (2026-05-14).

### Deliverables shipped

- `scripts/eval_corpus.py` — serial runner.
  - Iterates `sorted(tests/fixtures/cvs/*.{pdf,docx})` — finds 11 fixtures (10 corpus CVs + 09b anonymised variant for T20 bias delta).
  - For each: reads bytes, times `pipeline.run`, takes the final `Report`, writes `reports/<stem>.md` with a header (format / latency / cost) + `render_body(report)`.
  - Writes `reports/SUMMARY.md` with the per-CV table + totals (count / total spend / avg + max latency).
  - Exits **non-zero** if any CV produced a `StageFailure` at `profile` or `score` level — those are top-level bugs, not graceful degradation. Salary/confidence/growth StageFailure does *not* trigger a non-zero exit (PRD §4.6 explicitly allows degraded blocks).
  - Serial execution (DDG queries are rate-sensitive; 10 parallel pipelines would draw throttles).
  - `--profile {local,ci}` sets `GANDER_MODEL_PROFILE` *before* `gander.*` is imported, so `LLMClient` picks the right model on first instantiation.
  - Additional `--fixture-dir` / `--output-dir` flags for non-default runs (e.g. round-2 reviewer CV).
- `reports/.gitkeep` — keeps the directory committed.
- `reports/SUMMARY.md` — committed **placeholder** with the table skeleton and instructions to regenerate. The `.gitignore` rule was extended to exclude SUMMARY.md from the per-CV `reports/*.md` ignore so T23 README can link to a stable on-disk path.
- `.gitignore` — added `!reports/SUMMARY.md` exception (comment explains).

### Why placeholder, not real numbers

No `MINIMAX_API_KEY` in this worktree. The script is verified to import, parse args, iterate fixtures, and import `gander` lazily so the profile env-var takes effect. Operator regenerates SUMMARY.md before T23 ships:

```bash
uv run python scripts/eval_corpus.py            # ~3-5 min @ local profile
uv run python scripts/eval_corpus.py --profile ci   # ~2-3 min @ cheap model
git add reports/SUMMARY.md
```

### Quality gates

- `uv run ruff check scripts/eval_corpus.py` — clean.
- `uv run ruff format scripts/eval_corpus.py` — clean.
- `uv run mypy --strict scripts/eval_corpus.py` — clean.
- `uv run python -c "from scripts.eval_corpus import _iter_fixture_paths; ..."` — yields all 11 fixtures in sorted order.
- `uv run python -c "from scripts.eval_corpus import _parse_args; print(_parse_args(['--profile','ci']))"` — picks up the flag correctly.

### Known minor

The spec table mentions 10 rows; the script produces 11 because 09b (anonymised marek_anon) is also a PDF in the corpus directory. Keeping it in the run is the honest behaviour (matches "iterates over sorted *.pdf/*.docx") and gives T23 a clean side-by-side for the bias-delta number from T20.
