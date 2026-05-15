# T46 — Salary stage: country-agnostic, live-search-first

Status: pending
Owner: ai-ml-engineer
Depends on: none (touches salary stage + extraction prompt + Profile schema)
Unblocks: usable salary output for non-CZ CVs (DE / JP / US / GB / …)
Estimate: ~90 min

## Goal

Remove the CZ-only assumptions baked into the salary stage so that German,
Japanese, US, and any other-market CV produces a salary range in the correct
local currency from live web search — without us maintaining per-country
domain tables, currency whitelists, or `site:` filters. CZ stays as the one
curated baseline because we know the boards (`platy.cz`, `profesia.cz`);
everywhere else delegates to live search.

## Findings

`src/gander/salary.py` is structurally CZ-biased:

- `_CZ_TOKEN_PATTERN` + `_is_cz_location` collapse the world into CZ vs.
  not-CZ; missing location defaults to CZ.
- The non-CZ branch in `build_queries` hard-codes `site:glassdoor.com OR
  site:levels.fyi` and an `EUR 2025` cross-check — actively misleading for
  US (USD), JP (JPY), GB (GBP), CH (CHF), etc.
- City defaults to `"Europe"` when `detected_location` is missing —
  meaningless for Tokyo or San Francisco.
- `_SALARY_DOMAIN_PRIORITY` only ranks `platy.cz, profesia.cz, glassdoor,
  levels.fyi`; for DE/JP/US the ranker effectively becomes "Glassdoor
  first, ties otherwise."
- Currency whitelist is `{CZK, EUR, USD}`; period invariant is hard-coded
  CZK→month / EUR-USD→year. JPY, GBP, CHF, PLN, HUF, … are rejected.
- Sanity caps fire only for CZK.

We do live search precisely so we don't have to maintain per-country domain
tables. The fix is to push country + currency context into the queries and
the salary prompt, and stop *rejecting* non-{CZK,EUR,USD} outputs.

## Implementation

- `src/gander/schemas.py`: add `detected_country: str | None` to `Profile`,
  validated as 2-uppercase-letter ISO-3166 alpha-2 or null.
- `src/gander/prompts/extract.md`: request `detected_country` alongside
  `detected_location` — inferred from address, phone country code, or
  work-history geography; null if unclear.
- `src/gander/salary.py`:
  - Add `country_to_currency(country)` and `currency_to_period(currency)`
    flat-table helpers (~40 markets each). Unknown country → `USD`.
  - Reshape `build_queries`: CZ branch unchanged. Non-CZ becomes
    country-aware (`f"{role} salary {city} {country_name} {currency} {year}"`),
    no `site:` lock-in, no `EUR 2025` hardcode, city defaults to country
    name (never `"Europe"`).
  - Scope `_SALARY_DOMAIN_PRIORITY` application to CZ only. Non-CZ
    profiles preserve search-engine order.
  - Replace the `{CZK, EUR, USD}` currency whitelist with an ISO-4217
    shape check (`re.fullmatch(r"[A-Z]{3}", currency)`).
  - Replace the hard CZK→month / non-CZK→year invariant with a per-currency
    period hint; on mismatch, emit a `salary.period_mismatch` warning event
    but accept the LLM's choice.
  - Sanity cap stays CZK-only (per-currency caps are a future task driven
    by observed telemetry).
  - Extend the `salary.salary_search` event with `country`,
    `currency_hint`, and `sources_per_tld`.
- `src/gander/prompts/salary.md`: replace CZK/EUR/USD-only framing with
  "emit the local currency as it appears in the snippets (ISO 4217). Period
  defaults monthly for `CZK/PLN/HUF/RON/BGN`, annual otherwise; the
  snippets win." Inject `country`, `currency_hint`, `period_hint` into the
  prompt context.
- `tests/test_salary.py`:
  - Parametrize `build_queries` over `("CZ", "DE", "JP", "US", "GB")`.
  - Add an ISO-4217 shape validator test (`JPY` accepted, `XYZ` rejected,
    `EURO` rejected).
  - Keep existing CZ tests green unchanged.
- `tests/fixtures/cvs/` (modify existing, do NOT add new files):
  - `04_mle_kralova.txt` → relocate to **Berlin, Germany** (address,
    phone `+49`).
  - `05_mlops_benes.txt` → relocate to **Tokyo, Japan** (address, phone
    `+81`). The plan originally listed `08_staff_ml_engineer_dvorak`, but
    that fixture is the senior acceptance anchor (used by
    `tests/test_acceptance.py`, `tests/test_score.py`,
    `scripts/spike_minimax.py`, and `tests/test_salary.py`'s live test) and
    its relocation would break the cross-CV salary/score ordering
    invariants in PRD §5.4. `05_mlops_benes` is the cleanest non-critical
    swap: it's MLOps at a travel company (Kiwi.com, international by
    nature), and the smoke test that consumes it
    (`tests/test_pipeline_smoke.py::test_pipeline_smoke_end_to_end_mid_fixture`)
    doesn't assert a specific currency.
  - `02_da_svoboda.txt` → relocate to **San Francisco, US** (address,
    phone `+1`).
- `tests/fixtures/cvs/SOURCES.md`: annotate the three relocations.
- The `.pdf` / `.docx` siblings of the relocated fixtures stay as-is for
  this task (live-pipeline tests that consume binaries can be revisited
  per telemetry).

## Contract / binary acceptance

- CZ behavior unchanged on all existing fixtures and tests.
- `Profile` carries `detected_country: str | None`, populated by
  extraction; falls back to `_is_cz_location → "CZ"` when null.
- `build_queries` for a synthetic `DE` / `JP` / `US` profile emits queries
  containing the country name and the local currency token
  (`EUR` / `JPY` / `USD`), with no `site:glassdoor.com OR site:levels.fyi`
  lock and no `EUR 2025` hardcode.
- `estimate_salary` accepts any ISO-4217-shaped currency from the LLM; the
  `{CZK, EUR, USD}` whitelist is gone.
- `_SALARY_DOMAIN_PRIORITY` applies only when the resolved country is CZ.
- Telemetry: `salary.salary_search` includes `country`, `currency_hint`,
  `sources_per_tld`.
- Parametrized test in `tests/test_salary.py` covers
  `CZ`/`DE`/`JP`/`US`/`GB` query shapes; existing CZ tests stay green.

## Out of scope

- Per-country sanity caps (CZK cap stays; revisit per telemetry).
- Per-country domain priority curation (the live-search-first design
  explicitly avoids this; revisit only if telemetry shows live search
  consistently misses local boards for a specific country).
- Translating queries to local languages (e.g. `Gehalt` for DE,
  `給料` for JP) — defer unless empirical English-query results
  underperform.
- Regenerating `.pdf` / `.docx` binaries for the relocated fixtures.

## Verification

- `uv run pytest tests/test_salary.py` — full suite green, including the
  new parametrized country cases.
- `uv run pytest tests/test_salary.py -m live` — CZ live test
  (`OPENROUTER_API_KEY` present, `GANDER_LLM_PROVIDER=openrouter`)
  unchanged.
- `rg "EUR 2025|site:glassdoor.com OR site:levels.fyi|location else \"Europe\"" src/gander/`
  returns nothing.
- Synthetic smoke: hand-build a `Profile(detected_country="DE",
  detected_location="Berlin", …)`, pass to `estimate_salary` with mocked
  DDG returns including a `.de` source, assert currency `EUR` and at least
  one source. Repeat for `JP`/`Tokyo`/`JPY` and `US`/`San Francisco`/`USD`.
