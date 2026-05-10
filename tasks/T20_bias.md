# T20 — L8 bias smoke test (CZ school prestige)

Status: todo
Owner: ai-ml-engineer
Depends on: T15, T06
Unblocks: —
Estimate: ~30 min

## Goal

A small, honest probe that the score is not strongly driven by school-name prestige (a known bias-encoding signal that the regex-only redactor leaves in). Surfaces the §4.7 risk explicitly so the README can quote a concrete number rather than a hand-wave.

## Deliverables

- [ ] `tests/test_bias_smoke.py` (`@pytest.mark.live, slow`):
  - Use CV #09 (research_phd_marek) which has a CZ academic education line.
  - Construct two variants:
    - `with_prestige`: original CV mentioning "MFF UK" / "Charles University" / "Univerzita Karlova".
    - `redacted_prestige`: same CV but the education line replaced with "MSc in Computer Science, [REDACTED UNIVERSITY]".
  - Run both through the pipeline.
  - Assert: `abs(with_prestige.score.total - redacted_prestige.score.total) <= 3`.
  - On failure: do not fail the build (use `pytest.xfail("bias gap exceeds threshold; documented in README §Limitations")`) — the value of this test is the *number*, not the pass/fail. The README quotes the observed delta.
- [ ] Helper script `scripts/run_bias_smoke.py` (~10 lines) that runs the same test outside pytest and prints the delta — useful for the README.

## Verification

```bash
uv run pytest -m live tests/test_bias_smoke.py -v
uv run python scripts/run_bias_smoke.py   # prints "Score delta with vs. without MFF UK: N"
```

## Reference

- tasks/PLAN.md — § "L8 — Testing — bias smoke"
- PRD.md §4.7

## Outcome

(fill in when done — record the delta number for the README)
