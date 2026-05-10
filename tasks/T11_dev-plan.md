# T11 dev plan — L4b salary search + estimator (CZ-localized)

Branch: `feat/block-b-late-stages` (existing worktree, no sub-worktree).
Depends: T02, T05. Mirror T10 (`src/jobfit/score.py`) shape.

## 1. Files to create

- [ ] `src/jobfit/prompts/salary.md` — system prompt for the estimator LLM call.
- [ ] `src/jobfit/salary.py` — `build_queries`, `search`, `estimate_salary`.
- [ ] `tests/test_salary.py` — 3 fast tests + 1 live slow test.

No edits to upstream modules (`schemas.py`, `llm.py`, `errors.py`, `obs.py`, `verify.py`).

## 2. Prompt design — `prompts/salary.md`

Sections:

- **Role**: salary-range estimator for the JobFit pipeline. Default audience is CZ data/DS/ML.
- **Input**: a JSON array of `{title, snippet, url, domain}` search results plus the candidate context block (role, location, years).
- **Output schema**: a single JSON object matching `SalaryEstimate`:
  - `low: int`, `high: int` — integers, `low < high`, no thousand separators.
  - `currency`: `CZK` for CZ profiles (default), `EUR` for non-CZ Europe, otherwise `USD`. State the rule in the prompt.
  - `period`: `"month"` for `CZK`, `"year"` for `EUR`/`USD`.
  - `sources`: subset of input results actually used. Each entry must use the **input URL verbatim**; `snippet` may be trimmed to the cited fragment but never invented.
  - `reasoning`: 2–4 sentences citing which sources drove the low/high bounds.
- **Hard rules** (numbered, the model will see these):
  1. Every `sources[i].url` MUST appear verbatim in the input. No new URLs, no rewrites.
  2. If fewer than 2 sources support a defensible range, output the tightest defensible range and lower confidence in `reasoning`. Do not fabricate.
  3. Snippets must be substrings of the corresponding input snippet. If trimming, keep contiguous text only.
  4. Numbers are gross monthly (CZK) or gross annual (EUR/USD). State the basis in `reasoning`.
  5. Never include the candidate's name, employer, or PII.
- **Currency / period defaulting** (in prompt + restated in user message):
  - profile.detected_location contains "Czech", "CZ", "Praha", "Brno", "Ostrava", or is null/unknown → CZK / month.
  - non-CZ European city → EUR / year.
  - everything else → USD / year.
- **Examples**: one tiny shaped example (3 inputs, 2 sources used) showing the URL-verbatim discipline. Keep under ~20 lines to control token cost.

## 3. Module structure — `src/jobfit/salary.py`

### Imports

```python
from __future__ import annotations
import json
from pathlib import Path
from urllib.parse import urlparse

from ddgs import DDGS
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from jobfit.errors import StageFailure, stage_boundary
from jobfit.llm import LLMClient
from jobfit.obs import emit
from jobfit.schemas import Profile, SalaryEstimate, Source
```

`_PROMPT_PATH` / `_SYSTEM_PROMPT` loaded at module import, mirroring `score.py`.

### `build_queries(profile: Profile) -> list[str]`

- [ ] Extract `role = profile.detected_role.strip()`; fallback "data scientist" only if blank.
- [ ] Extract `city` from `profile.detected_location`; if None or matches CZ markers ("Czech", "CZ", "Praha", "Prague", "Brno", "Ostrava") treat as CZ; else non-CZ.
- [ ] CZ branch (default):
  - `f"{role} salary {city or 'Praha'} site:platy.cz OR site:profesia.cz"`
  - `f"{role} mzda CZK 2025"`
  - third optional: `f"{role} salary czech republic site:glassdoor.com"`
- [ ] Non-CZ branch (EUR-territory): substitute platy/profesia with `glassdoor.com` / `levels.fyi`, currency token `EUR`. Keep 2 base queries.
- [ ] If `profile.detected_years_experience >= 10`, append one EUR cross-check query: `f"senior {role} salary EUR Europe"`.
- [ ] Cap returned list at 3 entries. Order matters: locality-first, broader second.
- [ ] Pure function, no I/O — easy to unit test.

### `search(queries: list[str]) -> list[Source]` (async)

- [ ] Inner helper `_ddg_text(query: str) -> list[dict]` decorated with `@retry(stop=stop_after_attempt(2), wait=wait_exponential_jitter(initial=1, max=3), reraise=True)`. Body:
  ```python
  with DDGS() as ddg:
      return list(ddg.text(query, max_results=8))
  ```
  `DDGS().text` is sync; `search` runs it via `asyncio.to_thread(_ddg_text, q)` to avoid blocking the loop.
