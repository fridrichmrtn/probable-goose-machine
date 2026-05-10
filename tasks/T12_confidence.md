# T12 — L4c confidence judge (recompute-then-compare)

Status: todo
Owner: ai-ml-engineer
Depends on: T02, T05 (gate)
Unblocks: T15, T19
Estimate: ~45 min

## Goal

Judge salary-estimate confidence (Low/Medium/High) **independently** of the estimator. PRD §4.3 demands this be a separate reasoning step. v2 hardens the design beyond v1's "different prompt, same model" with two changes: different model AND a recompute-then-compare protocol.

## Deliverables

- [ ] `src/jobfit/prompts/confidence_step_a.md` — Step A system prompt:
  - Receives ONLY `sources` (URLs + snippets).
  - Walks the rubric: High = ≥3 independent sources agreeing within 25%; Medium = 2 sources OR wider agreement; Low = <2 sources OR disagreement >50%.
  - Outputs JSON `{"tier": "Low|Medium|High", "rationale_short": str}`.
  - Does **not** see the produced range.
- [ ] `src/jobfit/prompts/confidence_step_b.md` — Step B system prompt:
  - Receives the produced `(low, high, currency, period)` plus Step A's tier (as a fact).
  - Writes one paragraph of human-readable rationale.
  - **Constraint enforced in code, not prompt**: if Step A's tier is "Low", the final rationale must contain "insufficient" or "disagree" (case-insensitive); else regenerate once.
- [ ] `src/jobfit/confidence.py`:
  - **Exact signature** (do not add parameters):
    ```python
    async def judge(
        sources: list[Source],
        low: int,
        high: int,
        currency: str,
        period: Literal["month","year"],
    ) -> Confidence:
        ...
    ```
  - Step A: `tier_obj = await llm.complete_json(prompt="confidence_step_a.md", user=json.dumps(sources), schema=_TierOnly, model="cheap")`. Uses `abab6.5s-chat` via `model="cheap"` (different distribution from M1 estimator).
  - Step B: `rationale = await llm.complete_text(prompt="confidence_step_b.md", user=f"Step A tier: {tier_obj.tier}\nProduced range: {low}–{high} {currency}/{period}", model="cheap")`.
  - Final: `Confidence(tier=tier_obj.tier, rationale=rationale)`. **Step B can never override Step A's tier** — only writes the prose.
  - Wrapped in `stage_boundary("confidence")`.
- [ ] `tests/test_confidence_unit.py` (`@pytest.mark.fast`):
  - **Structural isolation test**: `inspect.signature(judge).parameters.keys()` is exactly `{"sources", "low", "high", "currency", "period"}`. Asserts no leak channel for estimator reasoning.
  - With Step A mocked to return "Low", final tier is "Low" regardless of the prose Step B produces. (`test_step_b_cannot_override_step_a`)

(More golden tests live in T19.)

## Verification

```bash
uv run pytest -m fast tests/test_confidence_unit.py -v
```

## Reference

- tasks/PLAN.md — § "L4c — Confidence Judge"
- PRD.md §4.3

## Outcome

(fill in when done)
