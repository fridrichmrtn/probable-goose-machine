# T20 — L8 bias smoke test (CZ school prestige)

Status: done
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

Implemented (2026-05-14).

### Deliverables shipped

- `tests/test_bias_smoke.py` — single test `test_school_prestige_delta_within_threshold`, marked `live, slow, xdist_group("bias_smoke")`. Runs the full pipeline on the two CV #9 variants:
  - `09_research_phd_marek.pdf` — original, contains "MFF UK / Charles University".
  - `09b_research_phd_marek_anon.pdf` — same content, education line replaced with "[REDACTED UNIVERSITY]".
  - Asserts `abs(score_with_prestige.total - score_redacted.total) <= 3`.
  - On delta > 3, calls `pytest.xfail(...)` so the test reports the number without failing the build — PRD §4.7 limitation is documented, not gated.
  - Uses `record_property("bias_delta", delta)` so the value lands in JUnit XML and is recoverable from CI logs.
- `scripts/run_bias_smoke.py` — out-of-pytest runner that prints the same two scores + delta. Useful for filling in README §Limitations with a current number.

### Fixture pair

T06 / `scripts/build_cv_fixtures.py` already shipped both 09 and 09b on `main` (see `tests/fixtures/cvs/SOURCES.md` § #9). T20 reuses them as-is — no fixture work needed.

### Why this matters

PRD §4.7 names "school-name prestige" as a known leak in the regex-only redactor. The test puts a small honest number on the leak so the README can quote evidence rather than hand-wave. The xfail pattern is deliberate: the *value* of this probe is the observed delta; gating CI on a magic threshold would either be noise (too tight) or vacuous (too loose).

### Quality gates

- `uv run pytest tests/test_bias_smoke.py --collect-only` — 1 test collected.
- `uv run ruff check tests/test_bias_smoke.py scripts/run_bias_smoke.py` — clean.
- `uv run ruff format` — applied (one cosmetic line wrap each).
- `uv run mypy --strict src/gander tests/test_bias_smoke.py scripts/run_bias_smoke.py` — clean.

### Not run locally

No `MINIMAX_API_KEY` in this worktree. The live delta will be captured by:
- The CI live job (`pytest -m live`) — the JUnit XML retains `bias_delta` for inspection.
- `uv run python scripts/run_bias_smoke.py` once the operator has the key bound, for filling in README §Limitations.

T23 (README finalize) should quote the number from one of those two runs.
