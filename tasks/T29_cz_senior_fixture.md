# T29 — Acceptance eval: bilingual senior fixture + assertions (eval A)

Status: done — fixtures, live scaffold, and OpenRouter CI run verified
Owner: ai-ml-engineer
Depends on: T24, T25, T26, T27, T28
Unblocks: T30 (CZ extension only — EN-triplet baseline ships independently)
Estimate: ~3h

## Goal

Add **three** synthesized bilingual CZ/EN CV fixtures so the regression class that broke on Profile.pdf is permanently guarded by live tests. **Why three, not one**: a single CZ fixture replicates the operator-blindness that produced the EN-only corpus in the first place. T24's section-vocab regex would happily memorize fixture #11's exact aliases and pass; the next CZ CV with a slightly different header set would fail again. Three fixtures spanning shape variation force T24/T26/T27/T28 to actually generalize.

The current corpus is 100% English with market-standard headline titles — none of the existing fixtures exercise CZ section headers, multi-column PDF stress, or non-market headline strings.

Fixtures must be fully synthesized (not derived from the operator's real CV) to keep `tests/` free of real-person PII. SOURCES.md must anchor a senior-management CZK row per fixture so deterministic salary asserts can run.

## Deliverables

- [ ] **Three personas** in `scripts/build_cv_fixtures.py` spanning the CZ-CV shape space:
  - **#11 — Bilingual senior at stealth startup** (`11_cz_bilingual_member_of_staff_<surname>`):
    - ~12y exp, current `"Member of Staff"` at stealth, prior `"Head of Data Science"` at CZ retail, prior `"Senior Manager, AI & Data"` at CZ enterprise. PhD applied ML.
    - Headers in CZ: `Pracovní zkušenosti`, `Vzdělání`, `Nejčastější dovednosti`, `Jazyky`, `Publikace`, `Certifikace`.
    - Mixed bullets: some EN technical, some CZ short bullets — mirrors Profile.pdf shape.
    - Headline tagline: `"Data Gardener | AI, Data Science & Engineering @Stealth"` (exercises T28 + T27 tagline-shape).
    - Multi-column PDF layout (exercises F1).
  - **#12 — Czech academic senior researcher** (`12_cz_academic_<surname>`):
    - ~15y exp, current `"Vedoucí výzkumného týmu"` at a CZ university, prior `"Postdoctoral Researcher"` abroad. PhD + habilitation.
    - Headers in CZ only: `Akademická praxe`, `Vzdělání`, `Publikace`, `Granty`, `Výuka`, `Konference`.
    - Bullets in CZ only.
    - Headline is a market-token CZ title (`Vedoucí výzkumného týmu`) — exercises T27 market-token allowlist on CZ tokens.
    - Single-column PDF layout.
  - **#13 — Czech corporate manager (no English at all)** (`13_cz_corporate_manazer_<surname>`):
    - ~10y exp, current `"Manažer datového oddělení"` at a CZ bank, prior `"Senior analytik"` at a CZ telco, prior `"Datový analytik"` at a CZ retailer.
    - Headers in CZ: `Praxe`, `Vzdělání`, `Dovednosti`, `Jazyky`, `Reference`.
    - All bullets in CZ; no English anywhere.
    - Headline `"Manažer datového oddělení"` — market-token CZ.
    - Single-column PDF.
- [ ] Render each persona to both `.pdf` and `.txt` under `tests/fixtures/cvs/`. **Determinism**: pin font + reportlab/weasyprint version in `scripts/build_cv_fixtures.py`; commit the resulting PDFs (not regenerated in CI). Document in script docstring: "regeneration requires reviewer sign-off; PDFs are committed artifacts".
- [ ] `tests/fixtures/cvs/SOURCES.md`: add **three rows** (one per fixture) anchoring expected salary bands with ≥2 source URLs each (platy.cz / profesia.cz / paylab.cz). Calibrated to the persona's seniority + sector:
  - #11 stealth-senior: 200–300k CZK/mo gross
  - #12 academic-senior: 60–110k CZK/mo gross (academia is lower-paying)
  - #13 corporate-manager: 110–180k CZK/mo gross
- [ ] New `tests/test_acceptance_cz.py` (`@pytest.mark.live, slow`):
  - Session-scoped fixture that runs the pipeline once per CZ fixture, caches each `Report`.
  - **Per-fixture assertions** (parametrize where possible):
    - `test_score_succeeds_on_cz_<n>` — `report.score` is `Score`, not `StageFailure`. `experience` verified. `total >= 65` (lower than EN baseline; CZ verify_quote may drop 1 component).
    - `test_score_dropped_components_at_most_one_on_cz_<n>` — `len(report.score.dropped) <= 1` per T25 policy.
    - `test_salary_lands_in_expected_band_<n>` — currency CZK, period month, `low <= expected_low * 1.1` AND `high >= expected_high * 0.9` per SOURCES.md row.
    - `test_pii_name_redacted_<n>` — `count_name >= 1` event fired per T28.
    - `test_pipeline_all_done_<n>` — `final.statuses["score"] == "done" and final.statuses["salary"] == "done"`.
    - `test_role_normalized_event_per_fixture_<n>` — assert `role_normalized` event fires per fixture, with `source` matching expected per persona (`tagline_shape` for #11, `market_token` for #12 + #13).
  - **Cross-fixture**:
    - `test_salary_non_overlap_with_junior_for_seniors` — for fixtures #11 and #13 (both senior+), `salary.low > junior_fixture(#1).salary.high`. Skip for #12 (academia is lower than senior IC).
- [ ] CI wiring: add a path-filtered live job that runs `test_acceptance_cz.py` on PRs touching `src/gander/{score,salary,verify,ingest,redact,extract,normalize,tenure}.py` or `src/gander/prompts/**`. Run nightly otherwise. Path filter via GitHub Actions `paths:`.

## Verification

```bash
uv run pytest -m live tests/test_acceptance_cz.py -v
```

Expected: all per-fixture tests pass after T24 + T25 + T26 + T27 + T28 land. Failure on a *single* fixture isolates which root-cause class wasn't fully addressed (e.g. #12 fails on CZ academic header → T24 vocab gap; #13 fails on CZ-only bullets → T26 fallback cap or extract.md prompt).

## Reference

- Plan: `/home/mf/.claude/plans/this-is-a-result-peaceful-blanket.md` § "T29 — Acceptance eval"
- PRD §5.3, §5.4, §4.7
- `tests/fixtures/cvs/SOURCES.md` (existing fixture provenance pattern)

## Outcome

Implemented the offline T29 surface:
- Added three fully synthetic CZ fixtures:
  - `11_cz_bilingual_member_of_staff_strelcova.pdf/.txt` — bilingual
    tagline-shaped senior/management CV in the two-column PDF template.
  - `12_cz_academic_simek.pdf/.txt` — CZ-only academic research-lead CV in
    the clean PDF template.
  - `13_cz_corporate_manazer_havelka.pdf/.txt` — CZ-only corporate data
    manager CV in the clean PDF template.
- Updated `scripts/build_cv_fixtures.py` with the source builders, while the
  generated commit only adds #11–#13 so the pre-existing T46 fixture drift is
  not overwritten.
- Updated `tests/fixtures/cvs/SOURCES.md` with provenance, anchors, and CZK
  salary calibration bands for all three personas.
- Added `tests/test_acceptance_cz.py`, a live+slow suite that runs the three
  CZ fixtures plus the junior baseline once, then checks score success,
  dropped-component limits, expected CZK/month salary windows, name-redaction
  observability, role-normalization source, and senior-vs-junior salary
  non-overlap for #11/#13.
- The suite now skips cleanly when the selected provider's API key is absent
  (`OPENROUTER_API_KEY` for `GANDER_LLM_PROVIDER=openrouter`, otherwise
  `MINIMAX_API_KEY`) so local `-m live` probes do not fail before credentials
  are configured.

Verified:
- `uv run pytest tests/test_acceptance_cz.py --collect-only -q`
  → `24 tests collected`.
- `uv run pytest -m live tests/test_acceptance_cz.py -q` with no provider key
  in this shell → `24 skipped`.
- `uv run pytest tests/test_redact.py -m fast -q`
  → `44 passed, 15 deselected`.
- `uv run ruff check scripts/build_cv_fixtures.py tests/test_acceptance_cz.py`
  → passed.
- PR #35 OpenRouter live CI run
  `25932192588` / job `76228665081` → passed. This run exercised the
  full live marker suite, including the CZ acceptance session fixture and the
  T29 score/salary/redaction/role-normalization checks.
- Current local collection with the additional T30 cross-fixture checks:
  `uv --cache-dir /tmp/uv-cache run pytest tests/test_acceptance_cz.py --collect-only --strict-markers -q`
  → `27 tests collected`.

Follow-up owned by T23:
- Capture fresh corpus-level scores, salary bands, costs, and bias numbers in
  `reports/SUMMARY.md` / README.
