# T25 — Score: experience-mandatory + re-normalized total (R2)

Status: todo
Owner: ai-ml-engineer
Depends on: —
Unblocks: T29, T30
Estimate: ~45 min

## Goal

`score.score_profile` currently emits `StageFailure("Could not verify enough scoring components from CV.")` if **any** of the four required components fails to verify. This is fail-all-or-nothing and diverges from `tasks/T10_score.md` line 23 (graceful-denominator spec). On a real bilingual senior CV, a single dropped component (e.g. `skills` because anchor section header didn't match) blocks the entire score block in the report.

Implement the policy chosen in the plan: **experience mandatory, others optional.** When `experience` verifies, render a partial Score over surviving components and re-normalize the weighted total against the surviving subset. When `experience` itself fails, keep the existing fail-closed StageFailure.

## Deliverables

- [ ] `src/gander/schemas.py::Score`:
  - Loosen `_require_one_component_per_category` validator: require `experience` to be present; allow any subset of `{skills, education, soft_signals}` to be missing.
  - Recompute `total` against surviving weights only: `total = round(sum(c.score * COMPONENT_WEIGHTS[c.name]) / sum(COMPONENT_WEIGHTS[c.name] for c surviving) * 100)` — i.e. the sum of weighted scores normalized by the sum of surviving weights, rescaled to 0–100.
  - Add `dropped: list[ComponentName] = Field(default_factory=list)` so renderer + obs see what was dropped.
- [ ] `src/gander/score.py:100-119`:
  - When `missing` is non-empty, branch:
    - `experience` in `missing` → keep existing StageFailure path.
    - `experience` not in `missing` → build `Score(components=[verified[name] for name in COMPONENT_WEIGHTS if name in verified], dropped=sorted(missing))`. Emit `obs.emit("score", "score_partial", dropped=sorted(missing), surviving=sorted(verified.keys()))`.
- [ ] `src/gander/report.py` Score section: when `score.dropped` is non-empty, render a one-line italic footer under the score block: `"_Note: {N} component(s) dropped (skills, soft_signals): no anchor verified against CV text._"` Match PRD §4.6 tone (clear, useful, not a stack trace).
- [ ] `tests/test_score.py`:
  - `test_score_partial_missing_skills` — model returns 4 components; only `experience`, `education`, `soft_signals` verify → returns Score with `dropped=["skills"]` and re-normalized total.
  - `test_score_partial_missing_two` — only `experience` + one other verify → returns Score with two dropped, re-normalized total.
  - `test_score_experience_missing_still_fails` — experience drops → StageFailure with existing message.
  - `test_score_total_renormalization_arithmetic` — concrete numbers: scores `{exp:80, edu:60, soft:40}` with weights `{exp:0.30, edu:0.20, soft:0.15}`, dropped `{skills:0.35}` → total = round((80*0.30 + 60*0.20 + 40*0.15) / (0.30+0.20+0.15) * 100) = round((24+12+6)/0.65 * 100) = round(64.62) = 65.
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
