
## t01-schemas — 2026-05-10T13:50Z
Report: tasks/dev-report.md (in dev/t01-schemas)

### Should-fix
- [ai-ml-engineer] src/gander/schemas.py — `GrowthAction.mechanism: str` is unanchored. PLAN §M4 Jaccard test only covers `what`; mechanism could become copy-paste boilerplate ("builds in-demand skills") and pass.
- [product-owner] src/gander/schemas.py — Add `Confidence.judged_by: Literal["independent"]` (or similar tracking field) so PRD §4.3 separation is encoded in the type, not just convention.
- [product-owner] src/gander/schemas.py — Add a `+30%` calibration field (per-action `expected_salary_delta_pct: int | None` or top-level `growth.target_uplift_pct: int = 30`) so T13/T17 can verify PRD §3 / §4.4 instead of trusting prose.
- [hiring-manager / codex] src/gander/errors.py:15 — `class stage_boundary` is snake_case (PEP 8 violation) AND lacks the decorator form the spec mentioned. Either rename to `StageBoundary` (accept capitalized call site) or implement `__call__` to support `@stage_boundary("score")` decorator usage. Current state is the worst of both.
- [ux-engineer] src/gander/errors.py:11 — `StageFailure.user_message` needs a one-line docstring noting it's reviewer-facing copy (PRD §4.6 strings), not engineer placeholder text — prevents T15/T16 authors from putting `repr(exc)` in there.
- [ux-engineer] src/gander/errors.py:65 — `user_message=str(exc) or type(exc).__name__` will leak raw Python exception strings to the UI surface. Add a comment requiring callers to overwrite with PRD §4.6 copy before the StageFailure renders.

### Must-fix (remaining — exhaustion)
- [ai-ml-engineer] src/gander/schemas.py:39-41 — `Anchor.section: str | None` constraint to `Literal[...]` rejected. Why: reviewer conflated CV-section vocabulary (open-ended: "Work Experience", "Projects", "Publications", "Open Source") with `Component.name` vocabulary (closed 4-element set). Forcing a Literal would be wrong. Addressed via clarifying docstring on `Anchor` in the heal commit.
- [ai-ml-engineer] src/gander/schemas.py:65-71 — `SalaryEstimate.reasoning` split or `for_judge()` projection rejected. Why: PLAN §L4c judge signature is `judge(sources, low, high, currency, period) -> Confidence` — individual fields, not the SalaryEstimate object. Reasoning never reaches the judge by construction; isolation is enforced at the T12 call site, not the schema. Addressed via clarifying docstring on `SalaryEstimate` in the heal commit.

### Nits
- [ai-ml-engineer] src/gander/schemas.py:60-62 — `ProfileItem.text` is paraphrasable (only `anchor.quote` is verified). Consider invariant: `text` ⊆ `anchor.quote`.
- [ai-ml-engineer] src/gander/schemas.py:81-83 — `Confidence` has no link back to the `SalaryEstimate` it judged; `judged_low/judged_high` would help the recompute-then-compare golden test.
- [ai-ml-engineer] src/gander/errors.py:48-71 — Add a comment that `asyncio.CancelledError` (BaseException, not Exception) deliberately propagates, so future "fixes" don't swallow cancellation.
- [ai-ml-engineer] tests/test_schemas.py — No test exercises the `Anchor.section` round-trip; the §4.5 hardening hangs on this.
- [product-owner] src/gander/schemas.py — `RawCV.content_bytes: bytes` is unbounded; add a `# size guard lives in T07 ingest` comment.
- [product-owner] src/gander/schemas.py — `Report.raw_cv_text: str` is non-optional; ingestion failure case can't construct a Report. Default to `""` or `str | None`.
- [hiring-manager] src/gander/schemas.py:111 — `Report.model_rebuild()` may be a no-op since `StageFailure` is eagerly imported (not behind `TYPE_CHECKING`). Drop or comment-justify.
- [hiring-manager] src/gander/schemas.py — Reorder so `Anchor`/`ProfileItem`/`Component` cluster together (the "claim-with-evidence" group).

## t02-utils — 2026-05-10T14:30Z
Report: tasks/T02_dev-report.md (in dev/t02-utils)

### Should-fix
- [ai-ml-engineer] src/gander/llm.py — Anthropic prompt caching not enabled. PLAN §"Cold-start mitigation" notes Anthropic fallback only — but if we ever ship it as primary, missing `cache_control` markers on the system prompt is a 90%+ cost regression. Add a `# T05/T22:` TODO at the Anthropic branch.
- [ai-ml-engineer] src/gander/llm.py:31 — `_ANTHROPIC_MODEL = "claude-sonnet-4-6"` is unverified against Anthropic's published model IDs. Confirm before T05 fallback path is exercised; if ID is wrong, fallback fails on first call.
- [ai-ml-engineer] src/gander/verify.py — Substring match has no word-boundary guard: a 6-word quote like "data engineer with five years of" would match inside "metadata engineer..." . Acceptable for L0 but flag for T07/T09.
- [ai-ml-engineer] src/gander/verify.py — `drop_unverified` uses `getattr(item, anchor_attr)` with no fallback; raises `AttributeError` on items missing the anchor field. Either gate with `hasattr` + skip, or document the contract that callers must pre-filter.
- [ux-engineer] src/gander/obs.py — `subscribe()` is sync-context only; Gradio's UI loop wants an async-iterable / queue for progress events. Wrap with an `async_subscribe()` that pushes onto an `asyncio.Queue` before T16 wires the UI.
- [ux-engineer] src/gander/errors.py — `StageFailure.user_message = str(exc) or type(exc).__name__` will leak raw Python exception strings to the UI. Add a comment requiring T15/T16 callers to overwrite with PRD §4.6 copy.
- [hiring-manager] src/gander/llm.py — `_chat_json` / `_chat_text` use `Any`-typed clients to dodge the OpenAI/Anthropic type divergence. Acceptable but flag a `# typing: provider dispatch` TODO so future readers know it's deliberate.
- [product-owner] src/gander/llm.py — `MODEL_PRICES` dated 2026-05-10 in a comment; consider a `# Re-verify after:` field with an explicit 90-day TTL so cost reports don't drift silently.
- [product-owner] src/gander/llm.py — `complete_text` always uses `cheap` model default; PLAN §L4c judge needs `reasoning` for the calibration leg. Either swap the default or document the per-call override at T12.

### Nits
- [codex] src/gander/verify.py:52 — `str.count()` ignores overlapping occurrences; for 6–7 word "unique" checks this is technically wrong but practically benign (overlapping 6-word repeats are vanishingly rare in CV prose). Leave as-is unless T17 acceptance flags it.
- [ai-ml-engineer] src/gander/obs.py — `_subscribers` uses immutable tuple (good for asyncio.gather), but mutation is O(n) per subscribe. Fine at expected fan-out (≤5 subscribers); flag if T16 hits more.
- [ai-ml-engineer] src/gander/llm.py — JSON-mode fallback for Anthropic uses prompt-injection ("Return JSON only, no prose."), not native tool-use. Switch to `tools=[{...}]` if Anthropic becomes primary.

## t03-ci-precommit — 2026-05-10T15:00Z
Report: tasks/T03_dev-report.md (in dev/t03-ci-precommit)

