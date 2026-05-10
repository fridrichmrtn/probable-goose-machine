
## t01-schemas — 2026-05-10T13:50Z
Report: tasks/dev-report.md (in dev/t01-schemas)

### Should-fix
- [ux-engineer] src/jobfit/schemas.py:16 — Add `"skipped"` to `StageStatus`. PLAN §L6 short-circuits L4c when L4b fails and L5 when L4a+L4b both fail; neither is `done`/`failed`/`running`/`pending`. UI tracker pill needs honest rendering.
- [ux-engineer / hiring-manager / codex] src/jobfit/schemas.py:103 — `Report.statuses: dict[str, StageStatus]` — three reviewers flagged the unconstrained key type. Tighten to a Literal-keyed dict, TypedDict, or per-stage Pydantic submodel so typos can't silently render an empty pill.
- [ux-engineer] tests/test_schemas.py:78-84 — `_statuses()` uses block-name keys (profile/score/salary/confidence/growth) but PLAN §L7 pills are stage-name (parse/redact/score/salary/plan). Decide which vocabulary the contract uses and lock it in the type before T15/T16 drift.
- [ai-ml-engineer] src/jobfit/schemas.py — `Score.total` rounding uses banker's rounding (`round`); calibration test (PLAN §L4a, variance ≤5) and §5 acceptance (≥30 spread) will be noisier than necessary. Switch to `int(x + 0.5)` for predictable half-up + docstring.
- [ai-ml-engineer] src/jobfit/schemas.py — `Report` lacks `total_cost_usd: float = 0.0` and `total_duration_ms: int = 0` aggregate fields. PLAN §M3 (`test_per_run_cost_budget`) + README per-run cost figure will need them; better to land in T01 contract than retrofit after T15 ships.
- [ai-ml-engineer] src/jobfit/schemas.py — `Component.justification: str` is unanchored free text; the `anchor` covers a single quote but justification can smuggle unverified specifics. Either anchor justification or document it as model commentary not a verifiable claim.
- [ai-ml-engineer] src/jobfit/schemas.py — `GrowthAction.mechanism: str` is unanchored. PLAN §M4 Jaccard test only covers `what`; mechanism could become copy-paste boilerplate ("builds in-demand skills") and pass.
- [product-owner] src/jobfit/schemas.py — `Source.url: str` should be `pydantic.HttpUrl`. PRD §5.6 ("working source URLs") is the cheapest type-level guarantee available; T11/T17 will otherwise hand-roll validators.
- [product-owner] src/jobfit/schemas.py — Add `Confidence.judged_by: Literal["independent"]` (or similar tracking field) so PRD §4.3 separation is encoded in the type, not just convention.
- [product-owner] src/jobfit/schemas.py — Add a `+30%` calibration field (per-action `expected_salary_delta_pct: int | None` or top-level `growth.target_uplift_pct: int = 30`) so T13/T17 can verify PRD §3 / §4.4 instead of trusting prose.
- [hiring-manager] src/jobfit/errors.py:43-52 — Async path (`__aenter__/__aexit__`) is currently dead weight: no T01 call site, no test. Either delete until T15's `asyncio.gather` actually awaits inside the boundary, or add an async test now.
- [hiring-manager] src/jobfit/errors.py:69 — `# T02:` TODO marker means swallowed exceptions go silent until T02 lands. Add a one-line `logging.getLogger(__name__).warning(...)` so failures surface somewhere immediately (CLAUDE.md §"Failures surface as useful messages").
- [hiring-manager / codex] src/jobfit/errors.py:15 — `class stage_boundary` is snake_case (PEP 8 violation) AND lacks the decorator form the spec mentioned. Either rename to `StageBoundary` (accept capitalized call site) or implement `__call__` to support `@stage_boundary("score")` decorator usage. Current state is the worst of both.
- [hiring-manager] src/jobfit/schemas.py — `SalaryEstimate` lacks a `@model_validator(mode="after")` asserting `low <= high`. Three-line addition that prevents a class of stage bugs the UI cannot recover from.
- [hiring-manager] tests/test_schemas.py — No test that `KeyboardInterrupt`/`SystemExit` propagate through `stage_boundary`. The docstring promises this; pin it with a `pytest.raises(KeyboardInterrupt)` test or someone will "simplify" `_handle` later.
- [ux-engineer] src/jobfit/errors.py:11 — `StageFailure.user_message` needs a one-line docstring noting it's reviewer-facing copy (PRD §4.6 strings), not engineer placeholder text — prevents T15/T16 authors from putting `repr(exc)` in there.
- [ux-engineer] src/jobfit/errors.py:65 — `user_message=str(exc) or type(exc).__name__` will leak raw Python exception strings to the UI surface. Add a comment requiring callers to overwrite with PRD §4.6 copy before the StageFailure renders.

### Must-fix (remaining — exhaustion)
- [ai-ml-engineer] src/jobfit/schemas.py:39-41 — `Anchor.section: str | None` constraint to `Literal[...]` rejected. Why: reviewer conflated CV-section vocabulary (open-ended: "Work Experience", "Projects", "Publications", "Open Source") with `Component.name` vocabulary (closed 4-element set). Forcing a Literal would be wrong. Addressed via clarifying docstring on `Anchor` in the heal commit.
- [ai-ml-engineer] src/jobfit/schemas.py:65-71 — `SalaryEstimate.reasoning` split or `for_judge()` projection rejected. Why: PLAN §L4c judge signature is `judge(sources, low, high, currency, period) -> Confidence` — individual fields, not the SalaryEstimate object. Reasoning never reaches the judge by construction; isolation is enforced at the T12 call site, not the schema. Addressed via clarifying docstring on `SalaryEstimate` in the heal commit.

