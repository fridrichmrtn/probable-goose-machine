# QA audit — refresh (2026-05-14)

This refreshes the v1 stub against current `main` (stream-C base). Findings re-verified by reading source and tests rather than task files alone. Resolved items are listed inline so the diff against v1 stays legible. Tag convention: `[must-fix]` / `[should-fix]` / `[nit]`.

Scope: `src/gander/` + `tests/` on `stream-C`, cross-referenced against PRD §5 (acceptance), §4.6 (failure modes), §4.8 (observability counters). Includes the T24–T31 hardening wave queued after the multi-agent plan review.

---

## 0. Resolved since v1

| v1 finding | Where it landed | Evidence |
|---|---|---|
| `[must-fix]` T11 emit `search_results_returned` | T11 → `src/gander/salary.py:120-127` | `emit("salary", "salary_search", raw_results=…, dedup_results=…)` |
| `[must-fix]` T12 emit `confidence tier` | T12 → `src/gander/confidence.py:111-116, 165-175` | `emit("confidence", "confidence_step_a", tier=…)` + `"confidence_decision"` |
| `[must-fix]` ingest input-fingerprint emit | T07 → `src/gander/ingest.py:46` | `obs.emit("ingest", "start", filename_suffix=…, size_bytes=…)` — PRD §4.8 fingerprint (size + type, not content) |
| `[must-fix]` T17 acceptance tests | PR #10 (`stream-c/T30-phase1-en-triplet`) | 8 acceptance tests + session-scoped triplet fixture |
| `[should-fix]` T18 failure-path tests | PR #12 (`stream-c/T18-failure-tests`) | 10 fast tests in `test_failures.py` + `test_partial_failure_streaming.py` |
| `[should-fix]` T22 HF Space deploy | `Status: done` in `tasks/T22_*.md` | hosted run reachable |
| `[nit]` T05 spike artifact | resolved at plan-review time; downstream T07–T13 unblocked | T05 status no longer gating |
| `[must-fix]` §4.8 per-stage duration | PR #35 sweep (`t46-salary-multi-market`) | `score`, `salary`, `confidence`, and `growth` now emit terminal `done` events with `duration_ms`; explicit `stage_failure` events on those stages also carry `duration_ms` |
| `[must-fix]` PRD §5(3) arbitrary-CV path | PR #35 sweep (`t46-salary-multi-market`) | `tests/test_arbitrary_cv_smoke.py` reads `GANDER_SMOKE_CV`, runs the live pipeline, and asserts every final block is populated or a reviewer-facing `StageFailure` |
| `[should-fix]` generic boundary raw exception leaks | PR #35 sweep (`t46-salary-multi-market`) | `stage_boundary` now uses curated stage messages for `StageFailure.user_message` and emits obs `error` events with `exc_type` only, not raw `exc_message` |
| `[should-fix]` rendered failure copy | PR #35 sweep (`t46-salary-multi-market`) | `tests/test_render.py::test_render_body_renders_failure_copy_for_each_stage` pins reviewer-facing failure copy for profile, score, salary, confidence, and growth |
| `[should-fix]` T27 corpus role-map coverage | PR #35 sweep (`t46-salary-multi-market`) | `tests/test_normalize.py::test_bundled_corpus_headlines_normalize_deterministically` pins the committed fixture headline strings, including CZ manager/research titles and the tagline senior case |
| `[should-fix]` T23 README falsifiability + fresh-clone smoke | PR #35 sweep (`t46-salary-multi-market`) | `README.md` now has a clean-clone runbook, the expected healthy-run signal, corpus regeneration, and opt-in arbitrary-CV smoke commands; `tasks/T23_readme.md` mirrors the verification |
| `[should-fix]` T22 secret rebind | PR #35 sweep (`t46-salary-multi-market`) | `README.md` and `tasks/T22_deploy.md` now list the HF Space secrets/env, GitHub secrets/vars, and `hf`/`gh` recovery commands |

Note: T17 and T18 still show `Status: todo` on stream-C base because the merging stream-C is awaiting PR review — work is on the PR branches, not yet on `main`. Treat both as **landed-pending-merge**, not unstarted.

---

## 1. Acceptance-criteria coverage matrix (PRD §5)

