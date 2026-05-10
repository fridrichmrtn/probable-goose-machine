# T00 — Project bootstrap: implementation checklist

Working directory: `/home/mf/GitHub/probable-goose-machine/.worktrees/t00-project-bootstrap` (branch `dev/t00-project-bootstrap`).

Scope: foundation only. No schemas (T01), no cross-cutting utils (T02), no CI / pre-commit / warm-keeper workflows (T03). Just: package skeleton, dependency pins via `uv`, directory layout, env example, HF Spaces README frontmatter, and a Gradio placeholder `app.py`. The existing root `.gitignore` already covers Python artifacts and is NOT to be touched.

## Steps

1. **Confirm `uv` is available.** Run `uv --version`. If missing, stop and surface the blocker — do not install via curl-pipe.

2. **Initialize `pyproject.toml` via `uv init --package`.** From the worktree root run `uv init --package --name jobfit --python 3.11 .`. If `uv init` refuses because files exist, hand-write `pyproject.toml` instead — see step 3 for the canonical contents. Either way the resulting `pyproject.toml` must end up matching step 3 exactly. Delete any `hello.py`, `src/jobfit/__init__.py` placeholder text, or scaffolded README that `uv init` drops; we own those contents.

3. **Hand-edit `pyproject.toml` to this shape** (rewrite if `uv init` produced a different layout):

   ```toml
   [project]
   name = "jobfit"
   version = "0.1.0"
   description = "Job Fit & Salary Estimator"
   requires-python = ">=3.11"
   dependencies = []  # populated by `uv add` in step 4

   [build-system]
   requires = ["hatchling"]
   build-backend = "hatchling.build"

   [tool.hatch.build.targets.wheel]
   packages = ["src/jobfit"]

   [tool.uv]
   package = true

   [tool.ruff]
   line-length = 100
   target-version = "py311"
   src = ["src", "tests"]

   [tool.ruff.lint]
   select = ["E", "F", "I", "UP", "B", "SIM"]

   [tool.ruff.format]
   # defaults — explicit section so future tweaks have a home

   [tool.mypy]
   python_version = "3.11"
   strict = true
   files = ["src/jobfit"]

   [tool.pytest.ini_options]
   asyncio_mode = "auto"
   testpaths = ["tests"]
   markers = [
     "fast: pure-function unit tests with no external IO (<1s each)",
     "slow: pipeline-level tests or anything >1s",
     "live: requires API keys (MiniMax, etc.) and network",
   ]
   ```

   Notes:
   - Keep `[project].dependencies = []` empty; `uv add` writes them in step 4.
   - `[tool.hatch.build.targets.wheel].packages = ["src/jobfit"]` is required because we use a `src/` layout and hatchling does not auto-detect it.
   - Do not add `[project.scripts]`, no console entrypoints — `app.py` is launched directly.

4. **Add runtime deps with `uv add`** (one command, in this order so the lockfile is deterministic):

   ```bash
   uv add openai gradio pypdf pdfplumber python-docx 'pydantic>=2' structlog ddgs tenacity
   ```

5. **Add dev deps with `uv add --dev`**:

   ```bash
   uv add --dev pytest pytest-asyncio ruff mypy pre-commit
   ```

   After steps 4–5 verify `uv.lock` exists and `pyproject.toml` `[project].dependencies` and `[dependency-groups].dev` are populated. Do not pin exact versions by hand — `uv add` picks current compatible ranges.

6. **Create the package directory layout.** Use `mkdir -p` then `touch` for `.gitkeep` files. Final tree (relative to worktree root):

   ```
   src/jobfit/__init__.py
   src/jobfit/prompts/.gitkeep
   tests/__init__.py
   tests/fixtures/cvs/.gitkeep
   scripts/.gitkeep
   eval_outputs/.gitkeep
   ```

7. **Write `src/jobfit/__init__.py`** with exactly:

   ```python
   __version__ = "0.1.0"
   ```

   (No re-exports, no `__all__`. T01 will populate the package; this is the import sentinel.)

