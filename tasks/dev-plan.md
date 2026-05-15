# dev-plan — Parallelize vision page loop + cap `max_tokens` per stage

Source of truth: `/home/mf/.claude/plans/as-it-is-after-nested-shell.md` (improvements A and B only; C and D are out of scope).

Branch: `dev/parallelize-vision-cap-max-tokens`
Worktree: `/home/mf/GitHub/probable-goose-machine/.worktrees/parallelize-vision-cap-max-tokens`

## 1. Files to modify

| Path | What changes |
|------|---|
| `src/gander/llm.py` | Add `max_tokens: int \| None = None` to `complete_json`, `complete_text`, `complete_vision_text`. Thread it into `_chat_json`, `_chat_text`, `_chat_vision_text` and forward into OpenRouter `chat.completions.create` (skip on MiniMax — that path keeps its own 4096 cap unchanged). |
| `src/gander/ingest.py` | Replace the serial `for png in pages` loop in `_extract_pdf_vlm` (lines 326-339) with `asyncio.gather` over per-page coroutines bounded by `asyncio.Semaphore(4)`. Pass `max_tokens=1500` to `complete_vision_text`. Preserve page order in `transcripts`. Per-page `ingest_vlm_page_done` events still fire with `page_index` and per-task `duration_ms`. First exception aborts; existing text-fallback path runs as today. |
| `src/gander/extract.py` | Pass `max_tokens=3000` at the `complete_json` call (line 241). |
| `src/gander/score.py` | Pass `max_tokens=1024` at the `complete_json` call (line 112). |
| `src/gander/salary.py` | Pass `max_tokens=768` at the `complete_json` call (line 296). |
| `src/gander/confidence.py` | Pass `max_tokens=128` at the step-A `complete_json` (line 150). Pass `max_tokens=256` at both step-B `complete_text` calls (lines 208 and 232 — the regenerate retry must use the same cap). |
| `src/gander/growth.py` | Pass `max_tokens=1536` at the `complete_json` call (line 229). |
| `tests/test_llm.py` | Add forwarding tests for `max_tokens` on `complete_json` / `complete_text` / `complete_vision_text` against the OpenRouter path. Existing `assert "max_tokens" not in fake_completions.kwargs` assertions in the no-cap baseline tests stay valid because the new param defaults to `None`. |
| `tests/test_ingest.py` | Add a concurrency / order-preservation test for `_extract_pdf_vlm`. |
| `tests/test_extract.py`, `tests/test_score.py`, `tests/test_salary.py`, `tests/test_confidence_unit.py`, `tests/test_growth_unit.py` | One small assertion per stage that the caller forwards the expected `max_tokens` cap. (Or one parametrized test under `tests/test_pipeline_fast.py` — see §3.) |

Total: 7 source files + 3 to 7 test files, depending on whether stage caller assertions land as a single parametrized test or per-file additions. Prefer the single parametrized test (less code, one place to read).

## 2. Detailed change set

### `src/gander/llm.py`

**`complete_json` (line 193):**

- Add `max_tokens: int | None = None` to the signature, immediately after `max_retries`.
- Pass it into `self._chat_json(resolved, system, current_user, temperature, max_tokens)` (the existing call site is line 224-230).

**`complete_text` (line 282):**

- Add `max_tokens: int | None = None` to the signature, after `temperature`.
- Pass it into `self._chat_text(resolved, system, user, temperature, max_tokens)` (existing call at line 302-308).

**`complete_vision_text` (line 351):**

- Add `max_tokens: int | None = None` to the signature, after `timeout_s`.
- Forward to `_complete_minimax_vision_text` and `_complete_openrouter_vision_text` (the MiniMax branch ignores it — see below).

**`_complete_minimax_vision_text` (line 375):**

- Accept and ignore `max_tokens` (the MiniMax `coding_plan/vlm` REST endpoint accepts `prompt`/`image_url` only; do not silently add a key the API rejects). One-line param + no use is fine; alternatively just don't plumb it into this branch and have `complete_vision_text` only forward to OpenRouter. The cleaner option is the second: leave MiniMax signature alone.

**`_complete_openrouter_vision_text` (line 431):**

- Add `max_tokens: int | None = None`, forward to `_chat_vision_text`.

**`_chat_json` (line 502):**

- Add `max_tokens: int | None = None` to the signature.
- MiniMax branch: keep the literal `max_tokens=4096` (line 515). Do not change MiniMax behaviour — A and B are OpenRouter-focused; MiniMax already has its own cap.
- OpenRouter branch (line 530): if `max_tokens is not None`, pass `max_tokens=max_tokens` to `client_o.chat.completions.create(...)`.

