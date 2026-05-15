# T41 — Wire OpenRouter; drop direct Anthropic provider

Status: implemented — pending live OpenRouter roundtrip
Owner: software-engineer
Depends on: —
Unblocks: cross-provider model evaluation (no follow-up task yet)
Estimate: ~60 min

## Goal

Add `openrouter` as the second supported value for `GANDER_LLM_PROVIDER` and delete the never-exercised direct `anthropic` branch from [src/gander/llm.py](../src/gander/llm.py). Net result: `GANDER_LLM_PROVIDER ∈ {minimax, openrouter}`. Claude (and ~hundreds of other models) reachable via OpenRouter slugs (`anthropic/claude-sonnet-4.5`, `openai/gpt-4o-mini`, `deepseek/deepseek-r1`, etc.) without per-experiment edits to `gander.llm`.

User intent (verbatim): "plan wiring open router to this, so we can test another models tomorrow" + "i want to keep minimax and implement open router option, it should cover every part of the pipeline" + "i do not want anthropic directly at all".

## Context

Today every pipeline stage (`extract`, `normalize`, `score`, `salary`, `confidence`, `growth`) and `scripts/spike_minimax.py` route through `LLMClient` — verified single chokepoint, no stage instantiates an SDK directly. Switching providers therefore needs no per-stage edits. The direct Anthropic branch in `LLMClient.__init__` was a T05 fallback that was never used; removing it shrinks the surface and unifies auth/billing/telemetry through one OpenAI-compatible client.

## Implementation

Full plan in [plan-wiring-open-router-wiggly-hopper.md](../../.claude/plans/plan-wiring-open-router-wiggly-hopper.md). Summary:

- **[src/gander/llm.py](../src/gander/llm.py)** — delete anthropic branch (TYPE_CHECKING import, `_ANTHROPIC_MODEL`, `__init__` elif, `_resolve_model` early return, anthropic branches in `_chat_json` / `_chat_text`); add openrouter branch using `AsyncOpenAI(base_url="https://openrouter.ai/api/v1", default_headers={HTTP-Referer, X-Title})`; add `OPENROUTER_MODEL_{REASONING,CHEAP}` env overrides on a small registry default; keep MiniMax quirks (`_strip_think`, `extra_body={"reasoning_split": True}`, `max_tokens=4096`) **strictly inside** the minimax branch; gate `_strip_think` behind `OPENROUTER_STRIP_THINK=1` for reasoning-trace routes; add `provider=self._provider` to both `obs.emit("llm_call", ...)` call sites.
- **[.env.example](../.env.example)** — drop `ANTHROPIC_API_KEY` line; add `OPENROUTER_API_KEY` + two model-override lines.
- **[scripts/spike_minimax.py](../scripts/spike_minimax.py)** — generalize `_preflight` to a 2-way `{minimax, openrouter}` lookup.
- **[tests/test_llm.py](../tests/test_llm.py)** — three new tests: openrouter constructs with stub key + honors model overrides (fast); openrouter `_chat_json` omits MiniMax quirks AND minimax branch retains them as a regression guard (fast); openrouter live JSON roundtrip gated on `OPENROUTER_API_KEY` (live).
- **[.github/workflows/ci.yml](../.github/workflows/ci.yml)** — no change; trunk CI stays MiniMax-only.

## Default model registry

```python
"openrouter": {
    "reasoning": "anthropic/claude-haiku-4.5",  # verified on OpenRouter 2026-05-15
    "cheap":     "google/gemini-2.5-flash",     # verified on OpenRouter 2026-05-15
}
```

Override per-run: `OPENROUTER_MODEL_REASONING=deepseek/deepseek-r1 OPENROUTER_STRIP_THINK=1 uv run …`. Slugs drift — confirm against OpenRouter's `/models` listing before relying.

## Out of scope (deliberate cuts)

- L4c judge slot (`LogicalModel = Literal["reasoning", "cheap", "judge"]`) — restores PRD §4.3 isolation but touches `confidence.py` + every caller. Separate task.
- `--model-reasoning` / `--model-cheap` CLI flags on `eval_corpus.py` — env vars suffice for tomorrow's exploration.
- `MODEL_PRICES` population for OpenRouter — `usd_cost=0.0` until then; rely on token counts.
- `workflow_dispatch` job for OpenRouter live tests in CI.
- `scripts/spike_minimax.py` rename — misleading once it speaks two providers.

## Verification

10-step runbook in the plan file. Mandatory before merge:

1. `uv run ruff format --check . && uv run ruff check . && uv run mypy src/`
2. `git grep -nE 'anthropic|ANTHROPIC|AsyncAnthropic|_ANTHROPIC_MODEL' -- src/ tests/ scripts/ .env.example` returns empty.
3. `MINIMAX_API_KEY=test-stub uv run pytest -m fast --strict-markers -v` (no regression).
4. `GANDER_LLM_PROVIDER=openrouter OPENROUTER_API_KEY=test-stub uv run pytest -m fast --strict-markers -v -k "llm or openrouter"` (new branch wires up).
5. Missing-key path raises `RuntimeError` containing `OPENROUTER_API_KEY`.
6. `GANDER_LLM_PROVIDER=anthropic …` raises `RuntimeError` listing only `'minimax' or 'openrouter'` (deletion regression).
7. Live single roundtrip: `pytest -m live tests/test_llm.py::test_openrouter_complete_json_roundtrip -v`.

Strongly recommended: 4-CV spike harness against OpenRouter (real money). Eval session: end-to-end on one fixture + A/B sanity diff between two models.

## Risks

- Provider-specific JSON-mode failures: some OpenRouter routes reject `response_format={"type": "json_object"}`. Plan lets `BadRequestError` propagate raw rather than wrapping.
- Reasoning-trace models (DeepSeek-R1, Qwen-QwQ, OpenAI o-series) emit `<think>` blocks; `OPENROUTER_STRIP_THINK=1` covers them, off by default.
- `usd_cost=0.0` for every OpenRouter row until `MODEL_PRICES` populated. Telemetry includes `provider` field so analyst can disambiguate from zeroed MiniMax rows.
- Slug drift on OpenRouter model IDs — flagged inline in registry comments.

## Outcome

Implemented:
- Removed the direct Anthropic provider branch from `src/gander/llm.py`.
- Added `GANDER_LLM_PROVIDER=openrouter` via the OpenAI-compatible `AsyncOpenAI` client at `https://openrouter.ai/api/v1`.
- Default OpenRouter models changed per user preference: `anthropic/claude-haiku-4.5` for `reasoning`, `google/gemini-2.5-flash` for `cheap`.
- Added `OPENROUTER_MODEL_REASONING` / `OPENROUTER_MODEL_CHEAP` overrides, optional OpenRouter headers, and provider telemetry on `llm_call`.
- Generalized `scripts/spike_minimax.py` preflight to `{minimax, openrouter}`.
- Updated `.env.example`.

Verified:
- OpenRouter slugs checked against OpenRouter model pages on 2026-05-15.
- `uv run pytest tests/test_llm.py -m fast -v`
- full fast suite: `350 passed, 57 deselected`
- `uv run ruff check .`
- `uv run mypy src/`

Still pending before checking T41 done:
- Live OpenRouter JSON roundtrip with `OPENROUTER_API_KEY`.
- Optional one-fixture end-to-end A/B run against Haiku/Gemini Flash.
