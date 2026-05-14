# QA audit — refresh (2026-05-14)

This refreshes the v1 stub against current `main` (stream-C base). Findings re-verified by reading source and tests rather than task files alone. Resolved items are listed inline so the diff against v1 stays legible. Tag convention: `[must-fix]` / `[should-fix]` / `[nit]`.

Scope: `src/gander/` + `tests/` on `stream-C`, cross-referenced against PRD §5 (acceptance), §4.6 (failure modes), §4.8 (observability counters). Includes the T24–T31 hardening wave queued after the multi-agent plan review.

---

## 0. Resolved since v1

| v1 finding | Where it landed | Evidence |
|---|---|---|
| `[must-fix]` T11 emit `search_results_returned` | T11 → `src/gander/salary.py:120-127` | `emit("salary", "salary_search", raw_results=…, dedup_results=…)` |
| `[must-fix]` T12 emit `confidence tier` | T12 → `src/gander/confidence.py:111-116, 165-175` | `emit("confidence", "confidence_step_a", tier=…)` + `"confidence_decision"` |
| `[should-fix]` ingest input-fingerprint emit | T07 → `src/gander/ingest.py:46` | `obs.emit("ingest", "start", filename_suffix=…, size_bytes=…)` — PRD §4.8 fingerprint (size + type, not content) |
| `[must-fix]` T17 acceptance tests | PR #10 (`stream-c/T30-phase1-en-triplet`) | 8 acceptance tests + session-scoped triplet fixture |
| `[should-fix]` T18 failure-path tests | PR #12 (`stream-c/T18-failure-tests`) | 10 fast tests in `test_failures.py` + `test_partial_failure_streaming.py` |
| `[should-fix]` T22 HF Space deploy | `Status: done` in `tasks/T22_*.md` | hosted run reachable |
| `[nit]` T05 spike artifact | resolved at plan-review time; downstream T07–T13 unblocked | T05 status no longer gating |

Note: T17 and T18 still show `Status: todo` on stream-C base because the merging stream-C is awaiting PR review — work is on the PR branches, not yet on `main`. Treat both as **landed-pending-merge**, not unstarted.

---

## 1. Acceptance-criteria coverage matrix (PRD §5)