### Should-fix
- [ux-engineer] .github/workflows/warm-keeper.yml:5 — `*/5 * * * *` is 288 runs/day — overkill for a hiring-committee review window of ~1–2 hours. Consider business-hours-only schedule (e.g. `*/10 8-22 * * *`) before T22 deploy. Free-tier Actions minutes are unlimited for public repos so this is harmless today, but worth tightening when traffic pattern is known.
- [hiring-manager] all of T03 commit dcddf96 — auto-format pass on T01/T02 source (`src/gander/llm.py`, `src/gander/schemas.py`, `tests/test_llm.py`) was bundled into T03 instead of landing as a separate "format ratchet" commit. Direction is right (CI's `ruff format --check` would otherwise red day one), but packaging is wrong — bundling ties the auto-fix to the workflow change so a revert of T03 would undo both. Acceptable cost for an L0 task; flag the pattern in `tasks/lessons.md` so future hygiene PRs land on their own commit.
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
- [hiring-manager] src/gander/py.typed — added in this branch as a marker file so `mypy --strict scripts/spike_minimax.py` resolves the local `gander` package. Mention in the upstream PR description so reviewers don't read it as accidental.
- [ai-ml-engineer] src/gander/obs.py — the `_stage` contextmanager defined inline in `scripts/spike_minimax.py` is a manual `current_stage` setter. If T07/T08 also need a "set stage but let exceptions propagate" helper (vs `stage_boundary` which swallows), promote it to `obs.py` rather than duplicating.
- [ai-ml-engineer] scripts/spike_minimax.py — the "≥6 consecutive words" instruction in extract/score prompts duplicates the constant in `src/gander/verify.py`. Risk of drift if the floor moves. Either import the constant or add a `# kept in sync with verify.py:_MIN_QUOTE_WORDS` comment in both places.
## add-qa-engineer — 2026-05-10T15:44Z
Report: tasks/dev-report.md (in dev/add-qa-engineer)

### Should-fix
- [ai-ml-engineer] .claude/agents/qa-engineer.md:17 — §5(4) differentiation eval bullet overlaps ai-ml-engineer ownership; tighten to "verify the assertion exists / would fail on regression", clarify ai-ml-engineer owns eval design vs qa owns presence-check.
- [ai-ml-engineer] .claude/agents/qa-engineer.md:17 — substring-grounded explanation bar (PRD §4.5) reads as inviting qa to grade grounding logic itself; reword to "a test asserts every claim in a sample report passes the substring check" so lane stays test-presence, not eval-design.
- [product-owner] .claude/skills/dev/SKILL.md:192 — qa-engineer fires every dev run; for docs/prompt-only diffs that burns burst tokens. Consider gating on diff-signal: tests/, src/gander/obs.py, stage workers, tasks/PLAN.md, tasks/T*.md.
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

## t06-heal — 2026-05-10T20:50Z
Report: T06 heal commit on `feat/block-c-corpus-render`.

### Should-fix
- [product-owner] T20 spec drift: PhD vs MSc school-line wording — `tasks/T20_bias.md` line 19 specifies the redacted variant as "MSc in Computer Science, [REDACTED UNIVERSITY]", but persona #9 is a PhD and the corpus renders `Ph.D. in Computer Science — [REDACTED UNIVERSITY]`. Either reword the T20 line to PhD to match the corpus, or replace the persona in T20 with a candidate whose canonical line is MSc. SOURCES.md flags the drift in the bias-pair section.

## t14-heal — 2026-05-10
Report: T14 commit on `feat/block-c-corpus-render`.

### Should-fix
- [ux-engineer] T14 spec drift — `tasks/T14_render.md` references `statuses["ingest"]` / `statuses["redact"]` and pill labels `Parse · Redact · Score · Salary · Plan`, none of which exist in `schemas.StageName` (`profile / score / salary / confidence / growth`); the schema's `_require_exact_status_keys` validator rejects unknown keys. Renderer (T14) maps the 5 schema stages to display labels `Profile / Score / Salary / Confidence / Plan` and treats `report.profile = StageFailure` as the top-level short-circuit. Owner: T14 spec author. File: `tasks/T14_render.md`.
- [ai-ml-engineer] Anchor/justification visual separation — `src/gander/report.py:163-170` renders `<p>justification</p>` immediately followed by `<blockquote>quote</blockquote>` with no visual hierarchy distinguishing model commentary from grounding evidence. Polish belongs in the CSS host. Owner: T16 — add `.evidence-label` and a contrasting border for `<blockquote>` inside `<details>`.
- [ai-ml-engineer] §4.6 strings not pinned as constants — PRD §4.6 user-facing failure copy ("Unable to read this file…", "Insufficient market data for this profile", "Could not generate this section reliably") is set per-call by upstream stages with no central registry; a string-drift regression has no test coverage. Cross-task: belongs to whichever task owns each stage worker (T07 ingest, T11 salary, etc.) — pin the strings as module-level constants and assert on them in the per-stage tests.
- [ai-ml-engineer] Top-level callout MD vs HTML inconsistency — `src/gander/report.py:245` short-circuit returns an HTML `<div class="gander-callout">` while every other failure path returns a markdown `> ⚠ …` blockquote. Works under Gradio's mixed renderer today but will surprise the next maintainer. Decision: when T16 wires the UI host, settle on one shape end-to-end (likely HTML for both) and align.
- [product-owner] Footer callout CSS glyph — `src/gander/report.py:98` — `.gander-callout::before` prepends `⚠` via CSS. The markdown variant (`_failure_callout_md`) prepends a literal `⚠` in the rendered text. If T16's host applies the CSS class to the markdown-rendered blockquote as well, both glyphs would stack. Verify no double-glyph when T16 wires the UI.

## T11 — 2026-05-10T18:30Z
Report: tasks/T11_dev-report.md (in feat/block-b-late-stages)

### Should-fix
- [ai-ml-engineer] src/gander/salary.py:80 — `kept` partial-drop branch (some URLs match input set, some don't) has no fast-test coverage; only the all-drop branch is exercised.
- [ai-ml-engineer] src/gander/salary.py:213 — URL-subset comparison is on the post-Pydantic-normalized form (`str(HttpUrl)`), not the raw DDG `href`. Document the matching invariant in code or prompt; add a unit test pinning normalization behavior on edge URLs (trailing slash, scheme casing).
- [hiring-manager] src/gander/salary.py:78 — `search()` raises `RuntimeError` while `estimate_salary()` returns `StageFailure` for post-LLM logical failures. Pattern inconsistency vs T10 (which only returns). Consider migrating `search` to a sentinel-return + caller-checks-and-returns shape so the canonical user copy lives next to the structured failure.
- [hiring-manager] src/gander/salary.py:107 — `profile.detected_role.strip() or "data scientist"` silently masks an empty role, which would be a T09 (profile) defect. Surface via StageFailure or at minimum emit telemetry.
- [hiring-manager] tests/test_salary.py — DDG mock returns either `[]` or raises. Defensive `body`/`snippet` and `href`/`url` key fallback in `_to_source` is therefore untested. Add a populated-result fast test that exercises both key shapes.
- [qa-engineer] tests/test_salary.py:173 — live test reads `cv_text` from senior fixture but only asserts truthiness — never pipes the CV through T09's parser → T10's redactor. Either drop the read or wire the upstream stages once T09 lands.
- [qa-engineer] src/gander/salary.py — telemetry key naming (`raw_results`, `dedup_results`, `dropped_invalid_url`) is stage-local. Audit cross-stage convention once T12/T13 land; consider a one-line `obs.py` schema doc.
- [qa-engineer] tasks/T11_salary.md — Verification block names commands but doesn't enumerate the events tests must assert on (`salary_search`, `salary_estimate`, `stage_failure`). Tighten when promoting T11 contract to durable doc.

### Nits
- [hiring-manager] src/gander/salary.py:154 — single-letter loop var `q`; rename to `query`.
- [hiring-manager] tests/test_salary.py — extract `_placeholder_item()` helper (used 4×).
- [ai-ml-engineer] src/gander/prompts/salary.md:33 — language about "if fewer than 2 input results corroborate" conflicts with the §4.5 hallucination guard; reword to forbid extrapolation explicitly.
- [hiring-manager] src/gander/salary.py:14 — `_SYSTEM_PROMPT = _PROMPT_PATH.read_text(...)` at import time defeats hot-reload; comment intent or move into a function.
- [ai-ml-engineer] src/gander/salary.py:124 — `>= 10` senior threshold is hardcoded with no comment.
- 7 additional minor naming/convention nits surfaced across reviewers — not enumerated.


## T12 — 2026-05-11T07:00Z
Report: tasks/T12_dev-report.md (in feat/block-b-late-stages)

### Should-fix
- [product-owner + ai-ml-engineer] src/gander/confidence.py:13 — `model="cheap"` and `model="reasoning"` both resolve to `MiniMax-M2.7-highspeed` under current `_PROFILE_MODELS`, so the "different model distribution" property promised by `tasks/PLAN.md §L4c` is degraded to "different prompt + temperature isolation". Revisit once T05 confirms a genuinely distinct cheap-tier provider (`abab6.5s-chat` was the original intent) or accept the degradation in PRD §4.3 documentation.
- [qa-engineer] src/gander/confidence.py:104 vs tasks/T12_dev-plan.md:97 — counter named `sources_count` in code, `n_sources` in plan. T11 also has a stage-local counter naming drift (`raw_results`, `dedup_results`). Audit cross-stage telemetry naming convention before T15 wires events into the renderer.
- [qa-engineer] tests/test_confidence_unit.py — no test for Medium/High tier paths skipping the regenerate logic entirely. The marker check only fires on Low; a regression that ran the check on every tier would still pass current tests. Add a Medium-tier mock to lock in the no-regenerate branch.
- [ai-ml-engineer] src/gander/prompts/confidence_step_a.md — rubric phrasing "deviation against the median of extracted snippet numbers" is unambiguous on paper but never live-tested. T19 golden tests should pin tier-stability across consecutive calls at temp=0 before this rubric is considered settled.
- [codex] src/gander/confidence.py:37 — `_RATIONALE_LOW_REGEX = re.compile(r"insufficient|disagree", re.I)` substring-matches inside "insufficiently" / "disagreement" / "disagreeable". Dev-plan §8 explicitly allows this lexical-family behavior, but a future tightener could add `\b` boundaries by mistake and break the regenerate path. Add a code comment pinning the intentional substring-match.
- [ai-ml-engineer] src/gander/prompts/confidence_step_b.md — no word/character cap on the rationale paragraph; combined with "3 to 5 sentences" can drift long. Add a soft ~80-word ceiling consistent with how the renderer will surface this string.
- [ai-ml-engineer] src/gander/confidence.py:71-73 — Step B's user payload formats the produced range without validating that `low < high` or that `(currency, period)` is a coherent pair. T11 enforces these in `estimate_salary`; T12 trusts its caller. Document the contract in the docstring or fail-loud here.
- [qa-engineer] tests/test_confidence_unit.py — no test for `sources=[]` empty-list edge. The signature accepts it, the prompt rubric says "Low if <2 sources", but a malicious/buggy upstream stage could pass `[]` and we have no probe.
- [hiring-manager] src/gander/confidence.py:108-109 — the regenerate branch duplicates the `complete_text` call. A `async def _draft_rationale()` helper would dedupe and make the "draft, check lexicon, redraft once, fall back" intent more legible.
- [codex] src/gander/prompts/confidence_step_b.md — register described as "Czech-English business" without defining whether the prose is in Czech or English. Tests + golden expectations are in English; spec the prompt to "English prose intended for a Czech-speaking reviewer" to remove the ambiguity.

### Nits
- [qa-engineer] tests/test_confidence_unit.py:78-85 — leak-channel assertion checks for substrings "low", "high", "month", "czk" but "low" appears in many ordinary English words (below, follow). Today's fixture snippets are controlled, but a future snippet edit could surface a confusing failure. Either use word boundaries or restrict to JSON key names.
- [hiring-manager] tests/test_confidence_unit.py — test name `test_step_b_cannot_override_step_a_and_regenerates_on_low` conflates two assertions; split into `test_step_b_cannot_override_step_a` + `test_regenerate_falls_back_when_marker_still_missing` for sharper failure messages.
- [product-owner] src/gander/prompts/confidence_step_b.md — example openings all start "Confidence in this estimate is X." Slightly bureaucratic but not load-bearing.
- [ai-ml-engineer] src/gander/confidence.py:30-35 — prompts loaded at import time; broken install / stripped wheel causes import failure rather than clean stage failure. T11 has the same pattern (consistency wins), but it's a latent footgun for both.
- [qa-engineer] tasks/T12_confidence.md:42 — task lists two fast tests; code ships six. Update the task contract to list the full set or move the strengthening into a checked deliverable.
- 4 additional minor naming/convention nits surfaced across reviewers — not enumerated.


## T13 — 2026-05-11T03:57Z
Report: tasks/T13_dev-report.md (in feat/block-b-late-stages)

### Should-fix
- [ai-ml-engineer] src/gander/growth.py:155 — `model="reasoning"` resolves to MiniMax-M2.7-highspeed under current `_PROFILE_MODELS` (same as confidence/salary). The original PLAN §L5 intent was a reasoning-tier distinct from the cheap path; revisit once T05 confirms a genuinely distinct reasoning provider, or accept the convergence in PRD §4.4 documentation.
- [qa-engineer] src/gander/growth.py:213-217 + 232-239 — `growth_actions_truncated.dropped` and `growth_anti_slop_check.dropped` both use the key `dropped` with different semantics (truncation overflow vs. ban/verify drops). Cross-stage rename pass for telemetry keys before T15 wires events into the renderer (echoes the T11/T12 naming-drift entry).
- [qa-engineer] tests/test_growth_unit.py — parametrized ban-phrase test reuses three non-banned actions across each case verbatim. A `_three_clean_actions()` helper would dedupe ~80 lines without obscuring what each parameter is testing.
- [product-owner] src/gander/growth.py:51 — `_BOILERPLATE_JACCARD_THRESHOLD = 0.6` is unverified against the corpus T17 will produce. Threshold sensitivity should be re-evaluated against the T17 baseline before T19 acceptance.
- [product-owner] src/gander/prompts/growth.md:30 — "every `what` MUST reference a specific element from the candidate's CV" is unenforced by the post-LLM code path (only the anchor's verbatim substring is checked). A future tightener could add a Jaccard check between the `what` and the anchor quote, or accept the gap as covered by verify_quote + ban list.
- [hiring-manager] src/gander/growth.py:144-273 — the inner-and-outer try/except gives two cascading failure paths with overlapping reasons (`llm_error` vs `unexpected_error`). Acceptable for the §4.6 guarantee but worth a docstring note describing the fallthrough order.
- [hiring-manager] src/gander/growth.py:33 — system prompt loaded at module-import time. Same pattern as T11 and T12; broken install causes import failure rather than a clean stage failure. Worth a cross-stage refactor (`_load_prompt_lazy()`) before T22 deploy.

### Must-fix (remaining — exhaustion)

None. Single heal iteration closed all 10 items.

### Nits
- [ai-ml-engineer] src/gander/growth.py:274 — unreachable `return StageFailure(..., debug_detail="unreachable")` exists solely for mypy; flagged so the next reader knows it's not dead code in the runtime sense.
- [ai-ml-engineer] src/gander/growth.py:43-49 — `_BAN_PHRASES` substring-matches inside longer words ("phd" inside "phdcandidate"); intentional and documented in the module docstring. Future tightener should not add word boundaries without checking the prompt-mirror invariant.
- [qa-engineer] tests/test_growth_unit.py — no direct test that the truncate event's `count_before` equals the actual model-emitted action count (only verified at 7). Add a parametrized 6/7/8/9-survivor case if regressions on the boundary become a concern.
- [hiring-manager] tests/test_growth_unit.py — fast tests do not include a CV with no Education section to exercise `section=None` survivor handling end-to-end (only the unverified-anchor branch uses `section=None`). Defer to T17 fixture diversity.


## T08-implement-l2-pii-redaction — 2026-05-10T19:00Z
Report: tasks/T08_dev-report.md (in feat/block-a-early-stages)

### Should-fix
- [codex] src/gander/redact.py:294 — audit-log spans drift when later passes shorten text before earlier replacements; spans point at wrong final-output offsets in multi-pass cases.
- [product-owner] PRD §4.7 lists "address" as PII; redaction covers only CZ postcode digits. Bare street lines (`Korunní 12, Praha 4` without postcode) leave the address intact.
- [product-owner] tasks/T08_redact.md:75-82 — Outcome §Known limitations omits the header-name bail-out and the address coverage gap; reads more confident than the implementation warrants.
- [hiring-manager] src/gander/redact.py:12-13 — audit-log `span` is recorded OUTPUT-relative; the design choice makes spans useless to consumers who want to highlight redacted regions on input. Input-relative spans were trivially available.
- [hiring-manager] src/gander/redact.py:154-183 — postcode `original` is only the digit run; the comma+city envelope that triggered the redaction is dropped, so an auditor can't see why this `110 00` was redacted when another wasn't.
- [hiring-manager] src/gander/redact.py:34-45 — `_PHONE` third alternative `\d{3}[\s-]\d{3}[\s-]\d{3,4}` can eat digit runs that resemble date sequences; risk not disclosed in Outcome §Known limitations.
- [hiring-manager] tests/test_redact.py:80-89 — the test labelled "idempotency_existing_markers" only verifies non-duplication in a single pass. The two-pass test below it is the real idempotency check; the first is misnamed.
- [hiring-manager] src/gander/redact.py:269 — `original=stripped` for the header-name path records the whole stripped line as the matched name; coupling to structural validation is implicit.
- [qa-engineer] tests/test_redact.py:91-104 — `audit_log == []` on second pass is over-strict; asserts an implementation detail (zero new entries) rather than the contract (no double-redaction). A future audit refinement could break this test for no user-visible reason.
- [qa-engineer] tests/test_redact.py — no negative tests for email/URL/phone: `email@` (no TLD), `https:foo` (malformed URL), `123456` or `EMP-12-345-6789` (should NOT match phone). Boundary guards in the regex are unpinned.
- [qa-engineer] tests/test_redact.py — no regression test for the documented phone limitations (`(420) 777 …`, `+1.555.…`, `00420 …`); the limitation is undefended against accidental over-matching.
- [qa-engineer] tests/test_redact.py — `_YEAR_BARE` is never exercised by a test; a bare `2018` outside a date context should be kept, but no assertion pins that boundary. Year over-redaction is the most likely regression target.
- [qa-engineer] tasks/T08_redact.md:23 — task contract still says spans are recorded with `original, replacement, span`; outcome clarifies OUTPUT-relative + "informational", but no test asserts `result.text[span[0]:span[1]] == replacement`. Downstream consumers (T15) need that pinned.

### Nits
- [product-owner] src/gander/redact.py:60-63 — Czech month names (`leden`, `únor`, …) not in `_MONTH`; CZ-language CVs get years masked only via the range branch.
- [product-owner] src/gander/redact.py:111-151 — schema `Redaction.span` has no docstring stating output-relative; a consumer reading the schema in isolation will assume input-relative.
- [hiring-manager] src/gander/redact.py:321-322 — `assert cm.failure is not None; return cm.failure` is defensive copy from `ingest.py`; the contract is already in `stage_boundary`.
- [hiring-manager] src/gander/redact.py:60-63 — `Sept` listed after `Sep` in `_MONTH` alternation; works only because of regex backtracking.
- [hiring-manager] src/gander/redact.py:198 — `year_m` and `m` in the same function with similar purpose; minor naming friction.
- [hiring-manager] tests/test_redact.py:186-191 — `test_fixture_corpus_present` is slow-marked but doesn't do IO worth marking; would be more useful as a fast test that fails CI without `-m slow`.
- [hiring-manager] src/gander/redact.py:302-318 — counts dict keyed by string; if `RedactionKind` ever gains a member, the count silently misses.
- [qa-engineer] tests/test_redact.py:80-89 — mixes existing-marker and fresh-PII inputs in one test; two separate tests would localize failure.


## T09-senior-fixture-anchor-survival — 2026-05-11T00:00Z
Report: tasks/T09_extract.md (Outcome section)

### Defer (cross-cutting)
- [qa-engineer] cross-cutting — failure path should emit a duration event. `stage_boundary` currently emits only an `error` event on failure, no matching `done`/`duration_ms`. T07/T08/T09 all follow the same pattern. Address uniformly at the boundary, not per-stage.


## t16-gradio-ui-stage-tracker — 2026-05-11T15:16Z
Report: tasks/T16_dev-report.md (in dev/t16-gradio-ui-stage-tracker)

### Should-fix
- [codex] app.py — stub intermediate yields use `StageFailure("pending")` for not-yet-run blocks; `render_body` short-circuits on `profile=StageFailure` and shows "## Score / Salary / Confidence / Plan" failure callouts for mid-stream yields. Visible defect when watching the stub in a browser. Either yield real-but-empty blocks throughout (only statuses advance) or skip body re-render until a stage's block is ready. Throwaway with the stub once T15 lands real `pipeline.run`, but the same shape problem will bite T15 unless its initial yields use `None`-blocks via the planned schema tweak.
- [codex] app.py header — "Processed in-memory; not stored" copy is technically misleading because `gr.File(type="filepath")` writes a temp file to disk. Either soften to "not retained after the session" or switch to `type="binary"` and refactor `handle()` to take bytes directly.
- [ux-engineer] app.py — no client-visible affordance for wrong file type or 10 MB cap. `gr.File(file_types=[".pdf",".docx"])` filters the OS picker but drag-and-drop / a `.txt` renamed `.pdf` bypasses it. `max_file_size="10mb"` produces a Gradio toast that does not match PRD §4.6's "Unable to read this file. Please upload a valid PDF or DOCX." Intercept extension/size in `handle()` and yield the PRD-specified callout, OR explicitly defer to L1 ingestion error path with a code comment.
- [ux-engineer] app.py — header sub-copy italicises both the constraint and the privacy claim on one line. Reviewer's first 60 seconds are the whole product; de-italicise the constraint (plain weight) and keep the privacy line as the italic aside, or split into two lines.
- [ux-engineer] app.py — `run_btn.click` has no `show_progress=` or button-disable wiring; user can re-click mid-stream and Gradio will queue a second job whose yields interleave with the first. Pass `show_progress="hidden"` (the tracker IS the progress UI) and either toggle the button to `interactive=False` for the duration, or set `concurrency_limit=1` on the queue.
- [ux-engineer] app.py — `gr.HTML` (tracker) and `gr.Markdown` (report body) carry no Gradio-level `label=`. Screen readers will read surrounding scaffolding before the live region. Add `label="Pipeline progress"` / `label="Report"` with `show_label=False`. The inner `aria-live="polite"` from T14's CSS already covers the live-region semantics — this is the component-level shim.
- [ux-engineer/product-owner/hiring-manager/qa-engineer] app.py — `open(file_path, "rb").read()` runs blocking I/O on the event-loop thread inside an async handler. For a 10 MB cap this is bounded but noticeable; `await asyncio.to_thread(Path(file_path).read_bytes)` is the one-line fix. Pairs with the next item.
- [product-owner] app.py — plain `open()`/`read()` has no `try/except OSError`. A mid-read failure (file pulled, permission, encoding-on-FS) bubbles as a stack trace + generic Gradio toast — violates PRD §4.6 ("clear, useful messages — not stack traces"). Wrap, catch `OSError`, yield the PRD-specified callout.
- [product-owner] app.py — no file-extension validation before invoking `pipeline_run`. Browser-side `file_types` is convenience, not a guarantee. Gate on suffix in the handler or document explicitly that L1 ingestion owns this in code.
- [product-owner/hiring-manager] app.py:113 — `# type: ignore[arg-type]` on `Source(url="https://platy.cz/path", ...)`. Plan §7.5 specified `HttpUrl(...)` or letting Pydantic v2 coerce the string; implementer chose the ignore. Stub-only code so low-blast, but the plan-vs-implementation divergence is a small judgment tell.
- [hiring-manager] app.py:55–241 — stub is 186 lines of near-identical `Report(...)` literals across 6 yields differing only in the `statuses` dict and which block is real. Refactor to a `for` loop over a list of `(status_map, block_overrides)` tuples; cuts to ~30 lines. Throwaway pre-T15, so low priority — but the same author may end up writing T15's test fixtures, and the muscle memory matters.
- [hiring-manager] app.py:267 — no defensive check that `pipeline_run` is async-iterable at import time. If T15 ships `run` as a regular `def` returning a list, this fails at runtime with a confusing `TypeError`. One-line `inspect.isasyncgenfunction(pipeline_run)` assert at import covers it.
- [hiring-manager/qa-engineer] tasks/T16_dev-plan.md — risk #7.1 (Gradio 6.14 async-generator yields streaming over the queue) is the headline runtime risk and was deferred to "Phase 2 must visually confirm." Phase 2 captured no browser-side evidence (orchestrator can't drive a GUI). Open a small follow-up to actually drive a browser (Playwright probe in a one-off script or a manual reviewer pass) before T22 ships.
- [qa-engineer/hiring-manager] tasks/T16_ui.md — contract carries deliverable bugs that the dev plan corrected: lines 50–54 list "Deployed-Space smoke" (T22 scope), line 46 says `max_file_size` lives on `queue()` (wrong; lives on `launch()` in 6.14), line 45 lists `prefers-reduced-motion` with no verification step. Either strike or fix the contract so it's falsifiable on its own.
- [qa-engineer] tasks/T16_ui.md:47–49 — manual smoke language ("watch pills transition", "no traceback in terminal") names no artifact to capture. Tighten to require captured evidence in the dev-report.
- [qa-engineer] README.md — still the bootstrap stub from T00. Not introduced by this diff; flagged here so T23 doesn't lose the thread.

### Nits
- [ux-engineer/hiring-manager] app.py — `_stub_pipeline_run(file_bytes: bytes, filename: str)` accepts both args but uses neither. Underscore-prefix or a one-line comment would signal intent.
- [hiring-manager] app.py — `handle()` defined inside `with gr.Blocks(...) as demo:` for no closure reason. Pull to module scope for testability and consistency with `_initial_report` / `_stub_pipeline_run`.
- [hiring-manager] app.py — `_initial_report()` rationale is correct but the comment burden it requires is the cost of the schema shortcut. Acceptable for T16; the right surface for the fix is T15 (add `None` to each block union or introduce a sentinel).
- [qa-engineer] tasks/T16_ui.md verification block — `curl -sf http://localhost:7860/ > /dev/null && echo "UI up"` proves a port bind, not that the Blocks app loaded or the click handler is registered. Acceptable given UI testing is deferred to T21, but the curl check should not be confused with evidence the UI works.
- [qa-engineer] app.py stub — `_score()` uses `section="Work Experience"` on an `education` Component anchor. Renderer doesn't grade section-coherence so this is cosmetic; flagged because a reviewer eyeballing the stub output may notice.
- [qa-engineer] app.py — `# type: ignore[import-not-found]` on the `from gander.pipeline import run` line is correctly gated by `find_spec` (post-heal). Once T15 lands, drop the ignore — mypy will then warn "unused type: ignore."
## T19-judge-tests — 2026-05-11T16:15Z
Report: tasks/T19_dev-report.md (in dev/T19-judge-tests)

### Should-fix
- [ai-ml-engineer] tests/test_confidence_judge.py:78 — parametrize the Step B render leakage check over `Low|Medium|High` (currently only `Low`); cheap insurance against tier-specific render branching slipping in later.
- [hiring-manager] src/gander/confidence.py:58 — `_render_step_b` is leading-underscore private but is now part of the T19 test contract; either drop the underscore or add a docstring noting "Step A/Step B contract: adding params here is a leakage-channel change."
- [ai-ml-engineer] tests/test_confidence_judge.py — live tests issue 2 MiniMax calls each (Step A + Step B); cost not budgeted in task Outcome. Note actual cost per run after first live exercise.
- [hiring-manager] tasks/T19_judge_tests.md §Outcome — `judge()` return type widened to `Confidence | StageFailure` vs. T12 contract; flag the contract change in T19 Outcome when filled in.

### Nits
- [ai-ml-engineer] tests/test_confidence_judge.py:21,27,33 — `# type: ignore[arg-type]` for `HttpUrl` strings repeats; a `_src(url, snippet, domain)` factory would remove the noise. Acceptable in a 6-test file.
- [hiring-manager] tests/test_confidence_judge.py:138 — add an inline note that the `insufficient|disagree` regex mirrors `_RATIONALE_LOW_REGEX` in the SUT, so the check is a protocol guard, not an LLM-behavior probe.
- [ai-ml-engineer] tests/test_confidence_judge.py:35-43 — single-source test uses a snippet identical to one of the three-agreeing snippets; vary the body so "single source" is the dominant signal if Step A rubric drifts toward content scoring.

## ui-polish-pass-2 — 2026-05-14T09:46Z
Report: tasks/dev-report.md (in dev/ui-polish-pass-2)

### Should-fix
- [ux-engineer] src/gander/report.py (dark-mode `.pill.running`) — `#fbbf24` hue reads as warning/caution rather than progress; consider amber that's clearly distinct from `.pill.failed` semantics, or a non-yellow accent (e.g., `#60a5fa` blue) for "in flight".
- [ux-engineer] src/gander/report.py — score-table CSS scoped via `.gander-output table` is broad; prefer `.gander-output table.gander-components` (or a similar dedicated class on the rendered table) so future markdown tables inside the same wrapper don't inherit the centered/bordered treatment.
- [ux-engineer] app.py — `visible=False` → `visible=True` on first yield may regress the aria-live "Profile running" announcement on the very first transition because the live region is mounted on the same tick. Verify with VoiceOver / NVDA, or pre-mount the wrapper invisibly via `visible="hidden"` instead of `False`.
- [product-owner] app.py — `handle()` lacks a try/finally envelope around the `async for report in pipeline_run(...)` loop. An unexpected exception escapes as a stack trace into Gradio's toast (violating PRD §4.6 "useful messages, not stack traces"); wrap and yield the §4.6 callout on `except Exception`.
- [product-owner] app.py:1-13 — module docstring still says "the `gr.Markdown` body is initialised empty — never with `render_body(_initial_report())`". After this pass the body is initialised `visible=False`, so the comment is partially stale; refresh to describe the visibility-toggle pattern.
- [hiring-manager] app.py `_HERO_CSS` — `button.primary, .gradio-container button.primary` doubles selectors AND uses `!important`. Pick one: either drop the container-prefixed selector (the `!important` already wins) or drop `!important` (and rely on the higher-specificity selector). Current state is cargo-cult specificity.
- [hiring-manager] app.py `_HERO_CSS` — `button.primary:focus-visible { outline: 2px solid #1d4ed8 }` uses a cool blue against a warm `#92400e` button; visually jarring. Derive the focus ring from the brand (a darker amber or neutral `currentColor`) for cohesion.
- [hiring-manager] app.py `_HERO_CSS` (dark-mode block) — dark-mode disabled button uses `#7c2d12`, which is the same color as the light-mode primary `:hover`. Two semantically different states sharing a color is a tell. Pick a distinct dark-mode disabled tone (e.g., `#a3490d` at lower opacity).
- [qa-engineer] tests/ — no unit test exercises the `handle()` async iterator's yield shape (visibility flags + value contents). A regression where a yield forgets `visible=True` ships without a failing test. Add an async test using `gr.update`-aware assertions.
- [qa-engineer] tests/ — no contract test pins the PRD §4.6 user-visible error strings ("Unable to read this file. Please upload a valid PDF or DOCX."). String drift in `app.py` ships without a failing test. Add a string-equality assertion.
- [qa-engineer] tests/ — no test detects a forgotten `visible=True` on a streaming yield. Could be covered by the same async-iterator test above.
- [codex] app.py — `AsyncIterator[tuple[dict[str, Any], dict[str, Any]]]` typing is more specific than Gradio's actual `gr.update` return contract. Either weaken to `tuple[Any, Any]` or import the precise `gr.events` update type if exported.

### Nits
- [ux-engineer] app.py `_HERO_CSS` — the `@keyframes ganderPulse` block is duplicated logic with `prefers-reduced-motion` override; consider a CSS custom property `--pulse-duration` set to `0s` in the reduced-motion block instead of `animation: none`.
- [product-owner] app.py — caption uses a single em-dash inside a sentence that already has two clauses separated by a period; reads slightly heavy. Could split: "Text-based PDFs only. Scanned/image PDFs aren't supported."
- [hiring-manager] app.py — `_HERO_CSS + _HERO_HTML` string concatenation at the `gr.HTML(...)` call site is unusual; either keep as-is with a comment or merge into one template literal.
- [hiring-manager] src/gander/report.py — `_CSS` is now ~75 lines inside a single Python string; moving to a sibling `.css` file (read at import) would improve syntax highlighting and lint coverage, but the import-time `read_text()` adds an FS dependency. Defer.
- [qa-engineer] tasks/dev-plan.md — verification block lists six gates but doesn't enumerate the observable browser checks (no orange bar, no dead gap, button states); the manual-check artifact is missing from the dev-report.
- [codex] app.py — `_read_error_report()` rebuilds the full `Report` shape per error branch; a tiny `_make_failed_initial(message)` factory would shorten the two error-branch yields by ~5 lines each.

## parallelize-vision-cap-max-tokens — 2026-05-15T11:00Z
Report: tasks/dev-report.md (in dev/parallelize-vision-cap-max-tokens)

### Should-fix
- [ai-ml-engineer / hiring-manager] src/gander/llm.py — three OpenRouter chat blocks (`_chat_json`, `_chat_text`, `_chat_vision_text`) carry near-identical `openrouter_kwargs` construction with conditional `max_tokens` injection. Extract a `_build_openrouter_kwargs(model, messages, *, max_tokens, response_format=None)` helper before the next provider change so the cap-forwarding contract has one home.
- [ai-ml-engineer / ux-engineer / hiring-manager / qa-engineer] src/gander/llm.py — MiniMax branch hard-codes `max_tokens=4096` on its SDK call and silently ignores the `max_tokens` parameter passed by callers. Two failure modes converge here: (1) the per-stage caps from §B are dead code on MiniMax, (2) the cap signal is invisible. Either thread `max_tokens` into the MiniMax branch too, or raise on a non-None `max_tokens` argument when the active provider is MiniMax. MiniMax is currently inactive so this is not a regression, but it's a foot-gun when the provider toggle flips.
- [qa-engineer] tests/test_ingest.py:test_pdf_vlm_parallel_preserves_page_order_and_bounds_concurrency — `peak["max"] >= 2` is a soft lower bound that depends on scheduler timing. Tighten with `asyncio.Event` gating so each task signals "in flight" before the assertion checks, making the lower bound deterministic.
- [qa-engineer] tests/test_ingest.py — no 2-page failure-isolation test. If page 2 raises (e.g., `_IngestLLMReject`), `asyncio.gather(..., return_exceptions=False)` cancels page 1 and page 3 mid-flight. Existing fallback path catches the exception, but there's no regression test that the user-visible behavior (text-mode fallback) is preserved when a parallel sibling fails.
- [qa-engineer] tests/test_confidence_unit.py — step-B regenerate path (`_RATIONALE_LOW_REGEX` miss → second `complete_text` call) is untested for the `max_tokens=256` cap. The regenerate branch is the one that fired in 2 of 3 measurement runs; a regression that drops the cap or changes the value would not fail any test today.
- [qa-engineer] src/gander/obs.py — `llm_call` events do not carry the `max_tokens` value sent with the request. Adding `max_tokens` to the event payload would close the loop with the new `llm_truncated` event: operators could compare actual completion_tokens against the cap without reading source.
- [hiring-manager] src/gander/{extract,score,salary,growth,confidence}.py — five call sites carry numeric `max_tokens=N` literals. Centralize the per-stage budget in a `STAGE_TOKEN_CAPS: dict[str, int]` registry in `gander.llm` so future cap tuning is a single-diff and the budgets are discoverable. Also surfaces the "what is the rationale for 3000 on extract?" question that currently has no inline comment.
- [hiring-manager / ai-ml-engineer] src/gander/confidence.py:214,236 — step-B `complete_text(..., max_tokens=256)` is a repeated literal across initial and regenerate calls. If the cap should ever diverge between paths, this is the place. Bind to a module constant `_STEP_B_MAX_TOKENS = 256`.
- [hiring-manager] tasks/T45_vision_parallel_and_token_caps.md — marked `Status: Done` but live suite verification was punted. Either run `openrouter-live` once on this branch and capture the result in the task Outcome, or downgrade to `Status: Implemented (live verification deferred to next pipeline run)`.
- [hiring-manager / product-owner] tasks/T45_vision_parallel_and_token_caps.md — no rationale captured for the 3000-token extract cap or the 128-token step-A cap. The plan derived them from observed peaks (2427 and 29 respectively) but the task spec doesn't quote the source. Add a one-line rationale per cap so future maintainers don't guess.
- [hiring-manager] src/gander/ingest.py — `_transcribe(i, png)` inner coroutine's emitted `duration_ms` includes time spent waiting on the semaphore. For wallclock budgeting this is the right number, but it conflates two costs. Either rename the field to `task_duration_ms` and emit a separate `provider_duration_ms` measured around the `await client.complete_vision_text(...)` call only, or add a code comment pinning the semantics.
- [ux-engineer] src/gander/extract.py — no local try/except around `complete_json(..., max_tokens=3000)`. If a downstream caller catches `_IngestLLMReject` or similar but `complete_json` raises something else, the user sees a stack trace instead of the PRD §4.6 callout. Wrap with stage-boundary's existing pattern or document the contract.
- [qa-engineer / hiring-manager] tests/test_extract.py / test_score.py / test_salary.py / test_growth_unit.py / test_confidence_unit.py — added `assert captured["max_tokens"] == N` assertions are tautological: they pin the value the same test just passed. Replace with an integration-style assertion that the cap is forwarded into the `chat.completions.create` call kwargs (the value of N is then a test fixture, not a tautology).

### Nits
- [hiring-manager] src/gander/ingest.py — `asyncio.Semaphore(4)` is a magic literal. Bind to `_VLM_MAX_CONCURRENCY = 4` with a one-line comment ("provider rate-limit headroom; raise carefully").
- [hiring-manager] tasks/dev-plan.md — overwriting the prior UI-polish dev-plan with the T45 plan loses provenance. Use `--prefix T45` next time so plan artifacts are namespaced (the skill supports this).
- [ai-ml-engineer] src/gander/ingest.py — `png_to_index` round-trip dict is a workaround for `asyncio.gather`'s preserve-order semantics that the function already relies on. Drop the dict; `gather` returns in submission order.
- [qa-engineer] tests/test_llm.py — three new `max_tokens` forwarding tests are near-identical (one per `complete_json` / `complete_text` / `complete_vision_text`). Parametrize over the three entry points.
- [hiring-manager] src/gander/ingest.py — `_transcribe(i, png)`: `i` is a single-letter loop variable that survives into a closure capture. Rename `page_index`.

## t47-current-employer-fix — 2026-05-15T00:00Z
Report: tasks/T47_dev-report.md (in dev/t47-current-employer-fix)

### Should-fix
- [ai-ml-engineer] src/gander/growth.py validator + 3-survivor floor — if 3+ benign actions get dropped (ban + closed-employer + unverified-anchor stack) the stage flips to `insufficient_verified_actions`. Consider lowering the gate to 2 OR adding a single retry that re-prompts only the dropped actions with the violation reason injected.
- [ai-ml-engineer] src/gander/growth.py `_COMPANY_STOPWORDS` — strips `data, ai, research, science, platform`. An employer literally named "Data Science Institute" or "AI Research Labs" produces zero candidates, so the validator is a no-op for them. Either tighten the stopword list to title words only OR fall back to full-header substring when no token candidates survive.
- [product-owner] src/gander/growth.py `_employer_match_candidates` — legal-form suffixes (`a.s`, `s.r.o`, `sro`, `ltd`, `gmbh`, `inc`, `llc`, `corp`) survive as 3-char tokens after edge-`.,;:` strip and would falsely match unrelated `"a.s"` substrings. Add them to `_COMPANY_STOPWORDS`.
- [product-owner] src/gander/growth.py `_violates_forward_setting` — current-employer match wins unconditionally over closed-employer match. If a current and closed employer share a rare non-stopword token (e.g. "Holding"), a closed-targeted action passes. Document as a known limitation OR use longest-token-wins.
- [product-owner] src/gander/timeline.py header walk-up — hardcoded 3-line window with bullet-glyph-only lines `continue`-ing (not decrementing budget). A CV with 4+ decorative lines plus a real header could lose the company. Count cleaned-empty lines toward budget OR break on non-content.
- [hiring-manager] src/gander/growth.py `_violates_forward_setting:265-271` — current-employer match short-circuits to PASS the moment ANY current candidate substring (e.g. `"independent"`, `"stealth"`) appears in `what`. The current-hit gate should require a non-stopword *company-segment* hit (post-dash side of the header), not any candidate.
- [hiring-manager] src/gander/growth.py `_employer_match_candidates` — `_COMPANY_STOPWORDS` is English-only. Czech CVs leak `vedoucí`, `analytik`, `oddělení` as "company tokens" because they look non-English-stopword. Either localize stopwords or restrict candidate extraction to the post-dash company segment.
- [hiring-manager] src/gander/growth.py `growth_action_dropped` event — omits `current_count`/`closed_count`. Adding both materially improves oncall triage when the LLM regresses.
- [hiring-manager] src/gander/growth.py `_build_user_message` optional-hint params — production always passes them; the default-None branch is effectively dead. Either drop the optional params (force callers) or document the test-only intent.
- [qa-engineer] tests/test_growth_unit.py — Missing explicit test for the `>3 closed-targeted drops → StageFailure` path. The existing failure test mixes ban + unverified, never closed-employer-setting drops.
- [qa-engineer] tests/test_growth_unit.py — Missing 3-letter acronym (DSV) targeted action validator case. `test_payload_bug_pdf_shape` includes DSV but no validator-side coverage of the short-acronym branch.
- [qa-engineer] tests/test_growth_unit.py `test_validator_normalizes_accents_for_match` — named for accent-stripping but inputs differ only in case + tokenization (`alza.cz` vs `Alza.cz a.s.`). Rename OR add a true accent fixture (e.g. `Škoda` vs `skoda`).
- [codex] src/gander/salary.py:595 — Currency gate accepts any 3 uppercase letters, so invalid currencies like `XYZ` can reach reports. Out-of-scope for T47 (salary stage); file separately.
- [codex] tests/test_salary.py:1026 — Live test skips on `OPENROUTER_API_KEY` but `LLMClient` still defaults to MiniMax unless `GANDER_LLM_PROVIDER` is set. Out-of-scope for T47 (salary stage); file separately.

### Must-fix (remaining — exhaustion)
- [codex] tests/test_salary.py:201 — Fast tests instantiate `LLMClient()` before mocked `complete_json` is reached; without a `MINIMAX_API_KEY` env var the constructor fails. Out-of-scope for T47 (salary test infrastructure, predates this branch). Filed for separate ticket. T47 ran fast tests with `MINIMAX_API_KEY=stub` to mirror the existing pattern.

### Nits
- [ai-ml-engineer] src/gander/prompts/growth.md Rule 7 part (c) — could steer LLM to generic OSS boilerplate when `current_employer_hint` is empty. Consider requiring the artefact to name a specific capability gap from `dropped_components`.
- [ai-ml-engineer] src/gander/growth.py emit field — uses `detail` for closed-employer drop, but the rest of the file uses `debug_detail`/`phrase`/`reason`. Minor schema drift.
- [product-owner] src/gander/prompts/growth.md Rule 7 fallback — "if BOTH hint lists are empty, treat top entry as current" is now narrower than the original behaviour. Worth a README "Decisions" note for the round-2 reviewer running on a snippet-shaped CV.
- [product-owner] Plan→code drift — `_BANNED_VERBS_NEAR_CLOSED` from `tasks/T47_dev-plan.md` was cut during implementation in favour of the simpler substring rule. Plan review section should record the cut.
- [hiring-manager] src/gander/timeline.py `_BULLET_GLYPHS` — includes `-`, `–`, `—` (also dash chars). One-line WHY comment would prevent a maintainer from "fixing" the apparent overlap.
- [hiring-manager] src/gander/timeline.py header lookback `range(i - 1, max(-1, i - 4), -1)` — correct but obtuse. A `# at most 3 lines back, stop at top of slice` comment would do.
- [hiring-manager] tests/test_growth_unit.py `test_validator_drop_emits_observability_event` — relies on `"synnex"` appearing in lowercased `detail`. A future refactor that title-cases detail will silently break the assertion without a clear failure message.

## t50-growth-stage-hardening — 2026-06-11T11:33Z
Report: tasks/T50_dev-report.md (in dev/t50-growth-stage-hardening)

### Should-fix
- [ai-ml-engineer] src/gander/growth.py:403-406 vs prompts/growth.md — top-up retry asks for "exactly N NEW action(s)" while the system prompt hard-codes "3 to 5 entries total" twice; contradiction Gemini resolves unpredictably. Also request headroom (needed..5) instead of the bare minimum, and add a top-up acknowledgment line to the prompt output-format section.
- [ai-ml-engineer] scripts/eval_corpus.py:226-231 — CI exit gate counts only status=="failed"; a regression dropping every fixture to a 1-action degraded plan exits 0. Bound the degraded rate at a separate, looser threshold.
- [ai-ml-engineer + ux-engineer + product-owner] src/gander/report.py:419-436 + growth.py growth_degraded — a degraded 1-2-action plan renders identically to a full plan; three reviewers converged. Add one muted, honest line when len(growth) < 3 (e.g. "Only actions that passed source verification are shown."); requires the renderer to see the degraded state. Tooltip-only is insufficient (hover-only, invisible to keyboard/SR users).
- [hiring-manager + product-owner] src/gander/growth.py / scripts/eval_corpus.py — commit 5 deleted the closed-employer signal along with the gate: a model mislabeling a backward-looking action as future_role passes with zero telemetry, and "monitored via live fixtures" has no signal to monitor. Add an observe-only event (closed-hint token in what of a non-current_employer action) plus declared-setting distribution counts in the emit and a SUMMARY column.
- [hiring-manager] src/gander/growth.py:506-548 — zero-survivor stage_failure reports only the final attempt's returned/drop_reasons; if attempt 2 returns an empty list the event hides why attempt 1 dropped everything. Aggregate across attempts.
- [heal trade-off] src/gander/growth.py _setting_violation — the >=3-alphanumeric gate on declared targets drops legitimate 2-char companies (O2); relies on the retry's future_role escape hatch. Consider an allowance for short all-caps/dotted tokens that appear verbatim in a hint.

### Nits
- [ai-ml-engineer] prompts/growth.md rule 4 claims >=8 words enforced by drop, but verify_quote still passes a unique 6-7-word quote; prompt overclaims in the safe direction.
- [ai-ml-engineer] src/gander/growth.py:298-302 — _action_key includes anchor.quote, so the same what with a different quote survives dedup as a duplicate; keying on normalized what alone would be tighter.
- [ai-ml-engineer] src/gander/timeline.py:87 — date.today().year makes is_current wall-clock-dependent; clock-injection seam if fixtures pin ranges near the current year.
- [ai-ml-engineer] src/gander/growth.py:451 — max_tokens=1536 unchanged while per-action payload grew (two new fields, 8-word anchors); each truncation heal re-bills the CV-bearing prompt; ~2048 is cheap insurance.
- [ux-engineer] PRD §4.8 — growth is now the likeliest longest-running pill (up to 2 LLM calls with longer retry prompts); a sub-status ("verifying actions, attempt 2") would be cheap insurance.
- [hiring-manager] src/gander/growth.py:387-392 — _Drop.quote flows uncapped into the retry message while the emit caps at 120 chars; unmotivated asymmetry.
- [hiring-manager] src/gander/timeline.py:84-87 — the year>=today signal flips any sub-80-char closed range whose RHS mentions a future year ("2018 - 2021 (extension option 2026)") to current; task doc understates the class.
- [hiring-manager] scripts/eval_corpus.py:53 — _GROWTH_EVENT_NAMES omits growth_attempt_error, so SUMMARY cannot distinguish drop-caused degrades from provider-outage degrades.
- [hiring-manager] src/gander/growth.py:222-229 — "missing_target" sentinel and arbitrary employer-prefix data share one return channel; a model literally emitting "missing_target" confuses the retry copy.
- [hiring-manager] src/gander/growth.py:125-130 — phd special case inline in the loop; phrase->matcher table if the contractual list ever grows.
- [hiring-manager] a future_role action with non-null target_employer passes silently, contradicting prompt rule 7; normalize-to-None hygiene.
- [hiring-manager] tests/test_schemas.py — no test pins that omitting setting raises ValidationError, the trigger for the complete_json self-heal path the design leans on.
- [qa-engineer] scripts/eval_corpus.py:404-412 — _growth_failure_rate_exceeded tested incl. boundary, but no test proves _run_corpus returns 1 when it trips (consistent with file convention).
- [qa-engineer] GrowthStats.retries computed and asserted but never surfaced — no SUMMARY column or aggregate; render it or delete it.
- [qa-engineer] softener scope (what-only; mechanism exempt) is a locked decision with no pinning test; widening to mechanism would be a false-drop regression with green CI.
- [qa-engineer] tests/test_timeline.py:69 — open-ended parametrize covers "2022 -", "2022 –", "ledna 2022 -" but not the no-space em-dash "2022—" variant the dev-plan names.

## t50-growth-stage-hardening PR-review round — 2026-06-11

Deferred from the PR #39 review-fix round:

- src/gander/growth.py:675 — the outer `except Exception` turns any non-LLM
  exception into a StageFailure even when the cross-attempt pool already holds
  1-2 verified survivors; a late rendering/emit bug discards a shippable
  degraded result.
- src/gander/growth.py `_setting_violation` — a location-suffix target variant
  ("Acme Retail, Prague" vs hint "Acme Retail s.r.o.") still drops: neither
  token sequence contains the other. Needs a suffix-stripping normalization or
  prompt guidance before it shows up in live fixtures.
- scripts/eval_corpus.py — `growth_degraded` events are captured into
  `growth_events` but the summarizer never reads them; degraded status is
  inferred from list length instead. Use the payload or stop capturing it.
- src/gander/growth.py — degraded and stage_failure emits still report only
  the last attempt's `returned`/`drop_reasons`; attempt-1 drop history is
  invisible when attempt 2 returns an empty list. Aggregate across attempts.
- src/gander/timeline.py — accepted endpoint pathologies: dash-joined
  annotations ("2018 - 2021 - extension 2026") and unparenthesised
  comma-year annotations ("2019 - 2026, maternity leave, 2021 - 2022")
  are string-indistinguishable from multi-dash ranges / rehire stints and
  resolve in the range's favor. Revisit only if live fixtures surface them.

## prod-readiness-p0 — 2026-06-12T07:35Z
Report: tasks/T51_dev-report.md (in dev/prod-readiness-p0)

### Should-fix
- [ai-ml-engineer] src/gander/prompts/growth.md:37 — HARD RULE 2 mechanism examples are still CZ-anchored ("30-50k CZK/mo"); the DE example lacks units/market name. Add a non-CZ concrete example (e.g. USD annual band delta) so non-CZK markets get pattern diversity.
- [ai-ml-engineer] src/gander/ingest.py — document that `_DEFAULT_MAX_INPUT_CHARS` is a post-annotation limit; `_annotate_sections` inflates size, so the effective raw-text budget is smaller than 50,000.
- [ai-ml-engineer] src/gander/schemas.py / salary.py — document that `market_provenance` is profile-derived (pre-generation), not LLM output, so reviewers don't mistake it for a generation-context leak into the confidence judge (§4.3).
- [ai-ml-engineer] tests/test_confidence_unit.py — add an assertion that the Step A user payload does not contain `market_provenance`/`provenance`, locking the §4.3 independence boundary programmatically.
- [ux-engineer] app.py:225 — queue overflow surfaces Gradio's raw "Queue is full. Max size is 4…" string; rewrite to calm product copy (§4.8: don't let unavailability read as breakage).
- [ux-engineer] src/gander/ingest.py:261 — magic-byte mismatch uses CORRUPT_MSG; for a renamed/wrong-format file the §4.6 UNKNOWN_MSG ("Unable to read this file. Please upload a valid PDF or DOCX.") is the more accurate copy.
- [ux-engineer] src/gander/ingest.py:314 — truncation is invisible to the user; add a report-visible notice when input was truncated ("analysis covers the first ~50,000 characters").
- [product-owner] tests/test_growth_unit.py — mock fixture mechanism strings throughout are still CZ-specific ("+30k CZK/mo", "in CZ market"); misleading post-de-CZ. Refresh fixture debt.
- [hiring-manager] src/gander/market.py:3 — docstring claims `resolve_market` "runs once post-normalize" but it is called 4× (build_queries, estimate_salary, 2× pipeline.py). Either hoist to a single resolution passed down or fix the docstring. (product-owner flagged the pipeline double-call too.)
- [hiring-manager] src/gander/salary.py — `_DDG_CACHE` read-check-write from `asyncio.to_thread` workers is not atomic; a `threading.Lock` around lookup/insert/evict removes the duplicate-fetch and eviction races.
- [hiring-manager] src/gander/normalize.py:232 — `years` param is `noqa: ARG001`-reserved for unimplemented band-floor logic; remove until the logic exists.
- [hiring-manager] src/gander/confidence.py:256-257 — `low_regex` is assigned once pre-regen but used in two places with different semantic requirements (salary-tier-Low vs CV-floor-Low); restructure for legibility.
- [hiring-manager] src/gander/market.py:22-26 — `_CZ_TOKEN_PATTERN` city tokens (`brno`, `prague`) can false-positive on non-location strings in the inferred-fallback path; consider tightening.
- [qa-engineer] tests/test_salary.py — the `ddg_cache_hit` obs emit (salary.py:237) is untested; if deleted, no fast test fails. Assert it on the cache-hit path.
- [qa-engineer] tests/test_privacy_obs.py — the PII-in-obs test only covers redact-stage events whose fields are structurally numeric; expand to an LLM-calling stage (mocked client) or document the scope limitation.
- [qa-engineer] tests/test_adversarial.py — autouse `_deterministic_ingest` fixture is a blanket module-wide env override; convert to per-test setup so test intent stays readable.

### Must-fix (remaining)
- none — all 5 consolidated must-fixes healed in ac4e43e.

### Nits
- [ai-ml-engineer→adjudicated, qa-engineer] src/gander/ingest.py:315 — `input_truncated` event lacks `duration_ms`; consistent with other mid-stage counters (`ingest_llm_fallback`, `docx_llm_start`). No action planned.
- [ai-ml-engineer] src/gander/prompts/salary.md:1 — "The pipeline's primary market is the Czech Republic" is stale CZ-bias post-MarketSpec.
- [ai-ml-engineer] src/gander/llm.py:682 — `get_client` lru_cache + env-at-construction coupling deserves a warning comment (stale client if key injected after first call).
- [ux-engineer] app.py:148 — disclosure caption sentence grouping: consider parallel structure "PDF pages are sent to OpenRouter/Gemini; DOCX is read locally; salary data is fetched via DuckDuckGo search."
- [product-owner] tests/test_adversarial.py:155 — test comment undersells the intent (magic passes, then parse error follows).
- [product-owner] src/gander/redact.py:9-18 — module docstring documents US paren phones as matching while line 18 notes CZ paren grouping does not; clarify side by side.
- [product-owner] tasks/todo.md — MiniMax references (T32–T35 listed open) not updated alongside R1 spike deletion.
- [hiring-manager] src/gander/market.py:3 — "Hoisted out of `salary.py` (P0.1)" task reference in docstring; keep the durable why, drop the task pointer.
- [hiring-manager] src/gander/pipeline.py:339 — enumerate-based yield gate ("yield after every task except the last") is less obvious than a counter drain.
- [hiring-manager] src/gander/growth.py:51-53 — `_BAN_PHRASES` docstring misses the punctuation-stripping behavior `_check_ban_phrase` actually applies.
- [hiring-manager] tests/test_pipeline_fast.py:159-166 — cascade-contract test asserts only a dict constant; documents intent but cannot catch a broken cascade.
- [qa-engineer] tests/test_redact.py:576 — version-string false-positive test should also assert `[ADDRESS]` absent to pin `_STREET_ADDR_LINE` against over-reach.
