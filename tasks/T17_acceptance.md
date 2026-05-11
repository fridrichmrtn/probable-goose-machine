# T17 — L8 acceptance tests

Status: todo
Owner: ai-ml-engineer
Depends on: T15, T06
Unblocks: T23
Estimate: ~90 min

## Goal

Encode PRD §5 in `pytest tests/test_acceptance.py`. If this passes against the 3-CV acceptance triplet (junior #1, mid #3, senior #8), the submission meets the hiring brief's quality bar. Strengthened beyond v1's verbatim-equality check to catch slop.

## Deliverables

- [ ] `tests/test_acceptance.py` — all marked `@pytest.mark.live, slow`. Use a session-scoped fixture that runs the pipeline once per CV and caches the resulting `Report`:
  ```python
  @pytest.fixture(scope="session")
  async def reports():
      out = {}
      for fname in ["01_junior_da_novotny.docx", "03_ds_horak.pdf", "08_staff_ml_engineer_dvorak.pdf"]:
          ...
          out[fname] = final_report
      return out
  ```
- [ ] Tests:
  - `test_score_spread_at_least_30(reports)` — `senior.score.total - junior.score.total >= 30`.
  - `test_salary_ranges_dont_overlap(reports)` — `senior.salary.low > junior.salary.high`.
  - `test_no_growth_plan_verbatim_repeats(reports)` — across all 3 reports' growth-plan items, no two `what` strings are equal.
  - `test_no_growth_plan_near_duplicates(reports)` — for every pair of `what` strings across CVs, `_jaccard_4gram(a, b) < 0.4` (uses helper from T13).
  - `test_growth_plan_anchors_distinct(reports)` — no anchor `quote` appears in more than one CV's growth plan.
  - `test_score_calibration(reports)` — *separate from the session fixture*: re-runs the mid CV 3× with `temperature=0`, asserts `max(scores) - min(scores) <= 5`.
  - `test_all_claims_substring_verified(reports)` — walks every `anchor.quote` in every report (Profile items, Score components, Growth actions); each must pass `verify_quote` against the corresponding source CV's redacted text.
  - `test_per_run_cost_budget(reports)` — sum of `usd_cost` events per pipeline run is < $0.05 (or < $0.02 when `JOBFIT_MODEL_PROFILE=ci`). README quotes both numbers.
- [ ] After acceptance tests run successfully once, **save the growth-plan items** of the 3 fixtures to `src/jobfit/data/growth_baseline.json` (used by T13's runtime n-gram smoke check; baseline lives inside the package so wheel installs keep the check wired).

## Verification

```bash
uv run pytest -m live tests/test_acceptance.py -v
```

If `test_score_spread_at_least_30` fails: the spread is too narrow → tighten the scoring rubric in T10's prompt or escalate the model.
If `test_salary_ranges_dont_overlap` fails: the salary estimator is anchoring to similar sources for both junior and senior → improve query construction in T11.
If `test_no_growth_plan_near_duplicates` fails: the growth-plan prompt is generic → tighten anti-slop rules in T13.

## Reference

- tasks/PLAN.md — § "L8 — Testing & Acceptance Verification"
- PRD.md §5

## Outcome

(fill in when done — actual numbers per acceptance test)
