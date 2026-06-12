# /dev Report

**Task:** Implement P1.1–P1.5 from `tasks/prod_readiness_plan.md` (the "P1 — first weeks" tier) — honest-AI UI framing, keep/redo results, operability (`run_id` + boot env check + Dockerfile), eval breadth, and the verify semantic-gap (claim–quote compatibility) gate.
**Branch:** dev/prod-readiness-p1
**Worktree:** /home/mf/github/probable-goose-machine/.worktrees/prod-readiness-p1
**Stack:** py, gradio (UI), precommit

## Commits (off `main`)
- `27860a5` — P1.3 operability: thread `run_id` (uuid4) through every `obs.emit` via an `obs.run_scope` ContextVar; make `LLMClient()` construction key-free (boot-time `check_env()` is the real gate); add Dockerfile.
- `4852367` — P1.1 honest-AI framing: "About this report" banner (copy grounded in PRD §4.7 / README, not invented) + `seniority_band` rendered next to the 0–100 score.
- `ed1d86b` — P1.2 keep/redo: Markdown download button; clear stale report on new upload; Cancel button for in-flight runs.
- `9c29da6` — P1.5 verify gap: `claim_supports_quote` Jaccard token-overlap gate (extract stage only), separate from anchor generation; deliberately-mismatched regression cases.
- `9492a6a` — P1.4 eval breadth: synthetic non-tech / career-changer / non-CZ fixtures asserting graceful degradation; slug-pinning documentation.
- `e2682e3` — heal: review must-fixes (check_env boot placement, run_id test coverage, cancel UX, docker hygiene, growth comment, degradation docstring).
- `42009c2` — slug re-pin (user-approved): Gemini 2.5 family was delisted from OpenRouter; re-pinned to `gemini-3.5-flash` (reasoning) / `gemini-3.1-flash-lite` (cheap/extract/vision) + a `live`-marked catalog guard.

## Files touched
- `src/gander/obs.py` — `run_scope` context manager + `current_run_id` ContextVar; `emit` stamps `run_id` internally (zero call-site churn).
- `src/gander/pipeline.py` — enter `run_scope(uuid4)` once at pipeline entry; reset on drain/cancel.
- `src/gander/llm.py` — key-free construction (placeholder key, `check_env()` is the gate); `_OPENROUTER_ROUTES` re-pinned to Gemini 3.x; route comment rewritten.
- `src/gander/report.py` — `_ABOUT_BANNER` (PRD §4.7-grounded) with markdown-in-HTML blank-line separators; seniority band in the score heading.
- `src/gander/verify.py` — `claim_supports_quote` / `_content_tokens` / `_STOPWORDS`; `drop_unverified(..., claim_attr=...)` with None-skip; `verify_claim_mismatch` obs event (no CV text).
- `src/gander/extract.py`, `src/gander/growth.py` — wire the gate at extract only; comments corrected.
- `app.py` — module-scope `check_env()` (HF imports the module; `__main__` never fires) with `GANDER_SKIP_ENV_CHECK` escape hatch; Markdown download (`_write_report_md`); clear-on-upload + hide dangling Cancel in `_on_file_change`; Cancel button + `_on_cancel`.
- `Dockerfile`, `.dockerignore`, `README.md` — additive local/alternative deploy path + docs.
- `.env.example`, `CLAUDE.md` — model-policy slugs updated to 3.x (tier intent unchanged).
- `tests/fixtures/cvs/14…fialova.txt`, `15…prochazkova.txt`, `16…neumann.txt`, `SOURCES.md` — synthetic degradation fixtures (no real CVs).
- `tests/test_obs.py`, `tests/test_pipeline_fast.py` — `run_scope` reset + run_id correlation (stage-boundary) + partial-drain cleanup tests.
- `tests/test_verify.py`, `tests/test_extract.py` — claim–quote gate + mismatch regression cases.
- `tests/test_degradation_synthetic.py` — out-of-corpus graceful-degradation assertions.
- `tests/test_render.py` — banner + band rendering (positive and negative).
- `tests/test_llm.py` — route/fallback expectations re-pinned to 3.x; strengthened env-override test; `live` catalog guard.
- `tests/test_concurrency.py` — minor run_id-related adjustments.

