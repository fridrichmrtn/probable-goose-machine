
## t01-schemas — 2026-05-10T13:50Z
Report: tasks/dev-report.md (in dev/t01-schemas)

### Should-fix
- [ai-ml-engineer] src/jobfit/schemas.py — `Report` lacks `total_cost_usd: float = 0.0` and `total_duration_ms: int = 0` aggregate fields. PLAN §M3 (`test_per_run_cost_budget`) + README per-run cost figure will need them; better to land in T01 contract than retrofit after T15 ships.
- [ai-ml-engineer] src/jobfit/schemas.py — `GrowthAction.mechanism: str` is unanchored. PLAN §M4 Jaccard test only covers `what`; mechanism could become copy-paste boilerplate ("builds in-demand skills") and pass.
- [product-owner] src/jobfit/schemas.py — Add `Confidence.judged_by: Literal["independent"]` (or similar tracking field) so PRD §4.3 separation is encoded in the type, not just convention.
- [product-owner] src/jobfit/schemas.py — Add a `+30%` calibration field (per-action `expected_salary_delta_pct: int | None` or top-level `growth.target_uplift_pct: int = 30`) so T13/T17 can verify PRD §3 / §4.4 instead of trusting prose.
- [hiring-manager / codex] src/jobfit/errors.py:15 — `class stage_boundary` is snake_case (PEP 8 violation) AND lacks the decorator form the spec mentioned. Either rename to `StageBoundary` (accept capitalized call site) or implement `__call__` to support `@stage_boundary("score")` decorator usage. Current state is the worst of both.
- [ux-engineer] src/jobfit/errors.py:11 — `StageFailure.user_message` needs a one-line docstring noting it's reviewer-facing copy (PRD §4.6 strings), not engineer placeholder text — prevents T15/T16 authors from putting `repr(exc)` in there.
- [ux-engineer] src/jobfit/errors.py:65 — `user_message=str(exc) or type(exc).__name__` will leak raw Python exception strings to the UI surface. Add a comment requiring callers to overwrite with PRD §4.6 copy before the StageFailure renders.

### Must-fix (remaining — exhaustion)
- [ai-ml-engineer] src/jobfit/schemas.py:39-41 — `Anchor.section: str | None` constraint to `Literal[...]` rejected. Why: reviewer conflated CV-section vocabulary (open-ended: "Work Experience", "Projects", "Publications", "Open Source") with `Component.name` vocabulary (closed 4-element set). Forcing a Literal would be wrong. Addressed via clarifying docstring on `Anchor` in the heal commit.
- [ai-ml-engineer] src/jobfit/schemas.py:65-71 — `SalaryEstimate.reasoning` split or `for_judge()` projection rejected. Why: PLAN §L4c judge signature is `judge(sources, low, high, currency, period) -> Confidence` — individual fields, not the SalaryEstimate object. Reasoning never reaches the judge by construction; isolation is enforced at the T12 call site, not the schema. Addressed via clarifying docstring on `SalaryEstimate` in the heal commit.

### Nits
- [ai-ml-engineer] src/jobfit/schemas.py:60-62 — `ProfileItem.text` is paraphrasable (only `anchor.quote` is verified). Consider invariant: `text` ⊆ `anchor.quote`.
- [ai-ml-engineer] src/jobfit/schemas.py:81-83 — `Confidence` has no link back to the `SalaryEstimate` it judged; `judged_low/judged_high` would help the recompute-then-compare golden test.
- [ai-ml-engineer] src/jobfit/errors.py:48-71 — Add a comment that `asyncio.CancelledError` (BaseException, not Exception) deliberately propagates, so future "fixes" don't swallow cancellation.
- [ai-ml-engineer] tests/test_schemas.py — No test exercises the `Anchor.section` round-trip; the §4.5 hardening hangs on this.
- [product-owner] src/jobfit/schemas.py — `RawCV.content_bytes: bytes` is unbounded; add a `# size guard lives in T07 ingest` comment.
- [product-owner] src/jobfit/schemas.py — `Report.raw_cv_text: str` is non-optional; ingestion failure case can't construct a Report. Default to `""` or `str | None`.
- [hiring-manager] src/jobfit/schemas.py:111 — `Report.model_rebuild()` may be a no-op since `StageFailure` is eagerly imported (not behind `TYPE_CHECKING`). Drop or comment-justify.
- [hiring-manager] src/jobfit/schemas.py — Reorder so `Anchor`/`ProfileItem`/`Component` cluster together (the "claim-with-evidence" group).

