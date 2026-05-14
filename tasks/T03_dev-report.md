# /dev Report

**Task:** T03 — CI + pre-commit + warm-keeper workflows (engineering hygiene from day one)
**Branch:** dev/t03-ci-precommit
**Worktree:** /home/mf/GitHub/probable-goose-machine/.worktrees/t03-ci-precommit
**Stack:** py (uv-managed), gradio (UI flag set; this diff has no UI surface)

## Files touched
- .pre-commit-config.yaml (new) — pre-commit stage: end-of-file-fixer, trailing-whitespace, ruff-format, ruff-check --fix. pre-push stage: mypy strict (`src/gander`) + `pytest -m fast -q`. `default_install_hook_types: [pre-commit, pre-push]` so one `pre-commit install` registers both. `always_run: true` on the pre-push hooks so config-only pushes still gate.
- .github/workflows/ci.yml (new) — pull_request + push-to-main gate. `astral-sh/setup-uv@v3` with cache keyed on `uv.lock`, `uv sync --frozen`, ruff format-check + lint, `mypy src/`, `pytest -m "not slow" -v` (live tests included per user directive — `not slow` filter only excludes `slow`). Job env: `MINIMAX_API_KEY` from secrets, `GANDER_MODEL_PROFILE: ci`. Concurrency `ci-${{ github.ref }}` cancel-in-progress. `timeout-minutes: 10` on the job (heal-pass addition).
- .github/workflows/warm-keeper.yml (new) — cron `*/5 * * * *` + workflow_dispatch. Two-step job: (1) guard fails fast if `vars.HF_SPACE_URL` is unset, (2) `curl -sfI "$HF_SPACE_URL" || true` keeps the Space warm without reddening the cron history on cold-start 502s. `timeout-minutes: 2`.
- src/gander/llm.py, src/gander/schemas.py, tests/test_llm.py — auto-format reflows from the first `pre-commit run --all-files` pass on existing T01/T02 code (line-collapse where the original break wasn't required by 100-char limit). Cosmetic only; verified by reviewers — no semantic change to retry logic, MODEL_PRICES, judge isolation, or skipif gate.
- scripts/.gitkeep — empty-dir placeholder for T22's `scripts/eval_corpus.py`.
- tasks/T03_ci_precommit.md — Status: todo → done; Outcome flags two user actions (`MINIMAX_API_KEY` Secret + `HF_SPACE_URL` Variable in GitHub repo settings).
- tasks/todo.md — T03 ticked.
- tasks/T03_dev-plan.md — Phase 1 plan (201 lines); §7 risk note corrected during heal to remove the incorrect "live tests excluded by `-m \"not slow\"`" statement.
- tasks/backlog.md — 8 should-fix + 6 nit items appended (auto-unioned on merge via `.gitattributes` `merge=union`).

## Checks
| Command | Initial | After heal |
|---|---|---|
| `uv run pre-commit install` | pass (registers pre-commit + pre-push) | pass |
| `uv run pre-commit run --all-files` | pass (after first auto-fix pass settled) | pass |
| `uv run pre-commit run --hook-stage pre-push --all-files` | n-a | **pass** (mypy + pytest fast) |
| `python3 -c "import yaml; ..."` (3 files) | pass | pass |
| `uv run pytest -m fast -q` | 32 passed | 32 passed |
| `uv run mypy src/gander/` | pass | pass |
| `uv run ruff check .` / `ruff format --check .` | pass / pass | pass / pass |

## Review findings

### Must-fix (resolved this run)
- [codex] .pre-commit-config.yaml:21 — Local `mypy` had `pass_filenames: false` but no `always_run: true`; pre-push could skip when no `.py` files matched (e.g., config-only pushes affecting typing via `pyproject.toml` or `uv.lock`). **Fixed**: added `always_run: true`, removed redundant `types: [python]` filter.
- [codex] .pre-commit-config.yaml:28 — Same for `pytest-fast`; tests could skip on non-Python pushes. **Fixed**: added `always_run: true`.
- [hiring-manager] .github/workflows/ci.yml — Network-touching job (live MiniMax calls + DDG retrieval) had no `timeout-minutes`; a hung LLM response could burn the default 360-minute runner budget. **Fixed**: added `timeout-minutes: 10` at job level. Also added `timeout-minutes: 2` to warm-keeper for symmetry.
- [ux-engineer] .github/workflows/warm-keeper.yml — `curl -sfI ""` silently no-opped if `HF_SPACE_URL` was unset (`|| true` swallowed the empty-URL error); reviewer would get zero feedback that warm-keeper was doing nothing. **Fixed**: added an explicit guard step that hard-fails the workflow when the variable is empty, so the user sees red until they configure it. The `|| true` on the actual curl is preserved (intentional for cold-start 502 absorption — different failure mode).
- [hiring-manager] tasks/T03_dev-plan.md:195 — §7 risk note incorrectly claimed `-m "not slow"` excludes `live` markers (it doesn't — it only excludes `slow`). **Fixed**: rewrote the paragraph to correctly describe how `pytest.mark.skipif(not MINIMAX_API_KEY)` is the actual gate today, and that adding the secret will cause every PR to hit the live API.

### Should-fix (deferred)
8 items appended to `tasks/backlog.md` — covering: warm-keeper cron frequency tuning, format-pass bundling pattern (lessons.md), main-vs-PR concurrency split, `MINIMAX_API_KEY` step-level env scoping, `--strict-markers`, Outcome failure-mode prose, pre-push uv-not-installed guard, T22 user-action checklist mirror.

### Nits
6 items in `tasks/backlog.md` — `ruff` explicit paths, mypy `entry` DRY, Outcome accuracy for `tests/test_llm.py`, `scripts/.gitkeep` justification, PLAN §1 cite traceability, warm-keeper HTTP-status logging.

## Hiring grade
**on-bar** — the multi-agent burst converged on `on-bar` from all 5 reviewers (ai-ml-engineer, ux-engineer, product-owner, hiring-manager, codex). Pre-commit/pre-push split is well-reasoned, ruff `rev:` pinned to match the dev pin, concurrency-cancel rationale is sound. The heal-pass closed the four real reliability bugs (silent hook skip, missing job timeout, silent warm-keeper no-op, incorrect dev-plan documentation). Remaining gaps are tuning concerns deferred to backlog.

## Cleanup
When you're done with this work:
```
git worktree remove .worktrees/t03-ci-precommit
git branch -D dev/t03-ci-precommit
```
Or, to land it:
```
git checkout main
git merge --no-ff dev/t03-ci-precommit
```
