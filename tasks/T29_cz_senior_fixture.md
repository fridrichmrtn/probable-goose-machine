# T29 — Acceptance eval: bilingual senior fixture + assertions (eval A)

Status: todo
Owner: ai-ml-engineer
Depends on: T24, T25, T26, T27
Unblocks: T30
Estimate: ~2h

## Goal

Add a synthesized bilingual CZ/EN senior-management CV fixture so the regression class that broke on Profile.pdf is permanently guarded by a live test. The current corpus is 100% English with market-standard headline titles — none of the existing fixtures exercise CZ section headers, multi-column PDF stress, or non-market headline strings.

The fixture must be fully synthesized (not derived from the operator's real CV) to keep `tests/` free of real-person PII. SOURCES.md must anchor a senior-management CZK row so deterministic salary asserts can run.

## Deliverables

- [ ] New persona text in `scripts/build_cv_fixtures.py`:
  - **Persona**: Czech bilingual senior data leader, ~12y experience, current title `"Member of Staff"` at a stealth startup, prior `"Head of Data Science"` at a CZ retail company, prior `"Senior Manager, AI & Data"` at a CZ enterprise. PhD applied ML.
  - **Headers in CZ**: `Pracovní zkušenosti`, `Vzdělání`, `Nejčastější dovednosti`, `Jazyky`, `Publikace`, `Certifikace`.
  - **Mixed bullets**: some EN technical bullets, some CZ short bullets, mirroring the real Profile.pdf shape.
  - **Headline tagline with comma**: `"Data Gardener | AI, Data Science & Engineering @Stealth"` (or equivalent) so T28's tagline fix is exercised end-to-end.
- [ ] Render fixture to `tests/fixtures/cvs/11_cz_member_of_staff_<surname>.pdf` (multi-column layout matching the real Profile.pdf shape). Also render plaintext to `tests/fixtures/cvs/11_cz_member_of_staff_<surname>.txt` for fast tests.
- [ ] `tests/fixtures/cvs/SOURCES.md`: add a new row for fixture #11 anchoring the expected senior-management salary band (e.g. 200k–300k CZK/mo gross), with at least 2 source URLs (platy.cz / profesia.cz) and a one-line provenance note.
- [ ] New `tests/test_acceptance_cz.py` (`@pytest.mark.live, slow`):
  - Session-scoped fixture that runs the pipeline once on fixture #11, caches the `Report`.
  - `test_score_succeeds_on_cz_senior` — `report.score` is `Score`, not `StageFailure`. `experience` component verified. `total >= 70`.
  - `test_score_dropped_components_at_most_one` — `len(report.score.dropped) <= 1` (we expect all 4 to land but allow one drop under T25 policy).
  - `test_salary_lands_in_senior_band` — `report.salary` is `SalaryEstimate`, `currency == "CZK"`, `period == "month"`, `high >= 180_000` (calibrated against SOURCES.md row #11).
  - `test_salary_non_overlap_with_junior` — load fixture #1 junior report (reuse session cache from T30 if available), assert `senior.salary.low > junior.salary.high`.
  - `test_pii_name_redacted` — assert at least one `kind="name"` entry in the audit log (T28 regression guard against the tagline bug).
  - `test_pipeline_all_done` — `final.statuses["score"] == "done" and final.statuses["salary"] == "done"`.
- [ ] CI wiring: add a path-filtered live job that runs `test_acceptance_cz.py` on PRs touching `src/gander/{score,salary,verify,ingest,redact,extract,normalize}.py` or `src/gander/prompts/**`. Run nightly otherwise. Path filter via GitHub Actions `paths:`.

## Verification

```bash
uv run pytest -m live tests/test_acceptance_cz.py -v
```

Expected: all 6 tests pass after T24 + T25 + T26 + T27 + T28 land. Failure of any of the 6 means the fix surface didn't fully land.

## Reference

- Plan: `/home/mf/.claude/plans/this-is-a-result-peaceful-blanket.md` § "T29 — Acceptance eval"
- PRD §5.3, §5.4, §4.7
- `tests/fixtures/cvs/SOURCES.md` (existing fixture provenance pattern)

## Outcome

(fill in when done — observed score, observed salary band, any cached numbers for the README)
