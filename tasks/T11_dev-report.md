# /dev Report — T11 L4b CZ-localized salary search + estimator

**Task:** Implement T11 — L4b salary search + estimator. Deliverables: `src/jobfit/prompts/salary.md`, `src/jobfit/salary.py` (`build_queries`, `async search`, `async estimate_salary`), `tests/test_salary.py` (3 fast + 1 live slow). CZ-localized DDG queries (platy.cz / profesia.cz / glassdoor czech republic), tenacity fail-fast (≤2 attempts/call), `StageFailure` if <2 sources, hard URL-grounding rule, currency↔period coupling, observability per §4.8.
**Branch:** `feat/block-b-late-stages` (no sub-worktree — `--no-worktree`)
**Worktree:** `/home/mf/GitHub/probable-goose-machine/.worktrees/block-b`
**Stack:** py, gradio, precommit
**Status:** clean (single heal pass resolved all 8 must-fix items first try)

## Files touched

- `src/jobfit/prompts/salary.md` — new (~60 lines). System prompt: input is `{context, results}` JSON, output matches `SalaryEstimate` schema, hard rules forbid URL invention / paraphrase, currency↔period iff-coupling pinned in prose ("`period` MUST be `month` if and only if `currency=='CZK'`. For EUR or USD, `period` MUST be `year`. No exceptions.").
- `src/jobfit/salary.py` — new (~225 LOC after heal). Mirrors T10's structure: module-load `_SYSTEM_PROMPT`, `async with stage_boundary("salary")`, return `SalaryEstimate | StageFailure`. Module constant `_INSUFFICIENT_DATA_MSG` ("Insufficient market data for this profile" — verbatim PRD §4.6 copy, no trailing period) used across all logical-failure branches; differentiation lives in structured `debug_detail` + `stage_failure.reason` event keys (`no_verifiable_sources`, `unsupported_currency`, `currency_period_mismatch`, `invalid_range`, `invalid_llm_output`).
- `tests/test_salary.py` — new (~190 LOC after heal). 5 fast tests + 1 live+slow guarded by `MINIMAX_API_KEY`. Two fast tests assert `obs.subscribe(events.append)` event streams (search-empty path: `salary_search` with `dedup_results=0` + boundary `error` event with `exc_type="RuntimeError"`; URL-grounding path: `stage_failure` with `reason="no_verifiable_sources"`).
- `tasks/T11_salary.md` — Status flipped `todo` → `done`; Outcome line added.
- `tasks/T11_dev-plan.md` — new (planning artifact, 206 lines).
- `tasks/backlog.md` — appended T11 block with 10 should-fix + 5 nits + count of further nits.

## Checks

| Command | Initial (Phase 2) | After heal (Phase 4) |
|---|---|---|
| `uv run ruff format --check src/jobfit/salary.py tests/test_salary.py` | pass | pass |
| `uv run ruff check src/jobfit/salary.py tests/test_salary.py` | pass | pass |
| `uv run mypy src/jobfit/salary.py` | pass | pass |
| `uv run pytest -q -m fast tests/test_salary.py` | pass (3) | pass (5) |
| `uv run pre-commit run --all-files` | pass | pass |

The live spike (with `MINIMAX_API_KEY` set, hits real DDG + MiniMax) is **deferred to the orchestrator's Block B integration check** — running `pytest -m "fast or live"` after all four task commits land. Live tests are guarded by `@pytest.mark.skipif(not os.environ.get("MINIMAX_API_KEY"))` so a clean clone does not error.

## Review findings

### Must-fix (resolved this run, single heal iteration)

