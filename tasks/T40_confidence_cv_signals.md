# T40 — CV-quality signals into confidence judge

Status: implemented — final private Profile.pdf rerun pending explicit approval
Owner: ai-ml-engineer
Depends on: T39 (Martin CV rerun verifies both fixes in one pass)
Unblocks: —
Estimate: ~75 min

## Goal

Surfaced from the same Martin-CV review session as T39: confidence read **High** while the score had silently dropped components, because [src/gander/confidence.py:68-86](../src/gander/confidence.py#L68-L86) only sees salary `sources`/`low`/`high`/`currency`/`period` and Step A's rubric ([src/gander/prompts/confidence_step_a.md:7-11](../src/gander/prompts/confidence_step_a.md#L7-L11)) judges purely on distinct salary domains + numeric spread. T38 already handles the hard-fail case (zero verifiable evidence → cascade); T40 fills the partial-extraction band between T38 and "all 4 components verified".

User intent (verbatim): "if we are unable to parse much from the cv, well the confidence should reflect that".

## Context

A CV where the L3 extractor pulled a sparse Profile (canonical_role unresolved, location missing) or L4a's `verify_quote` dropped 1-2 score components can still get **High** confidence today, because the salary search at [src/gander/pipeline.py:269-275](../src/gander/pipeline.py#L269-L275) might have returned 3+ tight DDG domains. Reviewer-visible outcome: a confident-looking salary band on a CV the system actually understood thinly. The fix widens the judge to receive CV-extraction quality signals and bakes a CV-floor rule into Step A, preserving the recompute-then-compare protocol (Step A stays the only tier authority).

## Approach

Widen `judge()` with a typed `CVQualitySignals` payload. Step A remains salary-source-only; deterministic code computes a CV-floor cap, emits `min(salary_tier, cv_floor)`, and passes the cap reason to Step B so the user-facing rationale does not blame market data for thin CV extraction. Pipeline builds the signals from `state.score.dropped`, `state.profile.role_normalization_source`, and `state.profile.detected_location` before the judge call.

## Critical files

- [src/gander/schemas.py](../src/gander/schemas.py) — new `CVQualitySignals(BaseModel)` near `Confidence`
- [src/gander/confidence.py](../src/gander/confidence.py) — widen `judge()` signature; keep Step A source-only; apply CV-quality cap and pass cap context into Step B
- [src/gander/prompts/confidence_step_a.md](../src/gander/prompts/confidence_step_a.md) — source-only salary-side rubric
- [src/gander/pipeline.py:269](../src/gander/pipeline.py#L269) — build `CVQualitySignals` from `state.score` + `state.profile` before calling `judge`
- [src/gander/pipeline.py:282](../src/gander/pipeline.py#L282) — short-circuit-Low branch unchanged (still Low when salary failed; CV signals don't matter there)
- [tests/test_confidence_unit.py](../tests/test_confidence_unit.py) — add cases for the combined rubric
- [tests/test_pipeline_smoke.py](../tests/test_pipeline_smoke.py) — pipeline-level case asserting `confidence_cv_floor_applied` emit

## Step-by-step changes

### 1. New schema — `CVQualitySignals` in [src/gander/schemas.py](../src/gander/schemas.py)

```python
class CVQualitySignals(BaseModel):
    """CV-extraction quality signals fed into the L4c confidence judge.

    Built in pipeline.py from successful Profile + Score so deterministic
    confidence code can cap the salary-side tier when extraction was thin
    (T40 — fills the band between T38's hard-fail gate and a fully-verified
    extraction).
    """
    dropped_score_components: int = Field(ge=0, le=3)  # at most 3 of {skills,education,soft_signals}
    canonical_role_resolved: bool
    location_detected: bool
```

Note the `le=3` bound: `experience` is mandatory per [src/gander/schemas.py:147-164](../src/gander/schemas.py#L147-L164) `_require_experience_component`, so the dropped count is capped at 3.

### 2. Widen `judge()` — [src/gander/confidence.py](../src/gander/confidence.py)

- Add keyword-only param: `judge(..., *, cv_quality: CVQualitySignals)`.
- Build `step_a_user` as a JSON object with one key:
  ```json
  {"sources": [...]}
  ```
- Emit a new event `confidence_cv_floor_applied` (with the salary-side tier and the cap) only when the cap actually lowered the tier. The current `confidence_step_a` event carries both `salary_tier` and final `tier`.
- Pass the final tier, salary tier, cap, and cap reason to Step B. The widened signature is keyword-only so the recompute-then-compare structural-isolation test still passes.

### 3. Step A prompt — [src/gander/prompts/confidence_step_a.md](../src/gander/prompts/confidence_step_a.md)

- Keep the input contract as `{"sources": [Source...]}` only.
- Keep the rubric focused on salary evidence only; the deterministic CV-floor cap lives in `confidence.py` so telemetry preserves the pre-cap salary tier separately from the final tier.

### 4. Pipeline wiring — [src/gander/pipeline.py:269](../src/gander/pipeline.py#L269)

- Just before calling `judge()`, build:
  ```python
  cv_quality = CVQualitySignals(
      dropped_score_components=len(state.score.dropped) if isinstance(state.score, Score) else 3,
      canonical_role_resolved=isinstance(state.profile, Profile) and state.profile.role_normalization_source != "unrecognized",
      location_detected=isinstance(state.profile, Profile) and state.profile.detected_location is not None,
  )
  ```
- Pass `cv_quality=cv_quality` to `judge()`.
- The `else` branch at line 281 (salary failed → Low) stays as-is — CV-quality is irrelevant when there's no salary at all.

### 5. Tests

- [tests/test_confidence_unit.py](../tests/test_confidence_unit.py) — add:
  - `test_cv_floor_caps_high_to_low_when_two_components_dropped` (mock LLM returns High; CV signals carry `dropped=2`; final tier=Low; `confidence_cv_floor_applied` emitted with `salary_tier="High"`, `cv_floor="Low"`).
  - `test_cv_floor_caps_high_to_medium_when_canonical_role_missing`.
  - `test_cv_floor_caps_high_to_medium_when_location_missing`.
  - `test_cv_floor_does_not_upgrade_low_to_medium` (clean CV; salary-side Low; final tier still Low; no cap event).
  - `test_judge_signature_keyword_only` (ensures the `cv_quality` param stays keyword-only — guards the recompute-then-compare structural test).
- [tests/test_pipeline_smoke.py](../tests/test_pipeline_smoke.py) — pipeline integration: build a state where Score has `dropped=["skills", "soft_signals"]`, salary clean → assert `state.confidence.tier == "Low"`.
- [tests/test_pipeline_smoke.py](../tests/test_pipeline_smoke.py) — assert the smoke run still produces a `Confidence` (not regressed by signature widening).

### 6. Out of scope (queued for follow-up)

- Anchor verify-rate as a third CV signal (more granular; needs bookkeeping changes in score.py to expose `verified/total`).

## Verification

1. `uv run pytest tests/test_confidence_unit.py tests/test_confidence_judge.py tests/test_pipeline_smoke.py` — all green.
2. Re-run the Martin CV through the full pipeline AFTER T39 lands. Expected: if L4a still drops 1+ components on Martin (it shouldn't, but if it does), confidence reads Medium/Low even with tight DDG agreement. If L4a verifies all 4, confidence is unaffected by T40.
3. Diff confidence tier across the EN/CZ acceptance fixtures with and without T40: only the fixtures with `score.dropped` non-empty should change.

## Risks

- Step A runs on the `cheap` model (MiniMax-M2.7-highspeed via `_PROFILE_MODELS`); a more complex rubric raises the chance of regression on the simple "all signals clean" path. Mitigation: rubric is strictly two-step (compute salary tier as today, then apply cap), so the clean branch stays identical to today's behavior.
- Backward compat: `judge()` signature change is keyword-only and internal — pipeline.py + the two test files are the only callers. No public API surface affected.
- T36 (senior_edu_anchor) is in flight on `verify_quote` and Score anchors. T40 only reads `Score.dropped`/`Profile.canonical_role`/`Profile.detected_location` — no collision.

## Outcome

Implemented:
- Added `CVQualitySignals` in `src/gander/schemas.py`.
- Widened `confidence.judge(..., *, cv_quality=...)`.
- Step A user payload remains `{"sources": ...}` only and stays blind to produced salary range/reasoning.
- Deterministic CV-floor cap applied after the salary-side tier: two dropped components -> Low; one dropped/missing canonical role/missing location -> Medium.
- Step B now receives the cap reason so Low/Medium rationales distinguish thin CV extraction from weak market data.
- Pipeline builds CV-quality signals from `state.score` and `state.profile` before calling the judge.

Verified:
- `uv run pytest tests/test_confidence_unit.py tests/test_confidence_judge.py tests/test_pipeline_smoke.py -m fast -v`
- full fast suite: `350 passed, 57 deselected`
- `uv run ruff check .`
- `uv run mypy src/`
- Live app-default Profile.pdf run on 2026-05-15 after the section-slicing fix
  reached all five stages. Score dropped `skills` and `soft_signals`; confidence
  rendered `Low`, proving the CV-quality cap path is visible in the user-facing
  report when parsing/scoring quality is thin.

Still pending before checking T40 done:
- Final private Profile.pdf rerun after the T39 role-prefix fix, with explicit
  approval to resend the local PDF to MiniMax/OpenRouter, to confirm any
  remaining dropped-score-components visibly cap confidence on the final salary
  role.
