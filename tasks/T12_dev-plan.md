# T12 — L4c confidence judge (dev plan)

Owner: ai-ml-engineer · Depends on: T02, T05 · Unblocks: T15, T19 · Estimate: ~45 min

Recompute-then-compare confidence judge. Step A derives the tier from sources only;
Step B writes prose. Step A always wins; Step B is decoration.

## 1. Files to create

- [ ] `src/jobfit/prompts/confidence_step_a.md` — Step A system prompt (sources -> tier JSON).
- [ ] `src/jobfit/prompts/confidence_step_b.md` — Step B system prompt (tier + range -> paragraph).
- [ ] `src/jobfit/confidence.py` — `judge(...)` coroutine, stage="confidence".
- [ ] `tests/test_confidence_unit.py` — `@pytest.mark.fast`, three tests (see §5).

No edits to upstream modules (`schemas.py`, `llm.py`, `errors.py`, `obs.py`).

## 2. Step A prompt (`confidence_step_a.md`)

Inputs the model sees: only `[Source]` JSON (url + snippet + domain). No range, no currency, no period.

Rubric, stated verbatim in the prompt:

- High = >=3 **independent** sources whose stated ranges agree within +/- 25%.
- Medium = exactly 2 sources, OR >=3 sources with wider but overlapping agreement.
- Low = <2 sources, OR disagreement >50% across what is provided.

Hard rules (top of prompt, before rubric):

- [ ] "Independent" = distinct `domain` values. Two snippets from the same domain count as one source.
- [ ] Never emit a number. Never quote a salary figure. Tier is derived from `len(distinct_domains)` and snippet-text agreement only.
- [ ] You will not be shown the produced salary range. Do not invent one.
- [ ] Output JSON with exactly two keys: `tier` (one of `"Low"`, `"Medium"`, `"High"`) and `rationale_short` (<= 30 words, internal-discipline only).

Output contract example block at the bottom of the prompt:

```json
{"tier": "Medium", "rationale_short": "two distinct domains, ranges overlap"}
```

## 3. Step B prompt (`confidence_step_b.md`)

Inputs: a single user line of the form `Step A tier: <T>\nProduced range: <low>-<high> <currency>/<period>`.

Output: one paragraph, 3-6 sentences, plain prose. No JSON, no bullets, no headings.

Style guidance written into prompt:

- [ ] First sentence names the tier explicitly (e.g. "Confidence in this estimate is Low.").
- [ ] Reference the produced range at least once.
- [ ] If tier is Low, prefer phrasing that includes "insufficient" or sources "disagree". (Hard enforcement happens in code.)
- [ ] Step A's tier is final. Step B may explain, never argue or override.

## 4. `src/jobfit/confidence.py` structure

Mirror `salary.py` (async stage worker, async `stage_boundary`).

Imports:

- [ ] `from __future__ import annotations`
- [ ] stdlib: `re`, `json`, `pathlib.Path`, `typing.Literal`
- [ ] third-party: `pydantic.BaseModel`
- [ ] internal: `jobfit.errors.{StageFailure, stage_boundary}`, `jobfit.llm.LLMClient`, `jobfit.obs.emit`, `jobfit.schemas.{Confidence, Source}`

Module constants:

- [ ] `_STEP_A_PROMPT = (Path(__file__).parent / "prompts" / "confidence_step_a.md").read_text(...)`
- [ ] `_STEP_B_PROMPT = (Path(__file__).parent / "prompts" / "confidence_step_b.md").read_text(...)`
- [ ] `_RATIONALE_LOW_REGEX = re.compile(r"insufficient|disagree", re.I)` — module-level so tests can `from jobfit.confidence import _RATIONALE_LOW_REGEX` if useful.

Schema:

```python
class _TierOnly(BaseModel):
    tier: Literal["Low", "Medium", "High"]
    rationale_short: str
```

Signature (deliberate divergence — see §6):

```python
async def judge(
    sources: list[Source],
    low: int,
    high: int,
    currency: str,
    period: Literal["month", "year"],
) -> Confidence | StageFailure:
```

