# T48 — Confidence source rubric and OpenRouter route-table refactor

Status: done — focused checks pass; full fast blocked by unresolved DOCX LFS pointers
Owner: software-engineer
Depends on: T12 (confidence judge), T41 (OpenRouter provider), T42 (OpenRouter Gemini defaults)
Unblocks: safer Flash-Lite default rollout and auditable confidence caps
Estimate: ~45 min

## Problem

The Flash-Lite default branch added a deterministic confidence cap beside the
LLM Step A rubric. The cap was useful, but it lived inline in
`src/gander/confidence.py` and parsed raw snippet text directly. That made it
easy for prompt text, Python heuristics, and tests to drift.

OpenRouter model routing also kept primary and fallback slugs in separate dicts
inside `src/gander/llm.py`, while tests repeated each logical slot manually.
Changing model order was therefore noisy and partially update-prone.

## Implementation

- Extract deterministic salary-source confidence into `gander.source_rubric`
  with a typed `SourceRubricResult`.
- Keep `judge(...)`, report schemas, model slot names, and `OPENROUTER_MODEL_*`
  env vars unchanged.
- Make the source rubric conservative:
  - fewer than two distinct domains is `Low`;
  - one median value is computed per distinct domain;
  - ranges contribute to that domain median;
  - mixed or ambiguous periods and missing numeric evidence do not cap.
- Keep `confidence_source_rubric_applied`, adding diagnostic fields for domain
  count, comparable value count, spread, and reason.
- Replace separate OpenRouter primary/fallback dicts with one typed route table.

## Verification

- Direct fast tests for one-domain Low, two-domain Medium, three-domain High,
  disagreement Low, duplicate domains, range snippets, mixed periods, and
  nonnumeric snippets.
- Confidence integration tests prove the source rubric can lower but cannot
  upgrade the model Step A tier, and Step A remains blind to the produced range.
- LLM route tests are parameterized across `reasoning`, `cheap`, `extract`, and
  `vision`, covering defaults, env overrides, and duplicate fallback removal.
- Run:
  - `uv run ruff check src/gander/source_rubric.py src/gander/confidence.py src/gander/llm.py tests/test_source_rubric.py tests/test_confidence_unit.py tests/test_llm.py`
  - `uv run mypy src/gander/source_rubric.py src/gander/confidence.py src/gander/llm.py`
  - `uv run pytest -q -o addopts= tests/test_source_rubric.py tests/test_confidence_unit.py tests/test_confidence_judge.py tests/test_llm.py`
  - `uv run pytest -q -o addopts= -m fast` when Git LFS fixtures are hydrated.

## Outcome

Implemented:
- `src/gander/source_rubric.py` now owns deterministic source-confidence
  evaluation and returns typed diagnostics.
- `src/gander/confidence.py` consumes the rubric result, only lowers Step A
  tiers, and emits cap diagnostics when the deterministic cap applies.
- `src/gander/llm.py` now uses a single typed OpenRouter route table while
  preserving `OPENROUTER_MODEL_*` and fallback env overrides.
- Added direct source-rubric tests, confidence integration guards, and
  parameterized OpenRouter route tests across all logical model slots.

Verified:
- `uv run ruff check src/gander/source_rubric.py src/gander/confidence.py src/gander/llm.py tests/test_source_rubric.py tests/test_confidence_unit.py tests/test_llm.py tests/test_pipeline_smoke.py`
  -> passed.
- `uv run mypy src/gander/source_rubric.py src/gander/confidence.py src/gander/llm.py`
  -> passed.
- `uv run pytest -q -o addopts= tests/test_source_rubric.py tests/test_confidence_unit.py tests/test_confidence_judge.py tests/test_llm.py tests/test_pipeline_smoke.py -m fast`
  -> `52 passed, 6 deselected`.
- `uv run pytest -q -o addopts= -m fast` -> `512 passed, 96 deselected`,
  `4 failed`; all failures are existing unresolved Git LFS pointer checks for
  `tests/fixtures/cvs/01_junior_da_novotny.docx`.
