# T19 — L8 confidence-judge tests

Status: done
Owner: ai-ml-engineer
Depends on: T12
Unblocks: —
Estimate: ~30 min

## Goal

Prove the confidence-judge isolation and recompute-then-compare protocol actually work. The structural test is the strongest guarantee; the golden tests catch protocol regressions.

## Deliverables

- [ ] `tests/test_confidence_judge.py`:
  - **`test_judge_signature_is_isolated`** (`@pytest.mark.fast`):
    ```python
    import inspect
    from gander.confidence import judge
    params = set(inspect.signature(judge).parameters.keys())
    assert params == {"sources", "low", "high", "currency", "period"}, \
        "judge() must not accept estimator reasoning, profile, or score — leakage channel"
    ```
  - **`test_step_a_high_with_three_agreeing_sources`** (`@pytest.mark.live`):
    Construct 3 synthetic `Source` objects with snippets all citing salaries in a tight 100k–110k CZK range. Call `judge(...)`. Assert tier == "High".
  - **`test_step_a_low_with_one_source`** (`@pytest.mark.live`):
    Single `Source`. Assert tier == "Low".
  - **`test_step_a_low_with_disagreeing_sources`** (`@pytest.mark.live`):
    3 sources citing 50k, 100k, 200k (>50% spread). Assert tier == "Low".
  - **`test_step_b_cannot_override_step_a_low`** (`@pytest.mark.live`):
    Single source (Step A returns Low). Assert final `Confidence.tier == "Low"` AND rationale contains "insufficient" or "disagree" (case-insensitive). This guards the v2 protocol — Step B cannot rubber-stamp.
  - **`test_step_b_does_not_see_estimator_reasoning`** (`@pytest.mark.fast`):
    Render the Step B prompt template (need to expose `_render_step_b(tier, low, high, currency, period)` from `confidence.py`) and assert it contains none of: "estimator", "reasoning", "profile" (the words the v1 prompt could have leaked).

## Verification

```bash
uv run pytest -m fast tests/test_confidence_judge.py -v
uv run pytest -m live tests/test_confidence_judge.py -v
```

## Reference

- tasks/PLAN.md — § "L4c — Confidence Judge"
- tasks/PLAN.md — § "Plan v2 — Confidence judge isolated more aggressively"

## Outcome

(fill in when done — esp. whether Step A tier-mapping was reliable on first prompt iteration)