**`_chat_text` (line 556):**

- Same shape: add `max_tokens: int | None = None`. MiniMax branch unchanged. OpenRouter branch conditionally forwards.

**`_chat_vision_text` (line 605):**

- Add `max_tokens: int | None = None`. OpenRouter is the only branch; forward conditionally.

Rationale for conditional forwarding (only when not `None`): keeps the existing `"max_tokens" not in fake_completions.kwargs` assertions in `tests/test_llm.py` (lines 275, 395) green for the no-cap baseline.

### `src/gander/ingest.py`

Replace lines 326-339 in `_extract_pdf_vlm`. Sketch:

```python
sem = asyncio.Semaphore(4)

async def _transcribe(i: int, png: bytes) -> str:
    page_t0 = time.perf_counter()
    async with sem:
        page_text = await client.complete_vision_text(
            image_bytes=png, prompt=prompt, max_tokens=1500
        )
    page_text = _strip_transcript_fences(page_text)
    if not page_text.strip():
        raise _IngestLLMReject("empty_output")
    obs.emit(
        "ingest",
        "ingest_vlm_page_done",
        page_index=i,
        chars=len(page_text),
        duration_ms=int((time.perf_counter() - page_t0) * 1000),
    )
    return page_text.strip()

transcripts = await asyncio.gather(
    *(_transcribe(i, png) for i, png in enumerate(pages))
)
```

Notes:
- `asyncio.gather` preserves the input order in its returned list, so the existing `"\n[PAGE_BREAK]\n".join(transcripts)` on line 341 stays correct.
- First raised `_IngestLLMReject` propagates out of `gather` (default `return_exceptions=False`), which matches today's behaviour: ingest aborts, the existing text-fallback path runs.
- The per-task `duration_ms` measured here is the per-task wall time (which includes time waiting on the semaphore) — that is the right number to keep for parity with today's per-page emit, and matches the spec ("the per-task time, not wall time").
- The `obs.emit("ingest", "ingest_vlm_start", ...)` at line 319 stays where it is.

`asyncio` is already imported in this file (used elsewhere) — verify in the edit; if not, add `import asyncio` at the top.

### `src/gander/extract.py` (line 241)

Add `max_tokens=3000` to the `client.complete_json(...)` kwargs.

### `src/gander/score.py` (line 112)

Add `max_tokens=1024` to the `client.complete_json(...)` kwargs.

### `src/gander/salary.py` (line 296)

Add `max_tokens=768` to the `client.complete_json(...)` kwargs.

### `src/gander/confidence.py`

- Line 150 (`complete_json`, step A): `max_tokens=128`.
- Line 208 (`complete_text`, step B initial): `max_tokens=256`.
- Line 232 (`complete_text`, step B regenerate): `max_tokens=256` (same cap — the retry user prompt is longer but the desired output length is unchanged).

### `src/gander/growth.py` (line 229)

Add `max_tokens=1536` to the `client.complete_json(...)` kwargs.

## 3. Tests to add / update

All new tests are `@pytest.mark.fast`, async, and mock the LLM client. No live calls in unit tests.

### A. `tests/test_ingest.py` — concurrency + order test

**Test name:** `test_pdf_vlm_parallel_preserves_page_order_and_bounds_concurrency`

- Build a 4-page PDF using the existing `_pdf_bytes(...)` helper in `tests/test_ingest.py`.
- Monkeypatch `LLMClient.complete_vision_text` with a stub that:
  - Tracks per-call entry order via a shared list (`call_order.append(image_hash)`).
  - Tracks a peak-concurrency counter using a shared `{"in_flight": 0, "max": 0}` dict, incrementing on entry and decrementing on exit with an `await asyncio.sleep(0.02)` between to force overlap.
  - Returns a deterministic per-page sentinel: e.g. `f"Summary Page {i} transcript with enough chars to pass MIN_TEXT_CHARS ..."` keyed off the image bytes hash so order can be verified.
- After `await extract_text(pdf_bytes, "cv.pdf")` returns, assert:
  - The joined transcript contains the per-page sentinels in original page order (split on `[PAGE_BREAK]`, check the sequence).
  - `peak["max"] <= 4` (semaphore bound respected).
  - `peak["max"] >= 2` (some real overlap actually occurred — guards against a regression that silently re-serializes).
  - The number of `ingest_vlm_page_done` obs events equals the page count, and their `page_index` values cover `0..N-1` exactly once (set equality, not order — events fire as tasks finish).

**Test name:** `test_pdf_vlm_first_failure_aborts_and_falls_back`