Body:

- [ ] `async with stage_boundary("confidence") as cm:`
- [ ] `client = LLMClient()`
- [ ] **Step A user payload**: `step_a_user = json.dumps([s.model_dump(mode="json") for s in sources])` — by construction, `low`/`high`/`currency`/`period` are NOT interpolated. The local vars exist in scope but never reach this string. This is the load-bearing isolation guarantee.
- [ ] `tier_obj = await client.complete_json(system=_STEP_A_PROMPT, user=step_a_user, schema=_TierOnly, model="cheap", temperature=0.0)`
- [ ] `assert isinstance(tier_obj, _TierOnly)`
- [ ] `emit("confidence", "confidence_step_a", tier=tier_obj.tier, n_sources=len(sources))`
- [ ] **Step B user payload**: `step_b_user = f"Step A tier: {tier_obj.tier}\nProduced range: {low}-{high} {currency}/{period}"`
- [ ] `rationale = await client.complete_text(system=_STEP_B_PROMPT, user=step_b_user, model="cheap", temperature=0.0)`
- [ ] `regenerated = False`
- [ ] If `tier_obj.tier == "Low" and not _RATIONALE_LOW_REGEX.search(rationale)`: call `complete_text` once more with the same args; assign result to `rationale`; set `regenerated = True`. No further retries — if the second attempt also misses the lexicon, ship as-is (the tier is already correct; prose is decoration).
- [ ] `emit("confidence", "confidence_step_b", regenerated=regenerated, rationale_len=len(rationale))`
- [ ] `emit("confidence", "confidence_decision", tier=tier_obj.tier, rationale_len=len(rationale))`
- [ ] `return Confidence(tier=tier_obj.tier, rationale=rationale)` — note `tier_obj.tier`, never derived from Step B.
- [ ] Outside the `async with`: `return cm.failure  # type: ignore[return-value]`

## 5. Tests (`tests/test_confidence_unit.py`)

All `@pytest.mark.fast`. Use `pytest-asyncio` per repo convention (mirror `tests/test_salary_unit.py`). Set `monkeypatch.setenv("MINIMAX_API_KEY", "test-stub")` in each test so `LLMClient.__init__` succeeds.

Fixture: two synthetic `Source` objects with `HttpUrl` strings and short snippets that contain NO digits (so the digit-avoidance assertion in Test 2 is meaningful).

- [ ] **Test 1 — structural isolation (signature):**
  - `from jobfit.confidence import judge; import inspect`
  - `sig = inspect.signature(judge)`
  - `assert set(sig.parameters.keys()) == {"sources", "low", "high", "currency", "period"}`
  - Assert each parameter annotation matches the contract (`sources: list[Source]`, `low: int`, `high: int`, `currency: str`, `period: Literal["month","year"]`).
  - Comment in the test explains: any future param like `produced_range`, `profile`, or `estimate` MUST break this assertion. That is the leak-channel firewall.

- [ ] **Test 2 — Step A input contains no range data:**
  - Mock `jobfit.confidence.LLMClient.complete_json` (capture `user` kwarg) to return `_TierOnly(tier="Medium", rationale_short="ok")`.
  - Mock `complete_text` to return `"Confidence in this estimate is Medium. Range 70000-120000 USD/year ..."`.
  - Call `await judge(sources=[s1, s2], low=70000, high=120000, currency="USD", period="year")` with snippets that do NOT contain the strings `"70000"` or `"120000"`.
  - Assert `"70000" not in captured_step_a_user` and `"120000" not in captured_step_a_user`.
  - Assert `"USD" not in captured_step_a_user` and `"year" not in captured_step_a_user`. (Both must be true given construction; this is the regression guard.)

