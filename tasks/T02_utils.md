# T02 — Cross-cutting utilities

Status: todo
Owner: software-engineer
Depends on: T01
Unblocks: T05, T07–T13
Estimate: ~60 min

## Goal

Land the four utilities every stage worker depends on: substring verifier, observability, async LLM client, and the stage_boundary decorator (from T01) wired up to obs.

## Deliverables

- [ ] `src/jobfit/verify.py`:
  - `def verify_quote(quote: str, source: str, *, section: str | None = None) -> bool`:
    - normalize: lowercase, collapse runs of whitespace to single space.
    - reject if quote has fewer than 6 words.
    - if quote has 6–7 words: must appear **exactly once** in source (positional uniqueness). If it appears 0 times → False; >1 times → False.
    - if quote has ≥8 words: must appear ≥1 times in source.
    - if `section` provided: source is restricted to the substring of `source` between section header `## section` (case-insensitive) and the next `##` (or end). Match must fall in that subrange.
  - `def drop_unverified[T](items: list[T], source: str, *, anchor_attr: str = "anchor") -> tuple[list[T], int]` — returns (kept, dropped_count). Reads `getattr(item, anchor_attr).quote` and `.section`.
- [ ] `src/jobfit/obs.py`:
  - `def emit(stage: str, event: str, **kv: Any) -> None` — writes a `structlog`-formatted JSON record to stdout with timestamp, stage, event, and all kv. For LLM calls, kv conventionally includes `prompt_tokens`, `completion_tokens`, `usd_cost`, `duration_ms`.
  - `def subscribe(callback: Callable[[dict], None]) -> ContextManager[None]` — context manager that registers a callback for the duration of a request; the Gradio handler uses this to forward events to the UI.
  - Internal: a `contextvars.ContextVar` holding the current callback list (so it works with asyncio).
- [ ] `src/jobfit/llm.py`:
  - `class LLMClient` — wraps `openai.AsyncOpenAI(base_url=..., api_key=os.environ["MINIMAX_API_KEY"])`.
  - Constructor reads `JOBFIT_MODEL_PROFILE` env var: `local` (default) → M1; `ci` → `abab6.5s-chat`. Each stage requests a model via a logical name (`reasoning` / `cheap`) which the profile resolves.
  - `async def complete_json(self, *, system: str, user: str, schema: type[BaseModel], model: Literal["reasoning","cheap"] = "reasoning", temperature: float = 0.0, max_retries: int = 1) -> BaseModel`:
    - Uses `response_format={"type": "json_object"}`.
    - On `pydantic.ValidationError`, retries once with the validation error appended to the user message ("Your previous output failed validation: ...").
    - Always emits `obs.emit("llm_call", stage=<stage from contextvar>, ...)` with token counts and duration.
    - USD cost from a hardcoded `MODEL_PRICES` dict (rough $/1M tokens for MiniMax-M1 and abab6.5s-chat).
  - `async def complete_text(self, *, system: str, user: str, model: Literal["reasoning","cheap"] = "cheap", temperature: float = 0.0) -> str` — for prose-only outputs (e.g., confidence rationale).
  - **Fallback hook**: if `os.environ.get("JOBFIT_LLM_PROVIDER") == "anthropic"`, the constructor uses `anthropic.AsyncAnthropic` with Sonnet 4.6 instead. T05 spike flips this if MiniMax fails its gates.
- [ ] `src/jobfit/errors.py` (extension): wire `stage_boundary` to call `obs.emit("error", stage=..., exc_type=..., exc_message=...)` on catch. Set the stage name in a `contextvars.ContextVar` so `llm.py` knows which stage to attribute its calls to.
- [ ] Tests (`@pytest.mark.fast`):
  - `tests/test_verify.py`:
    - 6-word quote appearing once → True.
    - 6-word quote appearing twice → False.
    - 8-word quote appearing twice → True.
    - 5-word quote → False.
    - section-locality: quote in different section → False.
  - `tests/test_obs.py`: emit + subscribe roundtrips events through the contextvar; works inside an `asyncio.gather`.
  - `tests/test_llm.py`: `@pytest.mark.live` (only runs when `MINIMAX_API_KEY` is set) — round-trip a trivial JSON schema and assert telemetry was emitted.

## Verification

```bash
uv run pytest -m fast tests/test_verify.py tests/test_obs.py -v
uv run mypy src/jobfit/verify.py src/jobfit/obs.py src/jobfit/llm.py src/jobfit/errors.py
# only if MINIMAX_API_KEY is set:
uv run pytest -m live tests/test_llm.py -v
```

## Reference

- tasks/PLAN.md — § "L0 — Foundation" (`verify`, `obs`, `errors`, `llm`)
- tasks/PLAN.md — § "Cross-cutting"
- tasks/PLAN.md — § "Hallucination guard hardened" (verify_quote contract)

## Outcome

(fill in when done — esp. MiniMax JSON-mode quirks)