- [ ] Iterate queries, gather raw results. Per-query failure is a hard fail — no swallowing, no per-query try/except. Tenacity handles the one retry.
- [ ] Dedupe by canonicalized URL (`urlparse(url).geturl()`), preserve first-seen order, slice top 8.
- [ ] Map each surviving result to `Source(url=..., snippet=body, domain=urlparse(url).netloc)`. Pydantic `HttpUrl` will reject malformed URLs — drop those silently and count them.
- [ ] Emit `salary_search` with `n_queries`, `raw_results`, `dedup_results`, `dropped_invalid_url`.
- [ ] If final `len(sources) < 2`, raise `RuntimeError("Insufficient market data for this profile.")`. The boundary in `estimate_salary` converts to `StageFailure(stage="salary", user_message=...)`. See §5 for the rationale.

### `estimate_salary(profile: Profile) -> SalaryEstimate | StageFailure` (async)

```python
async def estimate_salary(profile: Profile) -> SalaryEstimate | StageFailure:
    async with stage_boundary("salary") as cm:
        queries = build_queries(profile)
        sources = await search(queries)

        client = LLMClient()
        user_payload = json.dumps({
            "context": {
                "role": profile.detected_role,
                "location": profile.detected_location,
                "years": profile.detected_years_experience,
            },
            "results": [s.model_dump(mode="json") for s in sources],
        })
        estimate = await client.complete_json(
            system=_SYSTEM_PROMPT,
            user=user_payload,
            schema=SalaryEstimate,
            model="reasoning",
            temperature=0.0,
        )
        assert isinstance(estimate, SalaryEstimate)

        input_urls = {str(s.url) for s in sources}
        kept = [s for s in estimate.sources if str(s.url) in input_urls]
        dropped = len(estimate.sources) - len(kept)
        if dropped:
            emit("salary", "salary_sources_dropped", dropped=dropped, reason="url_not_in_inputs")
        if not kept:
            return StageFailure(
                stage="salary",
                user_message="Salary estimate produced no verifiable sources.",
                debug_detail=f"model_urls={[str(s.url) for s in estimate.sources]}",
            )
        if estimate.currency not in {"CZK", "EUR", "USD"}:
            return StageFailure(
                stage="salary",
                user_message="Salary estimate returned an unsupported currency.",
                debug_detail=f"currency={estimate.currency!r}",
            )

        verified = estimate.model_copy(update={"sources": kept})
        emit(
            "salary",
            "salary_estimate",
            low=verified.low,
            high=verified.high,
            currency=verified.currency,
            period=verified.period,
            n_sources=len(verified.sources),
        )
        return verified

    return cm.failure  # type: ignore[return-value]
```

- `low < high` is enforced by `SalaryEstimate._require_ordered_range` — no extra check needed.
- URL-subset check is the only post-hoc validation we own.
- Return path mirrors `score.py`: `StageFailure` returned from inside the boundary on logical failures; raised exceptions (e.g. DDG error, insufficient data, LLM JSON failure after retry) are converted by the boundary.

### Telemetry events emitted

- `salary_search` (in `search`): `n_queries`, `raw_results`, `dedup_results`, `dropped_invalid_url`.
- `salary_sources_dropped` (in estimator): `dropped`, `reason`.
- `salary_estimate` (success path): `low`, `high`, `currency`, `period`, `n_sources`.
- `error` (auto-emitted by `stage_boundary`) on any raise.
- `llm_call` is auto-emitted by `LLMClient.complete_json`.

## 4. Test design — `tests/test_salary.py`

Use `pytest.mark.fast` / `pytest.mark.live`, `pytest.mark.slow` per project conventions. Patch via `monkeypatch.setattr("jobfit.salary.DDGS", ...)`.

- [ ] **fast: build_queries CZ-locality** — construct a CZ `Profile` (location "Praha"); assert at least one query string contains `"platy.cz"` or `"profesia.cz"`; assert ≤3 queries returned.
- [ ] **fast: empty DDG → StageFailure** — `DDGS().text` returns `[]`. `await estimate_salary(profile)` returns `StageFailure(stage="salary", user_message="Insufficient market data for this profile.")`. Assert `cm.failure` shape via the returned object.
- [ ] **fast: DDG raising → ≤2 attempts then StageFailure** — `text` is a `Mock(side_effect=RuntimeError("rate limit"))`. After awaiting `estimate_salary`, assert `mock.call_count == 2` (one attempt + one retry per tenacity config) **for the first query only** (subsequent queries are not attempted because the first raise propagates after retry exhaustion). Assert returned `StageFailure.stage == "salary"` and `"rate limit"` appears in `debug_detail`.
- [ ] **live, slow: senior fixture end-to-end** — load senior fixture profile from `tests/fixtures/profiles/senior.json` (or whichever T09 produces); skipif `MINIMAX_API_KEY` not set; assert returned `SalaryEstimate`, `len(sources) >= 1`, all `source.url` ∈ DDG response set, `low < high`, `currency == "CZK"`, `period == "month"`.