## t02-utils — 2026-05-10T14:30Z
Report: tasks/T02_dev-report.md (in dev/t02-utils)

### Should-fix
- [ai-ml-engineer] src/jobfit/llm.py — Anthropic prompt caching not enabled. PLAN §"Cold-start mitigation" notes Anthropic fallback only — but if we ever ship it as primary, missing `cache_control` markers on the system prompt is a 90%+ cost regression. Add a `# T05/T22:` TODO at the Anthropic branch.
- [ai-ml-engineer] src/jobfit/llm.py:31 — `_ANTHROPIC_MODEL = "claude-sonnet-4-6"` is unverified against Anthropic's published model IDs. Confirm before T05 fallback path is exercised; if ID is wrong, fallback fails on first call.
- [ai-ml-engineer] src/jobfit/verify.py — Substring match has no word-boundary guard: a 6-word quote like "data engineer with five years of" would match inside "metadata engineer..." . Acceptable for L0 but flag for T07/T09.
- [ai-ml-engineer] src/jobfit/verify.py — `drop_unverified` uses `getattr(item, anchor_attr)` with no fallback; raises `AttributeError` on items missing the anchor field. Either gate with `hasattr` + skip, or document the contract that callers must pre-filter.
- [ux-engineer] src/jobfit/obs.py — `subscribe()` is sync-context only; Gradio's UI loop wants an async-iterable / queue for progress events. Wrap with an `async_subscribe()` that pushes onto an `asyncio.Queue` before T16 wires the UI.
- [ux-engineer] src/jobfit/errors.py — `StageFailure.user_message = str(exc) or type(exc).__name__` will leak raw Python exception strings to the UI. Add a comment requiring T15/T16 callers to overwrite with PRD §4.6 copy.
- [hiring-manager] src/jobfit/llm.py — `_chat_json` / `_chat_text` use `Any`-typed clients to dodge the OpenAI/Anthropic type divergence. Acceptable but flag a `# typing: provider dispatch` TODO so future readers know it's deliberate.
- [product-owner] src/jobfit/llm.py — `MODEL_PRICES` dated 2026-05-10 in a comment; consider a `# Re-verify after:` field with an explicit 90-day TTL so cost reports don't drift silently.
- [product-owner] src/jobfit/llm.py — `complete_text` always uses `cheap` model default; PLAN §L4c judge needs `reasoning` for the calibration leg. Either swap the default or document the per-call override at T12.

### Nits
- [codex] src/jobfit/verify.py:52 — `str.count()` ignores overlapping occurrences; for 6–7 word "unique" checks this is technically wrong but practically benign (overlapping 6-word repeats are vanishingly rare in CV prose). Leave as-is unless T17 acceptance flags it.
- [ai-ml-engineer] src/jobfit/obs.py — `_subscribers` uses immutable tuple (good for asyncio.gather), but mutation is O(n) per subscribe. Fine at expected fan-out (≤5 subscribers); flag if T16 hits more.
- [ai-ml-engineer] src/jobfit/llm.py — JSON-mode fallback for Anthropic uses prompt-injection ("Return JSON only, no prose."), not native tool-use. Switch to `tools=[{...}]` if Anthropic becomes primary.

## t03-ci-precommit — 2026-05-10T15:00Z
Report: tasks/T03_dev-report.md (in dev/t03-ci-precommit)

