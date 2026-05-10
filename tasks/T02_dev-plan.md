# T02 — Cross-cutting utilities: implementation plan

Worktree: `/home/mf/GitHub/probable-goose-machine/.worktrees/t02-utils` (branch `dev/t02-utils`).
Source of truth: `tasks/T02_utils.md` + `tasks/PLAN.md` §"L0 — Foundation", §"Cross-cutting", §"Hallucination guard hardened".

Read first (in this order, in the worktree):
1. `CLAUDE.md` — verification before done; no dead code; no decoration.
2. `tasks/T02_utils.md` — the contract.
3. `tasks/PLAN.md` lines 22, 126–131 (cross-cutting + hardened verify rule).
4. `src/jobfit/errors.py` — has the `# T02:` TODO on line 69; extend, do not rewrite.
5. `src/jobfit/schemas.py` — `Anchor(quote, section: str | None)` shape used by `drop_unverified`.
6. `pyproject.toml` — confirms `openai`, `structlog`, `pydantic`, `pytest-asyncio` (`asyncio_mode = "auto"`); markers `fast`/`slow`/`live` declared.

## Files to create
- `src/jobfit/verify.py` — `verify_quote(quote, source, *, section=None)` and `drop_unverified(items, source, *, anchor_attr="anchor")`.
- `src/jobfit/obs.py` — structlog setup (idempotent), `emit`, `subscribe`, `current_stage` ContextVar.
- `src/jobfit/llm.py` — `LLMClient` (MiniMax default; Anthropic fallback path); `complete_json`, `complete_text`; emits `llm_call` telemetry.
- `tests/test_verify.py` (`@pytest.mark.fast`).
- `tests/test_obs.py` (`@pytest.mark.fast`).
- `tests/test_errors_obs.py` (`@pytest.mark.fast`).
- `tests/test_llm.py` (`@pytest.mark.live`, `skipif(not os.environ.get("MINIMAX_API_KEY"))`).

## Files to extend
- `src/jobfit/errors.py` — replace the `# T02:` TODO on line 69 with `obs.emit(self.stage_name, "error", exc_type=..., exc_message=...)`; add `current_stage` token plumbing in `__enter__`/`__exit__` and `__aenter__`/`__aexit__`. Do not change the public `stage_boundary(stage_name)` signature or the `StageFailure` shape — `tests/test_schemas.py` (10 tests) must stay green.

## Files NOT to touch
- `src/jobfit/schemas.py` (T01 territory).
- `pyproject.toml` — except the *optional* anthropic extras step in section 9 below; if uncertain, skip and note in Outcome.
- `tests/test_schemas.py` and any T01 fixtures.

## Implementation order
1. `obs.py` first — no internal deps; everything else imports from it.
2. `errors.py` extension — depends on `obs.current_stage` + `obs.emit`.
3. `verify.py` — stdlib only; imports `Anchor` from `jobfit.schemas` at type-check time only (no runtime cycle, but `from __future__ import annotations` is the existing style).
4. `llm.py` — depends on `obs`.
5. Tests in any order; write them as you go to drive each module's surface.

## Key implementation notes (pin these — they are the easy-to-get-wrong bits)

### emit / subscribe call shape — pinned
- Signature: `def emit(stage: str | None, event: str, **kv: Any) -> None`.
- Positional order is `(stage, event)`. **`errors.py` must call `obs.emit(self.stage_name, "error", exc_type=..., exc_message=...)`** — stage first, event second. The original TODO comment in `errors.py` shows `obs.emit("error", stage=..., exc=...)`; that argument order is wrong relative to the signature in this plan. Use the signature above as the source of truth, and write the call accordingly.
- Subscriber callback receives the full event dict: `{"stage": <stage or None>, "event": <event>, **kv}`. Pin this dict shape in `tests/test_obs.py` so future changes break loudly.