| # | Criterion | Owning task → test | Status |
|---|---|---|---|
| 1 | Zero-setup hosted run | T22 (done) | covered |
| 2 | Local one-or-two-command run | T23 (todo) | partial — README owns the doc, no runnable fresh-clone check named |
| 3 | Works on arbitrary CVs | (none) | **still missing** — T17 fixture pins the EN triplet |
| 4a | Score spread ≥ 30 | T17 `test_score_spread_at_least_30` (PR #10) | covered (pending merge) |
| 4b | Salary ranges don't overlap | T17 `test_salary_ranges_dont_overlap` (PR #10) | covered (pending merge) |
| 4c | No verbatim / near-dup growth | T17 verbatim + Jaccard 4-gram (PR #10) | covered (pending merge) |
| 5 | Substring-grounded explanations | T17 `test_all_claims_substring_verified` (PR #10) | covered (pending merge) |
| 6 | Working salary source URLs | T11 + T17 (PR #10) | partial — URL shape asserted, reachability (`HEAD` 2xx) not |

**Findings**

- `[must-fix] PRD §5(3)` arbitrary-CV path still has zero coverage. Suggested fix: a `@pytest.mark.live` `test_arbitrary_cv_smoke` that loads a path from `GANDER_SMOKE_CV` (skipped when unset); assert every block in the final `Report` is either populated or a `StageFailure` with a user-facing message — no exceptions, no `running` status. Owner: T17 follow-up or new T32.
- `[should-fix] PRD §5(6)` reachability gap. Add `test_salary_source_urls_reachable` under `@pytest.mark.live` that does `httpx.head(url, follow_redirects=True, timeout=3)` per source and asserts `< 400` for at least 1 of the top-2 sources per CV. Without this, T17 passes on hallucinated-but-well-shaped URLs.
- `[should-fix] T23` verification block names "README updated", which is checklist-style and unfalsifiable. Concrete fix is captured below in §5.

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

- `[should-fix] PRD §4.6 rendered-copy` no test asserts that **`render_body` output** contains the user-facing failure copy for each mode. T18 asserts the strings on the `Report` dataclass; the renderer could regress without breaking T18. Suggested fix: extend `tests/test_render.py` with one parametrised test that builds a `Report` containing a `StageFailure` per stage and asserts the failure copy appears in the rendered HTML. Owner: T14 or T18 follow-up.
- `[should-fix] Multi-failure renderer` no test asserts the renderer handles **simultaneous** failures in two or more stages without exception. PR #10 introduced a partial test (`test_stage_failure_does_not_block_other_stages`) but it lives on the T17 branch — once merged, this finding is resolved.
- `[nit] T18 cascade contract ↔ T15` the "extract fails → score/salary/growth get cascade message" assertion depends on T15's `_CASCADE_PROFILE_FAILED` dict shape. T15 has no contract-level test for the cascade keys; if a stage name changes, only T18 catches it. Suggested fix: a 5-line unit test in `tests/test_pipeline_fast.py` asserting `_CASCADE_PROFILE_FAILED` covers `{"score", "salary", "growth"}`.

---

## 3. Observability gaps by stage (PRD §4.8)

PRD §4.8 names four counters: **claims verified**, **claims dropped**, **search results returned**, **confidence tier assigned**. Plus per-stage **duration**, plus error events with **stage + input fingerprint (file size + type, not CV content)**.

| Stage | Counters required by §4.8 | Plumbed? |
|---|---|---|
| L1 ingest | duration, fingerprint, error | covered — `ingest.py:46` (start: `filename_suffix`, `size_bytes`), `ingest.py:87/106/123/132` (done/rejected duration), `stage_boundary` error |
| L2 redact | duration | covered (via `stage_boundary`) |
| L3 extract | **claims verified, claims dropped**, duration | covered — `extract.py:64` (`verify` event with `dropped`/`kept`), `extract.py:65` (done) |
| L4a score | duration | covered (via `stage_boundary`) |
| L4b salary | **search results returned**, duration | covered — `salary.py:120-127` (`salary_search` w/ `raw_results`/`dedup_results`/`dropped_invalid_url`) |
| L4c confidence | **confidence tier assigned**, duration | covered — `confidence.py:111` (`confidence_step_a` w/ `tier`), `confidence.py:171` (`confidence_decision` w/ `tier`) |
| L5 growth | duration; runtime n-gram smoke | covered |

**Findings**

- `[should-fix] errors.py:89` `stage_boundary` emits `error` events with `exc_message=str(exc)`. PRD §4.8 explicitly excludes CV content from logs. If a parser raises with a snippet of the document (pypdf surfaces document strings in some `ValueError`s; `pydantic.ValidationError` includes the offending value), CV-derived text reaches obs sinks. Suggested fix: replace `exc_message=str(exc)` with `exc_class=type(exc).__name__, exc_code=getattr(exc, "code", None)`, **or** truncate to 200 chars and strip any chars outside `[A-Za-z0-9 .,:;()/_-]`. Audit before live deploy at scale.
- `[nit] tests/test_obs.py` no test asserts the four PRD-named counters are emitted on a single golden run end-to-end. Useful as a regression net if obs sink names ever drift. Cheap to add: a session-scoped `obs.subscribe` callback that collects events, then assert every name in `{"verify", "salary_search", "confidence_decision"}` appears at least once.
- `[nit]` `ingest.py:46` uses `filename_suffix` + `size_bytes` rather than a single `fingerprint` field — semantically equivalent to PRD §4.8's "file size and type, not CV content". Leave as-is; flagged here only so future readers don't grep for the literal word.

---

## 4. Reproducibility blockers

- `[should-fix] T23` no clean-environment reproducibility check is wired. PRD §5(2) demands a one-or-two-command local run. Concrete fix: T23 verification must include literal commands a reviewer can copy-paste, e.g.

  ```bash
  cd "$(mktemp -d)" && git clone <repo> gander && cd gander \
    && uv sync && uv run gander tests/fixtures/01_junior_da_novotny.docx
  ```

  with expected non-empty `score.total > 0`. Without this, T23 is unfalsifiable.
- `[should-fix] T22 secret rebind` HF Space deploy is done, but the redeploy path (`MINIMAX_API_KEY` binding in Space settings, push to the Space remote) is not documented in any task. If the Space is torn down, the path back is tribal knowledge. T23 README should enumerate the secrets and push target explicitly.

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

- `[should-fix] T27` add one parametrised unit test asserting the role-normalization map covers the role strings actually present in the bundled corpus. Without it, T27 can ship and silently miss the strings T17's session fixture exercises.
- `[should-fix] T30 Phase 2` once T29 lands, T30 Phase 2 must assert the same §5(4a)/(4b)/(4c)/(5) invariants on the CS/SK triplet. Currently only English. Without it, the multilingual claim is unverified.
- `[nit]` T24/T26/T28 are all on open PRs in the merge queue — re-audit after merge in case the deliverables drift during review.

---

## Summary

| Severity | Count |
|---|---|
| `[must-fix]` | 1 |
| `[should-fix]` | 7 |
| `[nit]` | 4 |

**Top three actionable items** (do before declaring stages done):

1. `[must-fix]` Cover PRD §5(3) — arbitrary-reviewer-supplied CV. Add `test_arbitrary_cv_smoke` reading a path from `GANDER_SMOKE_CV`.
2. `[should-fix]` Wire T23 fresh-clone smoke and document HF Space secret rebind. PRD §5(2) is otherwise unfalsifiable.
3. `[should-fix]` Sanitize `errors.py:89` `exc_message` before scaling up — CV content can otherwise leak into obs logs via parser tracebacks.

**Delta from v1 audit:** 3 of 3 `[must-fix]` resolved (salary counter, confidence counter, ingest fingerprint). 1 new `[must-fix]` from §5(3) gap (was previously flagged at `[must-fix]` but stayed open). Net: 1 `[must-fix]` outstanding, down from 3.
