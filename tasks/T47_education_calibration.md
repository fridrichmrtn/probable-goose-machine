# T47 — Education scoring rubric: degree-band calibration

Status: done — prompt, fast guard, PhD live, and bias live regression verified
Owner: software-engineer
Depends on: T10 (L4a scorer), T25 (score-partial / drop-as-zero)
Unblocks: PhD-and-multi-Master CVs landing in the 86–100 band as users expect
Estimate: ~30 min (prompt edit) + ~30 min (live regression + verification)

## Problem

A candidate CV with PhD + two Master's degrees scored 70/100 on the education
component. Root cause is in `src/gander/prompts/score.md`:

1. The absolute scale (`0–30 junior … 86–100 staff / principal`) is described in
   work-experience language. The LLM has no signal that a doctorate belongs in
   the top band when scoring the education component, so it lands a PhD at
   "senior" (~70) by default.
2. The one-line education definition (`formal credentials only — degree level,
   field, institution attendance dates`) is singular and gives no rule for how
   to treat multiple completed degrees.
3. The Score schema collapses N education items into one component score, so
   the LLM picks a single anchor quote and emits a single 0–100 number with no
   guidance to prefer the highest-credential line.

The Score schema, the 20 % education weight, and the four-component shape are
all out of scope. Prompt-only fix.

## Implementation

- `src/gander/prompts/score.md`
  - Replace the one-line `education:` definition with a band-mapped credential
    rubric (no degree → 0–30; partial → 31–50; Bachelor → 51–65; Master → 66–80;
    Doctorate → 86–100). Multiple advanced degrees push to the TOP of the
    highest applicable band. Preserve the existing prestige-blind rule and the
    "field-of-study fit is not an education signal" rule.
  - Reframe the existing "Absolute scoring scale" preface as applying to
    `skills / experience / soft_signals` only, with an inline pointer to the
    credential bands for education.
  - Add a bullet under "Evidence-based scoring rules": when a CV lists multiple
    degrees, the anchor quote must come from the HIGHEST credential line
    (PhD > Master's > Bachelor's), and the score must reflect that credential.

## Verification

- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_score.py tests/test_schemas.py -m fast --strict-markers -q`
- Fast prompt-contract guard:
  `tests/test_score.py::test_score_prompt_pins_education_credential_bands`
  asserts the doctorate band, multi-degree top-band rule, highest-credential
  instruction, and prestige-blind clause stay present.
- Add a live regression in `tests/test_score.py` that runs `score_profile` over
  the PhD fixture `tests/fixtures/cvs/09_research_phd_marek.txt` and asserts the
  surviving `education` component score is ≥ 85. Marker `live`, gated on
  `MINIMAX_API_KEY` / `OPENROUTER_API_KEY` like the existing senior live test.
- `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/gander/prompts/score.md` is
  not applicable (prompt is markdown). Run `uv run ruff check tests/test_score.py`
  on touched tests.
- Existing `tests/test_bias_smoke.py` PhD-prestige live test must continue to
  pass — the new rubric explicitly retains the prestige-blind clause, so the
  delta between `09_research_phd_marek` and `09b_research_phd_marek_anon`
  should stay within the existing tolerance.
- Spot-check end-to-end on the user's own CV through `scripts/eval_corpus.py`
  or the UI and confirm education lands in the 86–100 band.

## Out of scope

- Schema change to represent multiple education components (rejected; the
  single-component shape is preserved).
- Re-weighting the 20 % education share of `Score.total`.
- Field-of-study relevance / role-alignment scoring on the education axis.

## Outcome

Implemented the prompt-only calibration plus tests:
- `src/gander/prompts/score.md` now gives education its own credential bands
  instead of reusing work-experience seniority language.
- The education rule prefers the highest completed credential and pushes
  multiple advanced degrees toward the top of the highest applicable band.
- The prestige-blind clause remains explicit, so school name still must not
  move the education score.
- Added a fast prompt-contract test and a live PhD-fixture regression.
- The live PhD regression now skips cleanly when the selected provider's key is
  absent (`OPENROUTER_API_KEY` for `GANDER_LLM_PROVIDER=openrouter`, otherwise
  `MINIMAX_API_KEY`), matching the newer CZ acceptance suite's local-gating
  behavior.

Verified:
- `uv run pytest tests/test_score.py tests/test_schemas.py -m fast --strict-markers -q`
  → `36 passed, 4 deselected`.
- `uv run ruff check tests/test_score.py` → passed.
- `uv run pytest -m live tests/test_score.py -k phd_fixture_education_lands_in_doctorate_band -q`
  with no provider key in this shell → `1 skipped`.
- PR #35 OpenRouter live CI run
  `25932192588` / job `76228665081` → passed, including
  `tests/test_score.py::test_phd_fixture_education_lands_in_doctorate_band`
  and `tests/test_bias_smoke.py::test_school_prestige_delta_within_threshold`.