### ContextVar sibling-isolation (the structlog/asyncio.gather trap)
- `_subscribers: ContextVar[tuple[Callable[[dict], None], ...]] = ContextVar("subscribers", default=())`.
- **Tuple, not list.** Each `subscribe()` does `token = _subscribers.set((*_subscribers.get(), callback))` — copy-on-write. If you use a mutable list and `.append()`, every sibling task in `asyncio.gather` sees every other sibling's appends because they share the list object; ContextVar only isolates rebinds, not in-place mutation. Tests must cover this explicitly.
- `subscribe` should be a context manager. Either `@contextmanager def subscribe(callback)` with try/finally `_subscribers.reset(token)`, or a small class with `__enter__`/`__exit__`. Pick the `@contextmanager` form — it is shorter.
- `current_stage: ContextVar[str | None] = ContextVar("current_stage", default=None)` — module-level export, read by `llm.py`, set/reset by `errors.stage_boundary`.

### structlog config — idempotent
- `_CONFIGURED = False` module-level flag; `_configure_once()` guards `structlog.configure(...)` so importing `obs` twice in tests does not double-stack processors.
- Processors: `structlog.processors.TimeStamper(fmt="iso")`, `structlog.processors.add_log_level`, `structlog.processors.JSONRenderer()`. Logger writes to stdout (default `LoggerFactory`). No file handlers, no rotation — out of scope.

### errors.py extension — order of operations matters
- `__enter__`: `self._stage_token = obs.current_stage.set(self.stage_name); return self`.
- `__exit__`: keep `current_stage` set during `_handle` (so the emitted `error` event sees the right stage in any subscriber that reads `current_stage`), reset after:
  ```
  try:
      handled = self._handle(exc_type, exc)
  finally:
      obs.current_stage.reset(self._stage_token)
  return handled
  ```
- Mirror the same pattern in `__aenter__`/`__aexit__`. The `_handle` body itself does not need to change beyond replacing the `# T02:` line with the `obs.emit(self.stage_name, "error", exc_type=type(exc).__name__, exc_message=str(exc))` call.
- Do not emit on `KeyboardInterrupt`/`SystemExit` paths — current `_handle` already returns False before reaching the emit point, so this falls out for free.

### verify_quote — section parser + tokenization
- Normalize quote and source identically: `re.sub(r"\s+", " ", text.strip().lower())`. **Do not strip punctuation** — it is signal (e.g., "reduced churn by 18%" depends on `%`).
- Word count: `len(normalized_quote.split())`. Splits on whitespace only — punctuation stays attached to its word.
- Hit count: `normalized_source.count(normalized_quote)`. Substring count, not regex; the source is small (a CV) and `str.count` is fine.
- Decision rule (matches PLAN line 127):
  - `n < 6` → `False`.
  - `6 <= n <= 7` → `count == 1`.
  - `n >= 8` → `count >= 1`.
- Section parser: use `re.finditer(r"^##\s+(.+)$", source, flags=re.MULTILINE)` (case-insensitive via lowercasing the lookup key, not the regex flag — `IGNORECASE` would also lowercase the captured header name handling, do it explicitly to avoid surprise). Walk the match iterator once, recording `(name.strip().lower(), match.start())`. Slice the source pairwise: each section's text runs from its header's `match.end()` to the next header's `match.start()` (or `len(source)` for the last). Build `dict[lower_name → section_text]`. If `section.lower().strip()` is not a key → `False`. Otherwise normalize+count against that section's text only.
  - This is one pass and correct on edge cases (header at EOF, header at index 0, source with no headers + `section` requested).

### drop_unverified
- `def drop_unverified[T](items: list[T], source: str, *, anchor_attr: str = "anchor") -> tuple[list[T], int]`.
- For each item: `anchor = getattr(item, anchor_attr)`; call `verify_quote(anchor.quote, source, section=anchor.section)`. Keep on True. Return `(kept, len(items) - len(kept))`.
- No logging here — callers (T07–T13) decide whether to emit a `dropped` counter via `obs.emit`.

