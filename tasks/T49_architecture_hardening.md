# T49 - Architecture hardening from code-review audit

Status: done
Owner: software-engineer
Depends on: T41, T42, T45, T46, T48
Unblocks: safer arbitrary-CV operation, current salary evidence, clearer privacy and observability contracts
Estimate: ~1 day

## Problem

The 2026-05-25 architecture/code-review audit found that the staged pipeline
is generally well-shaped, but several production-facing boundaries are still
too loose:

- salary geography falls back to CZ when country and location are both missing;
- salary search queries hard-code year `2025`, which is stale after 2025;
- PDF vision ingest renders and transcribes every page without a hard page,
  pixel, memory, or spend budget;
- PDF ingest sends unredacted rendered pages to OpenRouter vision before local
  regex redaction, while product copy can be read as "redaction before all
  provider upload";
- text/JSON LLM calls and DDGS salary search have no explicit stage timeout;
- the report footer's "Total latency" is provider-call duration, not pipeline
  wall-clock latency;
- local verification is brittle when Git LFS fixtures are unresolved.

## Plan

### A - Salary geography policy

- Change `_is_cz_location(None)` semantics so unknown geography does not become
  CZ by default.
- Make `_resolve_country(profile)` explicit:
  - supported `detected_country` wins;
  - recognizable CZ `detected_location` maps to `CZ`;
  - otherwise return `XX` / unknown.
- For unknown country, either:
  - fail salary closed with the existing "Insufficient market data for this
    profile" copy, or
  - run broad USD/year queries only when the role and location are strong
    enough. Pick one policy and test it directly.
- Add fast tests for `detected_country=None, detected_location=None` and for
  explicit non-CZ countries.

### B - Current-year salary queries

- Replace hard-coded `2025` tokens in `build_queries()` with a single helper
  such as `_salary_query_year(today: date | None = None) -> int`.
- Use the helper in CZ, non-CZ, management, and senior query branches.
- Add a fast test that freezes the date to `2026-05-25` and asserts generated
  queries contain `2026`, not `2025`.

### C - PDF ingest budgets

- Add backend-side limits, independent of Gradio's `max_file_size`:
  - maximum rendered PDF pages;
  - maximum rendered pixel count or image bytes per page;
  - maximum total image bytes per document;
  - configurable vision concurrency.
- Return a clear `StageFailure(stage="ingest", ...)` when a document exceeds
  the limit.
- Emit observability events for `page_count`, `rendered_image_bytes`,
  `vision_pages_sent`, `vision_budget_rejected`, and fallback path.
- Add tests with synthetic multi-page PDFs and a low test-only page cap.

### D - Provider-upload privacy contract

- Make the privacy boundary explicit in README/UI copy:
  - PDF vision mode uploads rendered, unredacted pages to the configured LLM
    provider for transcription;
  - DOCX default mode stays local until post-redaction stages;
  - deterministic PDF text mode is available when provider upload is not
    acceptable.
- Consider changing the production default to `GANDER_PDF_INGEST_MODE=text`
  if "no unredacted provider upload" is the product promise.
- Add a smoke/test around the copy or config defaults so the behavior and
  documentation do not drift again.

### E - Timeouts and cancellation

- Add explicit timeout configuration for OpenRouter text/JSON calls, matching
  the existing vision timeout pattern:
  - `GANDER_LLM_TIMEOUT_S` default for text/JSON;
  - per-call override path if needed later.
- Add timeout protection around DDGS search calls. Prefer a small wrapper that
  preserves the existing partial-query tolerance and `StageFailure` copy.
- Add fast tests that patch the provider/search call to exceed the timeout and
  assert the pipeline returns controlled failures, not stuck tasks.

### F - Observability semantics

- Rename or split footer metrics:
  - `total_provider_latency_ms`: sum of provider call durations;
  - `wall_clock_ms`: elapsed pipeline wall clock.
- Keep cost aggregation as-is, but update renderer copy so it does not imply
  wall-clock latency when the number is summed concurrent provider time.
- Add a pipeline fast test where two mocked LLM calls overlap; assert wall
  clock is lower than summed provider latency and both fields render clearly.

### G - Local fixture hygiene

- Keep CI's `actions/checkout` `lfs: true` path unchanged.
- Improve local failure ergonomics:
  - document `git lfs pull` / `git-lfs` requirement in the local verification
    section, or
  - add a tiny non-LFS generated DOCX/PDF fixture for the fast tests that do
    not need the full binary corpus.
- Add a small preflight check or test helper so unresolved pointers fail with
  one actionable message instead of many ingest failures.

## Verification

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src/`
- Focused fast tests:
  - `uv run pytest -q -o addopts= tests/test_salary.py tests/test_ingest.py tests/test_llm.py tests/test_pipeline_fast.py tests/test_report.py -m fast`
- Full fast suite once Git LFS fixtures are hydrated:
  - `uv run pytest -q -o addopts= -m fast`
- Optional live gate with provider upload explicitly approved:
  - `GANDER_LLM_PROVIDER=openrouter OPENROUTER_API_KEY=... uv run pytest -m live -v`

## Outcome

Implemented:

- Unknown geography no longer resolves to CZ; salary now uses broad USD/year
  queries for unresolved country/location while preserving explicit CZ and
  supported non-CZ behavior.
- Salary query year tokens now come from the current year via a helper, with
  tests pinned to 2026-05-25 for the audit regression.
- PDF vision remains the default, but backend budgets now cap pages, page
  pixels, total rendered image bytes, and concurrency. Over-budget PDFs do not
  call vision transcription; selectable-text PDFs fall back locally, and
  text-poor over-budget PDFs fail with a budget-specific ingest message.
- OpenRouter text/JSON and vision calls now carry env-backed timeouts; salary
  DDGS search has per-query and total fan-out timeouts.
- Report snapshots now carry `wall_clock_ms`; renderer labels provider latency
  separately from wall clock.
- UI and README copy now disclose that default PDF vision uploads rendered,
  unredacted pages to the configured provider.
- Fast tests that previously required LFS binary fixtures now use generated
  in-memory fixtures where practical.

Review follow-up:

- The `_is_cz_location(None)` change is a deliberate migration: before T49, a
  CV with both `detected_country=None` and `detected_location=None` silently
  used CZ/Praha/CZK queries; after T49 it resolves to `XX` and emits broad
  USD/year, geography-unknown queries. This avoids inventing CZ locality when
  extraction has no geography signal.
- Unknown-geography salary payloads now include a `geography_note` instructing
  the estimator to treat XX results as a market-blind USD reference, not a
  localized personal estimate.
- Over-budget selectable-text PDFs now surface a report notice when vision is
  skipped and deterministic text extraction is used.

Verified:

- `uv run ruff check .` -> passed.
- `uv run ruff format --check .` -> passed.
- `uv run mypy src/` -> passed.
- `uv run pytest -q -o addopts= tests/test_config.py tests/test_salary.py tests/test_ingest.py tests/test_llm.py tests/test_pipeline_fast.py tests/test_render.py tests/test_schemas.py tests/test_failures.py tests/test_privacy_copy.py tests/test_ddg_cassettes.py -m fast`
  -> `266 passed, 18 deselected` after PR #38 review fixes.
- `uv run pytest -q -o addopts= -m fast` -> `543 passed, 96 deselected`.
