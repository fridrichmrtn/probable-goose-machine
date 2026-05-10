# QA audit — plan + task testability

> **Provenance note.** This file is a stub written by the `/dev` orchestrator, not by a real `qa-engineer` subagent invocation. The Agent/Task tool was not exposed in the orchestrator's environment for this run, so step 6 of `tasks/dev-plan.md` could not invoke `subagent_type: "qa-engineer"`. The findings below are produced from a single-pass static read of `PRD.md`, `tasks/PLAN.md`, `tasks/todo.md`, and the T07–T23 task files; they should be re-validated by a real `qa-engineer` invocation in a follow-up dev run before any are actioned.

Scope: `tasks/PLAN.md`, `tasks/todo.md`, T07–T23. Cross-referenced against PRD §5 (acceptance criteria), §4.6 (failure modes), and §4.8 (observability counters). Tag convention: `[must-fix]` / `[should-fix]` / `[nit]`.

---

## 1. Acceptance-criteria coverage matrix (PRD §5)

| # | Criterion | Owning task → test | Status |
|---|---|---|---|
| 1 | Zero-setup hosted run (under a minute, no install) | T22 (HF Space deploy) — verification block names a hosted-URL smoke check | covered |
| 2 | Local one-or-two-command run | T23 (README finalize) — verification block claims local-run path documented | partial — verification names "README updated", does not name a clean-env reproducibility check |
| 3 | Works on arbitrary CVs (round 2) | (none) — no task explicitly covers "reviewer-supplied unseen CV" beyond the bundled corpus | **missing** |
| 4a | Score spread ≥30 across junior/mid/senior | T17 `test_score_spread_at_least_30` | covered |
| 4b | Junior–senior salary ranges do not overlap | T17 `test_salary_ranges_dont_overlap` | covered |
| 4c | No verbatim growth-plan repeats | T17 `test_no_growth_plan_verbatim_repeats` + `test_no_growth_plan_near_duplicates` | covered |
| 5 | Substring-grounded explanations | T17 `test_all_claims_substring_verified` | covered |
| 6 | Working salary source URLs | T11 (live test asserts `sources have URLs`) — but no test asserts URLs return HTTP 2xx | partial |

**Findings**

- `[must-fix] PRD §5(3)` no test or task asserts the system handles an arbitrary, never-before-seen CV. T17's session fixture pins three named files. A reviewer in round 2 supplying their own CV is a hard acceptance criterion. Suggested fix: add a `test_arbitrary_cv_smoke` that loads a CV path from an env var (skipped in CI), or expand T16/T22 verification to include "upload a non-corpus CV and assert the report renders without StageFailure on every block".
- `[should-fix] tasks/T17_acceptance.md:34` "salary outputs include working source URLs" (PRD §5(6)) — T17 asserts URL presence and shape, not reachability. A `requests.head(url, timeout=3)` per source, gated `@pytest.mark.live`, would close the gap. Without it the test passes on hallucinated-but-syntactically-valid URLs.
- `[should-fix] tasks/T23_readme.md` verification block names "README covers run + decisions" but does not name a clean-env reproducibility check (e.g., `git clone … && uv sync && uv run …` from `/tmp` in CI or by hand). Setup friction is part of §5(2). Add an explicit "fresh-clone smoke" item to T23 verification.

---

## 2. Failure-path coverage matrix (PRD §4.6)

| Failure mode | Owning test → assertion | Status |
|---|---|---|
| Corrupt or unreadable file | T18 `test_corrupt_pdf` asserts `statuses["ingest"] == "failed"` and user-facing message | covered |
| Image-only / scanned PDF | T18 `test_image_only_pdf` asserts scanned-PDF message | covered |
| Salary search returns no usable data | T18 `test_ddg_returns_empty` asserts `StageFailure` w/ "Insufficient market data", `confidence.tier == "Low"`, *and* score/growth still populated | covered (this is the model the rest should follow) |
| Model output fails parsing after retry | T18 `test_extract_returns_garbage` asserts profile is `StageFailure`; downstream blocks degrade with explicit messages | covered |
| Whole report never crashes when one stage fails | T18 `test_streaming_no_running_at_end` + `test_streaming_no_traceback` | covered |