### LLMClient — minimal abstraction
- `MODEL_PRICES: dict[str, tuple[float, float]] = {"MiniMax-M1": (1.10, 4.40), "abab6.5s-chat": (0.20, 0.20)}` with the comment `# Pricing as of 2026-05-10 — re-check minimaxi.chat/pricing if cost reports drift.`
- `_PROFILE_MODELS: dict[str, dict[str, str]] = {"local": {"reasoning": "MiniMax-M1", "cheap": "abab6.5s-chat"}, "ci": {"reasoning": "abab6.5s-chat", "cheap": "abab6.5s-chat"}}`.
- `__init__()`:
  - `self._provider = os.environ.get("JOBFIT_LLM_PROVIDER", "minimax")`.
  - `minimax` branch: read `MINIMAX_API_KEY`; raise `RuntimeError("MINIMAX_API_KEY not set — add it to .env or export it")` if missing. Build `openai.AsyncOpenAI(api_key=..., base_url="https://api.minimaxi.chat/v1")`.
  - `anthropic` branch: `try: import anthropic` → on ImportError raise `RuntimeError("JOBFIT_LLM_PROVIDER=anthropic but `anthropic` package not installed — `uv add anthropic`")`. Read `ANTHROPIC_API_KEY` (raise with same shape if missing). Build `anthropic.AsyncAnthropic(api_key=...)`.
  - Unknown provider value → `RuntimeError(f"Unknown JOBFIT_LLM_PROVIDER={self._provider!r}; expected 'minimax' or 'anthropic'")`.
- `_resolve_model(self, logical: Literal["reasoning","cheap"]) -> str`:
  - For `minimax`: read `JOBFIT_MODEL_PROFILE` (default `local`); return `_PROFILE_MODELS[profile][logical]`. Unknown profile → `RuntimeError`.
  - For `anthropic`: return `"claude-sonnet-4-6"` for both logical names (the spike fallback uses Sonnet for everything, per PLAN §L0.5).
- `_estimate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float`:
  - If `model not in MODEL_PRICES`: return `0.0` (Anthropic path; comment says cost only modeled for MiniMax).
  - Else: `(prompt_tokens/1e6)*price[0] + (completion_tokens/1e6)*price[1]`.
- `async complete_json(self, *, system: str, user: str, schema: type[BaseModel], model: Literal["reasoning","cheap"] = "reasoning", temperature: float = 0.0, max_retries: int = 1) -> BaseModel`:
  - Resolve model name once; record `t0 = time.perf_counter()`. Initialize `prompt_tokens = completion_tokens = 0`, `usd_cost = 0.0` before the loop so the `finally` always has values to emit even if the network call raises.
  - Loop `for attempt in range(max_retries + 1):`
    - `current_user = user` on first attempt; on retry, `current_user = user + f"\n\nYour previous output failed validation: {err}\n\nReturn corrected JSON only."`
    - Call provider:
      - MiniMax (OpenAI SDK): `await self._client.chat.completions.create(model=resolved, messages=[{"role":"system","content":system},{"role":"user","content":current_user}], response_format={"type":"json_object"}, temperature=temperature)`.
      - Anthropic: `await self._client.messages.create(model=resolved, system=system + "\n\nReturn JSON only, no prose.", messages=[{"role":"user","content":current_user}], max_tokens=2048, temperature=temperature)`. Anthropic has no native `response_format`; the system-prompt instruction is the workaround. Extract `response.content[0].text`.
    - Reassign `prompt_tokens`/`completion_tokens` from the response (OpenAI: `response.usage.prompt_tokens`/`completion_tokens`; Anthropic: `response.usage.input_tokens`/`output_tokens`).
    - Parse `json.loads(text)`, then `schema.model_validate(parsed)`. On `pydantic.ValidationError as err`, if `attempt < max_retries`: continue loop. Else: re-raise.
    - On success: `return validated` (still inside `try` — the `finally` will run before return).
  - `finally:` compute `usd_cost = self._estimate_cost(resolved, prompt_tokens, completion_tokens)`; `duration_ms = int((time.perf_counter() - t0) * 1000)`; `obs.emit(obs.current_stage.get(), "llm_call", model=resolved, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, usd_cost=usd_cost, duration_ms=duration_ms)`. Telemetry is non-negotiable; runs on success, retry-exhaustion, and network exception alike.
