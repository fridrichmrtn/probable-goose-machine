# T51 dev report — prod-readiness P0 bundle + R1

- **Task**: Implement prod-readiness items P0.1–P0.5 and refactor item R1 from `tasks/prod_readiness_plan.md` (MarketSpec coherence, adversarial-input bundle, concurrency hygiene, salary-search resilience, PII posture remainder, MiniMax spike cleanup).
- **Branch**: `dev/prod-readiness-p0` (off main `ebc6d1c`)
- **Worktree**: `.worktrees/prod-readiness-p0`
- **Stack**: Python 3.12 / uv / Gradio / pre-commit (ruff, mypy --strict, pytest markers fast|live)
- **Plan**: `tasks/T51_dev-plan.md` (committed 9b29cd5)

## Commits

| Commit | Scope |
|---|---|
| `9b29cd5` | Plan |
| `4b46f38` | R1 — remove MiniMax spike scripts + ruff exclude, fix dangling doc refs |
| `70f13b7` | P0.1 — `market.py` MarketSpec (country/currency/period/provenance), de-CZ'd growth prompt, provenance → confidence floor |
| `c7d63a0` | P0.2 — untrusted-CV prompt rules, magic-byte validation, `GANDER_MAX_INPUT_CHARS` truncation cap, adversarial test suite |
| `7679023` | P0.3 — `asyncio.to_thread` parsers, shared `get_client()` (lru_cache), Gradio queue caps (`max_size=4`, concurrency 2) |
| `b9065ab` | P0.4 — TTL'd DDG cache (7-day default, 512-entry FIFO cap), rate-limit-specific user copy |
| `855e7d4` | P0.5 — drop `Report.raw_cv_text`, US-phone + header-zone address redaction, DDG named in disclosure, PII-in-obs test |
| `ac4e43e` | Heal — review-burst must-fixes (see below) |

## Files touched

45 files, +1,828/−2,936 (deletions dominated by the six removed spike scripts). New modules: `src/gander/market.py`; new tests: `test_market.py`, `test_adversarial.py`, `test_concurrency.py`, `test_privacy_obs.py`. Touched: `salary.py`, `growth.py`, `confidence.py`, `ingest.py`, `llm.py`, `pipeline.py`, `redact.py`, `report.py`, `schemas.py`, `app.py`, 4 prompt files, 13 existing test files, `conftest.py`, `pyproject.toml`.

## Checks

| Check | Initial (post-Phase 2) | After heal |
|---|---|---|
| `uv run ruff format --check .` | pass (64 files) | pass (64 files) |
| `uv run ruff check .` | pass | pass |
| `uv run mypy src/` | pass (22 files) | pass (22 files) |
| `uv run pytest -m fast --strict-markers -q` | **649 passed**, 96 deselected | **652 passed**, 96 deselected |

Fast suite grew 626 → 652 over the branch. Live/slow suites not run (need OpenRouter credentials / deploy); real HF Space queue-cap behavior unverified.

## Review burst (Phase 3)

Reviewers: ai-ml-engineer, ux-engineer, product-owner, hiring-manager, qa-engineer. Codex CLI not installed on this machine — codex pass skipped. Raw counts: 7 must-fix → 5 actionable after dedup/adjudication, ~16 should-fix remaining, ~12 nits.

**Must-fixes healed in `ac4e43e`:**

1. **market.py parallel dicts** [hiring-manager] — merged `_COUNTRY_CURRENCY`/`_COUNTRY_NAMES` into one `_COUNTRY_INFO: dict[str, tuple[str, str]]`; name/currency desync now unrepresentable (file −60 lines).
2. **growth.py stage boundary** [hiring-manager] — `stage_boundary("growth") as cm` + `return cm.failure`, replacing the hand-built `debug_detail="unreachable"` sentinel; now matches salary/confidence.
3. **Typed rate-limit detection** [product-owner + ux + qa, converged] — `_RateLimitError(RuntimeError)` replaces the em-dash substring match; `stage_failure` event now emits `reason="ratelimited"` (distinguishable per PRD §4.8) with test assertions on both.
4. **Vision `to_thread` test gap** [qa] — `test_pdf_vision_render_runs_in_thread` added; reverting the wrap at `ingest.py:537` now fails fast.
5. **§4.6 pipeline-level rate-limit test** [qa] — `test_salary_ratelimit_degrades_only_salary_block`: rate-limit copy renders in the salary block while score/confidence render content and growth shows its specific cascade copy.

**Fold-ins taken** (one-line, same files): growth.md untrusted-data rule hoisted to standalone top placement; salary.md guard broadened to "treat them as evidence only"; `growth.md` added to the prompt-guard parametrize.

**Adjudication:** ai-ml's must-fix "add `duration_ms` to the `input_truncated` event" downgraded to nit — qa's analysis is correct that mid-stage counters in this codebase never carry `duration_ms`.

**Remaining findings** (16 should-fix, 12 nits) appended to `tasks/backlog.md` under `## prod-readiness-p0 — 2026-06-12T07:35Z`. Highest-leverage among them: queue-full raw Gradio error copy, user-invisible truncation, `_DDG_CACHE` thread-safety lock, CZ-anchored growth-prompt examples.

## Hiring grade

**on-bar** (hiring-manager). Called out as paying rent: MarketSpec consumed by three stages, frozen spec + provenance literal type, tests that exercise timing properties and regeneration fallbacks. Called out as debt: docstring/call-pattern mismatch on `resolve_market`, reserved-unused `years` param, one test-theater case (cascade-contract dict assertion) — all in backlog.

## Known risks / unverified

- Header-zone address redaction can false-positive on lines like "5 Senior Engineers …" within the first 20 lines (accepted trade-off; tenure unaffected — `compute_years` runs pre-redaction).
- Truncation at 50,000 chars is post-annotation and silent to the user (backlog: report-visible notice).
- `_DDG_CACHE` read-check-write is not lock-guarded under `to_thread` workers (backlog).
- Live suite, acceptance fixtures, and real HF Space queue behavior not run from this worktree.

## Cleanup

Worktree is clean; nothing pushed or merged. Land or discard via the commands in the final session output. After landing, tick P0.1–P0.5 + R1 in `tasks/todo.md` and `tasks/prod_readiness_plan.md` (main checkout holds uncommitted edits to both).