**Findings**

- `[should-fix] tasks/T18_failures.md:18` `test_unknown_extension` asserts on the message string but the PRD §4.6 message for unknown ext isn't separately listed — this collapses three distinct failure modes (corrupt, scanned, unknown ext) into one user-visible string. Confirm with `product-owner` whether copy parity is intended; if so, leave; if separate copy is intended, add a dedicated assertion per mode.
- `[nit] tasks/T18_failures.md:21` `test_extract_returns_garbage` — the assertion that downstream blocks "are also failures with 'Cannot ... without profile' messages" depends on T15 implementing dependency-aware short-circuiting. Cross-check that T15's `Verification` block names this dependency contract; if it's only implicit, T15 could regress without breaking T18. Suggest adding a contract-level test in T15 too.
- `[should-fix] PRD §4.6 implies` "the failure block shows a specific user-visible message". T18 asserts string presence in the report dataclass; no test asserts that the *rendered* (`render_body`) output contains that copy. T14 owns the renderer; recommend a thin "render a Report containing a StageFailure for stage X, assert copy Y appears" test, owned by T14 or T18.

---

## 3. Observability gaps by stage (PRD §4.8)

PRD §4.8 names four counters: **claims verified**, **claims dropped**, **search results returned**, **confidence tier assigned**. Plus per-stage **stage name + duration**, plus error events with **stage + input fingerprint (file size + type, not CV content)**.

| Stage | Counters required by §4.8 | Owning task plumbs them? |
|---|---|---|
| L1 ingest | duration, error w/ fingerprint | partial — T07 wraps in `stage_boundary("ingest")`; no explicit fingerprint emit on success path |
| L2 redact | duration | partial — no named counter beyond stage_boundary defaults |
| L3 extract | **claims verified, claims dropped**, duration | covered — T09:23 `obs.emit("verify", stage="extract", dropped=N, kept=M)` |
| L4a score | duration | covered (via stage_boundary) |
| L4b salary | **search results returned**, duration | **missing** — T11 mentions `top 8` dedupe but no explicit `obs.emit("salary", search_results_returned=N)`; the counter is named in PRD but not in any task's deliverables |
| L4c confidence | **confidence tier assigned**, duration | **missing** — T12 wraps in stage_boundary but no `obs.emit("confidence", tier=...)` is named in deliverables |
| L5 growth | duration; runtime n-gram smoke (T13) | covered for n-gram; PRD-named counters n/a for this stage |

**Findings**

- `[must-fix] PRD §4.8 ↔ tasks/T11_salary.md` `search results returned` is a PRD-named counter. T11 currently has no deliverable that emits `search_results_returned`. Add a deliverable to T11: "Emit `obs.emit('salary', stage='salary', search_results_returned=len(results), kept=len(deduped))` after dedupe."
- `[must-fix] PRD §4.8 ↔ tasks/T12_confidence.md` `confidence tier assigned` is a PRD-named counter. T12 must emit it. Add a deliverable: "Emit `obs.emit('confidence', stage='confidence', tier=<low|med|high>)` after tier assignment."
- `[should-fix] tasks/T02_utils.md:24` `obs.emit` signature is documented but "input fingerprint" is not. PRD §4.8 explicitly requires error events to carry `stage + input fingerprint (file size and type, not CV content)`. T02 should land a small helper `fingerprint(content_bytes, suffix) -> dict` and document that error events must include it; T07's ingest stage is the natural caller.
- `[should-fix] tasks/T02_utils.md:37` `stage_boundary` emits `obs.emit("error", stage=..., exc_type=..., exc_message=...)`. `exc_message` may include CV-derived strings if a parser raises with a snippet of the document. Audit point: confirm `exc_message` is sanitized (or replaced by a `class+code` pair) before emit. PRD §4.8 explicitly excludes CV content from logs.
- `[nit]` no test asserts that observability events are *actually emitted* for each stage boundary. T19 owns judge tests; T18 owns failure-mode log behavior; nothing asserts the success-path log contains the four PRD-named counters. A small `test_obs_counters_present_per_stage` against a single golden run would close this.

