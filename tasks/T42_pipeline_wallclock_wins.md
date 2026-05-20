# T42 — Pipeline wallclock wins (parallel DDG, L4c ∥ L5, OpenRouter Gemini defaults)

Status: done — fast/live/UI-smoke verified
Owner: software-engineer
Depends on: T41 (OpenRouter provider)
Unblocks: lower-cost / lower-latency live runs in production
Estimate: ~90 min (3 deliverables × ~30 min each, including tests)

## Goal

Get warm-path wallclock per CV from current ~16–19s (OpenRouter spike runs with serial DDG and serial L4c→L5) down to ~10–14s by removing two unnecessary serializations and tuning the per-stage model choice. PRD §7 SLA is 60s, so this is headroom-building, not survival — but the same changes also reduce per-CV cost and tighten the failure surface.

## Spike evidence (frozen 2026-05-15)

Measured against `scripts/spike_minimax.py` (4 calls per run: extract+score on junior + senior fixtures), all calls forced to the same model via `OPENROUTER_MODEL_REASONING` + `OPENROUTER_MODEL_CHEAP` + `OPENROUTER_MODEL_EXTRACT` overrides.

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

### D3 — OpenRouter model slots and fallbacks  ([src/gander/llm.py:60-110](../src/gander/llm.py#L60-L110), [140-180](../src/gander/llm.py#L140-L180))

- Goal: Gemini Flash-Lite primary with Gemini Flash fallback for all OpenRouter work, including L3 extraction and PDF vision ingest, to keep the production path cheaper and faster while retaining the existing exception fallback path.
- Decision: `LogicalModel` now has dedicated `"extract"` and `"vision"` slots with `OPENROUTER_MODEL_{SLOT}` and `OPENROUTER_MODEL_{SLOT}_FALLBACK` overrides. OpenRouter defaults are Flash-Lite primary and Flash fallback for `reasoning`, `cheap`, `extract`, and `vision`; MiniMax keeps its recorded baseline mapping plus legacy `api-vlm`.
- Resolved design decision:
  - **Option A** — Override the existing two slots: `reasoning` → `google/gemini-2.5-flash`, `cheap` → `google/gemini-2.5-flash`. Simplest. Loses extract anchor fidelity (regression risk per the 81% senior result above).
  - **Option B (implemented first)** — Add a third logical slot `"extract"` to `LogicalModel` and `_OPENROUTER_MODELS`. L3 extract calls `model="extract"`; everything else stays on `reasoning` / `cheap`. Cleanest semantic separation; small surface change. New env var: `OPENROUTER_MODEL_EXTRACT`.
  - **Option C** — Per-stage env var override pattern (`OPENROUTER_MODEL_L3` etc.). Most flexible, biggest registry refactor, leaks pipeline-stage names into `llm.py`.
- **Follow-up decision (2026-05-20)** — User chose the cheaper/faster Gemini axis: Flash-Lite is now the primary OpenRouter model for all slots, with Flash as fallback. The Haiku spike result remains the trip-wire if acceptance/profile evidence regresses.
- Default OpenRouter registry:
  ```yaml
  reasoning: google/gemini-2.5-flash-lite
  cheap:     google/gemini-2.5-flash-lite
  extract:   google/gemini-2.5-flash-lite
  vision:    google/gemini-2.5-flash-lite
  fallbacks: google/gemini-2.5-flash per slot
  ```
- Update `tests/test_llm.py` model-resolution tests + any acceptance tests that hardcode model strings.
- Out of scope: changing MiniMax-side `_PROFILE_MODELS` defaults — MiniMax remains the recorded baseline.

Expected saving: ~12s per CV vs MiniMax baseline (six calls × ~2s avg instead of × ~16s). Per-CV text/JSON cost target stays below the OpenRouter live CI cap; PDF vision adds provider-reported OpenRouter image cost when `GANDER_INGEST_MODE=vision`.

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

- MiniMax-side VLM retirement — MiniMax `api-vlm` remains the legacy path when `GANDER_LLM_PROVIDER=minimax`.
- MiniMax-side `_PROFILE_MODELS` defaults — MiniMax stays at the existing single-tier mapping.
- L4c step A → step B parallelization. Step B's prompt at `confidence.py:204` bakes in step A's tier — true dependency, not addressable without prompt redesign.
- Configuring the GitHub `OPENROUTER_API_KEY` secret (T41 #7, repo-admin task).
- Bigger model spike (e.g. Sonnet) — separate task if Haiku's anchor rate ever proves insufficient.

## Risks

- **DDG rate limit (D1).** Small N today (~3–5 queries) makes a semaphore unnecessary, but if `build_queries` ever grows we'll need a `asyncio.Semaphore(3)` wrapper. Document the trip-wire in the salary module.
- **UI ordering shift (D2).** Gradio currently sees stage transitions in a fixed order. Verify the UI doesn't assert ordering before merging; if it does, switch the snapshot loop to `as_completed` like L4a∥L4b already does.
- **Extract anchor regression.** Spike shows Flash dropped to 81% senior anchor rate before the profile-smoke fixes, and Flash-Lite may have its own quality tradeoffs. We are intentionally shipping Flash-Lite primary for cheap/fast production behavior; keep the spike numbers as the trip-wire and switch `OPENROUTER_MODEL_EXTRACT` back to Flash or Haiku/Sonnet-class routing if acceptance/profile evidence regresses.
- **Provider drift.** OpenRouter slugs occasionally rename. The existing `_OPENROUTER_MODELS` comment already flags this; same comment applies to the `extract` and `vision` slots plus their fallback env vars.

## Outcome

Implemented D1–D3 locally on 2026-05-15. Salary DDG queries now fan out concurrently while preserving per-query failure tolerance and source prioritization; confidence and growth now run concurrently after score+salary finish; OpenRouter model routing has dedicated `extract` and `vision` slots and now defaults all OpenRouter slots to Gemini Flash-Lite primary with Gemini Flash fallback. Fast verification passed:
`uv run pytest tests/test_salary.py tests/test_pipeline_fast.py tests/test_llm.py tests/test_extract.py -m fast --strict-markers -v` (72 passed, 15 deselected).
Full fast verification passed: `uv run pytest -m fast --strict-markers -v` (366 passed, 58 deselected).
Live OpenRouter acceptance passed: `GANDER_LLM_PROVIDER=openrouter GANDER_INGEST_MODE=text uv run pytest tests/test_acceptance.py -m live --strict-markers --reruns 1 --reruns-delay 2 -v` (9 passed in 69.23s).
Post-vision update: PR CI `openrouter-live` now runs the same acceptance suite with `GANDER_INGEST_MODE=vision` so the Flash-Lite/Flash OpenRouter vision route is part of the normal quality and cost gate.

Manual/backend Gradio streaming smoke passed on 2026-05-15 using the real
`app.handle()` path with app-default PDF vision ingest and OpenRouter downstream
models: 10 UI updates, 9 pipeline snapshots, at least one snapshot with
`confidence=running` and `growth=running`, running pills rendered,
intermediate "Reading file"/"Generating report" copy rendered, and final body
included `## Plan`.