- `async complete_text(self, *, system: str, user: str, model: Literal["reasoning","cheap"] = "cheap", temperature: float = 0.0) -> str`:
  - Same telemetry pattern (`t0`, `finally → emit`); no JSON parsing, no retry. Returns `response.choices[0].message.content` (OpenAI) or `response.content[0].text` (Anthropic).
- Provider abstraction style: **inline `if self._provider == "minimax": ... else: ...`** inside the two methods. With only two providers and ~15 LOC of branch-specific code each, a `_ChatBackend` Protocol with two implementations costs more LOC than it saves and adds an indirection layer for a fallback path that may never be exercised. If the file grows past ~150 LOC, revisit and extract; not before.

## Tests to write

### tests/test_verify.py (`@pytest.mark.fast`)
Module-level `SOURCE` fixture: a multi-section CV-shaped string, e.g.:
```
## Skills
Python, PyTorch, async pipelines, vector databases, distributed systems.

## Experience
Built a recommendation system that reduced churn by 18% over six months.
Led migration from monolith to microservices across three quarters.

## Education
Charles University, MFF UK, MSc in Computer Science, 2018.
```

Pin these assertions:
1. **6-word unique** quote — `"recommendation system that reduced churn by"` (6 words, appears once) → True.
2. **6-word duplicated** quote — construct a `SOURCE_DUP` where the same 6-word phrase appears twice → False.
3. **8-word duplicated** quote — same `SOURCE_DUP` plus an 8-word phrase repeated twice → True.
4. **5-word** quote — any 5-word substring of `SOURCE` → False.
5. **Section mismatch** — quote that exists in `## Skills` searched with `section="experience"` → False.
6. **Section match** — quote that exists in `## Experience` searched with `section="experience"` → True.
7. **Missing section** — `section="references"` (header absent) → False.
8. **Punctuation preserved** — quote `"reduced churn by 18% over six months"` (8 words, contains `%`) → True. Guards against accidental punctuation stripping.
9. **drop_unverified** — define inline `class Item(BaseModel): anchor: Anchor` (import `Anchor` from `jobfit.schemas`); pass a list of 3 items where 1 has a verifiable quote in the right section, 1 fails section-locality, 1 has a 4-word quote → assert `len(kept) == 1` and `dropped == 2`.

### tests/test_obs.py (`@pytest.mark.fast`)
1. **Roundtrip** — `events: list[dict] = []`; `with subscribe(events.append): emit("stage_a", "tick", k=1)`; assert `events == [{"stage": "stage_a", "event": "tick", "k": 1}]`. After the `with` block, emit again; assert `events` length unchanged (subscriber unregistered).
2. **Sibling isolation under `asyncio.gather`** — two `async def` tasks; each opens its own `subscribe(...)` block, emits one event with a task-specific marker, awaits a tiny `asyncio.sleep(0)` to interleave, emits a second event, then exits the `with`. Run them via `asyncio.gather`. Assert each task's callback list contains *only* its own two events. This is the test that proves the tuple-not-list ContextVar pattern.
3. **`current_stage` round-trip** — assert `current_stage.get() is None`; `tok = current_stage.set("x")`; assert `current_stage.get() == "x"`; `current_stage.reset(tok)`; assert `current_stage.get() is None`.
4. **Idempotent configure** — `import jobfit.obs; importlib.reload(jobfit.obs); emit("s", "e")` must not raise. We are not asserting the absence of double-logging directly (hard to capture); the regression we care about is "does not crash on re-import".

