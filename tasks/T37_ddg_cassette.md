# T37 — Cassette/mock DDG for live acceptance + senior salary tests

Status: open
Owner: software-engineer (follow-up from T30 phase 1)
Depends on: T30 phase 1 (PR #10, merged at TBD)
Unblocks: removing defensive `_optional_growth` guard in
`tests/test_acceptance.py`; removing `@pytest.mark.flaky(reruns=2)` on
`tests/test_salary.py::test_senior_fixture_estimate_returns_czk_range`
Estimate: ~2 hours

## Symptom

DDG (duckduckgo_search) transport is the dominant source of CI flakes in
the `live` job. Two distinct flake shapes observed during the PR #10
merge train:

1. **`test_senior_fixture_estimate_returns_czk_range@ddg`** — DDG returns
   <2 valid sources, salary stage surfaces
   `StageFailure(user_message='Insufficient market data for this profile',
   debug_detail='model_urls=[]')`, test assertion `isinstance(result,
   SalaryEstimate)` fails. Iter 3 + iter 4 both hit this. Iter 5 absorbs
   it with `@pytest.mark.flaky(reruns=2)`; a clean fix is to record DDG
   responses and patch `_ddg_text` in the test fixture.

2. **Mid fixture `03_ds_horak.pdf` salary→growth cascade** in the
   acceptance triplet. CI run 25859428334: salary stage hit
   `DDGSException` on `data scientist salary Prague site:platy.cz OR
   site:profesia.cz`, the LLM returned an estimate with `model_urls=[]`,
   salary surfaced `StageFailure`, growth then surfaced
   `StageFailure('Cannot generate growth plan without salary baseline')`.
   Four acceptance tests choked on `isinstance(report.growth, list)`.
   Iter 5 absorbs this with `_optional_growth` helper that skips
   StageFailure'd CVs from cross-CV invariants (requiring ≥2 survivors).

The defensive guards keep CI green, but they obscure a real signal: if
DDG is unavailable for *all three* fixtures, the cross-CV survivor floor
trips with a misleading "need ≥2 CVs with usable growth" message.
Mocking DDG eliminates the entire class.

## Investigation steps

1. Capture a representative DDG response set for each of the 5
   live-acceptance + senior-salary queries:
   ```bash
   uv run python -c "
   from gander.salary import _ddg_text
   import json
   queries = [
       'data analyst salary Prague site:platy.cz OR site:profesia.cz',
       'data scientist salary Prague site:platy.cz OR site:profesia.cz',
       'staff machine learning engineer salary Prague site:platy.cz OR site:profesia.cz',
       # ...etc.
   ]
   for q in queries:
       print(q, '→', len(_ddg_text(q)), 'results')
       # capture full JSON to tests/fixtures/ddg/<slug>.json
   "
   ```
2. Inventory which queries the EN triplet fires under `build_queries`
   for each fixture (depends on `profile.canonical_role`,
   `profile.detected_location`, `profile.is_management`,
   `profile.detected_years_experience`).
3. Decide cassette format: per-query JSON files keyed by query string,
   loaded by a `patch_ddg` fixture in `conftest.py`.

## Fix paths (decide after investigation)

### Option A: pytest fixture patches `_ddg_text` (recommended)

- Add `tests/fixtures/ddg/` with per-query JSON cassettes.
- Add a `_patch_ddgs_live` fixture in `tests/conftest.py` that activates
  for the `live` marker and patches `gander.salary._ddg_text` to read
  from cassettes. Falls back to live network if cassette missing
  (logs a warning so we notice cassette drift).
- Live tests now exercise the full LLM path against deterministic DDG
  results — no transport flake possible.

Pros: tightest scope, deterministic, no test-shape change.
Cons: cassettes go stale when prompts change `build_queries`.

### Option B: VCR-style HTTP-level cassettes

- Use `pytest-recording` or `vcrpy` to record/replay HTTP at the
  requests/httpx layer.

Pros: doesn't depend on internal `_ddg_text` signature.
Cons: heavier dep, harder to inspect/edit cassettes.

### Option C: full mock with hand-curated fixtures

- Skip the live DDG entirely; tests use static `Source` lists.

Pros: simplest, fastest tests.
Cons: loses the "exercise real DDG once per CI run" signal.

## Verification

After landing T37:

- Remove `@pytest.mark.flaky(reruns=2)` from
  `test_senior_fixture_estimate_returns_czk_range` and confirm 10
  back-to-back CI runs pass.
- Remove `_optional_growth` from `tests/test_acceptance.py`, replace all
  call sites with `_require_growth`, and confirm acceptance suite passes
  10 back-to-back runs.
- Document cassette regeneration command in `tests/fixtures/ddg/README.md`.

## Reference

- PRD §4.6 (failure surfaces, blast-radius isolation)
- PRD §4.7 (growth depends on salary baseline)
- PR #10 self-heal iter 4 + iter 5 commits
- `src/gander/salary.py::_ddg_text` (transport boundary)
- `src/gander/salary.py::search` (the <2-sources StageFailure path)
- Existing `_patch_ddgs` fixture in `tests/test_salary.py` (template for
  the patching approach)