## Checks
| Command | Initial | After heal | After re-pin |
|---|---|---|---|
| `ruff format --check .` | pass | pass | pass |
| `ruff check .` | pass | pass | pass |
| `mypy src/gander` | pass | pass | pass (22 files) |
| `pytest -m fast --strict-markers` | pass | pass | pass (697 passed, 97 deselected) |

The `live`-marked tests (acceptance + the new catalog guard) were **not** run — they need an `OPENROUTER_API_KEY` and network, which this environment lacks.

## Review findings
Five reviewers fired in the Phase 3 burst (ai-ml-engineer, ux-engineer, product-owner, hiring-manager, qa-engineer). Codex was **skipped** — not on PATH.

### Must-fix (resolved this run)
- [product-owner / hiring-manager] `app.py:293` — `check_env()` sat inside `if __name__ == "__main__"`; HF Spaces imports the module, so boot-time env validation never ran in prod. Moved to module scope (gated by `GANDER_SKIP_ENV_CHECK=1` for keyless tooling).
- [ai-ml-engineer / product-owner] `src/gander/llm.py` — both the primary and fallback in every route pointed at the delisted Gemini 2.5 family (verified against the live OpenRouter catalog). Re-pinned to 3.x per the user-approved decision + a `live` catalog guard so it can't rot silently again. (Pre-existing on `main`, not a regression introduced by this branch.)
- [ux-engineer] `app.py` cancel path — cancelling the generator interrupted the final `yield`, leaving the UI stuck. `_on_cancel` now settles the UI; `_on_file_change` hides a dangling Cancel on new upload.
- [ux-engineer] `report.py` banner — `<details>` block lacked blank lines around the nested markdown (would not render). Added `\n\n` separators.
- [qa-engineer] run_id coverage ×2 — the correlation test only saw obs-silent stubs (added `test_run_id_present_on_stage_boundary_events` with emitting stubs); no cancel/partial-drain cleanup test (added `test_run_id_resets_after_partial_drain`).
- [qa-engineer] `tests/test_degradation_synthetic.py` — file docstring claimed an untested "salary fails → confidence Low" path; corrected to describe what is actually exercised.

### Must-fix (false alarm — no action)
- [product-owner] `tests/test_degradation_synthetic.py:34-38` — "fixture filenames referenced but not committed." The reviewer's Glob ran from the main checkout, which cannot see worktree-only files. Verified via `git ls-files`: all three `.txt` fixtures are tracked.

### Accepted deviations (documented, not "fixed")
- `src/gander/verify.py:237` — `_COMPAT_THRESHOLD = 0.10` ships instead of the plan's 0.15. Measured: lowest legitimate pair = 0.22 (≈2× margin). Reviewers concurred the measured value is better than the guessed one.
- Claim–quote gate is **extract-only** by design — score/growth call `verify_quote` directly (their own eval-graded paths). The verb-substitution case ("Led"/"Joined") is a known, documented limitation at this cost point.

### Should-fix / nits (deferred)
Appended to `tasks/backlog.md` under the `prod-readiness-p1` block (8 should-fix, 6 nits). Headlines: `llm.py:213` placeholder-key sentinel vs `""`; `_write_report_md` temp-file cleanup; Dockerfile `pip install uv` forward-compat; non-ASCII token drop in `_WORD_RE`; `_about_banner()` wrapper inline.

## Hiring grade
**strong** — judgment showed in the honest-AI framing grounded to the PRD rather than invented, the generation/grading separation in the P1.5 gate (cheap lexical check before any LLM), the measured-not-guessed threshold, and the disciplined escalation of the slug decision (gated runtime model-choice) instead of a silent rewrite.

## Remaining risks / unverified
- **Live paths unverified here:** the `openrouter-live` acceptance suite and the new `test_configured_slugs_present_in_catalog` guard need keys + network. The 3.x slugs were confirmed present in the live catalog by WebFetch during the session, but the automated guard has not executed in CI yet — it will run on the next `openrouter-live` lane.
- **Cancel/download UX** is verified by unit tests (UI wiring + run_id cleanup) but not by a live browser click-test (headless environment).
- **Re-pin is a runtime-cost/eval-baseline change.** Scores and per-call cost may shift vs. the 2.5 baseline; no live eval has been run against 3.x yet.

## Cleanup
When you're done with this work:
```
git worktree remove .worktrees/prod-readiness-p1
git branch -D dev/prod-readiness-p1
```
Or, to land it:
```
git checkout main
git merge --no-ff dev/prod-readiness-p1
```
