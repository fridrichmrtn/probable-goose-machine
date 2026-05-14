# T15 dev-report — L6 pipeline orchestrator

Branch: `feat/block-c-corpus-render`
Status: done
Plan: `tasks/T15_dev-plan.md` (a copy of the approved plan from plan mode lives at `/home/mf/.claude/plans/silly-zooming-conway.md`)

## Scope shipped

- **New `src/jobfit/pipeline.py`** (~225 lines incl. docstring): `async def run(file_bytes, filename) -> AsyncIterator[Report]`.
  - Initial yield: every block `None`, every status `pending`, `raw_cv_text=""`, totals 0.
  - L1 ingest (`extract_text`, sync) → L2 redact (`redact`, sync) → L3 extract (`extract_profile`, async). Each step rewrites `state.profile = StageFailure(stage="profile", …)` on failure, fans the failure across downstream blocks via `_cascade_all_downstream`, emits `pipeline_done`, yields, returns.
  - L4a + L4b concurrent: `asyncio.create_task` + `asyncio.as_completed`. Routes by `isinstance(result, Score | SalaryEstimate | StageFailure)`; for `StageFailure` it disambiguates via `result.stage`. Yields after each task completes so the UI sees the faster of score/salary first.
  - L4c confidence (conditional): if salary succeeded, await `judge(…)`. If salary failed, short-circuit to `Confidence(tier="Low", rationale="Insufficient market data — see salary block.")` — no LLM call.
  - L5 growth (conditional, Decision A): only runs `plan_growth(redacted, profile, score, mid, ccy)` when **both** score and salary succeeded. Cascades with a specific message otherwise (`_GROWTH_NO_BASELINE`, `_GROWTH_NEEDS_SCORE`, `_GROWTH_NEEDS_SALARY`).
  - Cost/latency accumulator: `with obs.subscribe(_make_accumulator(state))` wraps the whole run. The subscriber filters `event == "llm_call"` and sums `usd_cost` + `duration_ms` into the run state. Snapshots read those fields on every yield.
  - Pipeline-level lifecycle events: `pipeline_start` (with `filename`+`bytes`), `pipeline_done` (with `outcome` ∈ `ingest_failed | redact_failed | profile_failed | ok`), and a `pipeline_warn` for unrouted StageFailures (defence-in-depth — shouldn't fire).
  - `_Run` dataclass holds mutable state; `_Run.snapshot()` rebuilds an immutable `Report` per yield so the caller can hold references across iterations.

- **New `tests/test_pipeline_fast.py`** (13 `@pytest.mark.fast` tests, ~310 lines):
  | # | Test                                                                | What it locks                                                                                                          |
  | - | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
  | 1 | `test_initial_yield_is_all_pending`                                 | First yield's invariants: `None` blocks, `pending` statuses, empty raw text, zero totals.                              |
  | 2 | `test_happy_path_final_report_fully_populated`                      | Every block reaches its non-failure type; every status `done`; `raw_cv_text` propagates from L1.                       |
  | 3 | `test_happy_path_yields_in_expected_sequence`                       | Profile/score/salary statuses each pass through `pending → running → done` in the yield stream.                        |
  | 4 | `test_ingest_failure_short_circuits_and_cascades`                   | `extract_text → StageFailure` ⇒ `profile = StageFailure`, every downstream block is StageFailure, all `failed`.        |
  | 5 | `test_redact_failure_short_circuits_and_cascades`                   | Same shape via `redact()`.                                                                                             |
  | 6 | `test_profile_failure_cascades_with_specific_messages`              | `extract_profile → StageFailure` ⇒ downstream cascades carry the per-stage message ("without profile extraction").     |
  | 7 | `test_salary_failure_short_circuits_confidence_without_llm`         | Salary fail ⇒ no `judge()` call; `confidence.tier == "Low"`; growth cascades (Decision A).                             |
  | 8 | `test_score_failure_cascades_growth_without_calling_it`             | Score fail ⇒ no `plan_growth()` call; growth message contains "without scoring".                                       |
  | 9 | `test_score_and_salary_both_fail_growth_uses_combined_message`      | Both fail ⇒ growth uses the "scoring or salary" wording; confidence short-circuits to Low.                             |
  | 10 | `test_cost_and_latency_accumulate_from_obs_emit`                   | Three fake `llm_call` events from stages sum to the final report's `total_cost_usd`/`total_latency_ms`.                |
  | 11 | `test_score_and_salary_run_concurrently`                           | Salary (1ms sleep) finishes before score (50ms sleep); yield where salary=done shows score=running.                    |
  | 12 | `test_every_yield_is_a_valid_report_with_all_status_keys`          | Every yielded `Report` is schema-valid and carries the canonical 5 status keys.                                        |
  | 13 | `test_final_report_has_no_running_statuses`                        | Terminal contract for the UI: when the iterator is exhausted, no stage is still "running".                             |

  All stages are mocked via `monkeypatch.setattr(pipeline, "<stage_fn>", ...)` against the pipeline module's import namespace, so no network/LLM cost.

- **New `tests/test_pipeline_smoke.py`** (1 `@pytest.mark.live @pytest.mark.slow` test): runs the real pipeline against `tests/fixtures/cvs/05_mlops_benes.pdf`. Strong assertions (all `done`, no `StageFailure`, positive cost+latency) gate only on the all-green path; otherwise the test asserts the orchestrator still produced a well-formed final yield with no stuck `running` statuses. The looser fallback is deliberate — T17 owns model calibration, T18 owns partial-failure verification, and the smoke test should not become a flaky model-quality gate.

## Cross-task ripple (per plan)

Three modules outside the nominal T15 scope were patched. All confirmed in plan-mode AskUserQuestion + ExitPlanMode approval.

1. **`src/jobfit/schemas.py`** — `Report` blocks become `T | StageFailure | None = None` (initial-yield streaming semantics) and gain `total_cost_usd: float = 0.0` + `total_latency_ms: int = 0` aggregate fields. `_require_exact_status_keys` validator unchanged. Existing constructors that pass all 5 blocks explicitly still type-check.
2. **`src/jobfit/report.py`** — each `_score_section / _salary_section / _confidence_section / _growth_section` opens with `if block is None: return ""`. `render_body` adds `if report.profile is None: return ""` for the pre-profile streaming state. `_footer(report)` interpolates the new totals as `_Total cost: $X.XXXX · Total latency: N,NNN ms_` in place of the static T15 placeholder. Sections are joined with a filter (`s for s in sections if s`) so empty sections disappear cleanly.
3. **`tests/test_render.py`** — three additional tests: footer interpolation, profile=None ⇒ empty body, mid-stream snapshot with some blocks `None` and others completed renders the completed sections only.
4. **`tests/test_schemas.py`** — two additional tests: `test_report_accepts_none_blocks_for_pipeline_streaming` and `test_report_carries_cost_and_latency_totals`.

## Decisions worth recording

- **Decision A (open contract in plan).** `plan_growth` requires a real `Score`. The "salary-ok but score-failed" path is degenerate (score is cheaper and more reliable than salary), so growth cascades when either upstream fails rather than expanding T13's signature to accept `Score | None`. Symmetric for the salary-failed branch — a separate constant (`_GROWTH_NEEDS_SALARY`) keeps the user message specific without forcing T13 to handle a `mid=0` placeholder.
- **No `stage_boundary` wrap inside `run()`**. Each L1–L5 stage already returns `StageFailure` rather than raising, and the obs subscriber is exception-safe via the `@contextmanager` decorator. Wrapping again would only swallow programmer bugs we want to surface.
- **`asyncio.as_completed` over `asyncio.gather`**. The UI re-renders on every yield, so emitting the faster of score/salary first is the whole point of the fan-out. `gather` would force us to wait for both.
- **Initial yield before L1 starts running.** The renderer treats `profile=None` as "tracker only, no body". This gives the UI a first frame to mount the tracker before any LLM call latency.

## Verification evidence

```
uv run pytest -m fast tests/test_pipeline_fast.py -v     # 13 passed
uv run pytest -m fast -q                                  # 187 passed, 42 deselected
uv run mypy src/                                          # Success: no issues found in 15 source files
uv run ruff check .                                       # All checks passed!
uv run ruff format --check .                              # 34 files already formatted
uv run pre-commit run --all-files                         # all hooks Passed
uv run pytest -m live -k pipeline_smoke -v                # 1 passed (degraded mode — no MINIMAX_API_KEY)
```

## Known limitations / unverified

- **No real-LLM end-to-end timing recorded.** Live smoke ran in degraded mode because the worktree env has no `MINIMAX_API_KEY`. The fast suite already exercises every orchestration branch deterministically, and T17/T18 will run the all-green path against the calibration fixture set. If a wall-clock number is needed sooner, set the env var and re-run `pytest -m live -k pipeline_smoke`.
- **`asyncio.as_completed` ordering** is timing-dependent. Test #11 uses 1ms-vs-50ms sleeps to give a 50× margin, but on a heavily-loaded CI runner this could conceivably flake. If we see flakes, widen to 5ms-vs-200ms or rewrite the assertion as "score finishes after salary" without per-yield introspection.
- **Cost accumulator schema assumption.** `_make_accumulator` reads `usd_cost` and `duration_ms` from obs records. If `jobfit.llm` ever renames either field, totals will silently stay 0. Defensive `.get()` + `isinstance` already absorbs the rename; T18 should add a contract test that pins the obs `llm_call` event shape.
- **No T16 integration yet.** The async iterator is designed for Gradio's `gr.Markdown.update` pattern, but the actual wiring lands in T16. If T16 needs a different yield cadence (e.g. throttling), revisit `run()`.

## Files changed

- New: `src/jobfit/pipeline.py`, `tests/test_pipeline_fast.py`, `tests/test_pipeline_smoke.py`, `tasks/T15_dev-report.md`
- Modified: `src/jobfit/schemas.py`, `src/jobfit/report.py`, `tests/test_render.py`, `tests/test_schemas.py`, `tasks/T14_render.md` (footer placeholder closed), `tasks/T15_pipeline.md` (status → done + outcome)