### Nits
- [ai-ml-engineer] src/jobfit/schemas.py:60-62 — `ProfileItem.text` is paraphrasable (only `anchor.quote` is verified). Consider invariant: `text` ⊆ `anchor.quote`.
- [ai-ml-engineer] src/jobfit/schemas.py:81-83 — `Confidence` has no link back to the `SalaryEstimate` it judged; `judged_low/judged_high` would help the recompute-then-compare golden test.
- [ai-ml-engineer] src/jobfit/schemas.py — `Profile.detected_years_experience: int` lacks bounds; use `Field(ge=0, le=70)`.
- [ai-ml-engineer] src/jobfit/errors.py:48-71 — Add a comment that `asyncio.CancelledError` (BaseException, not Exception) deliberately propagates, so future "fixes" don't swallow cancellation.
- [ai-ml-engineer] tests/test_schemas.py — No test exercises the `Anchor.section` round-trip; the §4.5 hardening hangs on this.
- [product-owner] src/jobfit/schemas.py — `RawCV.content_bytes: bytes` is unbounded; add a `# size guard lives in T07 ingest` comment.
- [product-owner] src/jobfit/schemas.py — `Report.raw_cv_text: str` is non-optional; ingestion failure case can't construct a Report. Default to `""` or `str | None`.
- [product-owner] tasks/T01_schemas.md — Per-deliverable checkboxes (lines 15, 29, 32) still `[ ]` despite Status: done; flip them or the next reviewer will think the task half-shipped.
- [hiring-manager] src/jobfit/schemas.py:111 — `Report.model_rebuild()` may be a no-op since `StageFailure` is eagerly imported (not behind `TYPE_CHECKING`). Drop or comment-justify.
- [hiring-manager] src/jobfit/schemas.py — Reorder so `Anchor`/`ProfileItem`/`Component` cluster together (the "claim-with-evidence" group).
- [hiring-manager] tests/test_schemas.py:19-25 — `# type: ignore[arg-type]` could be avoided by exporting a `ComponentName = Literal[...]` alias from `schemas.py` and using it in test helpers.

## t02-utils — 2026-05-10T14:30Z
Report: tasks/T02_dev-report.md (in dev/t02-utils)

### Should-fix
- [codex] src/jobfit/llm.py:119 — Retry attempts overwrite `prompt_tokens` / `completion_tokens`; `finally`-emitted telemetry reports only the last attempt, undercounting usage and cost. Accumulate across attempts before emitting.
- [ai-ml-engineer] src/jobfit/llm.py — Anthropic prompt caching not enabled. PLAN §"Cold-start mitigation" notes Anthropic fallback only — but if we ever ship it as primary, missing `cache_control` markers on the system prompt is a 90%+ cost regression. Add a `# T05/T22:` TODO at the Anthropic branch.
- [ai-ml-engineer] src/jobfit/llm.py:31 — `_ANTHROPIC_MODEL = "claude-sonnet-4-6"` is unverified against Anthropic's published model IDs. Confirm before T05 fallback path is exercised; if ID is wrong, fallback fails on first call.
- [ai-ml-engineer] src/jobfit/verify.py — Quote/source not Unicode-NFC-normalized; CV text from PDFs frequently mixes pre-composed and decomposed accents (CZ corpus → á vs á). Add `unicodedata.normalize("NFC", ...)` in `_normalize`.
- [ai-ml-engineer] src/jobfit/verify.py — Substring match has no word-boundary guard: a 6-word quote like "data engineer with five years of" would match inside "metadata engineer..." . Acceptable for L0 but flag for T07/T09.
- [ai-ml-engineer] src/jobfit/verify.py — `drop_unverified` uses `getattr(item, anchor_attr)` with no fallback; raises `AttributeError` on items missing the anchor field. Either gate with `hasattr` + skip, or document the contract that callers must pre-filter.
- [ux-engineer] src/jobfit/obs.py — `subscribe()` is sync-context only; Gradio's UI loop wants an async-iterable / queue for progress events. Wrap with an `async_subscribe()` that pushes onto an `asyncio.Queue` before T16 wires the UI.
- [ux-engineer] src/jobfit/errors.py — `StageFailure.user_message = str(exc) or type(exc).__name__` will leak raw Python exception strings to the UI. Add a comment requiring T15/T16 callers to overwrite with PRD §4.6 copy.
- [hiring-manager] src/jobfit/llm.py — `_chat_json` / `_chat_text` use `Any`-typed clients to dodge the OpenAI/Anthropic type divergence. Acceptable but flag a `# typing: provider dispatch` TODO so future readers know it's deliberate.
- [hiring-manager] tests/test_llm.py — Single live test only; no coverage for the JSON-retry path (would need a stub provider). Add a `MockAsyncOpenAI` fixture under T05 to exercise retry-on-ValidationError without burning tokens.
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
