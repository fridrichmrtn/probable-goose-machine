# T45 — Vision page parallelization + per-stage `max_tokens` caps

Status: done
Owner: software-engineer
Depends on: T34 (PDF VLM ingest), T42 (OpenRouter routing)
Unblocks: lower wallclock on vision ingest; tighter cost/latency envelope on OpenRouter calls
Estimate: ~75 min (A: ingest fan-out + tests; B: caps across 6 stages + tests)

Branch: `dev/parallelize-vision-cap-max-tokens`
Plan: `tasks/dev-plan.md` (improvements A and B; C and D deferred)
Source plan: `/home/mf/.claude/plans/as-it-is-after-nested-shell.md`

## Goal

Two narrow wallclock/cost wins, both inside the OpenRouter live path:

- **A.** Replace the serial per-page loop in `_extract_pdf_vlm` with bounded-concurrency fan-out so multi-page PDFs no longer pay 4–6× page wallclock back-to-back.
- **B.** Cap `max_tokens` at the OpenRouter `chat.completions.create` boundary per stage so the model can't run away on a stage-specific budget (extraction 3000, score 1024, salary 768, confidence step A 128 / step B 256, growth 1536, vision 1500).

Scope is A + B only. C (provider-side retry tightening) and D (semaphore on DDG fan-out) are explicitly deferred and not touched here.

## Changes

### A — Parallel vision page transcription

- `src/gander/ingest.py`: added `import asyncio`; replaced the serial `for i, png in enumerate(pages):` loop in `_extract_pdf_vlm` with an `asyncio.gather` over per-page coroutines bounded by `asyncio.Semaphore(4)`. Each per-page coroutine still:
  - measures its own `duration_ms` (per-task time, includes semaphore wait),
  - strips transcript fences,
  - raises `_IngestLLMReject("empty_output")` on blank output (first exception propagates and triggers the existing text-fallback path),
  - emits `ingest_vlm_page_done` with `page_index`, `chars`, `duration_ms`.
- Page order is preserved by `asyncio.gather` returning results in input order, so the downstream `"\n[PAGE_BREAK]\n".join(transcripts)` stays correct without sorting.
- `complete_vision_text` is now called with `max_tokens=1500`.

### B — Per-stage `max_tokens` caps (OpenRouter only)

- `src/gander/llm.py`: added `max_tokens: int | None = None` to `complete_json`, `complete_text`, `complete_vision_text`, `_complete_openrouter_vision_text`, `_chat_json`, `_chat_text`, `_chat_vision_text`. OpenRouter branches build a kwargs dict and conditionally insert `max_tokens` before unpacking into `client_o.chat.completions.create(**kwargs)`; the MiniMax branches keep their existing literal cap behaviour unchanged. The MiniMax vision REST branch does not accept `max_tokens` and is intentionally not plumbed.
- Per-stage caps applied at the caller:
  - `src/gander/extract.py`: `max_tokens=3000`
  - `src/gander/score.py`: `max_tokens=1024`
  - `src/gander/salary.py`: `max_tokens=768`
  - `src/gander/confidence.py`: step A `complete_json` 128; step B initial + regenerate `complete_text` 256
  - `src/gander/growth.py`: `max_tokens=1536`
- The conditional-forward design preserves the existing `assert "max_tokens" not in fake_completions.kwargs` baseline assertions in `tests/test_llm.py` for tests that don't pass `max_tokens`.

## Tests added / modified

- `tests/test_llm.py`: added 3 fast tests that assert OpenRouter forwarding of `max_tokens` on `complete_json`, `complete_text`, `complete_vision_text`. Updated `_RetryingLLMClient._chat_json` test override signature to absorb the new positional kwarg.
- `tests/test_ingest.py`: existing `test_pdf_vlm_ingest_renders_pages_and_joins_transcripts` now asserts `max_tokens == 1500`. New `test_pdf_vlm_parallel_preserves_page_order_and_bounds_concurrency` builds a 6-page PDF, tracks peak in-flight, and asserts: 6 transcripts in input order, `peak["max"] <= 4`, `peak["max"] >= 2`, all calls receive `max_tokens=1500`, exactly six `ingest_vlm_page_done` events covering `page_index` 0..5.
- `tests/test_extract.py`, `tests/test_score.py`, `tests/test_salary.py`, `tests/test_growth_unit.py`, `tests/test_confidence_unit.py`: one assertion per stage capturing the kwargs forwarded to `complete_json` / `complete_text` and asserting the stage cap (3000 / 1024 / 768 / 128 + 256 / 1536). Per-file additions rather than a single parametrized cross-stage test — each stage's stub call shape differs slightly, so per-file assertions stayed cleaner.

## Verification

```bash
uv run pytest -m fast --strict-markers -q
uv run mypy src/gander/ingest.py src/gander/llm.py src/gander/extract.py \
            src/gander/score.py src/gander/salary.py src/gander/confidence.py src/gander/growth.py
pre-commit run --all-files
```

Results captured on 2026-05-15 in this worktree:

- Fast suite: `384 passed, 58 deselected in 6.53s`.
- mypy on the 7 touched source files: `Success: no issues found in 7 source files`.
- pre-commit: green on second pass (first pass reflowed two files via ruff format; re-staged and re-ran).
- Live suite: not run in this phase — manual `openrouter-live` is owned by the follow-up review pass.

## Plan divergences

- **One source line vs. lines-in-plan.** Plan referenced literal line numbers for the caller call sites (e.g. `extract.py:241`). Real call sites drifted by a few lines after recent merges; the change set still landed on the single `complete_json` / `complete_text` call in each stage, so the cap is at the right boundary.
- **Per-file stage assertions instead of one parametrized test.** Plan §3 allowed either. Per-file kept the diff smaller and avoided coupling six stage stubs into one test fixture.

## Impact

Wallclock measurement is **not** the goal of this task — Phase 4 owns the spike rerun and the wallclock table. The two improvements here are:

- A is structural: an N-page vision ingest now runs in O(N / 4) wall-clock instead of O(N), bounded by the semaphore at 4.
- B is defensive: per-stage caps protect the OpenRouter cost/latency envelope against pathological generations without changing happy-path output.

## Out of scope

- Improvement C (provider-side retry tightening / fallback policy on `max_tokens` truncation).
- Improvement D (DDG semaphore on salary search fan-out).
- MiniMax vision REST `max_tokens` (the endpoint does not accept it).
- Any wallclock spike rerun or live `openrouter-live` job — owned by the follow-up review phase.
