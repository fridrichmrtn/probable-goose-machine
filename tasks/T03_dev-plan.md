# T03 — Implementation Plan: CI + pre-commit + warm-keeper

Owner: software-engineer
Worktree: `.worktrees/t03-ci-precommit`
Depends on: T00 (already merged)
Status: planned, not implemented

---

## 0. Context check (pyproject.toml)

Read `pyproject.toml` in the worktree. Confirmed already-configured (no edits needed):

- `[tool.ruff]` — `line-length = 100`, `target-version = "py311"`, `src = ["src", "tests"]`, lint selects `E,F,I,UP,B,SIM`.
- `[tool.mypy]` — `python_version = "3.11"`, `strict = true`, `files = ["src/jobfit"]`.
- `[tool.pytest.ini_options]` — `asyncio_mode = "auto"`, markers `fast`/`slow`/`live` declared.
- Dev group has `pre-commit>=4.6.0`, `ruff>=0.15.12`, `mypy>=2.0.0`, `pytest>=9.0.3`, `pytest-asyncio>=1.3.0`.

No `pyproject.toml` changes required by this task. **Nothing missing — no flag.**

---

## 1. Files to create

| Path | Purpose |
|---|---|
| `.pre-commit-config.yaml` | Hook config: format/lint at commit (sub-second), type-check + fast tests at push. |
| `.github/workflows/ci.yml` | Lint, type-check, full non-slow test suite on PR + push to main. |
| `.github/workflows/warm-keeper.yml` | Cron HEAD-pings the HF Space every 5 min to avoid cold-start. |

Out of scope (do not create): `release-eval.yml` (deferred to T22 per task spec); any `pyproject.toml` edits.

---

## 2. Hook stage rationale (pre-commit vs pre-push split)

