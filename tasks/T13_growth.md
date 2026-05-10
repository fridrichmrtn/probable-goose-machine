# T13 — L5 growth plan

Status: todo
Owner: ai-ml-engineer
Depends on: T02, T05 (gate)
Unblocks: T15
Estimate: ~60 min

## Goal

Generate 3–5 CV-specific actions to grow salary by ~30%, each achievable within 12–24 months. Anti-slop is the central design constraint — generic recommendations are non-conformant per PRD §4.4.

## Deliverables

- [ ] `src/jobfit/prompts/growth.md` — system prompt:
  - Receives `Profile`, the four `Component` scores (with justifications), and the salary midpoint as the salary baseline.
  - Returns JSON: `{"actions": [GrowthAction, ...]}` (3–5 items).
  - **Anti-slop rules** (verbatim list in the prompt):
    - DO NOT propose: "complete a PhD", "found a startup", "improve communication", "learn more", "network more".
    - DO NOT use phrases like "consider", "explore", or "look into" — actions must be concrete.
    - Every `what` field must reference a specific element from the candidate's CV (project, technology, role, gap).
    - Every `mechanism` field explains how the action moves the salary needle (e.g., "moves you from individual contributor to tech-lead band, which in CZ market adds 30–50k CZK/mo").
    - `time_horizon_months` ∈ [1, 24]. Pydantic enforces; out-of-range responses are dropped.
  - Includes a one-shot example.
- [ ] `src/jobfit/growth.py`:
  - `async def plan_growth(profile: Profile, score: Score, salary_midpoint: int, currency: str) -> list[GrowthAction]`:
    - Single `llm.complete_json(prompt="growth.md", ..., schema=_GrowthList, model="reasoning")` call.
    - For each action, `verify_quote(action.anchor.quote, redacted.text)` → drop unverified.
    - **Runtime n-gram smoke check** (logging-only, not blocking): for the live request, compute Jaccard 4-gram overlap of each new action's `what` against a stored corpus of fixture growth-plan items (`tests/fixtures/growth_baseline.json`, populated after T17 runs). If any pair > 0.6, emit `obs.emit("growth.possible_boilerplate", action=...)` warning.
    - Returns the surviving list.
    - Wrapped in `stage_boundary("growth")`.
  - Helper: `_jaccard_4gram(a: str, b: str) -> float` (used by both runtime smoke and the T17 acceptance test).
- [ ] `tests/test_growth_unit.py` (`@pytest.mark.fast`):
  - With LLM mocked to return one action with `time_horizon_months=30` → that action is dropped (Pydantic validation).
  - `_jaccard_4gram` returns 1.0 for identical strings, 0.0 for fully disjoint.

## Verification

```bash
uv run pytest -m fast tests/test_growth_unit.py -v
```

(End-to-end + cross-CV uniqueness lives in T17.)

## Reference

- tasks/PLAN.md — § "L5 — Growth Plan"
- PRD.md §4.4

## Outcome

(fill in when done — note any anti-slop iteration)
