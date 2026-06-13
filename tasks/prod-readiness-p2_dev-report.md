# /dev Report

**Task:** Implement the "P2 — fast follows" tier from `tasks/prod_readiness_plan.md` — P2.1 accessibility (contrast + aria-live), P2.2 salary role·location context, P2.3 rerun crutch (decided: defer removal, fix the comment), P2.4 provider resilience (decided: seam + opt-in non-paid `local` fallback).
**Branch:** dev/prod-readiness-p2
**Worktree:** /home/mf/github/probable-goose-machine/.worktrees/prod-readiness-p2
**Stack:** py, gradio (UI), github-actions

## Decisions taken (user, this session)
- **P2.3 → defer removal, fix the comment.** No live budget to measure a local flake rate (needs `OPENROUTER_API_KEY` + network), so `--reruns 1` stays and the ci.yml comment was rewritten to be honest about what it does and does not rescue.
- **P2.4 → seam + opt-in non-paid `local` fallback** (env-gated, default OFF) + populate `MODEL_PRICES` from cited published pricing. No paid second provider; no `:free` hosted variants for CV content (data-use policy / saved memory `prototype-no-paid-services`).

## Commits (off `main`)
- `d9765ad` — **P2.1 a11y:** light-mode disabled button `#7c2d12` on `#fed7aa` (~6.5:1, was `#fff` on `#fdba74` = 1.69:1); skipped pill `#667085` (~4.84:1, was `#98a2b3` = 2.58:1) with line-through kept so "skipped" never relies on colour alone (WCAG 1.4.1); `render_tracker` pill row is now `role="group"` and a single visually-hidden polite region (`gander-sr-only`) announces one stage transition per yield via `_tracker_announcement()` instead of the whole pill container re-announcing all six pills.
- `b14ea63` — **P2.2 salary context:** `render_body` computes `role = canonical_role or detected_role` and passes `role` + `detected_location` into `_salary_section`, which emits a muted `.gander-salary-context` caption above `.gander-salary-range`. Both values are LLM-derived and escaped via `_html_inline`; degrades gracefully (no role → no caption; role but no location → role only). Render-only, no schema change.
- `4086deb` — **P2.4 provider resilience:** generalize the `LLMClient` seam to a second, non-paid, OpenAI-compatible provider (`local`, Ollama/self-hosted) opted in per slot via `GANDER_LLM_PROVIDER_<SLOT>=local`, default OFF. `MODEL_PRICES` populated with OpenRouter's published Gemini 3.x prices (cited, read 2026-06-13) as the `_estimate_cost` fallback; local models estimate to ~0.
- `5b2399a` — **P2.3 honesty fix:** rewrite the ci.yml `--reruns 1` comment; mark the P2 plan status lines.

## Files touched
- `app.py` — light-mode disabled-button pair `#7c2d12` on `#fed7aa`; opacity left at 1 so the rendered ratio equals the raw pair.
- `src/gander/report.py` — P2.1: `.gander-sr-only` clip CSS; `.pill.skipped` → `#667085` + line-through; `_tracker_announcement()`; `render_tracker` pill row `role="group"` + single SR `<p role="status" aria-live="polite">`. P2.2: `_salary_context_line()`; `_salary_section(..., role=None, location=None)` emits the caption; `.gander-salary-context` CSS (light `#667085` / dark `#a1a1aa`).
- `src/gander/llm.py` — `ProviderName = Literal["openrouter", "local"]`; `_validate_provider` accepts `local`; `_build_client` branches local → `AsyncOpenAI(base_url=GANDER_LOCAL_BASE_URL default http://localhost:11434/v1, api_key=GANDER_LOCAL_API_KEY or "local")` with no OpenRouter headers; provider-aware routing via `_LOCAL_ROUTES` + `_ROUTES_BY_PROVIDER` (still overridable by `OPENROUTER_MODEL_<SLOT>`); `extra_body` OpenRouter directive suppressed for local; vision stays OpenRouter-only (a `vision=local` override degrades back); `MODEL_PRICES` populated (cited).
- `.github/workflows/ci.yml` — P2.3 comment rewrite only; flag `--reruns 1 --reruns-delay 2` unchanged.
- `.env.example`, `README.md` (Providers), `CLAUDE.md` (model-context) — `GANDER_LLM_PROVIDER_<SLOT>=local` + `GANDER_LOCAL_BASE_URL`/`GANDER_LOCAL_API_KEY` opt-in docs; OFF by default, non-paid, vision stays OpenRouter.
- `tests/test_a11y_contrast.py` (new) — pure-Python WCAG relative-luminance helper asserting the disabled-button and skipped-pill fg/bg pairs clear 4.5:1, plus a wired-in check that the hexes are actually present in the CSS.
- `tests/test_render.py` — P2.1 live-region restructure (no `aria-live` on the pill row; SR region present; announcement reflects running/failed/complete) + 5 P2.2 caption cases (canonical+location, `detected_role` fallback, location omitted, empty role omits caption, injection escaped).
- `tests/test_llm.py` — +7 local-provider cases (client build against default/override base_url, per-slot route resolution, `_cost_usd` fallback/provider-cost/local-zero, vision-ignores-local); existing `_resolve_model` call sites updated for the new `provider` arg; provider-validation test extended to accept `local`.
- `tasks/prod_readiness_plan.md` — P2.1/P2.2/P2.4 → `[x]`, P2.3 → `[~]`.