### Should-fix
- [ux-engineer] .github/workflows/warm-keeper.yml:5 — `*/5 * * * *` is 288 runs/day — overkill for a hiring-committee review window of ~1–2 hours. Consider business-hours-only schedule (e.g. `*/10 8-22 * * *`) before T22 deploy. Free-tier Actions minutes are unlimited for public repos so this is harmless today, but worth tightening when traffic pattern is known.
- [hiring-manager] all of T03 commit dcddf96 — auto-format pass on T01/T02 source (`src/jobfit/llm.py`, `src/jobfit/schemas.py`, `tests/test_llm.py`) was bundled into T03 instead of landing as a separate "format ratchet" commit. Direction is right (CI's `ruff format --check` would otherwise red day one), but packaging is wrong — bundling ties the auto-fix to the workflow change so a revert of T03 would undo both. Acceptable cost for an L0 task; flag the pattern in `tasks/lessons.md` so future hygiene PRs land on their own commit.
- [ai-ml-engineer] .github/workflows/ci.yml — no CI runner exists for the `slow` pytest marker. Today only `fast` (in `static`) and `live` (in `live`) jobs run; `@pytest.mark.slow` tests would silently not execute. Design a trigger when T15 lands the first slow test (manual `workflow_dispatch`, scheduled nightly, or PR label like `run-slow`).
- [ux-engineer] tasks/T03_ci_precommit.md Outcome — should explicitly state the failure mode if user skips the two manual GitHub-settings actions: "Without `MINIMAX_API_KEY`, CI passes but live tests skip silently. Without `HF_SPACE_URL`, warm-keeper now hard-fails (after heal); set both before merging T22."
- [hiring-manager] .pre-commit-config.yaml — pre-push hook on a config-only branch fails confusingly if `uv` isn't installed; add a guard or document in README.
- [ux-engineer] .github/workflows/ci.yml — `actions/checkout@v4` and `astral-sh/setup-uv@v3` run on Node 20, deprecated by GitHub Actions: forced to Node 24 starting 2026-06-02 and Node 20 removed 2026-09-16. Bump to next major (likely `@v5` / `@v4`) once released, or set `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` as an interim opt-in. Observed in run 25630539366.
- [product-owner] tasks/T22_deploy.md — should mirror T03's user-action checklist (`MINIMAX_API_KEY` Secret + `HF_SPACE_URL` Variable) as a precondition so the T22 picker doesn't reverse-trace it from this task.

### Nits
- [hiring-manager] .github/workflows/ci.yml:31,34 — `ruff format --check .` and `ruff check .` rely on `.gitignore` to exclude `.venv`/`reports/`. Explicit `src tests` (or pyproject `[tool.ruff].src`) reads more honestly.
- [hiring-manager] .pre-commit-config.yaml:22 — `entry: uv run mypy src/` could be `uv run mypy` since `[tool.mypy].files` already scopes it. Style preference.
- [hiring-manager] tasks/T03_ci_precommit.md Outcome — mentions "three pre-existing T01 files" auto-formatted but actual diff also touched `tests/test_llm.py`. Minor accuracy nit.
- [hiring-manager] scripts/.gitkeep — added with no explanation. If T22 will populate `scripts/eval_corpus.py`, fine; otherwise drop.
- [product-owner] tasks/T03_ci_precommit.md:44 — "Deferred to T22 per plan §1" but PLAN §1 doesn't explicitly call out release-eval; the constraint comes from this task spec. Either drop the cite or update PLAN.
- [ai-ml-engineer] .github/workflows/warm-keeper.yml — log the HTTP status to job summary (`curl -sI -o /dev/null -w "%{http_code}\n"`) so a sustained 5xx is visible without failing the run.

## t22-deploy — 2026-05-10T14:30Z
Report: tasks/T22_deploy.md (Outcome section)

### Should-fix
- [software-engineer] `HF_TOKEN` GH secret was seeded from local `hf auth token` (account-wide write). Replace with a fine-grained Space-only token at https://huggingface.co/settings/tokens (`fridrichmrtn/probable-goose-machine` Spaces → Write only) to shrink blast radius on compromise. `gh secret set HF_TOKEN` to swap; no workflow change needed.
- [software-engineer] No drift guard between `requirements.txt` and `uv.lock`. If `pyproject.toml` is edited without re-running `uv export`, HF builds with stale deps. Add a pre-commit hook that regenerates `requirements.txt` whenever `uv.lock` changes (`uv export --quiet --no-hashes --no-dev --no-emit-project --format requirements-txt > requirements.txt`) AND/OR a CI step that re-exports and `git diff --exit-code requirements.txt`.
- [software-engineer] `.github/workflows/sync-to-hub.yml` triggers in parallel with `ci.yml`, not gated on it. A push that fails ruff/mypy/pytest-fast can briefly reach the HF Space (~60s window before next fix). Acceptable for personal-project review traffic; switch to `workflow_run`-gated on the `static` job (not `live` — too flaky) if reviewer load grows.
- [software-engineer] `huggingface/hub-sync@v0.1.0` rejected in favor of direct `git push` (chosen for proven path + history preservation). Revisit when the action graduates past v0.1.0 — file-mirror semantics auto-exclude `.github/` (currently dead-weight-mirrored to HF) and sidestep the protocol-v2 footgun.
- [software-engineer] `sync-to-hub.yml` uses `actions/checkout@v4` — third workflow now subject to the existing Node 20 deprecation entry (t03-ci-precommit batch). No new fix needed; flag for the same bump-day.
- [software-engineer] HF Spaces' pre-receive hook rejects raw binary blobs; T04 pushed `.pdf` + `.docx` fixtures without LFS coverage and broke `sync-to-hub` for two consecutive commits (67265a1, 4fff6bf — both stuck on eaa6d1f remote-side). Resolved by `git lfs migrate import --include="*.pdf,*.docx" --everything` + force-push; pre-existing `.gitattributes` had HF's stock ML-model filter set but no document filters. Forward fix: add a CI guard that fails if any non-LFS-tracked file matching the LFS filters is staged (catch the next `*.png` / `*.docx` / `*.pdf` slip before it ships). Track here so T06's 8 additional CV fixtures don't reintroduce the regression.

### Nits
- [software-engineer] `tasks/T22_deploy.md` Outcome's "Token note" paragraph duplicates the token-rotation Should-fix above. Drop the Outcome bullet when the rotation lands, or accept the duplication as intentional cross-reference.
- [software-engineer] `.gitattributes` carries HF's full LFS filter set (38 lines) for a project that ships no LFS-tracked binaries. Defensible for forward-compat (T16 may add fixture binaries) but a one-line `# kept for HF parity even though we ship no LFS today` comment would justify it for the next reader.

## implement-t05-minimax-capability-spike — 2026-05-10T15:39Z
Report: tasks/T05_dev-report.md (in dev/implement-t05-minimax-capability-spike)

### Nits
- [ai-ml-engineer] scripts/spike_minimax.py — extract/score prompts have no few-shot examples. The 70% anchor-rate gate is reachable without them (M2.7 is a strong instruction-follower) but adding 1 worked example per stage is the cheapest insurance against gate flakiness in T05 reruns.
- [hiring-manager] src/jobfit/py.typed — added in this branch as a marker file so `mypy --strict scripts/spike_minimax.py` resolves the local `jobfit` package. Mention in the upstream PR description so reviewers don't read it as accidental.
- [ai-ml-engineer] src/jobfit/obs.py — the `_stage` contextmanager defined inline in `scripts/spike_minimax.py` is a manual `current_stage` setter. If T07/T08 also need a "set stage but let exceptions propagate" helper (vs `stage_boundary` which swallows), promote it to `obs.py` rather than duplicating.
- [ai-ml-engineer] scripts/spike_minimax.py — the "≥6 consecutive words" instruction in extract/score prompts duplicates the constant in `src/jobfit/verify.py`. Risk of drift if the floor moves. Either import the constant or add a `# kept in sync with verify.py:_MIN_QUOTE_WORDS` comment in both places.
## add-qa-engineer — 2026-05-10T15:44Z
Report: tasks/dev-report.md (in dev/add-qa-engineer)

### Should-fix
- [ai-ml-engineer] .claude/agents/qa-engineer.md:17 — §5(4) differentiation eval bullet overlaps ai-ml-engineer ownership; tighten to "verify the assertion exists / would fail on regression", clarify ai-ml-engineer owns eval design vs qa owns presence-check.
- [ai-ml-engineer] .claude/agents/qa-engineer.md:17 — substring-grounded explanation bar (PRD §4.5) reads as inviting qa to grade grounding logic itself; reword to "a test asserts every claim in a sample report passes the substring check" so lane stays test-presence, not eval-design.
- [product-owner] .claude/skills/dev/SKILL.md:192 — qa-engineer fires every dev run; for docs/prompt-only diffs that burns burst tokens. Consider gating on diff-signal: tests/, src/jobfit/obs.py, stage workers, tasks/PLAN.md, tasks/T*.md.
- [product-owner] .claude/agents/qa-engineer.md:33 — lane-overlap risk with product-owner / ai-ml-engineer; add explicit "do not duplicate findings already in product-owner / ai-ml-engineer scope" line so the burst returns distinct findings.
- [product-owner] tasks/qa_audit.md:3 — stub disclosure is honest but creates ambiguity; a real qa-engineer re-run is now required before any audit finding is actioned.
- [product-owner] tasks/PLAN.md:531 — no decision rationale captured for adding a 5th reviewer at this stage of a 1-day budget; add a 1–2 line rationale so the addition reads deliberate.
- [hiring-manager] .claude/skills/dev/SKILL.md:192 — burst-size arithmetic wording: "4-agent burst (qa-engineer always fires)" reads as if 4 is always-on. Reword as "with UI flag = 5-agent burst, without = 4 (qa-engineer always fires)".
- [hiring-manager] tasks/qa_audit.md:1 — surface the stub disclosure into the dev-report itself and add a [STUB] tag in the H1 so an `rg "^# "` index does not equate this with future real audits.
- [codex] .claude/skills/dev/SKILL.md:192 — same arithmetic ambiguity as hiring-manager finding above; one-line wording fix.

### Nits
- [ai-ml-engineer] .claude/agents/qa-engineer.md:50 — "mock that defeats the test" example ("salary test mocks both search and LLM range estimator") is ambiguous — that pattern is correct for a salary-stage plumbing unit test; reword so false positives on legit stage-isolation tests are avoided.
- [ai-ml-engineer] tasks/qa_audit.md:25 — `requests.head(url, timeout=3)` is unreliable (servers return 405/403 on HEAD); prefer `requests.get(url, stream=True, timeout=3)` and inspect status without consuming body.
- [product-owner] tasks/qa_audit.md:97 — co-ownership recommendation for T18/T20 is buried in audit; surface it as a one-line PLAN.md addition instead.
- [hiring-manager] .claude/agents/qa-engineer.md:4 — Bash tool is unbounded; add a one-line constraint in the body ("Bash is for read-only inspection — no `>` / `tee` / `sed -i` against tracked files outside `tasks/qa_*.md`").
- [hiring-manager] .claude/agents/qa-engineer.md:33 — wording: "Read the diff against `main` end-to-end" — orchestrator already passes the diff in; reword so qa does not redundantly recompute.
- [hiring-manager] tasks/PLAN.md:531 — qa-engineer added to Owner enum but no T17–T21 task currently routes to qa ownership; not blocking, but consider adding a co-ownership note for T18/T20 so the new owner is not a dangling signal.
- [hiring-manager] tasks/lessons.md — no entry capturing the "Agent tool unavailable → stub-and-disclose" pattern; durable lesson would auto-fire the same workaround next time a /dev run hits a missing-tool gap.

## t05-latency-revisit — 2026-05-10T16:30Z
Report: tasks/T05_spike.md (Outcome section)

### Should-fix
- [ai-ml-engineer] scripts/spike_minimax.py:43-46 — p50 latency gate relaxed 8s → 20s because MiniMax-M2.x catalog is reasoning-only (no non-reasoning sibling per platform.minimax.io docs). Measured ~16s p50. Acceptable for prototype, but if user-visible latency becomes pain in T15 UI, evaluate Gemini Flash or another non-reasoning provider and revisit the gate.


## T08-implement-l2-pii-redaction — 2026-05-10T19:00Z
Report: tasks/T08_dev-report.md (in feat/block-a-early-stages)

### Should-fix
- [codex] src/jobfit/redact.py:294 — audit-log spans drift when later passes shorten text before earlier replacements; spans point at wrong final-output offsets in multi-pass cases.
- [product-owner] src/jobfit/redact.py:228-276 — header-name pass bails on common single-line headers like `Jan Novotný | +420 777 …` (digit/comma in first line). Real CV layout, silent miss.
- [product-owner] src/jobfit/redact.py:34-45 — `_PHONE` requires separators for the 9-10 digit local branch; bare `777123456` is not matched.
- [product-owner] PRD §4.7 lists "address" as PII; redaction covers only CZ postcode digits. Bare street lines (`Korunní 12, Praha 4` without postcode) leave the address intact.
- [product-owner] tasks/T08_redact.md:75-82 — Outcome §Known limitations omits the header-name bail-out and the address coverage gap; reads more confident than the implementation warrants.
- [hiring-manager] src/jobfit/redact.py:12-13 — audit-log `span` is recorded OUTPUT-relative; the design choice makes spans useless to consumers who want to highlight redacted regions on input. Input-relative spans were trivially available.
- [hiring-manager] src/jobfit/redact.py:154-183 — postcode `original` is only the digit run; the comma+city envelope that triggered the redaction is dropped, so an auditor can't see why this `110 00` was redacted when another wasn't.
- [hiring-manager] src/jobfit/redact.py:34-45 — `_PHONE` third alternative `\d{3}[\s-]\d{3}[\s-]\d{3,4}` can eat digit runs that resemble date sequences; risk not disclosed in Outcome §Known limitations.
- [hiring-manager] tests/test_redact.py:80-89 — the test labelled "idempotency_existing_markers" only verifies non-duplication in a single pass. The two-pass test below it is the real idempotency check; the first is misnamed.
- [hiring-manager] src/jobfit/redact.py:269 — `original=stripped` for the header-name path records the whole stripped line as the matched name; coupling to structural validation is implicit.
- [qa-engineer] tests/test_redact.py:91-104 — `audit_log == []` on second pass is over-strict; asserts an implementation detail (zero new entries) rather than the contract (no double-redaction). A future audit refinement could break this test for no user-visible reason.
- [qa-engineer] tests/test_redact.py — no negative tests for email/URL/phone: `email@` (no TLD), `https:foo` (malformed URL), `123456` or `EMP-12-345-6789` (should NOT match phone). Boundary guards in the regex are unpinned.
- [qa-engineer] tests/test_redact.py — no regression test for the documented phone limitations (`(420) 777 …`, `+1.555.…`, `00420 …`); the limitation is undefended against accidental over-matching.
- [qa-engineer] tests/test_redact.py — `_YEAR_BARE` is never exercised by a test; a bare `2018` outside a date context should be kept, but no assertion pins that boundary. Year over-redaction is the most likely regression target.
- [qa-engineer] tasks/T08_redact.md:23 — task contract still says spans are recorded with `original, replacement, span`; outcome clarifies OUTPUT-relative + "informational", but no test asserts `result.text[span[0]:span[1]] == replacement`. Downstream consumers (T15) need that pinned.

### Nits
- [product-owner] src/jobfit/redact.py:60-63 — Czech month names (`leden`, `únor`, …) not in `_MONTH`; CZ-language CVs get years masked only via the range branch.
- [product-owner] src/jobfit/redact.py:111-151 — schema `Redaction.span` has no docstring stating output-relative; a consumer reading the schema in isolation will assume input-relative.
- [hiring-manager] src/jobfit/redact.py:321-322 — `assert cm.failure is not None; return cm.failure` is defensive copy from `ingest.py`; the contract is already in `stage_boundary`.
- [hiring-manager] src/jobfit/redact.py:60-63 — `Sept` listed after `Sep` in `_MONTH` alternation; works only because of regex backtracking.
- [hiring-manager] src/jobfit/redact.py:198 — `year_m` and `m` in the same function with similar purpose; minor naming friction.
- [hiring-manager] tests/test_redact.py:186-191 — `test_fixture_corpus_present` is slow-marked but doesn't do IO worth marking; would be more useful as a fast test that fails CI without `-m slow`.
- [hiring-manager] src/jobfit/redact.py:302-318 — counts dict keyed by string; if `RedactionKind` ever gains a member, the count silently misses.
- [qa-engineer] tests/test_redact.py:80-89 — mixes existing-marker and fresh-PII inputs in one test; two separate tests would localize failure.


## T09-senior-fixture-anchor-survival — 2026-05-11T00:00Z
Report: tasks/T09_extract.md (Outcome section)

### Should-fix
- [ai-ml-engineer] src/jobfit/prompts/extract.md — senior fixture anchor-survival rate is unstable on MiniMax-M2.7-highspeed at 0-temperature: 5 runs returned 60% / 85% / 85% / 92% / 100%. The 60% outlier comes from the model emitting 4-word skill summaries (e.g. `"BigQuery, PostgreSQL, Kafka 3.7."`) that violate the prompt's 6-word literal-substring rule. Live gate is the spec-mandated ≥80%, so the senior fixture can flake. Next experiment: add a negative one-shot example to `extract.md` showing a paraphrased / too-short skill being dropped, paired with the corrected literal-quote variant; re-measure survival over ≥5 runs before tightening further.

### Defer (cross-cutting)
- [qa-engineer] cross-cutting — failure path should emit a duration event. `stage_boundary` currently emits only an `error` event on failure, no matching `done`/`duration_ms`. T07/T08/T09 all follow the same pattern. Address uniformly at the boundary, not per-stage.

### Defer (T09 reviewer findings, must-fix not in heal scope)
- [ai-ml-engineer] src/jobfit/prompts/extract.md — prompt nits deferred from heal: mention that `[]` (empty list) is valid for any of the four list fields; relax the "unique" wording on `anchor.quote` (currently can read as forbidding any 6-word substring that appears twice when 8+ words would be fine); reconcile `detected_years_experience` schema range (prompt says 0–50, spec says (0, 50) — i.e. test asserts >0, prompt allows 0).
- [hiring-manager] src/jobfit/extract.py:50 — `cast(Profile, raw)` is a typing-only no-op; `complete_json` already returns the schema type. Drop the cast or replace with `isinstance` runtime guard.
- [hiring-manager] tests/test_extract.py:155 — `_LIVE_FIXTURES = sorted(...)` runs at import time and silently empties on a fresh checkout without fixtures. Move the glob into a fixture or assert non-empty when MINIMAX_API_KEY is set.
