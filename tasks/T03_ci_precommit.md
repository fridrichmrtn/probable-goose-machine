# T03 — CI + pre-commit + warm-keeper workflows

Status: todo
Owner: software-engineer
Depends on: T00
Unblocks: T22 (deploy depends on warm-keeper existing)
Estimate: ~30 min

Can run in parallel with T01/T02 once T00 is done.

## Goal

Wire engineering hygiene from day one: every commit is linted/formatted/typechecked + fast tests; every PR runs the full live test suite; the HF Space stays warm via cron.

## Deliverables

- [ ] `.pre-commit-config.yaml`:
  - `ruff` (format + check) on all files.
  - `mypy` on `src/`.
  - Local hook running `uv run pytest -m fast --no-header -q` on changed files (use the `local` repo type).
  - Hook for end-of-file fixer + trailing whitespace.
- [ ] `.github/workflows/ci.yml` — triggers on PR + push to `main`:
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
- [ ] `.github/workflows/warm-keeper.yml` — cron `*/5 * * * *`:
  ```yaml
  - HEAD request to ${{ vars.HF_SPACE_URL }} with curl -sfI
  - exit 0 even on non-2xx (Space waking up shouldn't fail the cron)
  ```
- [ ] `.github/workflows/release-eval.yml` (optional, can defer to T22) — manually-dispatched workflow that runs `scripts/eval_corpus.py` and uploads `eval_outputs/` as a build artifact.
- [ ] `pyproject.toml` updates — confirm `[tool.ruff]` line-length 100, target-version `py311`; `[tool.mypy]` strict mode on `src/jobfit/*`; `[tool.pytest.ini_options]` markers declared.

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

(fill in when done — esp. CI cost-per-run figure)