8. **Write `tests/__init__.py`** as an empty file (just `touch`). Pytest uses `testpaths = ["tests"]` and rootdir conftest discovery; the empty `__init__.py` lets `tests` be importable if a future test wants relative helpers. No content.

9. **Write `.env.example`** at the worktree root:

   ```
   MINIMAX_API_KEY=
   # ANTHROPIC_API_KEY=   # fallback only — uncomment if T05 capability spike fails
   JOBFIT_MODEL_PROFILE=local
   ```

   Three lines. No commentary header — the file is self-explanatory and is checked into the repo as a template.

10. **Write `README.md`** at the worktree root (this is a new file — root has none yet):

    ````markdown
    ---
    title: Job Fit & Salary Estimator
    emoji: 📄
    colorFrom: indigo
    colorTo: purple
    sdk: gradio
    sdk_version: "<PINNED>"
    app_file: app.py
    python_version: "3.11"
    pinned: false
    ---

    Bootstrap stub — full README lands in T23. See `tasks/PLAN.md` and `tasks/T23_readme.md`.
    ````

    Replace `<PINNED>` with the exact `gradio` version from `uv.lock` after step 4 (look for the `[[package]] name = "gradio"` block, copy its `version = "x.y.z"`). The HF Space build pins `sdk_version` against this string, so it must match what's actually installed.

11. **Write `app.py`** at the worktree root:

    ```python
    import gradio as gr

    with gr.Blocks(title="Job Fit & Salary Estimator") as demo:
        gr.Markdown(
            "# Job Fit & Salary Estimator\n\n"
            "Pipeline not yet wired (T15 / T16). See `tasks/PLAN.md`."
        )

    if __name__ == "__main__":
        demo.launch()
    ```

    Must pass `ruff check` and `ruff format --check` as written. `mypy src/jobfit` does not see `app.py` (it's at repo root and `[tool.mypy].files = ["src/jobfit"]`); that is intentional — `app.py` grows in T16 and gets its own type coverage there.

12. **Do NOT touch `.gitignore`.** The existing root `.gitignore` already covers `.venv/`, `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.env`, `.env.*` (with `!.env.example`), `eval_outputs/*.md` (with `!eval_outputs/.gitkeep`), and IDE files. Re-adding any of this is out of scope for T00.

13. **Do NOT create any of the following** (out of scope, owned by other tasks):
    - `requirements.txt` (T22 exports it for HF Spaces)
    - `.pre-commit-config.yaml`, `.github/workflows/*.yml` (T03)
    - `src/jobfit/schemas.py`, `verify.py`, `obs.py`, `errors.py`, `llm.py` (T01, T02)
    - `tests/conftest.py` or any test files (T01+ as needed)
    - `tasks/todo.md` review section updates beyond marking T00 deliverables checked

## Verification (run from worktree root, in order)

```bash
uv sync
uv run python -c "import jobfit; print(jobfit.__version__)"   # prints 0.1.0
uv run python -c "import app"                                  # imports without launching server
uv run pytest --collect-only                                   # exits 0; "no tests ran" is fine
uv run ruff check .                                            # clean
uv run ruff format --check .                                   # clean
uv run mypy src/jobfit                                         # clean (only __init__.py to type)
```

All seven commands must exit 0 before T00 is done. If `ruff format --check` complains, run `uv run ruff format .` once and re-verify — the goal is the formatted state matches what we'd commit.

## Definition of done

- All deliverables in `tasks/T00_bootstrap.md` are checked.
- The seven verification commands above all pass on a clean `uv sync`.
- `git status` shows only intended additions (no stray `hello.py` from `uv init`, no editor swap files, no `requirements.txt`).
- `tasks/T00_bootstrap.md` Outcome section is filled with: gradio version pinned in README frontmatter, any deltas vs. this checklist, and the `uv` version used.
