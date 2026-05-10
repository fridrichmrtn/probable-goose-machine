---
name: audit-docs
description: Audit every documentation and skill artifact in this repo for staleness against its source of truth, then fix issues found. Tailored to the PRD → PLAN → INDEX → todo → T<NN> task-DAG and the eventual src/jobfit/ + tests/ + .github/ layout. Skip silently when a documented file is not yet built; report it once.
disable-model-invocation: true
---

# /audit-docs — Documentation drift audit

Perform a full audit of every documentation and skill file in this repo. Check each doc against its source-of-truth code or design artifact, fix all staleness, and report what changed.

This repo is a one-day candidate submission for a CV-evaluation pipeline. The build is staged across ~24 task files (`tasks/T<NN>_*.md`); most code in `tasks/PLAN.md` "Critical Files" is aspirational on day one and lands incrementally. The skill must distinguish:

- **Documented but not yet built** → skip silently, list once in the summary's "Not yet built — skipped" section. Never treat absence as a failure.
- **Built and doc is stale** → fix the doc (or flag the code-side discrepancy if the source artifact disagrees with itself).

Run from the repo root. Run **all** steps every invocation, regardless of which files are present. Do **not** commit; leave changes for the user to review.

---

## Step 0 — Scope and prioritisation

Build two sets up front:

```bash
git ls-files
```

For each path listed in [tasks/PLAN.md](../../../tasks/PLAN.md) §"Critical Files", classify it as `present` or `not_yet_built`. Stash both lists; the per-step summaries reference them.

Then check the recently-changed file list to prioritise attention (does **not** gate which steps run):

```bash
git diff main --name-only
# or, if currently on main:
git diff HEAD~20 --name-only
```

---

## Step 1 — Task-DAG consistency (the headline check)

Source of truth: the four-way agreement between [tasks/INDEX.md](../../../tasks/INDEX.md), [tasks/todo.md](../../../tasks/todo.md), [tasks/PLAN.md](../../../tasks/PLAN.md) §"Execution kickoff" task DAG, and the per-task files `tasks/T<NN>_*.md`.

Steps:

