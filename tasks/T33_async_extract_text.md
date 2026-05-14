# T33 — Make `extract_text` and `_extract_pdf` async (prerequisite refactor)

Status: done
Owner: software-engineer
Depends on: —
Unblocks: T34 (needs `extract_text` async to call `LLMClient.complete_vision_text`)
Estimate: ~30 min

## Goal

The vision tier in T34 calls `LLMClient.complete_vision_text` (async). Today `extract_text` is sync and `pipeline.py:176` calls it synchronously from an async generator. Calling `asyncio.run` inside that sync wrapper would `RuntimeError` from the running event loop. The cleanest fix is to make `extract_text` and `_extract_pdf` async and `await` the call site.

This refactor is independent of the vision spike outcome — it's worth landing even if T32 fails, since it cleans up a long-standing sync-in-async-context pattern. Ships ahead of T34 so the async surface is stable when the vision call is added.

## Deliverables

- [ ] `src/gander/ingest.py`:
  - Convert `extract_text(file_bytes, filename) -> str | StageFailure` to `async def`.
  - Convert `_extract_pdf` and `_extract_docx` to `async def` (no `await` inside today; the conversion is mechanical and prepares for T34's vision call site).
  - `stage_boundary` already supports `async with` ([errors.py](../src/gander/errors.py)) — switch the `with` → `async with`.
- [ ] `src/gander/pipeline.py:176` (and any other call site): `text = extract_text(...)` → `text = await extract_text(...)`.
- [ ] `tests/test_ingest.py`: convert sync tests calling `extract_text` to async (`pytest.mark.asyncio` + `await`). Existing test fixtures and assertions are unchanged.
- [ ] `tests/test_pipeline.py` (or wherever the end-to-end call lives): no change expected — already async.

## Verification

```bash
uv run pytest tests/test_ingest.py tests/test_pipeline.py -v
uv run mypy src/
```

All existing tests pass; no behavioural changes. Diff should be mechanical (`def` → `async def`, `with` → `async with`, `extract_text(...)` → `await extract_text(...)` at the one sync call site).

## Out of scope

- Vision dispatcher logic (T34).
- Any change to `_extract_pdf_text` internals (currently pypdf + pdfplumber).

## Reference

- Plan: `/home/mf/.claude/plans/so-i-have-lowkey-snoopy-dream.md` § "Files to add / modify" — async cascade row.
- Plan: `/home/mf/.claude/plans/so-i-have-lowkey-snoopy-dream.md` § "Known silent-regression risks" #5 (async cascade).

## Outcome

Implemented in T34: `extract_text` is async, `pipeline.run` awaits it, and
call-site tests were converted to async.
