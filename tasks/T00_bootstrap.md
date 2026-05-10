# T00 — Project bootstrap

Status: done
Owner: software-engineer
Depends on: —
Unblocks: T01, T03, T04
Estimate: ~30 min

## Goal

Stand up the Python project skeleton so `uv sync && uv run python -c "import jobfit"` works on a clean machine.

## Deliverables

- [x] `pyproject.toml` — `[project]` + `[tool.uv]` + `[tool.ruff]` + `[tool.mypy]` + `[tool.pytest.ini_options]` (with markers `fast`, `slow`, `live`, `pytest-asyncio mode = auto`).
- [x] Dependency pins (use `uv add ...`):
  - runtime: `openai`, `gradio`, `pypdf`, `pdfplumber`, `python-docx`, `pydantic>=2`, `structlog`, `ddgs`, `tenacity`
  - dev: `pytest`, `pytest-asyncio`, `ruff`, `mypy`, `pre-commit`
- [x] Directory layout:
  ```
  src/jobfit/__init__.py
  src/jobfit/prompts/        (empty for now, .gitkeep)
  tests/__init__.py
  tests/fixtures/cvs/        (.gitkeep)
  scripts/                   (.gitkeep)
  reports/                   (.gitkeep, gitignored contents)
  ```
- [x] `.gitignore` covering: `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `.env`, `reports/*` (but keep `.gitkeep`).
- [x] `.env.example` — `MINIMAX_API_KEY=` and `ANTHROPIC_API_KEY=` (commented as fallback) and `JOBFIT_MODEL_PROFILE=local`.
- [x] `README.md` — minimal frontmatter (HF Space metadata: `sdk: gradio`, `app_file: app.py`, `python_version: "3.11"`) + a one-line "see tasks/PLAN.md for architecture" stub. Full README is T23.
- [x] `app.py` — empty stub: `import gradio as gr; demo = gr.Blocks(); demo.launch()` so `uv run python app.py` doesn't error.

## Verification

```bash
uv sync
uv run python -c "import jobfit"          # exits 0
uv run pytest --collect-only              # no errors (no tests yet, just config check)
uv run ruff check .                       # clean
```

## Reference

- tasks/PLAN.md — § "L0 — Foundation"
- tasks/PLAN.md — § "Tech Stack (decisions confirmed)"

## Outcome

Bootstrap landed on branch dev/t00-project-bootstrap. Verification: uv sync + import + pytest collect + ruff + mypy all green.
