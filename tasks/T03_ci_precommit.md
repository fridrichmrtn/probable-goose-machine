# T03 — CI + pre-commit + warm-keeper workflows

Status: done
Owner: software-engineer
Depends on: T00
Unblocks: T22 (deploy depends on warm-keeper existing)
Estimate: ~30 min

Can run in parallel with T01/T02 once T00 is done.

## Goal

Wire engineering hygiene from day one: every commit is linted/formatted/typechecked + fast tests; every PR runs the full live test suite; the HF Space stays warm via cron.

## Deliverables

- [x] `.pre-commit-config.yaml`:
  - `ruff` (format + check) on all files.
  - `mypy` on `src/` (moved to `pre-push` stage — see plan §2).
  - Local hook running `uv run pytest -m fast -q` (moved to `pre-push` stage — see plan §2).
  - Hook for end-of-file fixer + trailing whitespace.
- [x] `.github/workflows/ci.yml` — triggers on PR + push to `main`:
  ```yaml
  - uv sync --frozen
  - uv run ruff format --check .
  - uv run ruff check .
  - uv run mypy src/
  - uv run pytest -m "not slow" -v   # full live suite per user directive
  env:
    MINIMAX_API_KEY: ${{ secrets.MINIMAX_API_KEY }}
    JOBFIT_MODEL_PROFILE: ci
  concurrency:
    group: ci-${{ github.ref }}
    cancel-in-progress: true
  # job-level concurrency: 1 (no parallel jobs across PRs to avoid DDG rate-limit collisions)
  ```
  - Uses `astral-sh/setup-uv@v3`.
  - Caches `~/.cache/uv` keyed on `uv.lock`.
- [x] `.github/workflows/warm-keeper.yml` — cron `*/5 * * * *`:
  ```yaml
  - HEAD request to ${{ vars.HF_SPACE_URL }} with curl -sfI
  - exit 0 even on non-2xx (Space waking up shouldn't fail the cron)
  ```
- [ ] `.github/workflows/release-eval.yml` (optional, can defer to T22) — manually-dispatched workflow that runs `scripts/eval_corpus.py` and uploads `reports/` as a build artifact. **Deferred to T22 per plan §1.**
- [x] `pyproject.toml` updates — confirm `[tool.ruff]` line-length 100, target-version `py311`; `[tool.mypy]` strict mode on `src/jobfit/*`; `[tool.pytest.ini_options]` markers declared. (Verified already-configured by plan §0; no edits needed.)

## Verification

```bash
uv run pre-commit install
uv run pre-commit run --all-files       # passes (or auto-fixes) on the bootstrapped tree
yamllint .github/workflows/*.yml         # if available; else just `cat` and eyeball
gh workflow list                         # shows ci, warm-keeper after first push
```

After T01+T02 land, push a PR — CI should run green.

## Reference

- tasks/PLAN.md — § "L0 — Foundation" (CI + pre-commit + warm-keeper)
- tasks/PLAN.md — § "Cold-start mitigation" (warm-keeper rationale)

## Outcome

Done. Created `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `.github/workflows/warm-keeper.yml`. Plan §2 split applied: ruff format/check + EOL/whitespace fixers run on `pre-commit` (sub-second), mypy + `pytest -m fast` run on `pre-push` (1–3 s). `default_install_hook_types: [pre-commit, pre-push]` means a single `uv run pre-commit install` registers both. Verification: pre-commit second pass clean, mypy clean, ruff clean, 32 fast tests pass. First pre-commit pass auto-formatted three pre-existing T01 files (`src/jobfit/llm.py`, `src/jobfit/schemas.py`, `tests/test_llm.py`) — pure formatter line-wrap reflows, no behavior change; required so CI's `ruff format --check` passes day one. Release-eval workflow deferred to T22 per plan.

**User actions required before T22 (cannot be done from code):**
1. Add repo **Secret** `MINIMAX_API_KEY` (GitHub → Settings → Secrets and variables → Actions → New repository secret) — consumed by CI's job-level env so live tests can reach MiniMax.
2. Add repo **Variable** `HF_SPACE_URL` (GitHub → Settings → Secrets and variables → Actions → Variables tab) — consumed by `warm-keeper.yml` to HEAD-ping the deployed Space every 5 min.
