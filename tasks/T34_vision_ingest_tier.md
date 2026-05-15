# T34 — MiniMax Token Plan LLM ingest implementation

Status: done
Owner: ai-ml-engineer
Depends on: T32 (Token Plan VLM spike passed), T33 (async ingest)
Unblocks: T35 (regression, gating, docs)
Estimate: ~1-2 sessions

## Goal

Make L1 ingest LLM-first while keeping deterministic extraction as a fallback:

- PDFs: render pages to PNG with PyMuPDF, send each page to MiniMax
  `POST https://api.minimax.io/v1/coding_plan/vlm`, join page transcripts
  with `[PAGE_BREAK]`.
- DOCX: extract paragraphs/tables with `python-docx`, then use the existing
  MiniMax text chat path to normalize the transcript and section breaks.
- No LibreOffice, Pandoc, OpenAI image blocks, Anthropic fallback, or
  `MiniMax-VL-01` model path.

`GANDER_INGEST_MODE` controls behavior:

- `vision` (default): PDF VLM first; DOCX text-LLM first; deterministic
  fallback for both.
- `text`: deterministic PDF/DOCX extraction only.

Provider update (2026-05-15): `LLMClient.complete_vision_text` now dispatches
by `GANDER_LLM_PROVIDER`. With `openrouter`, PDF pages use OpenRouter image URL
messages with Gemini Flash primary and Gemini Flash Lite fallback. With
`minimax`, the original MiniMax Token Plan `api-vlm` path below remains the
legacy provider route.

## Deliverables

- [ ] `src/gander/ingest.py`
  - `extract_text` is async and the pipeline awaits it.
  - Existing deterministic PDF/DOCX extraction is retained as
    `_extract_pdf_text` / `_extract_docx_text`.
  - PDF VLM path renders each page to PNG and calls
    `LLMClient.complete_vision_text`.
  - DOCX text-LLM path calls `LLMClient.complete_text` with a
    transcript-normalization prompt.
  - `_repair_inline_section_breaks(text)` runs before `_annotate_sections`.
  - Fallback happens on API errors, timeouts, empty/too-short output,
    low DOCX source overlap, and bad sidebar/body order.
- [ ] `src/gander/llm.py`
  - Add `complete_vision_text(image_bytes, prompt)` for MiniMax `API-vlm`.
  - Emit telemetry as `model="api-vlm"`, `usd_cost=0.06`, and
    `token_plan_m2_requests=3` per call.
- [ ] `src/gander/prompts/ingest_vlm.md`
  - Verbatim transcription prompt; preserve language, diacritics, bullets,
    headings, and sidebar-first ordering.
- [ ] `src/gander/prompts/ingest_docx.md`
  - Normalize deterministic DOCX text into a transcript without adding facts
    or paraphrasing source phrases.
- [ ] `app.py` and `README.md`
  - User copy says PDF pages and DOCX text may be sent to MiniMax for
    LLM-based extraction, and Gander does not retain files.

## Tests

- [ ] Async ingest conversion and pipeline call site.
- [ ] PDF page rendering and VLM request parsing.
- [ ] DOCX text-LLM prompt path with mocked `complete_text`.
- [ ] Deterministic fallback on VLM/text-LLM failure.
- [ ] Source-overlap guard rejecting paraphrased DOCX output.
- [ ] Inline section-break repair for collapsed VLM/LLM output.
- [ ] Telemetry for `api-vlm` cost and DOCX text-LLM calls.

## Verification

```bash
uv run pytest tests/test_ingest.py tests/test_llm.py tests/test_failures.py -v
uv run pytest tests/test_extract.py tests/test_redact.py -v
uv run mypy src/
uv run ruff check .
```

## Outcome

Implemented:

- `GANDER_INGEST_MODE=vision` is the default LLM-first mode.
- PDFs render pages with PyMuPDF and call MiniMax `API-vlm`; deterministic
  PDF extraction remains the fallback.
- DOCX uses `python-docx` source extraction plus MiniMax text-chat transcript
  normalization; deterministic DOCX text remains the fallback.
- Inline section-break repair runs before section annotation.
- VLM telemetry records `model="api-vlm"`, `$0.06/request`, and
  `token_plan_m2_requests=3`.

Post-T42 update:

- OpenRouter provider mode now covers PDF vision ingest too; it emits
  provider-reported token/cost telemetry and `models_attempted`.
- MiniMax `api-vlm` telemetry remains unchanged for `GANDER_LLM_PROVIDER=minimax`.
