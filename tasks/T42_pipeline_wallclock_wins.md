# T42 — Pipeline wallclock wins (parallel DDG, L4c ∥ L5, mixed-model defaults)

Status: done — fast/live/UI-smoke verified
Owner: software-engineer
Depends on: T41 (OpenRouter provider)
Unblocks: lower-cost / lower-latency live runs in production
Estimate: ~90 min (3 deliverables × ~30 min each, including tests)

## Goal

Get warm-path wallclock per CV from current ~16–19s (Flash/Haiku via OpenRouter, with serial DDG and serial L4c→L5) down to ~10–14s by removing two unnecessary serializations and tuning the per-stage model choice. PRD §7 SLA is 60s, so this is headroom-building, not survival — but the same changes also reduce per-CV cost and tighten the failure surface.

## Spike evidence (frozen 2026-05-15)

Measured against `scripts/spike_minimax.py` (4 calls per run: extract+score on junior + senior fixtures), all calls forced to the same model via `OPENROUTER_MODEL_REASONING` + `OPENROUTER_MODEL_CHEAP` overrides.

| Provider / model | p50 latency | Anchor (jr/sr) | Score spread | Cost (4 calls) |
|---|---|---|---|---|
| MiniMax M2.7-highspeed | 16.6s | ~100% / ~100% | 65 | n/a |
| OpenRouter — `google/gemini-2.5-flash` | 1.4s | 100% / **81%** | 55 | $0.0043 |
| OpenRouter — `anthropic/claude-haiku-4.5` | 3.6s | 100% / 100% | 60 | $0.014 |

Per-call breakdown (Gemini Flash): junior extract 1.9s / score 0.6s; senior extract 3.6s / score 0.9s.
Per-call breakdown (Haiku 4.5): junior extract 3.9s / score 1.7s; senior extract 5.9s / score 3.3s.

The senior anchor regression on Flash (81%) is the load-bearing data point for D3 — Flash drops 4 of 21 anchors on the senior fixture, while Haiku verifies all 16. Extract is the only stage where literal-quote fidelity matters; everything else is scoring or summarization.

## Deliverables

### D1 — Parallel DDG salary queries  ([src/gander/salary.py:188-246](../src/gander/salary.py#L188-L246))

- Replace the `for q in queries:` loop with `asyncio.gather(...)` over a small wrapper coroutine that preserves the existing per-query try/except so a single bad query shape (e.g. `site:a OR site:b`) still doesn't fail the stage.
- Preserve order-insensitivity: downstream `_prioritize_sources` + URL dedup already handle reordering.
- Telemetry: keep the existing `salary_search` event shape; `failed_queries` is still a list, just collected from the gather results instead of in-loop appends.
- Risk: thundering-herd against DDG. Mitigation: at typical N=3–5 queries, fan-out is small enough that no semaphore is needed today. Document the future cap point.
- Tests: extend `tests/test_salary.py` to cover (a) all queries succeed concurrently, (b) one query raises, others succeed, (c) all queries fail → still raises the same `RuntimeError(_INSUFFICIENT_DATA_MSG)`.

Expected saving: ~3–8s on L4b's pre-LLM phase. Bigger relative win on Flash (where the LLM portion of L4b is ~2s) than on Haiku (~4s).

### D2 — L4c confidence ∥ L5 growth  ([src/gander/pipeline.py:266-323](../src/gander/pipeline.py#L266-L323))

- L5 inputs at line 310: `redacted, profile, score, salary` — does **not** read `state.confidence`. L4c reads only salary. Both are runnable the moment L4a + L4b complete.
- Wrap both in `asyncio.gather`; route results into `state.confidence` / `state.growth` independently; preserve:
  - the existing salary-failed short-circuit for L4c (`Confidence(tier="Low", rationale=_CONFIDENCE_NO_SALARY_RATIONALE)` without an LLM call),
  - the existing score/salary cascade matrix for L5 (`_GROWTH_NO_BASELINE` / `_GROWTH_NEEDS_SCORE` / `_GROWTH_NEEDS_SALARY`).
- Streaming caveat: today the UI sees `confidence: running → done` before `growth: running` starts. After this change both flip to `running` together and finish in unspecified order. **Verify the Gradio UI doesn't depend on the sequential snapshot stream** before merging.
- Tests: existing pipeline tests cover the cascade matrix; ensure all `StageFailure` routing cases still pass and that `pipeline_done` still fires exactly once at the end.

Expected saving: ~3s on the warm-path budget (L4c is the cheap model; we save the smaller of the two stage durations on the critical path).

### D3 — Mixed-model defaults  ([src/gander/llm.py:60-80](../src/gander/llm.py#L60-L80), [90-145](../src/gander/llm.py#L90-L145))

- Goal: Haiku for L3 extract (anchor fidelity), Flash for everything else (latency + cost).
- Decision: **Option B implemented** — `LogicalModel` now has a dedicated `"extract"` slot used by L3, with `OPENROUTER_MODEL_EXTRACT` as its env override. OpenRouter defaults are Flash for `reasoning`/`cheap` and Haiku for `extract`; MiniMax maps all three logical slots to `MiniMax-M2.7-highspeed`.
- Resolved design decision:
  - **Option A** — Override the existing two slots: `reasoning` → `google/gemini-2.5-flash`, `cheap` → `google/gemini-2.5-flash`. Simplest. Loses extract anchor fidelity (regression risk per the 81% senior result above).
  - **Option B (recommended)** — Add a third logical slot `"extract"` to `LogicalModel` and `_OPENROUTER_MODELS`. L3 extract calls `model="extract"`; everything else stays on `reasoning` / `cheap`. Cleanest semantic separation; small surface change. New env var: `OPENROUTER_MODEL_EXTRACT`.
  - **Option C** — Per-stage env var override pattern (`OPENROUTER_MODEL_L3` etc.). Most flexible, biggest registry refactor, leaks pipeline-stage names into `llm.py`.
