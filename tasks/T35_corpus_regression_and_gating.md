# T35 — Regression, live gating, and docs for LLM ingest

Status: pending
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

(fill in when done)