- **[hiring-manager + ai-ml-engineer + qa-engineer]** No fast-test coverage of the URL-grounding rejection branch (`src/jobfit/salary.py:80` — `if not kept`). The §4.5 hallucination guard for salary URLs was unverified by CI. **Fixed:** added `test_estimate_salary_rejects_llm_urls_not_in_search_results` mocking DDG with 2 valid results, `LLMClient.complete_json` to return a `SalaryEstimate` whose `sources` are entirely external URLs, and asserting both the `StageFailure(stage="salary")` return and the `stage_failure` event with `reason="no_verifiable_sources"`.
- **[codex + qa-engineer + hiring-manager]** `build_queries` silently dropped the senior EUR cross-check for CZ profiles with years≥10: 3 CZ queries + 1 EUR appended → `[:3]` truncated EUR off. **Fixed:** raised the cap to 4 only when the senior EUR query is appended (the EUR cross-check is the senior-specific market signal); added one-line WHY comment; added a fast test pinning the senior CZ path returns 4 queries with EUR present.
- **[codex + ai-ml-engineer]** Currency↔period invariant unenforced — model could emit `CZK / year` (12× cost-display error) or `EUR / month` and only currency-set membership was checked. **Fixed:** added programmatic post-LLM check `(CZK & period!="month") or ((EUR|USD) & period!="year")` → `stage_failure` event with `reason="currency_period_mismatch"` + `StageFailure` return. Prompt strengthened with iff-coupling sentence.
- **[qa-engineer]** No `obs.subscribe()` event assertions in tests (T10 set the precedent; T11 emitted 4+ event types and asserted none). **Fixed:** two fast tests now subscribe and assert event streams (the search-empty case asserts `salary_search` with `dedup_results=0` plus the boundary `error` event with `exc_type="RuntimeError"`; the URL-grounding case asserts `stage_failure` with `reason="no_verifiable_sources"`).
- **[qa-engineer + ai-ml-engineer + hiring-manager]** Live test ran into `MINIMAX_API_KEY` errors instead of skipping cleanly in fresh-clone CI. **Fixed:** added `import os` and `@pytest.mark.skipif(not os.environ.get("MINIMAX_API_KEY"), reason="needs MINIMAX_API_KEY")`.
- **[qa-engineer + ux-engineer]** Three internal failure branches surfaced bespoke user-facing copy ("Salary estimate produced no verifiable sources.", "...returned an unsupported currency.", "...returned an invalid range."), all of which differ from the PRD §4.6 mandated copy. The PRD specifies this user-facing string verbatim: `"Insufficient market data for this profile"` (no trailing period). **Fixed:** module-level constant `_INSUFFICIENT_DATA_MSG` pinned to PRD copy (verified line 61); used across `search()`'s `RuntimeError`, all four logical-failure StageFailure returns, and the new `invalid_llm_output` branch. Differentiation moves to `debug_detail` + structured `stage_failure.reason` event.
- **[qa-engineer]** `assert isinstance(estimate, SalaryEstimate)` smuggled `AssertionError` to the user (boundary catches → `user_message="AssertionError"`). **Fixed:** explicit `if not isinstance(...): emit stage_failure(reason="invalid_llm_output", got_type=...); return StageFailure(user_message=_INSUFFICIENT_DATA_MSG, debug_detail=f"complete_json returned {type(...).__name__}")`.
- **[codex + hiring-manager + ai-ml-engineer + qa-engineer]** Retry-cap test asserted `text_mock.call_count <= len(queries) * 2` — would have allowed silent regression to widened retries. **Fixed:** tightened to `assert text_mock.call_count == 2` (first query exhausts retries, `reraise=True` propagates, no further query fires); test comment updated to explain the exact-count rationale.

### Must-fix (remaining — exhaustion)

None. Single heal iteration resolved all 8 items.

### Should-fix (deferred to backlog)

10 items captured in `tasks/backlog.md` under the `## T11 — 2026-05-10T18:30Z` block. Highlights: partial URL-drop branch lacks fast-test coverage; HttpUrl-normalization edge cases (trailing slash, scheme casing) untested; `search()` raise-vs-return inconsistency vs T10 pattern; `_CZ_MARKERS` substring matching false positives; live test reads CV text but doesn't pipe it through T09→T10; codex-flagged snippet/domain non-verification (URL is checked, but the LLM could pair a fabricated snippet with a verified URL).

### Nits

5 enumerated + ~7 minor (loop variable rename, helper extraction, hot-reload commentary, hard-coded threshold rationale). See backlog.

## Hiring grade

**below-bar → on-bar after heal.** Three reviewers (hiring-manager, qa-engineer, codex) returned below-bar on initial pass — strong signal across an independent model family. The convergent must-fix items: missing URL-grounding test (the load-bearing reliability check for §4.5), CZ-senior EUR cross-check silently dropped, currency↔period invariant unenforced. The single heal iteration addressed all 8 consolidated must-fix items; second-opinion reviewers noted the URL-rejection branch was previously dead code from the test suite's perspective. With the heal in, the stage emits structured signals on every failure path, fails closed when LLM hallucinates URLs, and pins the user-facing copy to PRD §4.6 verbatim.

## Codex reviewer note

Codex (gpt-5.5, OpenAI) independently surfaced three of the eight must-fix items at the same file:line as the Claude-family reviewers: the URL verification post-normalization concern (line 143), the CZ-senior EUR-query truncation (line 54), and the weak retry assertion (test line 77). Independent confirmation from a different model family is the strongest signal we get — flagging it here so the next operator reading this report knows the issues were not single-reviewer artifacts.

## What this run does NOT prove

- **Live MiniMax + DDG behavior.** The live test is guarded by `MINIMAX_API_KEY` and was not exercised in this delegation. The orchestrator will run `uv run pytest -m "fast or live" -q` after all four Block B tasks land, with `.env` sourced.
- **Real DDG result key shapes.** The fast tests mock DDG with synthetic `body`/`href` keys. The defensive `body`/`snippet` and `href`/`url` fallback in `_to_source` is exercised by the URL-grounding test (which uses `href`+`body`) but not the alternate keys. Live test will surface any real DDG schema drift.
- **Cross-stage telemetry naming consistency.** T11's keys (`raw_results`, `dedup_results`, `dropped_invalid_url`) are stage-local. T12/T13 will need a follow-up audit before T15 wires them into the renderer.

## Cleanup

Block B uses a single shared worktree across T10–T13. Do not remove until all four tasks land:

```bash
git worktree remove .worktrees/block-b
git branch -D feat/block-b-late-stages   # only after merging
```

To land:

```bash
git checkout main
git merge --no-ff feat/block-b-late-stages
```