### Mock strategy details

- Patch `jobfit.salary.DDGS` (the imported symbol) with a `MagicMock` whose context-manager protocol returns an object with `.text(...)` configured as a `Mock`. Pattern:
  ```python
  fake = MagicMock()
  fake.__enter__.return_value.text.return_value = []  # or side_effect=...
  monkeypatch.setattr("jobfit.salary.DDGS", lambda: fake)
  ```
- For the LLM, the empty-results test never reaches the LLM (search raises first), so no `LLMClient` mock needed.
- For the raising-DDG test, ditto.
- No fast test exercises the LLM path — covered by the live test. Adding a mocked-LLM test is optional polish, skip for time.

## 5. Decisions / trade-offs

- **`StageFailure` is a Pydantic model, not an Exception.** The contract in `tasks/T11_salary.md` says `search` should `raise StageFailure(...)` — that's not legal. We adopt the T10 split:
  - `search` is a helper; on insufficient data it raises plain `RuntimeError("Insufficient market data for this profile.")`.
  - `estimate_salary` runs inside `async with stage_boundary("salary")` which catches the `RuntimeError` and produces `StageFailure(stage="salary", user_message=str(exc), debug_detail=repr(exc))`.
  - This matches `score.py`'s pattern: stage boundary converts unexpected exceptions; `StageFailure` is `return`ed directly only for logical, anticipated branches (e.g., URL-subset check empty, unsupported currency).
- **Why per-call retry, not per-orchestrator.** Per task contract: DDG rate-limit on shared egress IPs won't recover on a multi-second wait. Two attempts per query is a courtesy; we don't retry the whole pipeline.
- **`asyncio.to_thread` wrapping `DDGS().text`.** `ddgs` is sync. Without offloading, we block the event loop for ~1–3s per query. Cheap insurance.
- **No filesystem cache for DDG results.** PRD §7 wants reviewer-runnable in <60s; cache adds invalidation logic with no payoff for a single-shot run.
- **Snippet trimming responsibility.** The model trims; we don't. We only verify URL membership. Trimmed snippets still being substrings of inputs is *guidance* in the prompt, not enforced — enforcing it adds fragile string ops for low marginal value.
- **No retry on the LLM call.** `complete_json` already retries once on validation failure (`max_retries=1` default). Stage failure on second miss is acceptable; full report still renders.

## 6. Verification commands

- [ ] `cd /home/mf/GitHub/probable-goose-machine/.worktrees/block-b && uv run ruff format --check src/jobfit/salary.py src/jobfit/prompts/salary.md tests/test_salary.py`
- [ ] `cd /home/mf/GitHub/probable-goose-machine/.worktrees/block-b && uv run ruff check src/jobfit/salary.py tests/test_salary.py`
- [ ] `cd /home/mf/GitHub/probable-goose-machine/.worktrees/block-b && uv run mypy src/jobfit/salary.py`
- [ ] `cd /home/mf/GitHub/probable-goose-machine/.worktrees/block-b && uv run pre-commit run --all-files`
- [ ] `cd /home/mf/GitHub/probable-goose-machine/.worktrees/block-b && uv run pytest -q -m fast tests/test_salary.py`
- [ ] (optional, gated on `MINIMAX_API_KEY` and network) `uv run pytest -q -m "live and slow" tests/test_salary.py`

## 7. Risks & open questions

- **DDG rate limit on shared HF egress.** Two-attempt retry is a token effort; expected failure mode is a clean `StageFailure` with the user-visible message. Acceptable per PRD §4.6.
- **`HttpUrl` vs `str` coercion.** `Source.url` is `HttpUrl`; comparisons must use `str(source.url)`. Tests must compare consistently or `in input_urls` will silently miss matches.
- **Model URL drift.** Models routinely paraphrase URLs (trailing slash, http→https, query strip). The strict verbatim-match drops those. Mitigation: prompt's hard rule #1; downstream telemetry counts `salary_sources_dropped` so drift is observable. Do **not** add fuzzy URL matching this round — adds attack surface for hallucinated domains.
- **`profile.detected_role` cleanliness.** T09 controls this; if it returns "Senior Data Scientist / ML Engineer" with slashes, queries still work but DDG quality degrades. Out of scope here; flag in dev report if observed.
- **`ddgs` package name.** Project task contract says `from ddgs import DDGS`. Confirm during implementation that the dependency is already in `pyproject.toml`. If not present, **stop and ask** — per lesson `feedback_no_unprompted_deps`, do not add deps unprompted.
- **Live test fixture path.** Senior profile fixture path depends on T09 output; resolve at implementation time (`rg "fixtures/profiles" tests/`). Defer if T09 fixture not yet present and mark the live test xfail with reason.
