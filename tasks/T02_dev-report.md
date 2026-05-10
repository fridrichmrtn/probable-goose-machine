# /dev Report

**Task:** T02 — verify, obs, llm + errors-extension (foundation utilities for Job Fit & Salary Estimator)
**Branch:** dev/t02-utils
**Worktree:** /home/mf/GitHub/probable-goose-machine/.worktrees/t02-utils
**Stack:** py, gradio (UI flag set on project; this diff has no UI surface, only the obs subscription contract that T16 will consume)

## Files touched
- src/jobfit/verify.py (new) — `verify_quote(quote, source, *, section=None)` and `drop_unverified` per PLAN §"Hallucination guard hardened" (≥6 words AND positionally unique OR ≥8 words; section-locality via markdown headers H1–H6).
- src/jobfit/obs.py (new) — `emit(stage, event, **kv)` over structlog JSON + `subscribe(callback)` ContextVar-scoped (immutable tuple → safe under `asyncio.gather` siblings) + `current_stage: ContextVar[str | None]`.
- src/jobfit/llm.py (new) — `LLMClient` async over MiniMax (`AsyncOpenAI` + `base_url=https://api.minimaxi.chat/v1`) with Anthropic fallback hook (`JOBFIT_LLM_PROVIDER`); `complete_json` retries once on `ValidationError | json.JSONDecodeError`; `MODEL_PRICES` dated 2026-05-10; telemetry emit in `finally`.
- src/jobfit/errors.py (extended) — `stage_boundary` now sets `obs.current_stage` on enter / restores on exit (sync + async); emits `obs.emit("error", stage, exc_type, exc_message)` on catch. T01 `# T02:` TODO resolved.
- tests/test_verify.py (new) — 11 fast tests (incl. heal regressions for H1/H3 section headers).
- tests/test_obs.py (new) — 5 fast tests (incl. heal regression: subscriber exception swallow).
- tests/test_errors_obs.py (new) — 6 fast tests covering current_stage attribution + obs error emission across sync/async paths.
- tests/test_llm.py (new) — 1 `@pytest.mark.live` test, skipped without `MINIMAX_API_KEY`.
- tasks/T02_dev-plan.md — Authored by the planning agent in Phase 1.
- tasks/backlog.md — 12 should-fix + 3 nit findings appended (auto-unioned on merge via `.gitattributes` `merge=union`).
- tasks/T02_utils.md — Status: todo → done; Outcome line.
- tasks/todo.md — T02 checkbox ticked.

## Checks
| Command | Initial | After heal |
|---|---|---|
| `uv run pytest -m fast -v` (32 tests: T02 19 + T01 regression 13) | 31 pass + 1 lossy heal-test | **32/32 pass** |
| `uv run mypy src/jobfit/verify.py src/jobfit/obs.py src/jobfit/llm.py src/jobfit/errors.py` | pass | pass |
| `uv run ruff check src/jobfit/ tests/` | pass | pass |
| `uv run pytest -m live tests/test_llm.py -v` | skipped (no `MINIMAX_API_KEY` in dev env) | skipped |

## Review findings

### Must-fix (resolved this run)
- [codex] src/jobfit/obs.py:42 — Subscriber callback exceptions propagated out of `emit()`, which could turn a handled `stage_boundary` failure into an unhandled crash. **Fixed**: wrapped each callback in `try/except Exception`, logging a `subscriber_error` warning instead of raising. Pinned by `test_subscriber_exception_is_swallowed_not_propagated`.
- [ai-ml-engineer + codex] src/jobfit/llm.py:122 — Retry path caught `ValidationError` only; malformed/fenced JSON (`json.JSONDecodeError`) bypassed the retry and failed on first attempt. **Fixed**: broadened the except clause to `(ValidationError, json.JSONDecodeError)`.
- [ai-ml-engineer] src/jobfit/verify.py:9 — Section regex `^##\s+(.+)$` accepted only H2; CV markdown commonly uses H1 ("# Experience") or H3 nested under a person header. **Fixed**: broadened to `^#{1,6}\s+(.+)$`. Pinned by `test_section_resolves_under_h1_header` + `test_section_resolves_under_h3_header`.

### Should-fix (deferred)
12 items appended to `tasks/backlog.md` — covering: token-count accumulation across LLM retries, Anthropic prompt-caching TODO, `_ANTHROPIC_MODEL` ID verification, Unicode NFC normalization, word-boundary matching, `drop_unverified` AttributeError robustness, async subscribe API for Gradio, `user_message` UI-leak guard, `MODEL_PRICES` TTL, `complete_text` model default for L4c judge, OpenAI/Anthropic typing dispatch comment, JSON-retry mock fixture.

### Nits
3 items in `tasks/backlog.md` — `str.count()` overlap, immutable-tuple subscribe O(n), Anthropic native tool-use vs prompt-injection.

## Hiring grade
**on-bar** — "stage-boundary obs wiring resolves T01's TODO; verify_quote contract correctly distinguishes 6-word/8-word rules; LLMClient retry path is now defensive against both schema and decode failures. Anthropic branch remains unverified end-to-end (model ID, pricing) but is documented as fallback-only and gated behind explicit env."

## Cleanup
When you're done with this work:
```
git worktree remove .worktrees/t02-utils
git branch -D dev/t02-utils
```
Or, to land it:
```
git checkout main
git merge --no-ff dev/t02-utils
```
