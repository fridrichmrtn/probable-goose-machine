# /dev Report

**Task:** T01 — Pydantic schemas + StageFailure + stage_boundary skeleton (foundation contracts for Gander)
**Branch:** dev/t01-schemas
**Worktree:** /home/mf/GitHub/probable-goose-machine/.worktrees/t01-schemas
**Stack:** py, gradio (UI flag set on project; this diff has no UI surface)

## Files touched
- src/gander/errors.py — `StageFailure` Pydantic model + `stage_boundary` dual sync/async context manager.
- src/gander/schemas.py — Full Pydantic v2 contract surface (RawCV → Report), `COMPONENT_WEIGHTS`, `StageStatus`, `Score.total` `@computed_field` + heal-pass component-set validator, `Report.model_rebuild()`.
- tests/test_schemas.py — 6 fast-marked tests (parametrized to 10 collected items) covering Score weighting + duplicate/missing component rejection, GrowthAction range bounds, Report-with-StageFailure-in-each-block, and stage_boundary catch behavior.
- tasks/T01_schemas.md — Status: todo → done; Outcome line.
- tasks/todo.md — T01 checkbox ticked.
- tasks/dev-plan.md — Authored by the planning agent in Phase 1.
- tasks/backlog.md — Phase 4 backlog of deferred should-fix / must-fix-exhausted / nit findings (auto-unioned on merge via `.gitattributes` `merge=union`).

## Checks
| Command | Initial | After heal |
|---|---|---|
| `uv run pytest -m fast tests/test_schemas.py -v` | pass (8/8) | pass (10/10) |
| `uv run mypy src/gander/schemas.py src/gander/errors.py` | pass | pass |
| `uv run ruff check src/gander/schemas.py src/gander/errors.py tests/test_schemas.py` | pass | pass |

## Review findings

### Must-fix (resolved this run)
- [codex] src/gander/schemas.py — `Score.total` accepted duplicate/missing components; could exceed 100 or omit categories. Fixed: added `@model_validator(mode="after")` requiring `{c.name for c in components} == set(COMPONENT_WEIGHTS.keys())` AND no duplicates. Two new tests pin both rejection paths.

### Must-fix (remaining — exhaustion)
See `tasks/backlog.md` for full rationale. Two items deferred with clarifying docstrings instead of code changes:
- [ai-ml-engineer] `Anchor.section` Literal constraint — rejected because reviewer conflated CV-section vocabulary (open) with Component-name vocabulary (closed). Docstring added.
- [ai-ml-engineer] `SalaryEstimate.reasoning` split / `for_judge()` — rejected because PLAN §L4c judge takes individual fields, not the SalaryEstimate object; isolation enforced at T12 call site. Docstring added.

### Should-fix (deferred)
17 items appended to `tasks/backlog.md` — covering: `StageStatus` 5th state ("skipped"), `Report.statuses` key typing (3 reviewers converged), `Score.total` rounding mode, `Report` cost/duration aggregates, `Component.justification` / `GrowthAction.mechanism` un-anchoring, `Source.url` → `HttpUrl`, `Confidence.judged_by` field, +30% calibration field, async path testing, decorator form, `low<=high` validator, `KeyboardInterrupt` propagation test, `user_message` reviewer-facing docstring + leak prevention.

### Nits
count: 11 (full list in `tasks/backlog.md`)

## Hiring grade
**on-bar** — "contracts are well-shaped (Anchor, computed total, COMPONENT_WEIGHTS export) but stage_boundary carries untested async + a TODO instead of the obs-emit the spec required."

## Cleanup
When you're done with this work:
```
git worktree remove .worktrees/t01-schemas
git branch -D dev/t01-schemas
```
Or, to land it:
```
git checkout main
git merge --no-ff dev/t01-schemas
```