---

## 4. Reproducibility blockers

- `[should-fix] tasks/T22_deploy.md` HF Space deploy is marked `[x] done` in `tasks/todo.md`, but the round-2 local-path smoke (PRD §5(2)) is not yet wired into a verification command anywhere. T23's verification names "README updated", which is checklist-style. Concrete suggestion: T23 verification should include `cd /tmp && git clone … && uv sync && uv run …` literally, with expected output (or absence of error) named.
- `[should-fix] PRD §7 zero-setup` round-1 hosted demo currently depends on environment variables (`MINIMAX_API_KEY`, possibly `ANTHROPIC_API_KEY` for fallback). No task documents the HF Space secret-binding step explicitly enough that a fresh reviewer reproducing the deploy could repeat it. If the Space is already up, reproducibility is preserved; if it's torn down, the path back is undocumented. Recommend T23 README explicitly enumerate "to redeploy: set X, Y secrets in HF Space settings, push to space remote".
- `[nit]` `tasks/T05_spike.md` is a hard gate for T07–T13 per `tasks/todo.md:13`. Spike outcomes typically belong in a written report; confirm T05 produces a captured artifact (`tasks/T05_*-report.md`) on success/fail, otherwise downstream owners can't tell whether the spike resolved a known capability gap or which model profile was chosen.

---

## 5. Plan/task testability gaps

| Task | `Verification` present? | Concrete enough to fail on? |
|---|---|---|
| T17 acceptance | yes | yes (named pytest invocation) |
| T18 failures | yes | yes (named pytest invocations, fast + live split) |
| T19 judge tests | yes | yes |
| T20 bias | yes | spot-check below |
| T21 eval corpus | yes | spot-check below |
| T22 deploy | yes | spot-check below |
| T23 readme | yes | weak — see [should-fix] above |
| T07–T16 stage workers | not audited line-by-line in this stub | unverified |

**Findings**

- `[should-fix] tasks/T23_readme.md:53` Verification block names doc-completeness items, not a runnable check. Add a one-liner: `cd "$(mktemp -d)" && git clone <repo> jobfit && cd jobfit && uv sync && uv run jobfit-cli tests/fixtures/01_junior_da_novotny.docx | tee /tmp/smoke.json && jq -e '.score.total > 0' /tmp/smoke.json`. If the local-run path is not a CLI, adapt to the actual entry point. Without a runnable check, T23 cannot fail.
- `[should-fix]` T20 bias smoke and T21 eval corpus: not deeply read in this stub, flagging as **unverified by this audit** rather than greenlit. A real `qa-engineer` pass should validate that T20's verification asserts behavior (not just "ran the script"), and that T21's eval corpus has a stable threshold or a recorded baseline against which regressions can be detected.
- `[nit]` Task `Owner:` enumeration in `tasks/PLAN.md` was just extended to include `qa-engineer`. None of T17–T21 currently route to `qa-engineer` ownership; consider whether T18 (failure tests) and T20 (bias smoke) would be better co-owned (`software-engineer` writes, `qa-engineer` reviews before close) — matches the agent's "stay in your lane" clause.

---

## Summary

| Severity | Count |
|---|---|
| `[must-fix]` | 3 |
| `[should-fix]` | 8 |
| `[nit]` | 4 |

**Top three actionable items** (do these before declaring stages done):

1. `[must-fix]` Add a deliverable to T11 emitting `search_results_returned`, and to T12 emitting `confidence tier`. PRD §4.8 names them; nothing currently emits them.
2. `[must-fix]` Add a test (or expand T17/T18 fixture) for "arbitrary reviewer-supplied CV". §5(3) currently has zero coverage.
3. `[should-fix]` Tighten T23 verification to a runnable fresh-clone smoke. The current "README updated" check is not falsifiable.

**Re-validation needed.** This stub was written without the `qa-engineer` agent in the loop. Re-run it via the real subagent before treating any of the above as binding — in particular, items 4 and 5 in the audit prompt were only spot-checked.
