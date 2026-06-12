# /dev Report

**Task:** Harden the L5 growth-plan stage per the 33-finding multi-agent review: five ordered changes (surgical heuristic fixes, retry redesign, prompt alignment, measurement, Plan B schema split) delivered as one commit train, with task-level tracking, docs, and tests.
**Branch:** dev/t50-growth-stage-hardening
**Worktree:** /home/mf/github/probable-goose-machine/.worktrees/t50-growth-stage-hardening
**Stack:** py (uv, ruff, mypy strict, pytest fast/slow/live), precommit, gradio

## Commit train

| # | Hash | Subject |
|---|---|---|
| C1 | 8b905c7 | T50: fix timeline, ban-phrase, and employer-candidate heuristics |
| C2 | 43e3ca9 | T50: pool verified survivors across retry attempts, degrade instead of failing |
| C3 | fbc09d4 | T50: align prompt anchor floor to 8 words and enforce softener ban |
| C4 | 17446aa | T50: add growth telemetry to eval runner and close test gaps |
| C5 | 2838e67 | T50: replace keyword employer gate with declared setting (Plan B) |
| heal | 25b19a2 | T50: address review findings |

Diff vs main (before docs commit): 13 files, +1102/−415; growth.py net −124 lines.

## Files touched

- src/gander/growth.py — retry pooling + degraded mode, softener gate, declared-setting validation, keyword-gate machinery deleted, telemetry enrichment, heal hardening of `_setting_violation`
- src/gander/timeline.py — `is_current` for end-year ≥ current-year and open-ended ranges
- src/gander/schemas.py — `GrowthAction.setting` (required literal) + `target_employer`
- src/gander/prompts/growth.md — 8-word anchor floor, untranslated-section guidance promoted, rule 7 rewritten to the declared-setting contract, examples carry new fields
- scripts/eval_corpus.py — per-CV growth telemetry via obs subscription, SUMMARY columns, corpus aggregates, >25% growth-failure exit gate
- tests/ — test_growth_unit.py, test_timeline.py, test_eval_corpus.py, test_schemas.py, test_render.py, test_failures.py, test_pipeline_fast.py
- tasks/T50_growth_stage_hardening.md — task file (goal/approach/steps/verification; status: implemented — live verification pending)
- tasks/T50_dev-plan.md, tasks/T50_dev-report.md, tasks/backlog.md — process artifacts (docs commit)

## Checks

| Command | Initial (per commit C1–C5) | After heal |
|---|---|---|
| uv run pre-commit run --all-files | pass | pass |
| uv run mypy src/ (strict) | pass | pass (20 files) |
| uv run pytest -q -m "not live" | pass — failure set byte-identical to the pre-existing 32-failure Git LFS fixture-pointer baseline at every commit | pass — 547 passed, same 32-failure baseline, zero new failures |

The 32 baseline failures predate this branch: git-lfs is not installed in this environment, so LFS-pointer fixtures cannot resolve. Verified byte-identical to `/tmp/t50_baseline_failures.txt` after every commit.

## Review findings

Reviewers: ai-ml-engineer, ux-engineer, product-owner, hiring-manager, qa-engineer (parallel burst).

### Codex

`codex CLI not found on PATH — skipping codex reviewer.` (captured verbatim; did not block Phase 4.)

### Must-fix (resolved this run, commit 25b19a2)

- [ai-ml-engineer + hiring-manager] growth.py `_setting_violation` — degenerate declared targets (" ", "—", "a", "of") rubber-stamped the bidirectional substring check. Fixed: punctuation-stripping normalization both sides + ≥3-alphanumeric gate; degenerate-target and punctuation-variant tests added.
- [qa-engineer] Attempt-2 invalid-output-with-pool degraded branch untested. Fixed: `test_plan_growth_degrades_when_second_attempt_returns_invalid_output` pins the degraded return, `growth_attempt_error` reason/got_type payload, and `growth_degraded`.
- [qa-engineer] `unverified_target_employer` top-up message branch untested. Fixed: `test_retry_message_renders_target_employer_and_matched_drops` pins the missing_target→"null" rendering, hint list, corrective instruction, and the "Matched:" line for ban/softener drops.
- [product-owner + hiring-manager] Task file said `Status: done` while the riskiest assumption (Gemini reliably emitting required `setting`/`target_employer`) is live-unverified. Fixed: status now "implemented — live verification pending"; test-count drift corrected.

Opportunistic (two reviewers each, same files): PRD §4.4 citation misattribution in debug_detail and module docstring reworded; dev-plan locked-contracts block updated to record the shipped attempt-2-degradation deviation.

### Must-fix (remaining — exhaustion)

None.

### Should-fix (deferred — see tasks/backlog.md block t50-growth-stage-hardening)

- [ai-ml-engineer] Top-up "exactly N NEW action(s)" contradicts the system prompt's "3 to 5 entries total"; request headroom.
- [ai-ml-engineer] Eval exit gate ignores the degraded rate; bound it at a looser threshold.
- [ai-ml-engineer + ux-engineer + product-owner] Degraded 1–2-action plans render identically to full plans; add a one-line honest caveat when count < 3 (three reviewers converged).
- [hiring-manager + product-owner] Closed-employer mislabel telemetry: observe-only signal + declared-setting distribution in emits/SUMMARY, so the surrendered keyword check stays observable.
- [hiring-manager] Zero-survivor stage_failure reports only the final attempt's drop_reasons; aggregate across attempts.
- [heal trade-off] ≥3-alnum gate drops legitimate 2-char companies (O2); consider a short-token allowance for verbatim hint matches.

### Nits

- count: 16 (listed in the backlog block, not here)

## Hiring grade

**on-bar** — "deliberate, well-explained, honestly-tested hardening that misses strong only because the replacement gate's matcher is trivially bypassable and the riskiest commit ships live-unverified under a 'done' label." Both blockers were resolved in the heal commit (matcher hardened + tested; status corrected). The deletion of ~250 lines of keyword heuristics was judged "judgment, not naivety."

## Verified / not verified

- **Verified:** all unit/contract behavior (547 passing tests incl. ~40 new), per-commit green train, mypy strict, ruff, prompt/code contract sync pins, deleted-symbol grep clean.
- **Not verified (named gate before merge):** live Gemini emission of the required `setting`/`target_employer` fields and a real `scripts/eval_corpus.py` run (no OPENROUTER_API_KEY in this environment). If Gemini under-complies, growth fails at the schema boundary on every CV — run live acceptance + eval_corpus before landing on main. `reports/SUMMARY.md` stays in the stale format until that run.
- **Residual accepted risk:** a model that writes a backward-looking `what` but declares `future_role` passes validation by design (the keyword gate it replaces was a demonstrated false-drop source); monitoring signal for this is a deferred should-fix.

## Cleanup

When you're done with this work:
```
git worktree remove .worktrees/t50-growth-stage-hardening
git branch -D dev/t50-growth-stage-hardening
```
Or, to land it:
```
git checkout main
git merge --no-ff dev/t50-growth-stage-hardening
```