- Two-page PDF. Monkeypatch `complete_vision_text` to raise on the first page-1 call. Assert `extract_text` returns the deterministic text-fallback transcript and the `ingest_vlm_done` event is NOT emitted. (This is largely covered by the existing `test_pdf_vlm_failure_falls_back_to_deterministic_text` at line 217; verify it still passes against parallel code and add a 2-page variant only if the existing single-page test does not exercise the gather path.)

### B. `tests/test_llm.py` — `max_tokens` forwarding

Three small tests, each ~10 lines, modelled on the existing `_client_with_fake_chat` pattern (line 245).

**Test name:** `test_openrouter_complete_json_forwards_max_tokens`

- `client, fake = _client_with_fake_chat("openrouter")`.
- `await client.complete_json(system="s", user="u", schema=Echo, model="cheap", max_tokens=512)`.
- Assert `fake.kwargs["max_tokens"] == 512`.

**Test name:** `test_openrouter_complete_text_forwards_max_tokens`

- Same shape with `complete_text`, `max_tokens=200`. Assert kwarg present and equal.

**Test name:** `test_openrouter_complete_vision_text_forwards_max_tokens`

- Same shape with `complete_vision_text(image_bytes=b"\x89PNG...", prompt="p", max_tokens=1500)`. Assert kwarg present and equal.

**Existing assertions to preserve:** `assert "max_tokens" not in fake_completions.kwargs` at lines 275 and 395 stay true because callers in those tests don't pass `max_tokens`. Keep them — they pin the no-cap default behaviour. The `assert fake_completions.kwargs["max_tokens"] == 4096` for MiniMax at line 521 is unchanged.

### C. Stage caller cap assertions

Preferred shape: one parametrized test in `tests/test_pipeline_fast.py` (or a new `tests/test_stage_max_tokens.py` if the existing file is large). Each parametrization:

1. Patches `LLMClient.complete_json` (or `complete_text` for confidence step B) with a capturing stub that records its kwargs.
2. Invokes the stage entry point with the minimum viable fixture.
3. Asserts `captured_kwargs["max_tokens"] == expected_cap`.

**Parametrization table:**

| Stage entry | Caller method | Expected cap |
|---|---|---|
| `extract.extract_profile` | `complete_json` | 3000 |
| `score.score_candidate` | `complete_json` | 1024 |
| `salary.estimate_salary` (or its equivalent — confirm symbol) | `complete_json` | 768 |
| `confidence.compute_confidence` step A | `complete_json` | 128 |
| `confidence.compute_confidence` step B | `complete_text` (first call only — capture by call index 0) | 256 |
| `growth.plan_growth` | `complete_json` | 1536 |
| `ingest._extract_pdf_vlm` | `complete_vision_text` | 1500 |

Each parametrization stubs only the LLM call surface; downstream stage logic that follows (verification, scoring math) can be allowed to short-circuit by returning a minimal valid payload from the stub. Where a stage already has a fast-path unit test in its own file (e.g. `tests/test_score.py::test_score_no_partial_when_all_verify` at line 92), prefer extending the existing capturing stub there with one extra assertion line instead of duplicating fixtures.

**Fallback / minimum bar:** if parametrization across heterogeneous stage signatures becomes ugly, ship per-stage one-line additions inside each stage's existing fast test that already stubs `complete_json` (the score/extract/salary/growth tests already do this — see `test_score.py:115`, similar in extract/salary/growth). Add `assert kwargs.get("max_tokens") == EXPECTED` inside each existing `fake_complete_json` stub.

## 4. Check commands

Run from the worktree root, in this order:

```
pre-commit run --all-files
uv run pytest -m fast --strict-markers -q
GANDER_LLM_PROVIDER=openrouter GANDER_INGEST_MODE=vision uv run pytest tests/test_acceptance.py -m live
```