The original `T03_ci_precommit.md` puts mypy and `pytest -m fast` on the per-commit hook. We split them: ruff format/check + EOL/whitespace fixers on `pre-commit` (sub-second, won't tempt `--no-verify`), and mypy + `pytest -m fast` on `pre-push` (1–3 s, runs once per push instead of per commit). This keeps the inner commit loop fast — the single largest predictor of devs *actually using* the hooks — while still catching type errors and broken fast tests before they reach the remote. Using `default_install_hook_types: [pre-commit, pre-push]` means a single `uv run pre-commit install` registers both. CI re-runs everything as the authoritative gate, so a skipped local hook can't sneak in a regression.

---

## 3. `.pre-commit-config.yaml` sketch

```yaml
default_install_hook_types: [pre-commit, pre-push]
default_stages: [pre-commit]

repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: end-of-file-fixer
      - id: trailing-whitespace

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.12
    hooks:
      - id: ruff-format
      - id: ruff-check
        args: [--fix]

  - repo: local
    hooks:
      - id: mypy
        name: mypy (src/jobfit, strict)
        entry: uv run mypy src/
        language: system
        types: [python]
        pass_filenames: false
        stages: [pre-push]
      - id: pytest-fast
        name: pytest -m fast
        entry: uv run pytest -m fast -q
        language: system
        types: [python]
        pass_filenames: false
        stages: [pre-push]
```

Notes:
- ruff `rev` pinned to `v0.15.12` to match `dev.ruff>=0.15.12` in `pyproject.toml` (avoids drift between hook ruff and dev ruff).
- `pre-commit-hooks` pinned to `v6.0.0` (current stable as of 2026-05).
- `local` repo + `entry: uv run …` means hooks reuse the project's locked toolchain — no separate venv per hook.
- `pass_filenames: false` for mypy/pytest because both work on the project as a whole, not per-file.
- `ruff-check` uses `--fix` (auto-repair on commit). CI runs the strict `--check`-style equivalent (no `--fix`), which catches anything the local hook missed.

---

## 4. `.github/workflows/ci.yml` sketch

Pinned actions: `actions/checkout@v4`, `astral-sh/setup-uv@v3`.

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  check:
    runs-on: ubuntu-latest
    env:
      MINIMAX_API_KEY: ${{ secrets.MINIMAX_API_KEY }}
      JOBFIT_MODEL_PROFILE: ci
    steps:
      - uses: actions/checkout@v4

      - name: Set up uv
        uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
          cache-dependency-glob: uv.lock

      - name: Install dependencies
        run: uv sync --frozen

      - name: Ruff format check
        run: uv run ruff format --check .

      - name: Ruff lint
        run: uv run ruff check .

      - name: Mypy (strict, src/jobfit)
        run: uv run mypy src/

      - name: Pytest (not slow)
        run: uv run pytest -m "not slow" -v
```

Notes:
- `setup-uv@v3` provides Python via uv's pinned interpreter (`requires-python = ">=3.11"` resolves to whatever uv selects from `uv.lock`). No separate `actions/setup-python` — adding one would shadow uv's interpreter and risk version skew.
- `enable-cache: true` + `cache-dependency-glob: uv.lock` caches `~/.cache/uv` keyed on the lockfile, per spec.
- Job-level env exposes `MINIMAX_API_KEY` (must be set in repo Secrets) and `JOBFIT_MODEL_PROFILE=ci` (consumed by `jobfit.llm` once T05/T15 land).
- `concurrency` group cancels superseded PR runs; main pushes still serialize per-ref.
- Single `ubuntu-latest` runner — no matrix; one Python version is sufficient for a one-day submission.

---

## 5. `.github/workflows/warm-keeper.yml` (full)

```yaml
name: warm-keeper

on:
  schedule:
    - cron: "*/5 * * * *"
  workflow_dispatch:

jobs:
  ping:
    runs-on: ubuntu-latest
    steps:
      - name: HEAD-ping HF Space
        run: curl -sfI "${{ vars.HF_SPACE_URL }}" || true
```

Notes:
- No checkout step — pure curl, nothing in the repo is needed.
- `|| true` swallows non-2xx so a Space cold-start (502 while waking) doesn't redden the cron history. The point is *to wake it*, not to assert it's healthy.
- `vars.HF_SPACE_URL` is a **repo-level variable** (not a secret) — must be set in GitHub Settings → Variables before T22.

---

## 6. Verification plan

Run in this order from the worktree root. All must succeed.

| # | Command | Expected |
|---|---|---|
| 1 | `uv sync --frozen` | exit 0; pre-commit binary available via `uv run`. |
| 2 | `uv run pre-commit install` | exit 0; prints `pre-commit installed at .git/hooks/pre-commit` and `…/pre-push`. |
| 3 | `python -c "import yaml; [yaml.safe_load(open(p)) for p in ['.github/workflows/ci.yml','.github/workflows/warm-keeper.yml','.pre-commit-config.yaml']]"` | exit 0; all three files parse as valid YAML. |
| 4 | `uv run pre-commit run --all-files` | First run may exit 1 if EOL/whitespace fixers modify files — that's expected. |
| 5 | `uv run pre-commit run --all-files` | Second run **must** exit 0 (clean tree). |
| 6 | `uv run pre-commit run --hook-stage pre-push --all-files` | exit 0; runs mypy + pytest fast. |
| 7 | `uv run pytest -m fast -q` | exit 0; fast tests still green (unchanged from T01/T02 baselines). |

If step 5 fails, inspect the diff from step 4 and either (a) commit the auto-fix or (b) fix the lint error manually — do not silently re-run.

---

## 7. Risks / decisions

**Decision — ruff `--fix` on commit, `--check` in CI.** Local hook auto-repairs so devs aren't blocked by trivial issues; CI rejects anything that escaped (e.g., a `--no-verify` push). Avoids the failure mode where the hook modifies tracked files mid-commit without the dev noticing.

**Decision — pre-push runs mypy + fast tests.** Caller spec overrides the original `T03_ci_precommit.md` (which had both on pre-commit). The push-time placement keeps the per-commit hook sub-second while still gating the remote. Trade-off: `git push` adds ~1–3 s for mypy + the 32 fast tests (~0.5 s). Acceptable for the current test surface; revisit if fast suite grows past ~5 s.

**Decision — no `actions/setup-python`.** `setup-uv@v3` installs the interpreter uv selects per `uv.lock`. Adding a separate setup-python step would create two Pythons on `PATH` and risk uv falling back to the wrong one.

**Risk — `MINIMAX_API_KEY` and `vars.HF_SPACE_URL` not set.** These are user actions in GitHub repo settings, out of scope for this task. CI will run without `MINIMAX_API_KEY` (live tests are gated by the `slow`/`live` markers and excluded by `-m "not slow"`); warm-keeper will silently no-op (curl with empty URL → `|| true`). **Flag in T03 Outcome:** reviewer must add `MINIMAX_API_KEY` (Secret) and `HF_SPACE_URL` (Variable) before T22.

**Risk — pre-push pytest may run on a branch with broken tests mid-development.** Devs can `git push --no-verify` for WIP branches; CI is the authoritative gate. Document in the eventual README if this becomes friction.

**Risk — ruff hook version drift.** `pre-commit` rev (`v0.15.12`) pins the hook ruff; `pyproject.toml` pins the dev ruff with `>=0.15.12`. If `uv lock` ever bumps dev ruff to a version with breaking format-rule changes, the hook and CI may disagree. Mitigation: bump the `rev:` in lockstep when the dev pin changes. Not worth a renovate bot for a one-day project.

**Out of scope — release-eval.yml:** deferred to T22 per task spec. Do not create.