| # | Criterion | Owning task → test | Status |
|---|---|---|---|
| 1 | Zero-setup hosted run | T22 (done) | covered |
| 2 | Local one-or-two-command run | T23 (todo) | covered by README fresh-clone runbook; live corpus/bias numbers still pending before T23 closes |
| 3 | Works on arbitrary CVs | `tests/test_arbitrary_cv_smoke.py` | covered opt-in via `GANDER_SMOKE_CV` |
| 4a | Score spread ≥ 30 | T17 `test_score_spread_at_least_30` (PR #10) | covered (pending merge) |
| 4b | Salary ranges don't overlap | T17 `test_salary_ranges_dont_overlap` (PR #10) | covered (pending merge) |
| 4c | No verbatim / near-dup growth | T17 verbatim + Jaccard 4-gram (PR #10) | covered (pending merge) |
| 5 | Substring-grounded explanations | T17 `test_all_claims_substring_verified` (PR #10) | covered (pending merge) |
| 6 | Working salary source URLs | T11 + T17 (PR #10) | partial — URL shape asserted, reachability (`HEAD` 2xx) not |

**Findings**

- `[resolved] PRD §5(3)` arbitrary-CV path has opt-in coverage via `GANDER_SMOKE_CV`; the test skips when unset so private reviewer CVs stay out of the repo.
- `[should-fix] PRD §5(6)` reachability gap. Add `test_salary_source_urls_reachable` under `@pytest.mark.live` that does `httpx.head(url, follow_redirects=True, timeout=3)` per source and asserts `< 400` for at least 1 of the top-2 sources per CV. Without this, T17 passes on hallucinated-but-well-shaped URLs.
- `[resolved] T23` README verification is now falsifiable: fresh clone, dependency sync, app launch, expected report signal, corpus regeneration, and arbitrary-CV smoke commands are named explicitly.

---

## 2. Failure-path coverage matrix (PRD §4.6)

| Failure mode | Owning test → assertion | Status |
|---|---|---|
| Corrupt or unreadable file | T18 `test_corrupt_pdf_full_pipeline_emits_corrupt_message` (PR #12) | covered (pending merge) |
| Image-only / scanned PDF | T18 `test_image_only_pdf_full_pipeline_emits_scanned_message` (PR #12) | covered (pending merge) |
| Unknown extension | T18 `test_unknown_extension_full_pipeline_emits_unknown_message` (PR #12) | covered (pending merge) |
| Salary returns no usable data | T18 `test_ddg_returns_empty_short_circuits_salary` (PR #12) | covered — asserts `salary=StageFailure`, `confidence` is a Low `Confidence` object (NOT StageFailure), judge never runs, growth cascades |
| Salary transport error | T18 `test_ddg_raises_connection_error_short_circuits_salary` (PR #12) | covered (pending merge) |
| Model output fails parsing after retry | T18 `test_extract_validation_error_cascades_to_every_downstream_stage` (PR #12) | covered (pending merge) |
| Whole report never crashes when one stage fails | T18 `test_every_yield_is_renderable_without_exception` + `test_final_report_has_no_running_statuses` + `test_no_traceback_on_stderr_during_corrupt_run` (PR #12) | covered (pending merge) |

**Findings**

- `[resolved] PRD §4.6 rendered-copy` `tests/test_render.py` now has a parametrized `StageFailure` render test covering profile, score, salary, confidence, and growth copy.
- `[resolved-pending-merge] Multi-failure renderer` PR #10's `tests/test_report.py::test_stage_failure_does_not_block_other_stages` asserts the renderer emits every section's failure callout (Score, Salary, Confidence, Plan) when all four downstream stages fail simultaneously. Single-stage-fails-alone permutations are owned by `tests/test_render.py`. No remaining gap on this axis; re-verify on merge.
- `[nit] T18 cascade contract ↔ T15` the "extract fails → score/salary/growth get cascade message" assertion depends on T15's `_CASCADE_PROFILE_FAILED` dict shape. T15 has no contract-level test for the cascade keys; if a stage name changes, only T18 catches it. Suggested fix: a 5-line unit test in `tests/test_pipeline_fast.py` asserting `_CASCADE_PROFILE_FAILED` covers `{"score", "salary", "growth"}`.

---

## 3. Observability gaps by stage (PRD §4.8)

PRD §4.8 names four counters: **claims verified**, **claims dropped**, **search results returned**, **confidence tier assigned**. Plus per-stage **duration**, plus error events with **stage + input fingerprint (file size + type, not CV content)**.

`stage_boundary` (`src/gander/errors.py:18-92`) only enters/exits the obs `current_stage` contextvar and, on exception, emits a single `error` event carrying `exc_type`. It does **not** emit a `duration_ms` on the success path and does **not** emit one on the error path either. Per-stage duration is therefore present where the stage body explicitly times itself and emits a terminal `done`/`rejected` event with `duration_ms=_ms()`.

| Stage | Counters required by §4.8 | Plumbed? |
|---|---|---|
| L1 ingest | duration, fingerprint, error | covered — `ingest.py:46` (start: `filename_suffix`, `size_bytes`), `ingest.py:53/60/67/73/80/83/92` (`rejected`/`done` carry `duration_ms=_ms()`), `stage_boundary` error |
| L2 redact | duration | covered — `redact.py:418-422` (`obs.emit("redact", "done", duration_ms=_ms(), …)`) |
| L3 extract | **claims verified, claims dropped**, duration | covered — `extract.py:64` (`verify` event with `dropped`/`kept`), `extract.py:65` (`done` with `duration_ms=_ms()`) |
| L4a score | duration | covered — `score.py` emits `done` with `duration_ms`, total, component count, and dropped count |
| L4b salary | **search results returned**, duration | covered — `salary_search` carries search counters; `salary.py` emits `done` with `duration_ms`, source count, country, currency, and period |
| L4c confidence | **confidence tier assigned**, duration | covered — `confidence_decision` carries tier; `confidence.py` emits `done` with `duration_ms`, salary tier, final tier, and CV floor |
| L5 growth | duration; runtime n-gram smoke | covered — `growth_anti_slop_check` carries returned/dropped/survived; `growth.py` emits `done` with `duration_ms` and action count |

`src/gander/pipeline.py:145` aggregates `duration_ms` off `llm_call` records to populate `Report.total_latency_ms`; the stage-level `done`/`rejected` events now provide the per-stage timing view separately.

**Findings**

- `[resolved] §4.8 per-stage duration` `score`, `salary`, `confidence`, and `growth` now time themselves and emit `obs.emit(<stage>, "done", duration_ms=…)` on success. The explicit `stage_failure` events in those stages also include `duration_ms`.
- `[resolved] errors.py:82,89` the generic boundary no longer uses `str(exc)` for reviewer-facing copy or obs error messages. Raw exception text remains only in `StageFailure.debug_detail`, which is not rendered in the report.
- `[nit] tests/test_obs.py` no test asserts the four PRD-named counters are emitted on a single golden run end-to-end. Useful as a regression net if obs sink names ever drift. Cheap to add: a session-scoped `obs.subscribe` callback that collects events, then assert every name in `{"verify", "salary_search", "confidence_decision"}` appears at least once.
- `[nit]` `ingest.py:46` uses `filename_suffix` + `size_bytes` rather than a single `fingerprint` field — semantically equivalent to PRD §4.8's "file size and type, not CV content". Leave as-is; flagged here only so future readers don't grep for the literal word.

---

## 4. Reproducibility blockers

- `[resolved] T23` clean-environment reproducibility is now documented with literal commands a reviewer can copy-paste:

  ```bash
  cd "$(mktemp -d)" && git clone <repo> gander && cd gander \
    && uv sync && MINIMAX_API_KEY=… uv run python app.py
  ```

  The README also states the expected non-empty `score.total > 0` after a CV
  upload, notes the LFS fixture caveat, and names `scripts/eval_corpus.py` plus
  the opt-in `GANDER_SMOKE_CV` live smoke.
- `[resolved] T22 secret rebind` HF Space deploy recovery is documented in
  README and T22: active-provider secret, `GANDER_MODEL_PROFILE`,
  `PYTHONPATH`, `HF_TOKEN`, `HF_SPACE_URL`, and the sync workflow target are
  all named.

---

## 5. T24–T31 hardening-wave testability

These tasks were added after v1 audit. Most are scoped well; a few have weak verification blocks.

| Task | Verification quality | Notes |
|---|---|---|
| T24 multilingual section vocab | concrete (cs/sk strings + test on existing CS fixture) | gated on T28 merging — fine |
| T25 score partial-credit policy | concrete | covers `Score.components` partial cases |
| T26 verify_quote section-fallback | concrete (per-stage miss cap) | currently on PR #9 |
| T27 role normalization | weak — names "canonical role map" but no test of the mapping itself | suggest one parametrised test with 6–10 raw → canonical pairs |
| T28 redact tagline+tenure | concrete | currently on PR #11 |
| T29 CZ senior fixture | fixture only — verification is "fixture loads + redacts cleanly" | acceptance-tier assertion belongs to T30 Phase 2 |
| T30 acceptance CI | Phase 1 done on PR #10; Phase 2 (CS/SK triplet) still owed | tie Phase 2 to T29 landing |
| T31 multimodal spike | deferred — no action |

**Findings**

- `[resolved] T27` role-normalization coverage now includes a parametrized test for the headline strings present in the bundled corpus.
- `[should-fix] T30 Phase 2` once T29 lands, T30 Phase 2 must assert the same §5(4a)/(4b)/(4c)/(5) invariants on the CS/SK triplet. Currently only English. Without it, the multilingual claim is unverified.
- `[nit]` T24/T26/T28 are all on open PRs in the merge queue — re-audit after merge in case the deliverables drift during review.

---

## Summary

| Severity | Count |
|---|---|
| `[must-fix]` | 0 |
| `[should-fix]` | 2 |
| `[nit]` | 4 |

Open `[should-fix]` bullets: PRD §5(6) reachability and T30 Phase 2. The PR #10 multi-failure renderer item is tracked separately as `[resolved-pending-merge]`.

**Top actionable follow-ups**:

1. `[should-fix]` Add source reachability coverage for salary URLs, preferably with a tolerant GET/HEAD fallback rather than a brittle HEAD-only check.
2. `[should-fix]` Run the CZ triplet live and close T30 Phase 2 once the provider-key gate is satisfied.

**Delta from v1 audit:** 3 of 3 v1 `[must-fix]` resolved (salary counter, confidence counter, ingest fingerprint), and the later §4.8 per-stage-duration plus PRD §5(3) arbitrary-CV gaps have both been closed. The raw-exception leak, rendered-copy, and corpus role-map should-fixes are also closed. 0 `[must-fix]` findings remain open in this audit.