- Default registry under Option B:
  ```yaml
  reasoning: google/gemini-2.5-flash    # was anthropic/claude-haiku-4.5
  cheap:     google/gemini-2.5-flash    # unchanged
  extract:   anthropic/claude-haiku-4.5 # new slot, used only by extract.py
  ```
- Update `tests/test_llm.py` model-resolution tests + any acceptance tests that hardcode model strings.
- Out of scope: changing MiniMax-side `_PROFILE_MODELS` defaults — MiniMax remains the recorded baseline.

Expected saving: ~12s per CV vs MiniMax baseline (six calls × ~2s avg instead of × ~16s). Per-CV cost ≈ $0.02 (one Haiku extract + five Flash calls).

## Verification

1. Re-run the spike on Flash and Haiku and confirm numbers match the evidence table (within ±20%):
   ```bash
   set -a; source .env; set +a
   GANDER_LLM_PROVIDER=openrouter \
     OPENROUTER_MODEL_REASONING=google/gemini-2.5-flash \
     OPENROUTER_MODEL_CHEAP=google/gemini-2.5-flash \
     OPENROUTER_MODEL_EXTRACT=google/gemini-2.5-flash \
     uv run python scripts/spike_minimax.py
   GANDER_LLM_PROVIDER=openrouter \
     OPENROUTER_MODEL_REASONING=anthropic/claude-haiku-4.5 \
     OPENROUTER_MODEL_CHEAP=anthropic/claude-haiku-4.5 \
     OPENROUTER_MODEL_EXTRACT=anthropic/claude-haiku-4.5 \
     uv run python scripts/spike_minimax.py
   ```
2. End-to-end live pipeline run via the live acceptance suite, measuring total wallclock from `pipeline_start` → `pipeline_done` in the emitted `obs` events.
   ```bash
   set -a; source .env; set +a
   GANDER_LLM_PROVIDER=openrouter uv run pytest tests/test_acceptance.py -m live -v
   ```
   Targets (post-D1+D2+D3 with Option B): **≤14s warm-path** end-to-end per CV.
3. Unit tests pass:
   ```bash
   uv run pytest tests/test_pipeline.py tests/test_salary.py tests/test_llm.py -v
   ```
4. Full suite green: `uv run pytest -q`.
5. CI `openrouter-live` job green on the PR.
6. Manual UI smoke (D2 risk): start Gradio, upload one CV, confirm the streaming view still renders sensibly when L4c and L5 fire in parallel rather than sequentially.

## Out of scope

- VLM ingest tier (hardcoded MiniMax `api-vlm`).
- MiniMax-side `_PROFILE_MODELS` defaults — MiniMax stays at the existing single-tier mapping.
- L4c step A → step B parallelization. Step B's prompt at `confidence.py:204` bakes in step A's tier — true dependency, not addressable without prompt redesign.
- Configuring the GitHub `OPENROUTER_API_KEY` secret (T41 #7, repo-admin task).
- Bigger model spike (e.g. Sonnet) — separate task if Haiku's anchor rate ever proves insufficient.

## Risks

- **DDG rate limit (D1).** Small N today (~3–5 queries) makes a semaphore unnecessary, but if `build_queries` ever grows we'll need a `asyncio.Semaphore(3)` wrapper. Document the trip-wire in the salary module.
- **UI ordering shift (D2).** Gradio currently sees stage transitions in a fixed order. Verify the UI doesn't assert ordering before merging; if it does, switch the snapshot loop to `as_completed` like L4a∥L4b already does.
- **Extract anchor regression (D3 Option A).** Spike shows Flash drops to 81% senior anchor rate. Option A would ship this regression. Option B avoids it. The spike numbers in this file are the trip-wire — re-run them and abort Option A if the gap reproduces.
- **Provider drift.** OpenRouter slugs occasionally rename (`anthropic/claude-haiku-4.5` etc.). The existing `_OPENROUTER_MODELS` comment already flags this; same comment applies to the new `extract` slot.

## Outcome

Implemented D1–D3 locally on 2026-05-15. Salary DDG queries now fan out concurrently while preserving per-query failure tolerance and source prioritization; confidence and growth now run concurrently after score+salary finish; OpenRouter model routing now keeps L3 extraction on Haiku via a new `extract` slot while defaulting `reasoning`/`cheap` to Gemini Flash. Fast verification passed:
`uv run pytest tests/test_salary.py tests/test_pipeline_fast.py tests/test_llm.py tests/test_extract.py -m fast --strict-markers -v` (72 passed, 15 deselected).
Full fast verification passed: `uv run pytest -m fast --strict-markers -v` (366 passed, 58 deselected).
Live OpenRouter acceptance passed: `GANDER_LLM_PROVIDER=openrouter GANDER_INGEST_MODE=text uv run pytest tests/test_acceptance.py -m live --strict-markers --reruns 1 --reruns-delay 2 -v` (9 passed in 69.23s).

Manual/backend Gradio streaming smoke passed on 2026-05-15 using the real
`app.handle()` path with app-default PDF vision ingest and OpenRouter downstream
models: 10 UI updates, 9 pipeline snapshots, at least one snapshot with
`confidence=running` and `growth=running`, running pills rendered,
intermediate "Reading file"/"Generating report" copy rendered, and final body
included `## Plan`.
