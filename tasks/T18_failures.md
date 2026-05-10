# T18 — L8 failure-path + partial-failure-streaming tests

Status: todo
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

(fill in when done)