Notes:
- The third command requires `OPENROUTER_API_KEY` in the environment (already in the user's `.env`). It is the live acceptance gate per `CLAUDE.md` "CI + prod gate on OpenRouter only". May be optional in CI but should run locally.
- `pre-commit run --all-files` runs `end-of-file-fixer`, `trailing-whitespace`, `ruff-format`, and `ruff-check --fix` per `.pre-commit-config.yaml`. `mypy` and `pytest -m fast` are configured as `pre-push` hooks; running `pytest -m fast` explicitly (command 2) covers the unit path. Run `uv run mypy src/` manually before push if you want to short-circuit a `pre-push` failure.

## 5. Verification path

After the three checks pass:

1. Run `scripts/measure_pipeline.py` against `/home/mf/Downloads/Profile.pdf`:

   ```
   GANDER_LLM_PROVIDER=openrouter GANDER_INGEST_MODE=vision \
     uv run python scripts/measure_pipeline.py /home/mf/Downloads/Profile.pdf 2>&1 | tee /tmp/profile_run.parallel.log
   ```

2. Same for `/home/mf/Downloads/Profile_new.pdf` (output to `/tmp/profile_new.parallel.log`).

3. Compare against the baseline `/tmp/profile_run.log`:
   - **Ingest wall-clock:** expect a roughly N× speedup where N = min(page_count, 4). Profile.pdf has multiple pages — the ingest stage duration in the new log should be materially lower while the sum of per-page `ingest_vlm_page_done.duration_ms` should be comparable to baseline (parallelism cuts wall time, not work).
   - **Total pipeline duration:** expect a measurable drop (ingest is one of the longer stages).
   - **Per-stage completion-token counts:** in `llm_call` events, `completion_tokens` should be `<= max_tokens` for the corresponding stage. Spot-check at least extract (≤3000), score (≤1024), growth (≤1536), and a vision page (≤1500).
   - **Report content:** end-to-end report still renders all blocks. No new `stage_failure` events vs baseline.

4. If `scripts/measure_pipeline.py` is not present in the worktree (it lives in `/home/mf/GitHub/probable-goose-machine/scripts/` on main but not in this worktree at plan time — see Risks), either copy it in before measuring or run the measurement from a checkout that has the implementation merged onto a branch that includes the script. Do not block the plan on script availability; the unit + live acceptance tests are the binding gates.

## 6. Risks / known unknowns

1. **`scripts/measure_pipeline.py` is not in the worktree.** It exists at `/home/mf/GitHub/probable-goose-machine/scripts/measure_pipeline.py` on main but is missing under the worktree's `scripts/` (only `build_cv_fixtures.py`, `eval_corpus.py`, `run_bias_smoke.py`, `spike_minimax.py`, `spikes/` are present). Either (a) cherry-pick / copy the script into the worktree before measuring, or (b) run the measurement against a branch that has it. The plan's verification step assumes (a).

2. **OpenRouter `max_tokens` for vision calls.** OpenRouter's OpenAI-compat shim accepts `max_tokens` on vision chat completions for Gemini 2.5 Flash today (it is a standard chat-completions param). If a specific upstream model silently truncates mid-token and produces unparseable output, the cap 1500 may be too tight — mitigation: the existing per-page `_IngestLLMReject("empty_output")` check (line 330-331) plus the established text-fallback path catch this case. If a real CV consistently trips it, raise the cap or skip the cap for vision until eval'd.

3. **OpenRouter providers vary on `max_tokens` semantics.** Most accept it; a small number reject unknown params strictly. Mitigation: conditional forward (`if max_tokens is not None: kwargs["max_tokens"] = max_tokens`) — the no-cap baseline path is unchanged, and our caps target the actually-configured `google/gemini-2.5-flash[-lite]` slugs which accept it.

4. **`mypy` strictness.** New `max_tokens: int | None = None` params must be threaded through internal helpers with consistent typing; missing one signature triggers `[no-untyped-def]`. Fix during implementation; `pre-push` hook will catch.

5. **`ruff-format` may reflow** the new long `client.chat.completions.create(...)` kwargs blocks (esp. `_chat_json` OpenRouter branch). Acceptable — let ruff own the layout.

6. **Confidence step B has two call sites** (lines 208 and 232) both reading the same prompt. Both need the cap. The stage-caller test must verify the first; the regenerate path is best covered by the existing `confidence_step_b_regenerated` test (in `tests/test_confidence_unit.py`) — confirm during implementation that it still passes.

7. **Per-task `duration_ms` measurement under semaphore wait.** Some readers might want "actual inference time, excluding queueing". The spec says per-task time, which is what we measure (entry-to-exit including the semaphore await). Document this in the obs counter description if it surfaces during review.

8. **`complete_text` plumbing was previously absent.** The current OpenRouter `_chat_text` path passes no `max_tokens`. The fix is the same shape as `_chat_json`. Confirmed by reading `src/gander/llm.py:556-603`.

9. **Test-side breakage from default arg change.** Tests that construct `LLMClient` and call into `_chat_*` directly with positional args (e.g. `tests/test_llm.py:262`, `:303`, `:383`) pass `model, system, user, temperature` positionally. Adding `max_tokens` as a new last param with a `None` default keeps them passing — verify by re-running `uv run pytest -m fast tests/test_llm.py` after the signature change.

10. **CI live job.** Per project memory: only `openrouter-live` runs `-m live` in CI. The third check command matches the CI gate. If the CI box doesn't have a billable OpenRouter key, the live job will be skipped; local verification stays the binding signal.