- [ ] **Test 3 — Step B cannot override Step A + regeneration on Low:**
  - Mock `complete_json` -> `_TierOnly(tier="Low", rationale_short="single domain")`.
  - Mock `complete_text` to always return `"High confidence pending market check."` (no `insufficient`/`disagree`).
  - `result = await judge(...)`
  - Assert `result.tier == "Low"` (Step A wins).
  - Assert `complete_text.call_count == 2` (regeneration was triggered; ships as-is on second miss).
  - Assert `result.rationale` equals the mocked string.

## 6. Decisions / trade-offs

- **Signature widening to `Confidence | StageFailure`** — deliberate divergence from `T12_confidence.md` which says `-> Confidence`. Rationale: parity with `score_profile` and `estimate_salary` (T10/T11). The structural-isolation test asserts on input parameter keys only, so it still passes. Document at top of `confidence.py` docstring.
- **Model resolution** — `T12_confidence.md` mentions `abab6.5s-chat`. `PLAN.md` §L4c and post-T05 reality use `MiniMax-M2.7-highspeed` for both `local` and `ci` via `_PROFILE_MODELS["<profile>"]["cheap"]` in `src/jobfit/llm.py`. We pass `model="cheap"` (logical) and let resolution land on `MiniMax-M2.7-highspeed`. No code change needed; the literal `"cheap"` is correct.
- **Regeneration budget** — one retry only when tier == Low AND rationale lacks `insufficient`/`disagree`. If retry also misses the lexicon, ship as-is. The tier is the correctness gate; the prose is decoration.
- **`rationale_short` is captured but unused.** It exists as a model-discipline mechanism — forcing Step A to articulate before committing. Not surfaced to the user. Keep it in the schema; do not log it.
- **Step A leak channel is closed by construction**, not by validation. The function body never interpolates `low`/`high`/`currency`/`period` into Step A's user message. Test 2 is the regression guard.
- **No Medium/High lexicon check.** `_RATIONALE_LOW_REGEX` only fires when tier == Low. A Medium rationale that happens to say "insufficient" is fine — there is no regeneration in that branch.

## 7. Verification commands

```bash
cd /home/mf/GitHub/probable-goose-machine/.worktrees/block-b && uv run ruff format src/jobfit/confidence.py tests/test_confidence_unit.py
cd /home/mf/GitHub/probable-goose-machine/.worktrees/block-b && uv run ruff check src/jobfit/confidence.py tests/test_confidence_unit.py
cd /home/mf/GitHub/probable-goose-machine/.worktrees/block-b && uv run mypy src/jobfit/confidence.py
cd /home/mf/GitHub/probable-goose-machine/.worktrees/block-b && uv run pre-commit run --all-files
cd /home/mf/GitHub/probable-goose-machine/.worktrees/block-b && uv run pytest -q -m fast tests/test_confidence_unit.py
```

All five must pass before marking T12 done.

## 8. Risks & open questions

- [ ] **Leak-channel regressions.** Any future refactor that adds `produced_range`, `profile`, or `estimate` to `judge`'s signature breaks the recompute-then-compare contract. Test 1 catches this.
- [ ] **`_RATIONALE_LOW_REGEX` substring matches.** `"insufficient"` and `"disagree"` are substrings — they will also match `"insufficiency"`, `"disagreement"`, `"disagreed"`. That is fine; we want lexical-family hits, not exact word matches. No `\b` boundaries needed.
- [ ] **One-shot regeneration is intentionally cheap.** If Step B is repeatedly unable to use the required lexicon under Low, the right next step is a prompt revision, not a retry-loop. Keep the loop at one.
- [ ] **Step A's `model="cheap"` cost** — same MiniMax-M2.7-highspeed model as reasoning paths in current profile config. Re-check when T05 cost data lands; if a true cheap tier is added, change `model="cheap"` is a no-op (logical name unchanged).
- [ ] **Sources truncation.** No code-level truncation here; we hand all sources to Step A. If salary returns >8 sources, Step A's prompt budget is the only limit. Acceptable given current `search()` caps at 8.
- [ ] **No prompt eval set in T12 scope.** Acceptance criteria are structural (signature, no-leak) and behavioural (Step A wins, Low regenerates). Semantic eval lives in T19.
