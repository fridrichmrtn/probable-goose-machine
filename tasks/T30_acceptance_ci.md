# T30 — §5.4 differentiation eval wired into CI (close T17)

Status: todo
Owner: ai-ml-engineer
Depends on: T29
Unblocks: T17
Estimate: ~60 min

## Goal

`tasks/T17_acceptance.md` is `Status: todo` while T15 / T16 / T19 / T22 (HF Space deploy) all merged. The §5.4 differentiation eval — the gate that would have caught the bilingual-senior regression — is not running anywhere. T22 shipped without an automated quality gate behind it.

Ship the §5.4 acceptance test that should already exist per T17. Keep the triplet `[01_junior_da_novotny, 03_ds_horak, 08_staff_ml_engineer_dvorak]` as the EN baseline; once T29 lands, add fixture #11 (CZ senior) as an additional senior anchor so both EN and CZ senior CVs are guarded.

A pure non-overlap check (`senior.salary.low > junior.salary.high`) passes even when both bands compress toward the middle (the failure mode this report exposed: senior CV → IC band). Add a senior-multiplier check (`senior.salary.high >= 2.5 * junior.salary.high`) to catch "senior collapsed to mid" silently.

## Deliverables

- [ ] `tests/test_acceptance.py` (`@pytest.mark.live, slow`) — the test file T17 specs but never landed:
  - Session-scoped fixture that runs the pipeline once per CV in the triplet, caches the resulting `Report`. Mirror the fixture shape in [T17_acceptance.md:15-24](T17_acceptance.md).
  - `test_score_spread_at_least_30(reports)` — `senior.score.total - junior.score.total >= 30`.
  - `test_salary_ranges_dont_overlap(reports)` — `senior.salary.low > junior.salary.high`.
  - `test_senior_salary_multiplier(reports)` — `senior.salary.high >= 2.5 * junior.salary.high`. Catches the regression class that pure non-overlap allows.
  - `test_no_growth_plan_verbatim_repeats(reports)` — across the 3 reports, no two `what` strings equal.
  - `test_no_growth_plan_near_duplicates(reports)` — for every pair of `what` strings across CVs, `_jaccard_4gram(a, b) < 0.4` (helper from T13).
  - `test_growth_plan_anchors_distinct(reports)` — no anchor `quote` appears in more than one CV's growth plan.
  - `test_all_claims_substring_verified(reports)` — walks every `anchor.quote` in every report (Profile items, Score components, Growth actions); each must pass `verify_quote` against the corresponding source CV's redacted text.
  - `test_per_run_cost_budget(reports)` — sum of `usd_cost` events per pipeline run is `< 0.05` (or `< 0.02` when `GANDER_MODEL_PROFILE=ci`).
- [ ] `test_score_calibration` — separate from the session fixture: re-runs CV `03_ds_horak` 3× with `temperature=0`, asserts `max(scores) - min(scores) <= 5`. Mark `slow, live` and exclude from path-filtered runs (nightly only — calibration is expensive and noisy on small N).
- [ ] After acceptance tests run successfully once on `main`, save the growth-plan items of the 3 fixtures to `src/gander/data/growth_baseline.json` (per T17 deliverable, used by T13's runtime n-gram smoke check).
- [ ] Once T29 lands: add fixture #11 (CZ senior) as `senior_cz` to the same `reports` fixture. Add `test_score_spread_at_least_30_cz` and `test_salary_non_overlap_cz`. The CZ-specific salary band assertion lives in `tests/test_acceptance_cz.py` (T29) — this file owns the cross-fixture differentiation only.
- [ ] CI wiring: extend `.github/workflows/ci.yml::live` to also run `tests/test_acceptance.py` (it is currently `pytest -m live` so it should already be picked up — verify by grep). Path-filter is NOT needed here — acceptance must run on every PR that ships, not just code-touching ones, because prompt edits can also regress salary spread.
- [ ] **Remove the `@pytest.mark.xfail` markers** on `tests/test_score.py::test_junior_fixture_scores_below_40` and `tests/test_score.py::test_senior_fixture_scores_above_70` per T17 deliverable. Resolve via T25 (partial-score path) — once experience-mandatory landed, the senior fixture should land >70 with at most one dropped component.
- [ ] Update `tasks/T17_acceptance.md::Status` to `done` with a one-line outcome quoting the actual numbers observed (spread, salary multiplier, per-run cost).

## Verification

```bash
uv run pytest -m live tests/test_acceptance.py -v
```

Expected: all 8 tests pass on the EN triplet. After T29 lands, the CZ-extension tests pass too.

Failure-mode mapping:
- `test_score_spread_at_least_30` fails → tighten T10 score-prompt rubric or escalate model.
- `test_salary_ranges_dont_overlap` fails → T27 role-normalization regression; check `build_queries` output for both CVs.
- `test_senior_salary_multiplier` fails → senior collapsed to mid band; check whether `is_management` lift fired in salary prompt.
- `test_no_growth_plan_near_duplicates` fails → T13 anti-slop drift; tighten growth-plan prompt.

## Reference

- Plan: `/home/mf/.claude/plans/this-is-a-result-peaceful-blanket.md` § "T30 — Wire §5.4 differentiation eval into CI"
- [T17_acceptance.md](T17_acceptance.md) (currently `Status: todo` — this task closes it)
- PRD §5.4

## Outcome

(fill in when done — observed score spread, salary multiplier, per-run USD cost, link to first green CI run)
