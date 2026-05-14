# T10 — L4a seniority scorer

Status: done
Owner: ai-ml-engineer
Depends on: T02, T05 (gate)
Unblocks: T15
Estimate: ~45 min

## Goal

Produce a 0–100 seniority score with four named components (skills / experience / education / soft_signals), each carrying its own substring-verified justification quote. One structured LLM call (not four), to honor the latency budget.

## Deliverables

- [ ] `src/gander/prompts/score.md` — system prompt:
  - Returns JSON: `{"components": [Component, Component, Component, Component]}` — one per `["skills","experience","education","soft_signals"]`.
  - Per component: integer score 0–100; one-sentence justification; `anchor.quote` as a literal ≥6-word substring of the redacted CV.
  - Anti-paraphrase reminder; explicit definitions of each component (skills = breadth+depth of named technologies; experience = years + role progression; education = formal credentials; soft_signals = leadership / communication / domain).
- [ ] `src/gander/score.py`:
  - `async def score_profile(redacted: RedactedCV, profile: Profile) -> Score`:
    - Single `llm.complete_json(..., model="reasoning")` call returning the four components.
    - For each component, `verify_quote` against `redacted.text` (with `section=anchor.section` if set). Drops failures.
    - Computes `Score.total` via the weighted sum from `COMPONENT_WEIGHTS` (defined in T01). Surviving components only — dropped components contribute 0 weighted in the numerator AND get their weight removed from the denominator (graceful degradation: a CV with no education section doesn't get penalized to 0 on the education component, it just shrinks the denominator).
    - Wrapped in `stage_boundary("score")`.
- [ ] `tests/test_score.py`:
  - `@pytest.mark.fast`: aggregation math is deterministic given a fixed `Score.components` list (no LLM call).
  - `@pytest.mark.fast`: with one component dropped, the `total` re-normalizes correctly.
  - `@pytest.mark.live`: per acceptance triplet → score lands in expected band (junior < 40, mid 40–70, senior > 70).
  - `@pytest.mark.live, slow`: **calibration** — run mid fixture 3× with `temperature=0` → score variance ≤ 5.

## Verification

```bash
uv run pytest -m fast tests/test_score.py -v
uv run pytest -m live tests/test_score.py -v
```

## Reference

- tasks/PLAN.md — § "L4a — Seniority Scorer"

## Outcome

Shipped `src/gander/prompts/score.md`, `src/gander/score.py`, `tests/test_score.py`; fast suite green (2 passed, 3 live deselected); live junior/senior bands and calibration variance pending MINIMAX_API_KEY-equipped run (covered by T17 acceptance).
