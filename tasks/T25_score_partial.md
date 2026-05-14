# T25 — Score: experience-mandatory + re-normalized total (R2)

Status: todo
Owner: ai-ml-engineer
Depends on: —
Unblocks: T29, T30
Estimate: ~45 min

## Goal

`score.score_profile` currently emits `StageFailure("Could not verify enough scoring components from CV.")` if **any** of the four required components fails to verify. This is fail-all-or-nothing and diverges from `tasks/T10_score.md` line 23 (graceful-denominator spec). On a real bilingual senior CV, a single dropped component (e.g. `skills` because anchor section header didn't match) blocks the entire score block in the report.

Implement the policy chosen in the plan: **experience mandatory, others optional.** When `experience` verifies, render a partial Score over surviving components — **dropped components contribute 0 to the weighted total** (the existing 4-of-4 formula `sum(c.score_0_100 * weight)` is reused as-is; missing components simply don't contribute). When `experience` itself fails, keep the existing fail-closed StageFailure.

**Why "drop = 0" and NOT re-normalize against surviving weights**: the original spec re-normalized (`/ sum(surviving_weights) * 100`). AI/ML review caught two bugs in that approach: (1) the `* 100` is arithmetically wrong because `Component.score_0_100` is already on a 0–100 scale (verified in `src/gander/schemas.py::Score`), and (2) re-normalizing lets a senior who drops 3 components report `total = experience.score_0_100`, which can land *higher* than a junior with all 4 components verified — silently breaking the PRD §5.4 differentiation gate. Treating dropped components as 0 preserves cross-CV calibration (you cannot score better by failing verification) and aligns with PRD §4.5 "drop, don't fabricate."

## Deliverables

- [ ] `src/gander/schemas.py::Score`:
  - Loosen `_require_one_component_per_category` validator: require `experience` to be present; allow any subset of `{skills, education, soft_signals}` to be missing.
  - **Do NOT change `total` computation** — keep the existing formula (`int(sum(c.score_0_100 * COMPONENT_WEIGHTS[c.name]) + 0.5)`). With missing components, surviving weights sum to <1.0 and `total` is naturally lower; that's the intended penalty for verification miss.
  - Add `dropped: list[ComponentName] = Field(default_factory=list)` so renderer + obs see what was dropped.
- [ ] `src/gander/score.py:100-119`:
  - When `missing` is non-empty, branch:
    - `experience` in `missing` → keep existing StageFailure path.
    - `experience` not in `missing` → build `Score(components=[verified[name] for name in COMPONENT_WEIGHTS if name in verified], dropped=sorted(missing))`. Emit `obs.emit("score", "score_partial", dropped=sorted(missing), surviving=sorted(verified.keys()))`.
- [ ] `src/gander/report.py` Score section: when `score.dropped` is non-empty, render a one-line italic footer under the score block: `"_Note: {N} component(s) dropped (skills, soft_signals): no anchor verified against CV text._"` Match PRD §4.6 tone (clear, useful, not a stack trace).
- [ ] `tests/test_score.py`:
  - `test_score_partial_missing_skills` — model returns 4 components; only `experience`, `education`, `soft_signals` verify → returns Score with `dropped=["skills"]`. Total reflects 3-of-4 weighted sum, no re-normalization.
  - `test_score_partial_missing_two` — only `experience` + one other verify → returns Score with two dropped.
  - `test_score_experience_missing_still_fails` — experience drops → StageFailure with existing message.
  - `test_score_total_arithmetic_drop_as_zero` — concrete numbers: scores `{exp:80, edu:60, soft:40}` with weights `{exp:0.30, edu:0.20, soft:0.15}`, dropped `{skills:0.35}` → total = round(80×0.30 + 60×0.20 + 40×0.15) = round(24 + 12 + 6) = **42**. Compare to 4-of-4 baseline same exp/edu/soft + skills:50 → total = round(42 + 0.35×50) = round(59.5) = 60. Demonstrates dropped-component CV cannot beat the same CV with verified components.
  - `test_score_partial_no_inflation_vs_full_verification` — assert that for any score values, a partial-Score CV's `total` is strictly ≤ the same components' contribution in a 4-of-4 Score. Catches accidental re-normalization regression.
  - `test_score_partial_emits_obs_event` — uses `gander.obs.subscribe(callback)` to capture emitted events; asserts a `score_partial` event fires with `dropped=[<name>]` and `surviving=[...]` in the payload when partial path is taken. **Required per PRD §4.8** — without this assertion, the obs event is unprotected by CI.
  - Update existing fail-closed test to assert the new dropped-component path doesn't trigger when all 4 verify.

## Verification

```bash
uv run pytest tests/test_score.py -v
uv run mypy src/
```

## Reference

- Plan: `/home/mf/.claude/plans/this-is-a-result-peaceful-blanket.md` § "Decision (this session)"
- `tasks/T10_score.md` line 23 (original graceful-denominator spec)
- PRD §4.2, §4.5, §4.6

## Outcome

(fill in when done — actual normalization formula, tests counts, any prompt-side change considered)
