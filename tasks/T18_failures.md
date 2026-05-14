# T18 — L8 failure-path + partial-failure-streaming tests

Status: done
Owner: software-engineer
Depends on: T15
Unblocks: —
Estimate: ~45 min

## Goal

Prove PRD §4.6 graceful degradation: every failure path produces a clean user-facing message; nothing escapes as a traceback; partial failures don't leave the UI in a broken state.

## Deliverables

- [ ] `tests/test_failures.py` (`@pytest.mark.fast` where mockable; `@pytest.mark.live, slow` otherwise):
  - `test_corrupt_pdf` — pass random bytes with `.pdf` suffix → final Report has `statuses["ingest"] == "failed"` and the user-facing corrupt-file message; no other blocks attempted.
  - `test_image_only_pdf` — pass the `tests/fixtures/scanned.pdf` (from T07) → final Report has the scanned-PDF message.
  - `test_unknown_extension` — pass bytes with `.txt` suffix → "Unable to read this file" message.
  - `test_ddg_returns_empty` — mock `ddgs.DDGS().text` to return `[]` → `report.salary` is a `StageFailure` with "Insufficient market data"; `report.confidence.tier == "Low"` (short-circuited, no LLM call); `report.score` and `report.growth` still populated.
  - `test_ddg_raises` — mock `ddgs.DDGS().text` to raise `ConnectionError` → same as above (fail-fast retry caught at stage_boundary).
  - `test_extract_returns_garbage` — mock `llm.complete_json` for the extract stage to raise `pydantic.ValidationError` after the one retry → `report.profile` is a `StageFailure`; downstream `score`, `salary`, `growth` are also failures with "Cannot ... without profile" messages.
- [ ] `tests/test_partial_failure_streaming.py`:
  - `test_streaming_no_running_at_end` — collect every `Report` yielded by `pipeline.run` for a corrupt-PDF input; assert every yielded report is renderable (no exception from `render_body`); assert the *final* yielded report has zero blocks in `running` (every status is `pending`, `done`, or `failed`).
  - `test_streaming_no_traceback` — same harness, capture stderr; assert no Python tracebacks were written to stderr (errors should go to `obs.emit` JSON logs, not raw tracebacks).

## Verification

```bash
uv run pytest -m fast tests/test_failures.py -v
uv run pytest -m fast tests/test_partial_failure_streaming.py -v
uv run pytest -m live tests/test_failures.py -v   # the few that need real LLM
```

## Reference

- tasks/PLAN.md — § "L8 — Testing"
- PRD.md §4.6

## Outcome

Delivered on the `stream-C` worktree (2026-05-14). 10 fast tests across two files; `pytest -m fast -q` green at 206 passed / 47 deselected.

### `tests/test_failures.py` (7 tests, all `@pytest.mark.fast`)

- `test_corrupt_pdf_full_pipeline_emits_corrupt_message` — random bytes through real `extract_text` → final report carries `CORRUPT_MSG` on `profile`, every downstream `statuses[...] = "failed"`, every downstream block is a `StageFailure`.
- `test_image_only_pdf_full_pipeline_emits_scanned_message` — reportlab-synthesized image-only PDF (same synthesis as `tests/test_ingest.py::test_scanned_pdf_returns_scanned_failure`), real ingest path → `SCANNED_MSG`.
- `test_unknown_extension_full_pipeline_emits_unknown_message` — `.txt` suffix → `UNKNOWN_MSG` before any LLM call.
- `test_ddg_returns_empty_short_circuits_salary` — mock `gander.salary.DDGS`, leave the real `estimate_salary` running. Asserts (a) salary returns `StageFailure("Insufficient market data …")`, (b) confidence is a Low **Confidence object** (not StageFailure) with rationale referencing salary, (c) growth cascades (Decision A), (d) judge() is never called.
- `test_ddg_raises_connection_error_short_circuits_salary` — same harness, DDG raises `ConnectionError`. Asserts the transport detail stays in `debug_detail`, not in `user_message`.
- `test_extract_validation_error_cascades_to_every_downstream_stage` — patches `LLMClient.complete_json` to raise (simulating retry-exhausted parse failure); real `extract_profile` catches via `stage_boundary` and surfaces a `StageFailure(stage="extract", …)`. Pipeline cascades the "Cannot … without profile extraction" message to all four downstream stages.
- `test_no_failure_path_leaves_running_status` — meta sanity: spot-checks the corrupt-PDF and DDG-empty paths to ensure final yield has no stage in `"running"`. Companion to the streaming file's per-yield contract.

### `tests/test_partial_failure_streaming.py` (3 tests, all `@pytest.mark.fast`)

- `test_every_yield_is_renderable_without_exception` — every intermediate `Report` from `pipeline.run(corrupt_pdf)` round-trips through `gander.report.render_body` without raising. Protects the Gradio re-render loop.
- `test_final_report_has_no_running_statuses` — after the iterator exhausts, every stage settles to `pending` / `done` / `failed`. Prevents the "permanent spinner" UI regression.
- `test_no_traceback_on_stderr_during_corrupt_run` — uses pytest's `capfd` to assert no Python traceback line ever reaches stderr during a corrupt-PDF run. `stage_boundary` already routes diagnostics through `obs.emit`; this gate notices if that contract breaks.

### Coverage diff vs `tests/test_pipeline_fast.py`

`test_pipeline_fast.py` mocks each stage worker via `monkeypatch.setattr(pipeline, "extract_text", ...)` and exercises the **cascade contract**. T18 deliberately drives one level deeper:

- Ingest tests use no mocks — real `pypdf` / `pdfplumber` / `python-docx` paths.
- DDG tests mock `gander.salary.DDGS` (the actual library seam) so changes to `estimate_salary`, `search`, or query construction stay covered.
- Extract test mocks `LLMClient.complete_json` so `stage_boundary` and the cascade messages dictionary stay covered.

No mark-skip / `xfail`. No new live tests needed — the brief's "tests that need real LLM" cases were folded into the existing acceptance suite from T30 Phase 1 (which exercises the happy-path LLM stack end-to-end across the EN triplet).

### Quality gates

```text
uv run ruff check src/ tests/      → All checks passed!
uv run ruff format --check src/ tests/ → 34 files already formatted
uv run mypy src/                   → Success: no issues found in 15 source files
uv run pytest -m fast -q           → 206 passed, 47 deselected in 4.86s
```