1. Glob `tasks/T*.md`. For each, parse the header block to extract `(id, title, status, owner, depends_on, unblocks)`. The header format is fixed by [tasks/PLAN.md](../../../tasks/PLAN.md) §"Step 2 — Decompose into discrete pickup-able task files".
2. Compare against [tasks/INDEX.md](../../../tasks/INDEX.md) §"Task list":
   - Every `T<NN>_*.md` file must appear as a row.
   - Every row must have a corresponding file (allow rows for tasks that haven't been authored yet — record them in `not_yet_built`, do not delete the row).
   - Titles must match.
3. Compare against [tasks/todo.md](../../../tasks/todo.md):
   - Every existing task file must have a checkbox line.
   - Every checkbox's `(tasks/T<NN>_*.md)` parenthetical must point at an existing file. If the parenthetical is wrong, fix it.
   - Status: an existing task file's `Status: done` must match a checked box `[x]`; `Status: todo` or `Status: wip` must match an unchecked `[ ]`. **The task file wins** when they disagree — update todo.md.
4. Compare against the table in [tasks/PLAN.md](../../../tasks/PLAN.md) §"Execution kickoff" §"Task DAG":
   - Same ID set, same titles, same `Depends on` set per ID.
   - The ASCII DAG image in INDEX.md is informational; eyeball it, do not parse.
5. Inside each task file, every ID listed under `Depends on:` and `Unblocks:` must exist in the canonical task set.

Fix policy: when docs disagree, prefer in this order: **task file > INDEX.md > todo.md > PLAN.md** (the task file is closest to the work; PLAN.md is the most aspirational).

---

## Step 2 — PRD ↔ PLAN coverage

Source of truth: [PRD.md](../../../PRD.md) §4 (Functional requirements) and §5 (Acceptance criteria).

Checks:

1. Each PRD §4.x bullet should be referenceable from [tasks/PLAN.md](../../../tasks/PLAN.md) by section name (e.g., §4.5 hallucination guard ↔ `verify_quote` in L0/L3/L4a/L5), by an L<N> phase, or by a T<NN> task. A §4.x bullet with no PLAN reference → **flag, do not auto-fix** (it's a design gap).
2. Each PRD §5 acceptance criterion must map to a planned test in [tasks/PLAN.md](../../../tasks/PLAN.md) §"L8 — Testing & Acceptance Verification". Missing mapping → flag.
3. **Submission deadline.** Compare PRD §"Submission deadline" + PLAN.md "Submission deadline" against today's date. If today is past the deadline, surface a banner at the top of the summary.
4. **Numeric drift.** When PLAN copy quotes PRD numerics (60s SLA, score spread ≥30, Jaccard ≤0.4, time horizons 1–24 months, ≥6 / ≥8 word `verify_quote` thresholds), the numbers must match. Fix PLAN to quote PRD literally.

---

## Step 3 — PLAN ↔ artifacts (skip-when-absent)

Source of truth: [tasks/PLAN.md](../../../tasks/PLAN.md) §"Critical Files".

For each path:

- **Absent** → record once in "Not yet built — skipped"; do not flag.
- **Present** → run the matching check below.

| Path | Check | Why |
|---|---|---|
| `pyproject.toml` | Python ≥3.11; pytest markers `fast`/`slow`/`live` declared; deps include those listed in PLAN "Tech Stack" (openai, gradio, pypdf, pdfplumber, python-docx, pydantic, structlog, ddgs, tenacity, pytest, pytest-asyncio, ruff, mypy). | PLAN claims the stack; pyproject is the runtime contract. |
| `requirements.txt` | Mirrors `pyproject.toml`; present whenever HF Space deploy is in scope (T22 done). | PLAN L9: HF Spaces builds from `requirements.txt`. |
| `app.py` | Imports `gradio`; references `pipeline.run`, `render_tracker`, `render_body`. | PLAN L7. |
| `src/jobfit/schemas.py` | Defines every model in PLAN L0 (`RawCV`, `RedactedCV`, `Profile`, `Component`, `Score`, `SalaryEstimate`, `Source`, `Confidence`, `GrowthAction`, `Report`, `StageFailure`) and the `StageStatus` literal `pending\|running\|done\|failed`. | PLAN L0 contract. |
| `src/jobfit/verify.py` | `verify_quote(quote, source, *, section=None) -> bool`; the rule (≥6 words AND positionally unique OR ≥8 words; section-locality where applicable) appears in module docstring or comment. | PRD §4.5 hardening. |
| `src/jobfit/llm.py` | `base_url="https://api.minimaxi.chat/v1"`; reads `JOBFIT_MODEL_PROFILE` env. | PLAN tech-stack table + CI config. |
| `src/jobfit/confidence.py` | `judge` signature is exactly `(sources, low, high, currency, period) -> Confidence` — five params, no others. | PLAN L4c structural isolation. |
| `scripts/spike_minimax.py` | argparse/click flags match PLAN L0.5 / T05 description. | PLAN L0.5 gate script. |
| `scripts/eval_corpus.py` | Iterates `tests/fixtures/cvs/*.{pdf,docx}`; writes `eval_outputs/SUMMARY.md` with the columns PLAN specifies. | PLAN "Eval corpus runner". |
| `tests/fixtures/cvs/SOURCES.md` | Lists all 10 fixtures; format split is 5 PDF + 5 DOCX; each entry has synthesis prompt + anchors + format-stress note. | PLAN "CV Corpus" table. |
| `tests/test_acceptance.py` | Function names: `test_score_spread_at_least_30`, `test_salary_ranges_dont_overlap`, `test_no_growth_plan_verbatim_repeats`, `test_no_growth_plan_near_duplicates`, `test_growth_plan_anchors_distinct`, `test_score_calibration`, `test_all_claims_substring_verified`, `test_per_run_cost_budget`. | PLAN L8. |
| `.github/workflows/ci.yml` | Runs `uv sync`, `ruff format --check`, `ruff check`, `mypy src/`, `pytest -m "not slow"`; sets `JOBFIT_MODEL_PROFILE=ci`. | PLAN L9 + T03. |
| `.github/workflows/warm-keeper.yml` | Cron `*/5 * * * *`; HEAD to Space URL. | PLAN cold-start mitigation. |
| `.pre-commit-config.yaml` | Hooks: ruff (format + check), mypy on `src/`, `pytest -m fast`. | PLAN L0. |
| `.env.example` | Lists `MINIMAX_API_KEY` and `ANTHROPIC_API_KEY`; plus any other env vars `src/jobfit/llm.py` reads at runtime. | PLAN L9 + L0. |

Fix policy: edit the **doc** when the doc is wrong. Code-side discrepancies are flagged, not auto-rewritten — `audit-docs` does not silently mutate source.

---

## Step 4 — CLAUDE.md model-layer drift

Source of truth: [CLAUDE.md](../../../CLAUDE.md).

Checks:

1. **Model layers.** CLAUDE.md must distinguish:
   - Claude Code / subagent infrastructure: Claude Opus-level reasoning is the coding-agent model layer.
   - Application runtime LLM: MiniMax via the OpenAI-compatible API (`MiniMax-M1` + `abab6.5s-chat`) is the submitted app's provider, with Claude Sonnet 4.6 only as the documented fallback if T05 fails.
   Do **not** replace the Claude infrastructure model with MiniMax; that collapses two different layers and creates stale guidance for agents.
2. **Subagent list.** Every name in CLAUDE.md §"Available local subagents" must have a `.claude/agents/<name>.md`. Every `.claude/agents/*.md` must appear in CLAUDE.md. Today: 5 ↔ 5.
3. **Path references.** Backticked paths in CLAUDE.md must resolve. References to planning artifacts (`tasks/lessons.md`, `tasks/todo.md`, `tasks/PLAN.md`) must exist or be acknowledged in CLAUDE.md as planned.
4. **Command examples.** `uv run pytest …`, `uv run ruff …`, `uv sync` are only checked once `pyproject.toml` exists. Skip silently before then.

Fix: edit CLAUDE.md.

---

## Step 5 — `tasks/lessons.md` format

Source of truth: [CLAUDE.md](../../../CLAUDE.md) §4 ("Self-Improvement Loop"), which prescribes:

```
- Date:
- Correction:
- Pattern:
- Rule:
```

Check every entry in [tasks/lessons.md](../../../tasks/lessons.md):

- All four fields present.
- `Date:` is absolute (`YYYY-MM-DD`), not relative ("yesterday", "last week").

Fix policy: if a field is missing or a date is relative, **do not fabricate** the missing content. Quote the CLAUDE.md template back at the user with the offending entry, ask them to fill in.

---

## Step 6 — Cross-reference integrity

Walk every markdown link `[text](path)` in:

- Root: [PRD.md](../../../PRD.md), [CLAUDE.md](../../../CLAUDE.md), `README.md` (when it lands).
- `tasks/`: every `.md` (`PLAN.md`, `INDEX.md`, `todo.md`, `lessons.md`, all `T<NN>_*.md`).
- `.claude/`: every `.md` under `agents/` and `skills/`.

For each relative link, resolve from the file's directory and verify the target exists. For each absolute repo path, check from repo root. Skip `https://`, `http://`, and `mailto:` links.

Fix or remove broken links — **do not invent new targets**.

---

## Step 7 — `.claude/` internal accuracy

Source of truth: directory contents under `.claude/`.

Checks:

1. For each `.claude/skills/*/SKILL.md`, verify the `name:` frontmatter equals the directory name (e.g., `dev/SKILL.md` has `name: dev`).
2. For each `.claude/agents/*.md`, verify the `name:` frontmatter equals the filename basename.
3. Every `/<skill-name>` mention inside any `.claude/**/*.md` must correspond to a real `.claude/skills/<skill-name>/SKILL.md`.
4. Every backticked agent name (`software-engineer`, `product-owner`, `ai-ml-engineer`, `ux-engineer`, `hiring-manager`) inside `.claude/**/*.md` must correspond to a real `.claude/agents/<name>.md`.
5. Code symbols mentioned in `.claude/**/*.md` (e.g., `verify_quote`, `StageStatus`, `pipeline.run`) — once `src/jobfit/` exists, grep that they still exist in the codebase. Skip silently before then.

Fix: edit the `.md` file to point at the real artifact.

---

## Step 8 — README.md (when it exists)

Source of truth: [tasks/PLAN.md](../../../tasks/PLAN.md) §"L9 — Deployment + README".

Skip silently until `README.md` lands. Once present:

1. **HF Space frontmatter** is YAML at the top with `sdk: gradio`, `app_file: app.py`, `python_version: 3.11`.
2. **Run** section quotes a hosted URL above the fold and the documented "First request may take ~20s" note.
3. **Decisions** section is non-empty and mentions: MiniMax + token plan, DuckDuckGo, Gradio + HF Spaces, regex-only PII, the cuts list, per-run USD cost.
4. **Bias acknowledgment** section exists (PRD §4.7).
5. **Limitations** section enumerates: single-language, no OCR, DDG dependency, MiniMax not benchmarked vs frontier, no fairness validation.
6. Quoted commands (`uv sync`, `uv run python app.py`, `uv run python scripts/eval_corpus.py`) match what `pyproject.toml` and `scripts/` actually expose.

---

## Step 9 — CV corpus consistency (when fixtures land)

Source of truth: [tasks/PLAN.md](../../../tasks/PLAN.md) §"CV Corpus" table.

Skip silently until `tests/fixtures/cvs/` exists. Once present:

1. Exactly 10 CV files (`.pdf` + `.docx` combined), 5 PDFs + 5 DOCX.
2. Filenames follow `{NN}_{role-slug}_{name-slug}.{pdf|docx}` per PLAN convention.
3. `SOURCES.md` lists all 10 with synthesis prompt + 5–15 anchors + format-stress note.
4. The 3 acceptance fixtures (rows 1, 3, 8 in the PLAN table — junior / mid / senior) are tagged in `SOURCES.md` as such.

Fix: update `SOURCES.md` when fixtures change. Flag (do not fix) when the corpus diverges from PLAN's table.

---

## Step 10 — Summarise

Print this table at the end of the run:

```
## Documentation Audit Summary

| Check | Files Checked | Issues Found | Issues Fixed | Skipped (not yet built) |
|---|---|---|---|---|
| 1. Task-DAG consistency        | … | … | … | — |
| 2. PRD ↔ PLAN coverage         | … | … | … | — |
| 3. PLAN ↔ artifacts            | … | … | … | … |
| 4. CLAUDE.md drift             | … | … | … | … |
| 5. lessons.md format           | … | … | … | — |
| 6. Cross-references            | … | … | … | — |
| 7. .claude/ internal accuracy  | … | … | … | — |
| 8. README.md                   | … | … | … | … |
| 9. CV corpus                   | … | … | … | … |
```

Then:

- **Changes made**, grouped by file (`path/to/file.md` → bulleted list of edits).
- **Flagged (not auto-fixed)** — design gaps, code-side discrepancies, unfilled lessons entries.
- **Not yet built — skipped** — one line per absent path from PLAN's "Critical Files".
- **Banner** at the top if today is past the PRD submission deadline.

Do **not** run `git add` or `git commit`. Leave the working tree dirty so the user reviews the diff.

---

## When NOT to use this skill

- During active implementation of a single task — finish the task, then audit. Running mid-task creates noise.
- For verifying that the code itself works — that's `pytest` + `/dev`. This skill audits **docs against artifacts**, not artifacts against behaviour.
- For one-off "is this link broken?" lookups — just grep.
