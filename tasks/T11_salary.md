# T11 — L4b salary search + estimator (CZ-localized)

Status: todo
Owner: ai-ml-engineer
Depends on: T02, T05 (gate)
Unblocks: T15
Estimate: ~75 min

## Goal

Estimate a market-grounded salary range for the candidate, defaulting to CZK monthly gross given the corpus is CZ data/DS/ML. Sources are real, cited URLs from DuckDuckGo. Fail fast and gracefully if data is sparse.

## Deliverables

- [ ] `src/jobfit/prompts/salary.md` — system prompt:
  - Receives a list of `{title, snippet, url}` search results.
  - Outputs JSON matching `SalaryEstimate`: `low`, `high` (both integers), `currency` (CZK by default for CZ profiles, EUR if profile.detected_location is non-CZ Europe), `period` ("month" for CZK, "year" for EUR), `sources` (subset of inputs the model actually used, with `snippet` trimmed to the cited fragment), `reasoning`.
  - Hard rule: every entry in `sources` must be one of the input URLs verbatim.
- [ ] `src/jobfit/salary.py`:
  - `def build_queries(profile: Profile) -> list[str]`:
    - CZ-local queries first: `f"{role} salary {city} site:platy.cz OR site:profesia.cz"`, `f"{role} mzda CZK 2025"`, `f"{role} salary czech republic site:glassdoor.com"`.
    - For senior profiles (years ≥ 10), add an EUR cross-check query.
    - Returns 2–3 queries.
  - `async def search(queries: list[str]) -> list[Source]`:
    - For each query, call `ddgs.DDGS().text(query, max_results=8)`.
    - Wrap each call in `tenacity.retry(stop=stop_after_attempt(2), wait=wait_exponential_jitter(initial=1, max=3))`. Fail fast — DDG rate-limit on shared HF egress IP won't recover in retry.
    - Combine across queries, dedupe by URL, keep top 8.
    - Each result → `Source(url=..., snippet=..., domain=urlparse(url).netloc)`.
    - If total < 2 results: raise `StageFailure("Insufficient market data for this profile.", stage="salary")`.
  - `async def estimate_salary(profile: Profile) -> SalaryEstimate`:
    - `sources = await search(build_queries(profile))`
    - Calls `llm.complete_json(prompt="salary.md", user=json.dumps(sources), schema=SalaryEstimate, model="reasoning")`.
    - Validates: `low < high`, `currency in {"CZK","EUR","USD"}`, every `source.url` in the input set.
    - Wrapped in `stage_boundary("salary")`.
- [ ] `tests/test_salary.py`:
  - `@pytest.mark.fast`: `build_queries` for a CZ profile contains "platy.cz" or "profesia.cz".
  - `@pytest.mark.fast`: mocked DDG returning 0 results → `StageFailure` propagates with the right message.
  - `@pytest.mark.fast`: mocked DDG raising → fail-fast (≤ 2 attempts), then `StageFailure`.
  - `@pytest.mark.live, slow`: end-to-end against the mid + senior fixtures; assert sources have URLs, low<high, currency=CZK.

## Verification

```bash
uv run pytest -m fast tests/test_salary.py -v
uv run pytest -m live tests/test_salary.py -v
```

## Reference

- tasks/PLAN.md — § "L4b — Salary Search + Estimate"
- PRD.md §4.3, §4.6

## Outcome

(fill in when done — DDG rate-limit observations, query phrasing iterations)
