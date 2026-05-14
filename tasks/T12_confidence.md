# T12 — L4c confidence judge (recompute-then-compare)

Status: done
Owner: ai-ml-engineer
Depends on: T02, T05 (gate)
Unblocks: T15, T19
Estimate: ~45 min

## Goal

Judge salary-estimate confidence (Low/Medium/High) **independently** of the estimator. PRD §4.3 demands this be a separate reasoning step. v2 hardens the design beyond v1's "different prompt, same model" with two changes: different model AND a recompute-then-compare protocol.

## Deliverables

- [ ] `src/gander/prompts/confidence_step_a.md` — Step A system prompt:
  - Receives ONLY `sources` (URLs + snippets).
  - Walks the rubric: High = ≥3 independent sources agreeing within 25%; Medium = 2 sources OR wider agreement; Low = <2 sources OR disagreement >50%.
  - Outputs JSON `{"tier": "Low|Medium|High", "rationale_short": str}`.
  - Does **not** see the produced range.
- [ ] `src/gander/prompts/confidence_step_b.md` — Step B system prompt:
  - Receives the produced `(low, high, currency, period)` plus Step A's tier (as a fact).
  - Writes one paragraph of human-readable rationale.
  - **Constraint enforced in code, not prompt**: if Step A's tier is "Low", the final rationale must contain "insufficient" or "disagree" (case-insensitive); else regenerate once.
- [ ] `src/gander/confidence.py`:
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

Shipped 2026-05-11. `judge(sources, low, high, currency, period) -> Confidence | StageFailure` (signature widened for parity with T10/T11; structural-isolation test still pins parameter keys). Step A's user payload is sources-only by construction (`json.dumps([s.model_dump(mode="json") for s in sources])`); `low`/`high`/`currency`/`period` are interpolated into Step B's user message exclusively. Both steps use `model="cheap"` which currently resolves to MiniMax-M2.7-highspeed via `_PROFILE_MODELS` — same model as the estimator, so the "different model distribution" property promised by `tasks/PLAN.md §L4c` is degraded to "different prompt + temperature isolation"; documented in code header and backlog. Step B's regenerate-once-on-Low path now appends a corrective hint to the retry's user message (so temp=0.0 retries are not byte-identical no-ops); if the second draft still lacks the `insufficient|disagree` marker, the code substitutes `_LOW_FALLBACK_RATIONALE` ("The underlying market data is insufficient or in disagreement, so treat this estimate as provisional.") and emits `confidence_low_fallback_used` — Low tier is never paired with confidently-positive prose. PRD §4.6 user copy pinned via module-level `_FAILURE_MSG = "Could not generate this section reliably"`; both LLM calls and the post-`complete_json` type-check route through explicit `StageFailure` returns rather than letting `stage_boundary` build `user_message=str(exc)`. 6 fast tests pass: signature isolation, Step A no-leak (low/high/currency/period substrings absent from Step A's user payload), Step B cannot override + regenerate path that ends in fallback, regenerate path that recovers when the second draft contains the marker, no-regenerate-when-marker-present, StageFailure-path when `complete_json` raises. See `tasks/T12_dev-report.md` for review burst details (5 reviewers including codex; 2 below-bar pre-heal; single heal pass closed all 8 must-fix items, the load-bearing one being the Low-tier-honesty fix #2/#8). Should-fix and nit residuals captured in `tasks/backlog.md`.
