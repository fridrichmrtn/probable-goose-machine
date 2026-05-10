# T15 — L6 pipeline orchestrator

Status: todo
Owner: software-engineer
Depends on: T07, T08, T09, T10, T11, T12, T13, T14
Unblocks: T16, T17, T18, T20, T21
Estimate: ~45 min

## Goal

The async iterator that runs the whole pipeline, yielding a fresh `Report` after every meaningful state change so the UI can re-render. Implements the conditional flow that prevents L4c from crashing when L4b failed (and L5 from running with no inputs).

## Deliverables

- [ ] `src/jobfit/pipeline.py`:
  - **Public entrypoint**:
    ```python
    async def run(file_bytes: bytes, filename: str) -> AsyncIterator[Report]:
        ...
    ```
  - Initial yield: `Report` with all blocks `None` and statuses set to `pending`. `raw_cv_text=""`.
  - Step 1 — **L1 ingest** (sequential):
    - Set `statuses["ingest"] = "running"`, yield.
    - Call `extract_text(...)`. On failure: store `StageFailure` in a top-level field; `statuses["ingest"] = "failed"`; yield; return.
    - On success: `statuses["ingest"] = "done"`; store `raw_cv_text`; yield.
  - Step 2 — **L2 redact** (sequential): same pattern. On failure → top-level fail.
  - Step 3 — **L3 extract** (sequential, but allowed to soft-fail):
    - On failure → store `StageFailure` in `report.profile`; **do not** abort the pipeline. Salary still works on detected_role from… actually, no — salary needs profile.detected_role. If extract fails, salary cannot run; degrade gracefully:
      ```python
      report.salary = StageFailure("Cannot estimate salary without profile extraction.", stage="salary")
      report.score = StageFailure("Cannot score without profile extraction.", stage="score")
      ```
      and yield, then jump to confidence/growth conditional logic below.
  - Step 4 — **L4a + L4b concurrent**:
    ```python
    score_task = asyncio.create_task(score_profile(redacted, profile))
    salary_task = asyncio.create_task(estimate_salary(profile))
    for coro in asyncio.as_completed([score_task, salary_task]):
        result = await coro
        # store on report.score or report.salary based on type, update status, yield
    ```
  - Step 5 — **L4c confidence (conditional)**:
    - If `report.salary` is a `SalaryEstimate` → `await judge(salary.sources, salary.low, salary.high, salary.currency, salary.period)`.
    - If `report.salary` is a `StageFailure` → set `report.confidence = Confidence(tier="Low", rationale="Insufficient market data — see salary block.")` directly. Skip the LLM call. **This closes the v1 bug where L4c's signature wanted `Source` objects.**
    - Yield.
  - Step 6 — **L5 growth (conditional)**:
    - If both `report.score` AND `report.salary` are failures → `report.growth = StageFailure("Cannot generate growth plan without scoring or salary baseline.", stage="growth")`.
    - Else → `await plan_growth(profile, score, salary_midpoint, currency)`. (If only one is a failure, use whichever is available — pass `None` for the missing one and have `plan_growth` handle it.)
    - Yield.
  - Final yield: full `Report` with footer-relevant aggregate fields (`total_cost_usd`, `total_latency_ms`) populated from accumulated `obs.emit` events.
- [ ] `tests/test_pipeline_smoke.py`:
  - `@pytest.mark.live, slow`: end-to-end run on the mid fixture; assert final Report has all 5 status keys = "done"; assert no `StageFailure` in any block.

(Partial-failure tests live in T18.)

## Verification

```bash
uv run pytest -m live -k pipeline_smoke -v
```

## Reference

- tasks/PLAN.md — § "L6 — Report Assembly + Orchestration"

## Outcome

(fill in when done — observed end-to-end latency on the mid fixture)
