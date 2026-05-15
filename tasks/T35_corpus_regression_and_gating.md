# T35 — Regression, live gating, and docs for LLM ingest

Status: implemented — opt-in live smoke pending
Owner: qa-engineer
Depends on: T34 (LLM ingest implementation)
Unblocks: —
Estimate: ~1 session

## Goal

Verify the MiniMax Token Plan ingest path does not regress the existing corpus,
keeps live spend visible, and documents that PDF pages and DOCX text may be
sent to MiniMax. The synthetic VLM spike remains the safe live smoke; private
or real CV testing stays separate explicit approval.

## Deliverables

- [ ] Regression tests
  - Existing PDF and DOCX fixtures still extract at least 200 chars.
  - DOCX fixtures produce recognizable role/section anchors under
    `GANDER_INGEST_MODE=vision`.
  - Synthetic Token Plan VLM smoke remains the only live image test by
    default.
- [ ] Live gating
  - Fast PR tests avoid network and force deterministic/mocked ingest where
    needed.
  - Live VLM tests require `MINIMAX_API_KEY` and an explicit marker.
  - Expected spend is printed or documented before live VLM runs:
    `API-vlm` is $0.06/request or 3 M2.7 token-plan requests per call.
- [ ] Docs and UI copy
  - README and app copy explain: PDFs are rendered to page images and DOCX
    source text may be sent to MiniMax for LLM-based extraction.
  - Gander does not retain uploaded files.
  - Scanned/private real-CV live testing is opt-in only.

## Verification

```bash
uv run pytest tests/test_ingest.py tests/test_llm.py tests/test_failures.py -v
uv run pytest tests/test_extract.py tests/test_redact.py -v
uv run mypy src/
uv run ruff check .
```

## Outcome

Implemented:
- Mocked PDF VLM and DOCX text-LLM ingest regressions already cover the
  no-network fast path.
- Added an opt-in synthetic MiniMax `API-vlm` live smoke:
  `GANDER_RUN_MINIMAX_VLM=1 MINIMAX_API_KEY=... uv run pytest tests/test_llm.py -m "live and slow" -k minimax_api_vlm`.
  It uses a 1x1 synthetic PNG, not a real/private CV page.
- The smoke asserts `usd_cost == 0.06` and
  `token_plan_m2_requests == 3`, making expected spend visible.
- README now documents that PDF page ingest sends one rendered page per VLM
  request, at `$0.06` / 3 M2.7 token-plan requests, and that private real-CV
  live testing is opt-in only.
- App copy already states PDF page images and DOCX text may be sent to the
  configured provider and that files are not retained.

Verified fast:
- `uv run pytest tests/test_llm.py -m fast -q`
- `uv run ruff check README.md tests/test_llm.py`

Still pending before checking T35 done in `tasks/todo.md`:
- Run the opt-in MiniMax VLM smoke with a real `MINIMAX_API_KEY` and
  `GANDER_RUN_MINIMAX_VLM=1`.
