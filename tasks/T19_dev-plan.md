# T19 — L8 confidence-judge tests: dev plan

## Scope

Deliver `tests/test_confidence_judge.py` with the 6 tests from `tasks/T19_judge_tests.md` §Deliverables — 2 `@pytest.mark.fast`, 4 `@pytest.mark.live`. Extract a small `_render_step_b()` helper out of `src/jobfit/confidence.py::judge()` so the Step B prompt rendering can be unit-tested for leakage without an LLM call. No behaviour change to Step A, telemetry, regenerate-on-Low retry loop, or fallback paths.

## Files to modify

### `src/jobfit/confidence.py`

Extract the Step B user-message string into a pure module-level function. The current code (lines 108-110 of `src/jobfit/confidence.py`) inlines it inside `judge()`:

```python
        step_b_user = (
            f"Step A tier: {tier_obj.tier}\nProduced range: {low}-{high} {currency}/{period}"
        )
```

After:

```python
def _render_step_b(
    tier: str,
    low: int,
    high: int,
    currency: str,
    period: str,
) -> str:
    return f"Step A tier: {tier}\nProduced range: {low}-{high} {currency}/{period}"
```

…and `judge()` now calls it:

```python
        step_b_user = _render_step_b(tier_obj.tier, low, high, currency, period)
```

The retry-user string keeps appending the regenerate suffix to `step_b_user` exactly as today. The signature of `judge()` is unchanged. Telemetry, `_RATIONALE_LOW_REGEX`, `_LOW_FALLBACK_RATIONALE`, and `_FAILURE_MSG` are untouched. Existing T12 fast tests (`tests/test_confidence_unit.py`) continue to pass because the rendered user string is byte-identical to before.

Leading-underscore name is intentional: matches the existing convention (`_TierOnly`, `_LOW_FALLBACK_RATIONALE`, `_FAILURE_MSG`) and T12 tests already import private symbols from this module — so the import path `from jobfit.confidence import _render_step_b` works.

## Files to create

### `tests/test_confidence_judge.py`

Style matches `tests/test_confidence_unit.py`: `from __future__ import annotations`, `pytest` import, `Source` / `judge` / `Confidence` from `jobfit`, a small `_sources_*` helper per scenario. Live tests use `os.environ.get("MINIMAX_API_KEY")` skipif (pattern from `tests/test_salary.py:299-302`).

Six tests, exactly as spec'd:

1. **`test_judge_signature_is_isolated`** — `@pytest.mark.fast`. No mocks. Uses `inspect.signature(judge)` → `set(...parameters.keys()) == {"sources","low","high","currency","period"}`. Failure message asserts the leakage-channel rationale. (Effectively duplicates T12's `test_judge_signature_isolation`; spec explicitly lists both — keep both as the leakage-channel guard is the headline structural test.)

2. **`test_step_b_does_not_see_estimator_reasoning`** — `@pytest.mark.fast`. No mocks. Imports `_render_step_b` from `jobfit.confidence`. Calls it with representative args (e.g. `("Low", 100000, 200000, "CZK", "month")`). Lowercases the result. Asserts each of `"estimator"`, `"reasoning"`, `"profile"` is not in the lowered string. Single function call, three asserts.

3. **`test_step_a_high_with_three_agreeing_sources`** — `@pytest.mark.live` + `@pytest.mark.skipif(not os.environ.get("MINIMAX_API_KEY"), reason="needs MINIMAX_API_KEY")`. Builds 3 `Source` objects with distinct domains (e.g. `platy.cz`, `profesia.cz`, `glassdoor.com`); each snippet cites a salary in a tight 100k–110k CZK range. Calls `await judge(sources=..., low=100000, high=110000, currency="CZK", period="month")`. Asserts `isinstance(result, Confidence)` and `result.tier == "High"`.

4. **`test_step_a_low_with_one_source`** — `@pytest.mark.live` + skipif. Single `Source` with a credible snippet. Asserts `result.tier == "Low"` (Step A rubric: fewer than 2 distinct domains ⇒ Low).

5. **`test_step_a_low_with_disagreeing_sources`** — `@pytest.mark.live` + skipif. 3 sources, distinct domains, snippets citing ~50k, ~100k, ~200k CZK (median 100k → spread 100% > 50% threshold). Asserts `result.tier == "Low"`.

6. **`test_step_b_cannot_override_step_a_low`** — `@pytest.mark.live` + skipif. Single source so Step A returns Low. Asserts both `result.tier == "Low"` AND `re.search(r"insufficient|disagree", result.rationale, re.I)` matches. This is the v2-protocol guard — Step B prose cannot rubber-stamp Low away, and the regenerate-or-fallback loop guarantees the lexical marker.

Each live test passes `currency="CZK"`, `period="month"`. Numbers in snippets are stringified naturally (no exotic formatting) so Step A's median/spread reasoning has clean input.

## Mock strategy

- Fast tests: zero mocks. Test #1 inspects a signature, test #2 calls a pure function.
- Live tests: hit the real MiniMax API via `LLMClient` — no monkeypatching. The skipif decorator ensures offline runs are clean-skipped, not errored. T12 already proves the mocked Step A/B paths; T19's live tests are the protocol-regression net against prompt drift.

## Verification commands

```bash
uv run pytest -m fast tests/test_confidence_judge.py -v       # targeted fast
uv run pytest -m fast                                          # full fast suite (no regressions in test_confidence_unit.py)
pre-commit run --all-files
uv run mypy src
uv run pytest -m live tests/test_confidence_judge.py -v       # live, requires MINIMAX_API_KEY; document skip if unset
```

Live skip is documented inline (decorator `reason="needs MINIMAX_API_KEY"`) and in the final report when summarising T19.

## Risks / open questions

- **`_render_step_b` is private but imported by tests.** Same convention as T12 (`_TierOnly`, `_LOW_FALLBACK_RATIONALE`). Acceptable; no public-API contract widened.
- **Live tests are flaky-by-nature.** Real LLM, real network. Mitigated by deterministic Step A prompt (rubric is mechanical: count distinct domains, compute spread vs median) and `temperature=0.0` already set in `judge()`. If a tier assertion ever flakes, the diagnosis is prompt drift, not test bug — exactly what the test is meant to catch.
- **No new runtime dependencies.** All imports are stdlib (`inspect`, `os`, `re`) plus existing `pytest` and `jobfit.*`.
- **mypy strict on src only** (`pyproject.toml:41` — `files = ["src/jobfit"]`). The test file is not type-checked; no strict-mode burden.
- **No behaviour change to `judge()`.** The extraction is a pure refactor; existing T12 fast tests prove it (same byte-level user string preserved).