## Checks
| Command | Result |
|---|---|
| `ruff format --check .` | pass (67 files) |
| `ruff check .` | pass |
| `mypy src/` | pass (22 files) |
| `pytest -m fast --strict-markers` | pass (736 passed, 97 deselected) |

A render-level Python smoke confirmed P2.1/P2.2 at the HTML level: exactly one `aria-live` attribute in the tracker output (on the SR-only region, not the pill row), the seed announcement "Score: in progress", and the caption "Senior Software Engineer · Prague" rendered above the range.

The `live` / `openrouter-live` lanes were **not** run — they need an `OPENROUTER_API_KEY` and network, which this environment lacks. P2.3 is a comment-only change to that lane, so its behavior is unchanged regardless.

## Accepted deviations (documented, not "fixed")
- **P2.3 removal deferred, not done.** The plan's "drop the rerun crutch" is intentionally a no-behavior-change comment fix this round. The backlog entry `prod-readiness-p1-live-flaky` records that `--reruns 1` *cannot* rescue the growth-JSON truncation flaky (the `StageFailure` is cached in the session-scoped `triplet` fixture, so a per-test rerun re-reads the same failed `Report`); the rewritten comment states this plainly rather than parroting the plan's looser framing. Removal is gated on a measured live flake rate.
- **Vision stays OpenRouter-only.** A `GANDER_LLM_PROVIDER_VISION=local` override degrades back to OpenRouter by design (local models often lack a vision head) — documented in README/CLAUDE.md/`.env.example`, not treated as a bug.

## Remaining risks / unverified
- **`MODEL_PRICES` figures are page-reported, not invoice-verified.** The two Gemini 3.x entries were transcribed from the OpenRouter model pages on 2026-06-13. Low impact: `_cost_usd` prefers OpenRouter's per-response `usage.cost` and only falls through to the table when that field is absent (rare on the live path). Recorded in the backlog for re-confirmation before any decision leans on the *estimated* cost.
- **`local` provider has unit coverage only.** No live/integration test issues a real request to a running Ollama/self-hosted server; the OpenAI-compatible contract is assumed. Marked "implemented, not live-verified" in the backlog — the first real local run may surface response-shape or `response_format` differences the mocks don't model.
- **Browser/AT evidence not captured.** The contrast pairs are guarded by a pure-Python WCAG helper (and confirmed by hand once) but not cross-checked against an external calculator in CI; the single-announcement-per-stage SR behavior is verified at the HTML/attribute level, not with VoiceOver/NVDA. Same browser-evidence gap the `ui-polish-pass-2` block flagged for the prior live-region change.
- **`vision=local` degradation is silent.** No obs event signals that the override was dropped; an operator could expect local vision traffic and silently get OpenRouter. Backlog should-fix.

Full review-burst leftovers (4 should-fix, 2 nits) are appended to `tasks/backlog.md` under the `prod-readiness-p2` block.

## PR #44 review pass (commit `fix(p2): PR #44 review pass`)
A review burst on PR #44 surfaced two genuine functional bugs (both filed by the
author), one render bug, one test-quality issue, and a docs-clarity gap. All five
fixed on this branch; details in `tasks/backlog.md` (`prod-readiness-p2` block,
"Resolved in the PR #44 review pass"):
- **A — `_tracker_announcement`** announced "Analysis complete" on the all-pending
  initial yield and the profile-done/downstream-pending gap (no stage running/failed
  → fell through to completion). Now gated on all-terminal; otherwise announces the
  next waiting stage. +2 regression tests.
- **B — `check_env`** raised without `OPENROUTER_API_KEY` even when every text slot
  was `local`, blocking the P2.4 headline feature from booting. Now provider-aware
  (key required only if a text slot routes to OpenRouter; vision excluded). +3 tests.
- **C — salary caption** suppressed when `canonical_role` was whitespace-only; strip
  before the `or detected_role` fallback. +1 test.
- **E — `test_a11y_contrast.py`** assertions scoped to the specific CSS rule blocks
  (were unscoped substring matches that other rules' reused hexes could satisfy).
- **D — docs** (`README.md`, `.env.example`): global `GANDER_LLM_PROVIDER=local`
  switches all text slots at once; keyless boot caveat for PDF vision ingest.

Gate after the pass: `ruff format --check` / `ruff check` / `mypy src/` clean;
`pytest -m fast --strict-markers` → **742 passed, 97 deselected** (+6 from the
736 above). `live`/`openrouter-live` still not run locally (no key/network).

## Cleanup
When you're done with this work:
```
git worktree remove .worktrees/prod-readiness-p2
git branch -D dev/prod-readiness-p2
```
Or, to land it:
```
git checkout main
git merge --no-ff dev/prod-readiness-p2
```