### tests/test_errors_obs.py (`@pytest.mark.fast`)
1. **Sync error event** — `events = []; with subscribe(events.append):` then `with stage_boundary("test_stage"): raise RuntimeError("boom")`. Assert exactly one event with `stage="test_stage"`, `event="error"`, `exc_type="RuntimeError"`, `exc_message="boom"`.
2. **Stage attribution during block** — inside `with stage_boundary("test_stage"):` assert `current_stage.get() == "test_stage"`. After the `with` block exits cleanly (no exception), assert `current_stage.get() is None`.
3. **Stage reset on exception** — after a `with stage_boundary("s"): raise RuntimeError(...)`, assert `current_stage.get() is None` (the `finally` in `__exit__` ran).
4. **Async mirror** — `async with stage_boundary("test_stage_async"): raise RuntimeError("async-boom")` produces the same event shape. Captures the `__aenter__`/`__aexit__` path.
5. **Regression** — `from jobfit.errors import StageFailure, stage_boundary` still works; the failure object after a caught exception still has `stage`, `user_message`, `debug_detail` populated as before. (Implicit coverage: `tests/test_schemas.py` must stay 10/10.)

### tests/test_llm.py (`@pytest.mark.live`)
- File-level: `pytestmark = [pytest.mark.live, pytest.mark.skipif(not os.environ.get("MINIMAX_API_KEY"), reason="MINIMAX_API_KEY not set")]`.
- `class Echo(BaseModel): message: str`.
- `async def test_complete_json_roundtrip():`
  - `events: list[dict] = []`
  - `client = LLMClient()`
  - `with subscribe(events.append): echo = await client.complete_json(system="You echo. Return JSON {\"message\": \"...\"}.", user="Echo back the word pong.", schema=Echo, model="cheap")`
  - Assert `"pong" in echo.message.lower()` (lenient — model wording varies).
  - Assert exactly one event with `event == "llm_call"`, `prompt_tokens > 0`, `duration_ms >= 0`, `usd_cost >= 0.0`.
- No retry/error tests live — those would burn tokens to verify branches that are already exercised by unit-level mocking we are explicitly *not* writing in T02 (deferred to whichever stage first hits a flaky model response).

## Verification commands (run inside the worktree)
```bash
uv run pytest -m fast tests/test_verify.py tests/test_obs.py tests/test_errors_obs.py -v
uv run mypy src/jobfit/verify.py src/jobfit/obs.py src/jobfit/llm.py src/jobfit/errors.py
uv run ruff check src/jobfit/verify.py src/jobfit/obs.py src/jobfit/llm.py src/jobfit/errors.py tests/test_verify.py tests/test_obs.py tests/test_errors_obs.py tests/test_llm.py
uv run pytest -m live tests/test_llm.py -v   # skips if MINIMAX_API_KEY absent
uv run pytest -m fast tests/test_schemas.py -v   # regression: must stay 10/10 green
```

All must pass. mypy is `strict` per `pyproject.toml`; ruff selects `E,F,I,UP,B,SIM`. No `# type: ignore` without a one-line reason comment.

## Optional: pyproject.toml — anthropic extras
- Try `uv add --optional anthropic anthropic` (creates `[project.optional-dependencies] anthropic = ["anthropic>=..."]`). If it works cleanly and `uv lock` stays small, keep it; document in Outcome. If it fails, drift, or balloons the lockfile, **skip** and document the skip in `tasks/T02_utils.md`'s Outcome section. The Anthropic path is a fallback we may never exercise; not worth blocking on.

## Out of scope (deferred — do not touch)
- All stage workers L1–L6 (T07–T16).
- CI / pre-commit / GitHub Actions workflows (T03).
- Modifying `src/jobfit/schemas.py` (T01 territory).
- `tests/conftest.py` (no shared fixtures needed for these four modules; defer to whichever later task first needs one).
- Mocking the LLM client (no `respx`/`pytest-httpx` setup); live test or nothing in T02.
- Cost dashboards, log aggregators, OpenTelemetry — `structlog` JSON to stdout is the contract.
- Anthropic cost modeling (return 0.0; revisit if/when the fallback actually ships).
- Retry policies beyond the single ValidationError retry (no `tenacity` wiring here; that is per-stage).

## Definition of done
- All five verification commands pass (live test skips cleanly if no key).
- `tests/test_schemas.py` stays 10/10 green.
- `errors.py` no longer contains the `# T02:` TODO comment.
- `tasks/T02_utils.md` Outcome section filled in with: any MiniMax JSON-mode quirks observed, whether the optional anthropic extras step landed, and any deviations from this plan with one-line rationale.
