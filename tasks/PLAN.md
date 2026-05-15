# Gander — Implementation Plan

## Plan v3 — User direction: engineering hygiene + real eval corpus

After v2 (review-driven revisions), the user added these directives:

1. **Pre-commit + CI/CD from the beginning** — folded into L0. Pre-commit: `ruff format` + `ruff check` + `mypy` + fast unit tests (marked `@pytest.mark.fast`). CI: GitHub Actions on every PR runs the **full test suite with live MiniMax + live DDG** — catches model and search regressions immediately. Burns tokens deliberately; CI uses `MiniMax-M2.7-highspeed` for stages where reasoning isn't critical (configured via env var `GANDER_MODEL_PROFILE=ci`) to keep costs bounded.
2. **10 synthesized CZ data/DS/ML CVs** — I author them spanning junior→senior across roles (data analyst, data scientist, ML engineer, MLOps, research scientist). Mixed formats: roughly half PDF, half DOCX, so `scripts/eval_corpus.py` exercises both ingestion paths end-to-end. Three of the 10 serve as the §5.4 acceptance triplet (junior/mid/senior).
3. **CZ localization** — salary stage defaults to CZK monthly gross; search queries target CZ aggregators (platy.cz, profesia.cz, glassdoor.com/Location/Czech-Republic-Salaries) plus EUR cross-checks for senior roles. Bias smoke test uses CZ-specific prestige signal (Charles University / MFF UK / VŠE vs anonymized).
4. **`scripts/eval_corpus.py` as the user's gauging surface** — runs all 10 CVs through the **real live pipeline** (true e2e smoke, not VCR), writes one `<cv_name>.md` per CV plus an `reports/SUMMARY.md` table (candidate | format | score | salary range | confidence | top growth action). User runs it locally to manually gauge output quality before submission.

These directives expand build budget by ~3.5h. Acceptable given the 5-day calendar window.

## Plan v2 — Revisions after multi-agent review

After product-owner, software-engineer, ai-ml-engineer, ux-engineer, and hiring-manager reviews of v1, the following high-severity issues are addressed below in their respective sections:

1. **Latency budget honestly costed.** New "Latency budget" table; L4a collapsed to one structured call; L4a/L4b run concurrently via `asyncio.gather` (not just "parallel work tracks"); MiniMax-M2.7-highspeed reserved for stages where reasoning matters.
2. **Cold-start mitigation is now real, not wishful.** GitHub Actions warm-keeper cron (5 min) replaces the "ping ~10 min before" line; README leads with a "first request may take 20s" note above the fold.
3. **Gradio UI pattern fixed.** Drop the `gr.Progress` + tuple-yield conflation. Pipeline yields a single `Report` state object to a `gr.HTML` stage-tracker + `gr.Markdown` body; renderer is a pure function of state. Hero stage-card pills as the first 10s impression.
4. **Confidence judge isolated more aggressively.** _(Note: under M2.x highspeed-only deployment the "different model" defense degrades to prompt-/temperature-only isolation; revisit during T12.)_ Temperature 0, recompute-then-compare protocol: judge derives its own tier from sources alone, then is shown the produced range only to write its rationale. Token-grep isolation test dropped (false-positives on shared vocab); replaced with a structural test asserting the function signature.
5. **Hallucination guard hardened.** `verify_quote` floor raised to **≥6 words AND match must be unique in the source** (or ≥8 words if not unique). Experience-section claims must match within their own section, not anywhere in the CV.
6. **Acceptance tests strengthened beyond verbatim-equality.** Added n-gram overlap check (Jaccard ≥0.4 across any two growth-plan items across CVs is a fail) and a calibration test (same CV run 3× → score variance ≤5).
7. **Early MiniMax capability spike (L0.5)** before sinking time into all six stages. Hard gate: anchor-quote literal-copy rate ≥70% on 2 fixtures and score spread ≥20 between junior/senior on those 2. Fallback path documented (Claude Sonnet 4.6).
8. **Partial-failure flow specified.** L6 explicitly short-circuits L4c when L4b failed and L5 when L4a+L4b both failed. Each block emits a status enum (`pending|running|done|failed`) so the UI re-renders cleanly.
9. **Cost + latency telemetry** in `obs.py` (`prompt_tokens`, `completion_tokens`, `usd_cost`, `duration_ms`) — README quotes a per-run cost figure.
10. **README Decisions section repositioned as load-bearing** — author-voice framing of MiniMax (price/availability + creativity-by-constraint) and DDG (zero-setup ethos extends to the build), with the cuts listed and rationalized.

A "Deferred nits" list at the bottom captures lower-severity findings.

## Context

We are building the round-1 deliverable for an AI-first developer hiring case study (PRD v0.11). A reviewer uploads a CV and gets back a defensible seniority score (0–100), a market-grounded salary range with sources and an independently-judged confidence tier, and a CV-specific +30% growth plan with achievable actions.

**Submission deadline:** 15 May 2026 (5 days from today, 2026-05-10).
**Build budget:** ~1 focused day; remaining days are buffer for testing, hosting, and README polish.

**What "done" means here** (from PRD §5 + §9):
- A reviewer with no prior context produces a complete report on their own CV in <60s with zero setup (hosted demo).
- The same code runs locally with one or two commands.
- On three test CVs spanning seniority: scores span ≥30 points, junior/senior salary ranges do not overlap, and no growth-plan item repeats verbatim across CVs.
- Every claim about a candidate is a programmatically-verified substring of the extracted CV text.
- README "Decisions" section reads like a senior submission — visible tradeoff thinking, deliberate cuts, bias acknowledgment.

The discriminator is judgment + reliability. Anything that does not serve those is decoration.

---

## Tech Stack (decisions confirmed)

| Concern | Choice | Why |
|---|---|---|
| UI framework | **Gradio (Blocks API)** | Native AI-community surface; `gr.Progress` covers §4.8 observability and §8 first-impression risk; clean file upload + markdown rendering; same `app.py` works locally and on HF Spaces. |
| Hosting | **Hugging Face Spaces (Gradio SDK)** | Free public URL straight from a GitHub-synced or HF-hosted repo; secrets via Space settings; matches the AI-first hiring lens. |
| LLM | **MiniMax** via OpenAI-compatible API (user's token plan on minimax.io) | Default model: `MiniMax-M2.7-highspeed` (reasoning) for scoring, confidence, and growth-plan stages; `MiniMax-M2.7-highspeed` for cheaper extraction/redaction passes. Endpoint: `https://api.minimaxi.chat/v1`. Use the `openai` Python SDK with `base_url` override. No prompt caching assumed (graceful: keep prompts compact). |
| Web search (salary) | **DuckDuckGo** via `ddgs` Python package | No API key (preserves zero-setup ethos), free, returns title + snippet + URL. Risk: rate-limit / HTML-scrape brittleness — handled with retry, jittered sleep, and a search-empty path that triggers §4.6 fallback. |
| PDF parsing | **pypdf** (primary) + **pdfplumber** (layout fallback) | Pure-Python, no system deps; pdfplumber rescues column-heavy CVs when pypdf returns empty. |
| DOCX parsing | **python-docx** | Standard, no system deps. |
| Schema / validation | **Pydantic v2** | Catches model-output shape failures before they corrupt downstream stages. |
| Testing | **pytest** with marker-segregated suites (`fast` / `slow` / `live`) | Local fast iteration runs `-m "not live"`; CI runs the full live suite per user directive. VCR dropped — adds complexity for marginal benefit when CI is live anyway. |
| Packaging | **uv** + `pyproject.toml` | One-command install: `uv sync && uv run python app.py`. |
| Observability | **structlog** → JSON to stdout + Gradio `gr.Progress` events | Same event stream feeds CLI logs and UI progress; logs are visible in the HF Space console. |

---

## Architecture: Pipeline DAG

```
                    [ Upload PDF/DOCX ]
                             │
                  ┌──────────▼──────────┐
                  │  L1  Ingestion       │   pypdf | python-docx
                  │  - extract_text()    │   detect scanned PDF
                  │  - detect_format()   │   → user-facing fail msg
                  └──────────┬──────────┘
                             │ extracted_text
                  ┌──────────▼──────────┐
                  │  L2  PII Redactor    │   regex (email/phone/URL)
                  │  - redact()          │   + LLM pass for name/address
                  │  - audit_log         │   verified-by-substring removal
                  └──────────┬──────────┘
                             │ redacted_text
                  ┌──────────▼──────────┐
                  │  L3  Profile Extract │   single LLM call → Pydantic
                  │  - skills[]          │   every item carries an
                  │  - experience[]      │   anchor_quote that is
                  │  - education[]       │   substring-verified
                  │  - soft_signals[]    │
                  └──────────┬──────────┘
                             │ profile (verified)
              ┌──────────────┼──────────────┐
              ▼                             ▼
     ┌────────────────┐           ┌──────────────────┐
     │ L4a  Scorer    │           │ L4b  Salary      │
     │ per-component  │           │  - search query  │
     │ score+quote    │           │  - DDG fetch     │
     │ aggregate→0-100│           │  - estimator LLM │
     └────────┬───────┘           └────────┬─────────┘
              │                            │ range + sources
              │                            ▼
              │                   ┌──────────────────┐
              │                   │ L4c  Confidence  │  *separate*
              │                   │  judge           │   LLM call,
              │                   │  Low/Med/High +  │   sees sources
              │                   │  criteria        │   + range only
              │                   └────────┬─────────┘
              │                            │
              └──────────────┬─────────────┘
                             ▼
                  ┌──────────────────────┐
                  │  L5  Growth Plan     │   actions w/ horizon +
                  │  - 3-5 actions       │   mechanism + anchor_quote;
                  │  - achievability     │   12-24 mo achievability check;
                  │  - cv-specificity    │   substring-verified
                  └──────────┬───────────┘
                             ▼
                  ┌──────────────────────┐
                  │  L6  Report Assembly │   failure-aware: each block
                  │  - per-block render  │   either renders or shows
                  │  - drop unverified   │   a clear fallback message
                  └──────────┬───────────┘
                             ▼
                        [ Gradio UI ]
```

**Cross-cutting (used at every level):**
- `verify_quote(quote, source, *, section: str | None = None) -> bool` — case-insensitive, whitespace-collapsed substring check. Quote must be **≥6 words AND appear exactly once** in the source, OR **≥8 words** if it appears more than once. If `section` is provided (e.g., "experience"), match must fall inside that section's text, not just anywhere in the CV. Single source of truth for §4.5.
- `emit(stage, event, **kv)` — structured log (incl. `prompt_tokens`, `completion_tokens`, `usd_cost`, `duration_ms` for LLM calls) + push status updates to a Gradio queue the UI consumes. Single source of truth for §4.8.
- Per-stage exception boundary that converts failures into a `StageFailure(stage, message)` the assembler renders gracefully (§4.6).
- `StageStatus = Literal["pending","running","done","failed"]` — every block in the report carries one. UI renders are a pure function of the current `Report` state.

## Latency budget (warm path, p50)

The 60s SLA (PRD §7) is tight. Honest per-stage estimate, costed before we start:

| Stage | Est. p50 | Notes |
|---|---|---|
| L1 ingestion | 0.5s | local |
| L2 redaction (regex-only default) | 0.1s | LLM pass deferred unless capability spike shows we need it |
| L3 profile extract | 6s | one M1 structured call |
| L4a scoring (one structured call) | 6s | concurrent with L4b |
| L4b salary search + estimate | 8s | DDG ~2s + M1 ~6s, concurrent with L4a |
| L4c confidence | 3s | MiniMax-M2.7-highspeed, sequential after L4b |
| L5 growth plan | 6s | M1 |
| L6 assembly + render | 0.2s | local |
| **Sequential total** | **~30s warm** | well under 60s, leaves headroom for cold path |

L4a/L4b run via `asyncio.gather` — not just "parallel work tracks". If the L0.5 spike shows M1 latency is 2× this estimate, downgrade L3 and L5 to `MiniMax-M2.7-highspeed` and re-measure.

---

## Parallel Work Tracks (DAG of WORK, not data)

Once **L0 (foundation)** is in place, four tracks can proceed in parallel. Each track owns its files; merge points are the schema contracts defined in L0.

```
                        ┌───── L0  Foundation ─────┐
                        │ pyproject, schemas (Pydantic),    │
                        │ verify_quote, emit/logger,        │
                        │ StageFailure, llm.py, app.py shell│
                        └────────────────┬─────────┘
                                         │
                        ┌──── L0.5 capability spike ────┐
                        │ scripts/spike_minimax.py:     │
                        │ extract+score on 2 fixtures.  │
                        │ Hard gates → swap to Claude   │
                        │ if MiniMax fails them.        │
                        └────────────────┬──────────────┘
                                         │
        ┌────────────────────┬───────────┼────────────────────┬──────────────────┐
        ▼                    ▼           ▼                    ▼                  ▼
  Track A (backend)    Track B (UI)   Track C (tests)   Track D (deploy + CI)   Track E (CZ CV corpus)
        │                    │           │                    │                       │
   L1 → L2 → L3        K1 upload     M1 load fixtures    L9a HF Space setup       E1 synth 2 CVs
   ↓                   K2 stage      M2 unit tests       L9b secrets                 (junior+senior)
   L4a ‖ L4b           tracker       M3 end-to-end       L9c warm-keeper             FOR L0.5 SPIKE
   (asyncio.gather)   K3 report      M4 acceptance       L9d ci.yml (live)        E2 synth other 8
   L4c (skip if 4b    K4 errors      M5 failure paths    L9e pre-commit              (5 PDF + 5 DOCX
        failed)                      M6 partial-failure  N1 README incl.              across roles)
   L5 (skip if 4a+4b               M7 confidence-judge   Decisions section        E3 SOURCES.md
        failed)                     M8 bias smoke (CZ)                            E4 eval_corpus.py
   L6                              M9 eval_corpus smoke                              runner
```

**Hand-off discipline:**
- Track A publishes the `Report` Pydantic model first thing in L0 → Track B can render against a mocked `Report` immediately, no waiting.
- Track E (CV fixtures) is the lever for Track C — author all three CVs in the first hour so the differentiation test (§5.4) has data the moment L6 lands.
- Track D begins as soon as L1 + L7 (UI shell) render anything end-to-end, even with stub stages — surfacing deploy issues early de-risks the §8 first-impression latency risk.

---

## Phase-by-Phase Detail

### L0 — Foundation (blocking, ~110 min, single agent: software-engineer)

(Budget bumped further from v2's 75 min to account for v3 additions: pre-commit + CI + warm-keeper workflows, marker setup, pytest-asyncio config.)


Files to create:
- `pyproject.toml` — uv + Python 3.11+, pin: openai (for MiniMax-compatible client), gradio, pypdf, pdfplumber, python-docx, pydantic, structlog, ddgs, tenacity (retry), pytest, pytest-asyncio, ruff, mypy. Pytest markers declared: `fast`, `slow`, `live`.
- `app.py` — Gradio entrypoint at repo root (HF Spaces convention), with upload widget + a progress panel wired to `emit()` events.
- `requirements.txt` — exported from uv lock for HF Spaces (HF builds from `requirements.txt`, not `pyproject.toml`).
- `src/gander/schemas.py` — Pydantic models: `RawCV`, `RedactedCV`, `Profile`, `Component`, `Score`, `SalaryEstimate`, `Source`, `Confidence`, `GrowthAction`, `Report`, `StageFailure`. Every model carrying a claim has an `anchor_quote: str` field.
- `src/gander/verify.py` — `verify_quote(quote, source) -> bool` (≥4 words, case-insensitive, whitespace-collapsed) and `drop_unverified(items, source) -> tuple[list, int]`. Plus tests.
- `src/gander/obs.py` — `emit(stage, event, **kv)` writing structlog JSON to stdout + pushing to a thread-local Gradio progress callback when present.
- `src/gander/errors.py` — `StageFailure` + `stage_boundary` decorator that converts exceptions into `StageFailure` and emits an error event.
- `src/gander/llm.py` — thin wrapper around the OpenAI SDK client configured for MiniMax (`base_url="https://api.minimaxi.chat/v1"`, model selection per stage). Methods: `complete_json(messages, schema, *, temperature=0.0)`, `complete_text(messages)`. Async by default (`AsyncOpenAI`); JSON mode used for structured stages with one retry on schema-validation failure. Emits `prompt_tokens`/`completion_tokens`/`usd_cost`/`duration_ms` via `obs.emit()` for every call.
- `tests/conftest.py` — fixtures, sample-CV loader, marker registration. `ddgs` pinned to a single tested version (HTTP backend has churned). `pytest-asyncio` mode = `auto` so the async pipeline tests don't need decorators.
- `.github/workflows/warm-keeper.yml` — cron `*/5 * * * *` HEAD request to the HF Space URL. Free, keeps Space hot through the review window.
- `.github/workflows/ci.yml` — on every PR + push to main: `uv sync` → `ruff format --check` → `ruff check` → `mypy src/` → `pytest -m "not slow"` with **live `MINIMAX_API_KEY` + live DDG**. `GANDER_MODEL_PROFILE=ci` env var swaps M1 for `MiniMax-M2.7-highspeed` in stages where reasoning is dispensable, keeping CI token spend bounded. Concurrency: 1 (avoid DDG rate-limits and token-plan thrash).
  - **2026-05-15 update**: CI's live job now gates on OpenRouter (`GANDER_LLM_PROVIDER=openrouter`, `OPENROUTER_API_KEY`), matching the HF Space provider. The MiniMax `live` job was retired — prod and CI both run OpenRouter; MiniMax stays in `gander.llm` for local dev and the VLM-only ingest path (T35 owns the live VLM gate).
- `.pre-commit-config.yaml` — hooks: `ruff` (format + check), `mypy` on `src/`, `pytest -m fast` (only tests marked `@pytest.mark.fast` — pure-function unit tests under 1s, no external calls).
- `pyproject.toml` includes pytest markers: `fast` (no external IO), `slow` (>1s or external IO), `live` (requires API keys).

### L0.5 — MiniMax capability spike (~30 min, blocking, gates L3+)

Before committing all six stages to MiniMax-M2.7-highspeed, prove it can do the job. Requires that **2 of the 10 corpus CVs (one junior, one senior) are synthesized first** — Track E starts in parallel with L0 specifically to unblock this spike. Spike script `scripts/spike_minimax.py`: run M1 against those 2 fixtures on just the extract + score prompts. Hard gates:

- **Anchor-quote literal-copy rate ≥70%** (counts items whose `anchor_quote` passes `verify_quote` against the source).
- **Score spread ≥20** between junior and senior on the 2 test fixtures.
- **JSON-mode survival rate ≥90%** (pydantic-validates on first try).
- **Per-call p50 ≤8s** on M1.

If any gate fails, switch to the documented fallback (Claude Sonnet 4.6 via Anthropic SDK — `llm.py` is structured to swap clients behind one interface) and re-run the spike. Add a paragraph to README "Decisions" about the swap if it happens.

### L1 — Ingestion (~30 min, parallel inside the level)
Files: `src/gander/ingest.py`
- `extract_text(file_bytes, filename) -> str` — dispatch on suffix; pypdf → fallback pdfplumber if empty.
- Scanned-PDF detection: if total extracted text < 100 chars and PDF has pages, raise `StageFailure("This appears to be a scanned PDF...")`.
- Format detection: unknown suffix → `StageFailure("Unable to read this file...")`.
- Tests: real PDF, real DOCX, deliberately-corrupt bytes, image-only PDF fixture.

### L2 — PII Redaction (~30 min, regex-only by default)
Files: `src/gander/redact.py`
- Regex pass: emails, phone numbers (international + US), URLs, postal codes, common name patterns ("Name: X", header-line all-caps name detection).
- **Date redaction**: `19xx`/`20xx` four-digit year *inside a date-like context* (e.g., adjacent to a month name or a `–` range) → `[YEAR]`. Must not eat "Python 3.10" / "C++17".
- LLM pass: **deferred to optional**. v1 promised an `MiniMax-M2.7-highspeed` name/address pass. Cost: extra model surface, extra failure mode, extra latency. v2 default: ship with regex-only and disclose the limitation in README. Re-enable only if regex misses on real fixtures.
- Output: `RedactedCV(text, audit_log: list[Redaction])`.
- Tests: known-name CV, already-anonymized CV, year-only-no-context (should NOT redact "Python 3.10" or "C++17"); audit log must cover at least name + email on each fixture.

### L3 — Profile Extraction (~45 min)
Files: `src/gander/extract.py`
- One MiniMax-M2.7-highspeed call via `llm.complete_json()` with JSON mode + Pydantic schema in the system prompt. System prompt: "extract the candidate's profile. For each item, copy the EXACT substring from the CV that supports it into `anchor_quote` — do not paraphrase."
- Pydantic-validate; for each item with an `anchor_quote`, call `verify_quote` → drop unverified items, log drop count.
- Tests: golden-output snapshot per fixture CV; assertion that >80% of items survive verification (MiniMax may need a stronger anti-paraphrase instruction than Claude — adjust if survival rate is low).

### L4a — Seniority Scorer (~45 min, **runs concurrently with L4b**)
Files: `src/gander/score.py`
- **One** structured M1 call producing all four `Component(name, score_0_100, justification, anchor_quote)` items in a single response. (v1 listed "four calls or one" — v2 picks one to honor the latency budget.)
- `verify_quote` on each component's anchor; unverified components are dropped (the user sees a shorter list, per §4.5).
- Aggregation: documented weighted sum (`0.35 skills, 0.30 experience, 0.20 education, 0.15 soft`) — weights live in a constant; both rendered in the report UI (collapsible "How is this scored?" panel) and linked from the README.
- Pipeline orchestrator runs L4a and L4b inside `await asyncio.gather(score_async(...), salary_async(...))`.
- Tests: per fixture CV the score lands in expected band (junior < 40, mid 40–70, senior > 70); aggregation math deterministic; **calibration test** — same fixture run 3× with `temperature=0` → score variance ≤5.

### L4b — Salary Search + Estimate (~75 min, **runs concurrently with L4a**)
Files: `src/gander/salary.py`
- Build 2–3 search queries from `Profile` (role title + seniority hint + location guessed from CV).
- **Localization**: if location resolves to Czech Republic (default for this corpus), queries target CZ aggregators with CZK monthly gross output. Example queries: `"senior data scientist plat Praha 2025 site:platy.cz OR site:profesia.cz"`, `"machine learning engineer salary czech republic site:glassdoor.com"`, `"senior data engineer mzda CZK"`. For senior roles, add an EUR cross-check query (`"senior ML engineer salary EUR remote europe"`) so the estimator can sanity-check ranges. Fallback location is "Europe" only if no signal at all.
- DDG search via `ddgs.DDGS().text(query, max_results=8)`. **Fail-fast retry**: max 2 attempts with short backoff (1s, 2s + jitter). Rate-limited HF egress IPs won't recover via retry — better to trip §4.6 quickly than burn the latency budget.
- Combine results across queries, dedupe by URL, keep top 8.
- Estimator call (M1, `temperature=0`): input is merged snippets + URLs; output is `SalaryEstimate(low, high, currency, period, sources: list[Source])`. Each source carries the URL DDG returned **and** the snippet excerpt the estimator cited.
- If <2 sources usable → raise `StageFailure("Insufficient market data for this profile.")` (per §4.6).
- Tests: VCR-recorded DDG fixture per role level; assert sources have URLs; assert `low < high`; assert currency+period present; mock DDG raising / returning [] → assert `StageFailure` propagates with right message.

### L4c — Confidence Judge (~45 min, **architecturally separate, recompute-then-compare**)
Files: `src/gander/confidence.py`

The v1 design ("separate prompt, same model, same provider") was correctly flagged as theatre by the AI/ML review — same RLHF distribution will rubber-stamp itself. v2 isolates more aggressively:

1. **Different-model defense degraded.** v1 used `abab6.5s-chat` for L4c vs `MiniMax-M1` for L4b to break same-distribution self-grading; under M2.x highspeed-only (post-2026-05 catalog), both stages run on `MiniMax-M2.7-highspeed`. Isolation now relies on prompt structure + temperature 0 + the two-step protocol below. T12 should re-evaluate whether MiniMax exposes a sufficiently distinct sibling model (or revive a Claude Sonnet 4.6 fallback for L4c).
2. **Recompute first, compare second.** Two-step protocol inside `judge()`:
   - Step A: model receives `sources` only and outputs its own tier (Low/Med/High) by walking the rubric. Does NOT see the produced range.
   - Step B: model receives the produced `(low, high, currency, period)` plus its own Step-A tier and writes a one-paragraph rationale. If Step A's tier is Low, the rationale must include the words "insufficient" or "disagree". The final `Confidence.tier` is **always Step A's tier** — Step B can only write prose.
3. **Function signature**: `judge(sources: list[Source], low: int, high: int, currency: str, period: str) -> Confidence`. No parameter for the estimator's reasoning.
4. **Rubric** (in prompt): High = ≥3 independent sources agreeing within 25%; Medium = 2 sources OR wider agreement; Low = <2 sources OR disagreement >50%.
- **Tests**:
  - synthetic sources → assert Step-A tier matches rubric expectation;
  - **structural isolation test**: assert `inspect.signature(judge)` has only the five permitted parameters (drops the v1 token-grep test, which false-positives on shared vocabulary);
  - golden test: when Step A returns Low, final `tier == "Low"` regardless of Step B's text.

### L5 — Growth Plan (~60 min)
Files: `src/gander/growth.py`
- One M1 call (`temperature=0`). Input: profile + score components (especially low ones) + current salary midpoint. System prompt explicitly enumerates anti-slop rules ("do not propose: PhD, founding a company, generic 'improve communication'") and demands each action reference a specific phrase from the CV.
- Output: 3–5 `GrowthAction(what, time_horizon_months, mechanism, anchor_quote)`. Schema constrains `time_horizon_months ∈ [1, 24]` — Pydantic rejects out-of-range; no duplicate runtime check (dead code in v1).
- Validations:
  1. `verify_quote` on anchor → drop unverified.
  2. **Runtime n-gram smoke check**: for the round-2 reviewer's CV, compute Jaccard 4-gram overlap of each new action's `what` against the 3 fixture CVs' growth plans; if any pair >0.6, log a `growth.possible_boilerplate` warning. (Test catches this offline; smoke check catches it live.)
- Tests: per fixture, ≥3 actions survive verification; anchors all substring-match; (acceptance test §M4 asserts cross-CV uniqueness via Jaccard).

### L6 — Report Assembly + Orchestration (~45 min)
Files: `src/gander/report.py`, `src/gander/pipeline.py`

**Orchestrator** (`pipeline.run(file_bytes, filename) -> AsyncIterator[Report]`):
1. L1 → L2 → L3 sequentially. If L1 or L2 fails → yield top-level failure Report and stop.
2. `await asyncio.gather(L4a_score(profile), L4b_salary(profile))` — both run concurrently, each yielding an intermediate Report state when done.
3. **Conditional L4c**: only call `confidence.judge(...)` if L4b returned `SalaryEstimate`. If L4b is a `StageFailure`, set `Confidence(tier="Low", rationale="Insufficient market data — see salary block.")` directly. (Closes the v1 bug: L4c's signature wants `Source` objects, not `StageFailure`.)
4. **Conditional L5**: only call growth-plan if L4a (score) succeeded. If both L4a and L4b failed, render growth plan as `StageFailure("Cannot generate growth plan without scoring or salary baseline.")`.
5. Yield the final `Report`.

**`Report`** carries every block plus a `StageStatus` enum (`pending|running|done|failed`) per block, so each yielded state is a complete UI snapshot — no block ever "stuck on running" because every yield reasserts the world.

**Tests**: `test_partial_failure_streaming` consumes the async iterator with mocked stage failures injected at each level → assert (a) no traceback escapes, (b) final state has no block in `running`, (c) the assembler emits the correct user-facing copy per failure case.

### L7 — UI / Gradio (Track B, runs parallel to A) — pattern locked in v2
Files: `app.py` (expanded), `src/gander/ui.py` (renderers)

**Layout** (`gr.Blocks`):
- File upload (`gr.File`, `.pdf`/`.docx`, 10 MB cap) + helper text: "PDF or DOCX, max 10 MB. Your CV is processed in-memory and not stored."
- "Generate report" button.
- **Stage tracker** (`gr.HTML`): five horizontal pills — `Parse · Redact · Score · Salary · Plan` — each transitioning `pending → running → done | failed` as the pipeline progresses. CSS-only, ~30 lines, animation gated on `prefers-reduced-motion`. **This is the first-10s impression** the hiring reviewer should land on (PRD §9).
- **Report body** (`gr.Markdown`): rendered from the current `Report` state.

**Streaming pattern** (locked, no `gr.Progress` conflation):
- The handler bound to the button click is an async generator: `async def run(file): async for report in pipeline.run(file): yield render_tracker(report), render_body(report)`.
- `outputs=[stage_tracker_html, report_markdown]` — two outputs, two values per yield. Each yield re-renders both from the same `Report` state, so the UI is a pure function of state.
- No thread-locals, no `gr.Progress` — the queue/async story Just Works because every yield reasserts the world.

**Renderers** (`ui.py`):
- `render_tracker(report) -> str` (HTML): one pill per stage with `class="pill done|running|failed|pending"`.
- `render_body(report) -> str` (Markdown):
  - **Score**: top-line number + a table of components (`Skills 78 | Experience 72 | Education 65 | Soft 70`), with each row's justification in a `<details>` (first row open by default — the reviewer sees one verified quote immediately as credibility proof).
  - **Salary**: range + currency + period + Confidence badge (`[!] High` / `[~] Medium` / `[?] Low` — text+icon, not color alone) + rationale + source list rendered as `[domain.com] — "snippet excerpt the estimator cited…"` (not bare URLs).
  - **Growth plan**: numbered list, each item `**What** — *N months* — Mechanism`.
  - **Failure blocks**: rendered inline as a callout with the §4.6 user-facing copy. Top-level failures (L1/L2) replace the whole body. No tracebacks ever surface — they go to `obs.py` logs only.
  - **Footer**: link to "How is this scored?" (collapsible), exposing the aggregation weights and the per-stage cost+latency from `obs.py`.

### L8 — Testing & Acceptance Verification (Track C, runs parallel)
Files: `tests/`
- `tests/fixtures/cvs/` — three real anonymized public CVs (see §"CV Fixture Sourcing"). Kept as both `.pdf` and `.txt`. **At least one fixture must be a messy real-world Word→PDF export** (two-column or footer cruft) to stress L1's `pdfplumber` fallback — not all clean LaTeX templates, which would be overfit.
- `test_unit.py` — every module's pure functions.
- `test_pipeline.py` — end-to-end on each fixture (VCR-cached MiniMax + DDG; documented re-record command).
- `test_acceptance.py` — encodes PRD §5, **with v2 strengthening**:
  - `test_score_spread_at_least_30()` — junior vs senior score delta ≥ 30.
  - `test_salary_ranges_dont_overlap()` — `senior.low > junior.high`.
  - `test_no_growth_plan_verbatim_repeats()` — no `GrowthAction.what` string appears verbatim across CVs.
  - **`test_no_growth_plan_near_duplicates()`** *(new)* — Jaccard 4-gram overlap between any two `what` strings across CVs must be < 0.4. Catches the slop the verbatim test misses.
  - **`test_growth_plan_anchors_distinct()`** *(new)* — each `anchor_quote` must be unique to its source CV (no shared anchor strings across the 3 reports).
  - **`test_score_calibration()`** *(new)* — run mid fixture 3× with `temperature=0` → score variance ≤ 5.
  - `test_all_claims_substring_verified()` — every `anchor_quote` in every report passes `verify_quote` against its source CV (with section-locality where applicable).
  - **`test_per_run_cost_budget()`** *(new)* — sum of `usd_cost` events per pipeline run is below a documented ceiling (e.g., $0.05 with M1 profile, $0.02 with `ci` profile). README quotes both numbers.
- `test_failures.py` — corrupt PDF, image-only PDF, DDG-empty, DDG-raises, model-returns-garbage, mock L4b failure → assert L4c short-circuits to Low, mock both L4a+L4b fail → assert L5 short-circuits with proper message. All assert no traceback.
- `test_partial_failure_streaming.py` — consumes `pipeline.run()` with injected mid-stream failures → asserts (a) every yielded `Report` is renderable, (b) final state has no block in `running`.
- `test_confidence_judge.py` — synthetic-source scenarios → assert tier mapping; **structural isolation test** asserting `inspect.signature(judge)` has only the five permitted parameters (replaces v1's noisy token-grep test); golden test for "Step A Low ⇒ final tier Low".
- **`test_bias_smoke.py`** *(new, CZ-localized)* — pair-test: mid-fixture with "MFF UK / Charles University" header vs same fixture with university line redacted → assert the score delta is ≤ 3 points. Surfaces the CZ-specific school-prestige bias risk (PRD §4.7).
- **Pytest markers**: `@pytest.mark.fast` on pure-function unit tests (no IO); `@pytest.mark.slow` on pipeline-level tests; `@pytest.mark.live` on tests that hit MiniMax/DDG. Pre-commit runs `-m fast` only; CI runs `-m "not slow"` (or `-m ""` if user wants the full live suite per directive — see L9 CI config).

### L9 — Deployment + README (Track D)
Files: `README.md` (with HF Space metadata in YAML frontmatter — there is no separate `huggingface.yaml`), `.env.example`, `requirements.txt`, `.github/workflows/warm-keeper.yml`
- **HF Space setup**: create a Gradio Space, sync from GitHub repo (or push directly to HF), set `MINIMAX_API_KEY` as a Space secret. Frontmatter (`sdk: gradio`, `app_file: app.py`, `python_version: 3.11`). Public URL goes at top of README.
- **Warm-keeper**: `.github/workflows/warm-keeper.yml` runs every 5 min, HEADs the Space URL. Free, keeps Space hot through the whole review window — including round-2 share-screen.
- **CI**: `.github/workflows/ci.yml` on every PR/push: lint, format check, mypy, full pytest with **live MiniMax + live DDG** (per user directive). Repo secrets: `MINIMAX_API_KEY`. Concurrency: 1. Env: `GANDER_MODEL_PROFILE=ci` to swap M1→`MiniMax-M2.7-highspeed` where reasoning is dispensable, keeping CI cost <$0.50/run.
  - **2026-05-15 update**: live CI flipped to OpenRouter (matches the HF Space provider). Repo secret is now `OPENROUTER_API_KEY`; the MiniMax `live` job is gone. See the §L0 CI bullet for the full update.
- **Local-run**: `uv sync && MINIMAX_API_KEY=... uv run python app.py` (one command after `.env` is filled).
- **Eval corpus**: `uv run python scripts/eval_corpus.py` writes `reports/SUMMARY.md` and one report per CV. README documents this as the recommended manual gauging step before submission.
- **README sections** (the Decisions section is load-bearing — written in author voice, not box-checking the PRD back):
  - **Run** — hosted URL **above the fold** with a one-line note: "First request may take ~20s if the Space is asleep — the warm-keeper cron usually prevents this."
  - **How the pipeline works** — DAG image + stage descriptions with explicit callouts for: (a) confidence judged by a *different model* with a *recompute-then-compare* protocol; (b) every claim is a substring-verified anchor with section-locality; (c) per-stage cost+latency surfaced in the UI footer.
  - **Decisions** — written in first person, ~600 words, covering:
    - **MiniMax + token plan**: why use a non-frontier provider in an AI-first hiring case study. Honest framing — token plan made it cheap, the L0.5 spike validated it's good enough for this task, and using a less-obvious provider is what the §1.4 "creativity in approach" priority rewards. Includes the spike result.
    - **DuckDuckGo over paid search**: zero-setup ethos extends from the reviewer to the build itself; trades reliability for one-click reproducibility; tradeoff noted with the §4.6 fallback as the safety net.
    - **Gradio + HF Spaces**: AI-community surface, free, single-file deploy.
    - **Structural PII redaction with regex-only default**: chosen over LLM-based redaction to remove a failure mode and a model-cost surface; explicit on what's redacted and what's not.
    - **Cuts**: no OCR (loud failure), no auth/persistence, no batch, no LLM-PII pass, no multi-language. Each with a one-line *why we cut*.
    - **What this cost**: per-run USD figure from `test_per_run_cost_budget`.
  - **Bias acknowledgment** — author-voice expansion of PRD §4.7 (not a paste): what we structurally remove, what bias-encoding signals remain (employer prestige, language patterns, school names not removed by regex), the bias-smoke test result, and the explicit framing that outputs are *candidate hypotheses for the reviewer to validate*.
  - **Limitations** — single-language, no OCR, DDG availability dependency, MiniMax not benchmarked against frontier on CV reasoning, no fairness validation across protected groups.

---

## Critical Files (full list)

```
pyproject.toml
requirements.txt                    # uv-exported, for HF Spaces
README.md                           # incl. HF Space frontmatter; Decisions section is load-bearing
.env.example                        # MINIMAX_API_KEY=... (and optional ANTHROPIC_API_KEY for fallback)
.github/workflows/warm-keeper.yml   # 5-min cron HEAD to Space URL (cold-start mitigation)
app.py                              # Gradio entrypoint (Track B)
src/gander/__init__.py
src/gander/schemas.py               # Pydantic contracts (L0); StageStatus enum
src/gander/verify.py                # substring verifier (L0); ≥6w+unique OR ≥8w; section-locality
src/gander/obs.py                   # structlog + cost/latency telemetry (L0)
src/gander/errors.py                # StageFailure + boundary decorator (L0)
src/gander/llm.py                   # async OpenAI-SDK wrapper for MiniMax (+Claude fallback iface)
src/gander/ingest.py                # L1
src/gander/redact.py                # L2 (regex-only by default)
src/gander/extract.py               # L3
src/gander/score.py                 # L4a (one structured call)
src/gander/salary.py                # L4b (DDG fail-fast + estimator)
src/gander/confidence.py            # L4c (MiniMax-M2.7-highspeed + recompute-then-compare)
src/gander/growth.py                # L5
src/gander/report.py                # L6 renderer
src/gander/pipeline.py              # L6 orchestrator (async iterator, conditional flow)
src/gander/ui.py                    # Gradio renderers + stage-tracker HTML (L7)
src/gander/prompts/                 # one .md per stage prompt
scripts/spike_minimax.py            # L0.5 capability spike script
scripts/eval_corpus.py              # 10-CV manual gauging runner (live pipeline)
.pre-commit-config.yaml             # ruff + mypy + pytest -m fast
.github/workflows/ci.yml            # live pytest on every PR
.github/workflows/warm-keeper.yml   # Space cold-start mitigation
tests/conftest.py
tests/fixtures/cvs/{01..10}_*.{pdf,docx,txt}   # 10 CZ data/DS/ML CVs (5 PDF + 5 DOCX)
tests/fixtures/cvs/SOURCES.md       # synthesis prompts + anchors + format-stress notes
tests/test_unit.py                  # @pytest.mark.fast where possible
tests/test_pipeline.py              # @pytest.mark.live (hits MiniMax + DDG)
tests/test_acceptance.py            # encodes PRD §5 + v2 strengthening
tests/test_failures.py
tests/test_partial_failure_streaming.py
tests/test_confidence_judge.py      # structural isolation + recompute-protocol golden
tests/test_bias_smoke.py            # CZ school (MFF UK / Charles University) pair test
reports/                       # gitignored; populated by scripts/eval_corpus.py
tasks/todo.md                       # checked off as work proceeds
```

## CV Corpus (Track E, ~2.5h) — 10 synthesized CZ data/DS/ML CVs

Authored by me, spanning the seniority spectrum and the role spectrum so both the §5.4 acceptance triplet and the user's manual gauging corpus get exercised.

**Composition (10 total):**

| # | Role | Seniority | Format | Used for |
|---|---|---|---|---|
| 1 | Junior Data Analyst | 1 yr, 1 role | DOCX | acceptance: junior |
| 2 | Marketing Analyst → Data Analyst | 3 yrs | PDF (clean LaTeX) | gauging |
| 3 | Data Scientist (mid) | 5 yrs, 2 roles | PDF (clean) | acceptance: mid |
| 4 | ML Engineer (mid) | 6 yrs | DOCX | gauging |
| 5 | MLOps / Platform | 7 yrs | PDF (messy Word→PDF, footer cruft) | gauging — stresses pdfplumber fallback |
| 6 | NLP-focused DS | 8 yrs | DOCX | gauging |
| 7 | Senior Data Scientist | 10 yrs, leadership | PDF (clean) | gauging |
| 8 | Staff ML Engineer | 13 yrs | PDF (two-column messy) | acceptance: senior |
| 9 | Research Scientist (PhD) | 12 yrs, academia→industry | PDF (clean) | gauging — tests Czech Republic academic prestige signal handling |
| 10 | Head of Data | 15 yrs, leadership-heavy | DOCX | gauging |

**Authoring rules:**
- All Czech Republic context: employers are real CZ companies (Avast, Kiwi.com, Productboard, Rohlik, Mall.cz, ČSOB, T-Mobile CZ, etc.) or plausible CZ-based subsidiaries; universities are CZ (MFF UK, ČVUT FIT/FEL, VŠE, MUNI, VUT Brno); cities Prague / Brno / Ostrava / Plzeň. Salary expectations and role titles match the local market.
- All names are clearly fictional (e.g., "Jan Novotný", "Petra Svobodová") — not real CZ professionals.
- Each CV embeds 5–15 verifiable specifics (project names, tech stack versions, metrics like "reduced churn by 18%") that downstream stages can anchor `verify_quote` against. This is what makes the differentiation tests meaningful.
- Format diversity: 5 PDFs + 5 DOCX. Within PDFs: 3 clean (LaTeX-style), 2 messy (Word→PDF with two-column or footer cruft).
- File naming: `tests/fixtures/cvs/{01_junior_da_novotny,02_da_svoboda,...}.{pdf,docx}` plus `.txt` extracted golden text alongside each.
- **Provenance log** at `tests/fixtures/cvs/SOURCES.md` — for each CV: synthesis prompt summary, role/seniority targets, the 5–15 verifiable anchors, and the format-stress purpose. Demonstrates the §1.4 "creativity in sourcing data" lens (synthesis-with-deliberate-design beats unfiltered scraping).

**Calibration check** (during authoring, not a CI test): the 3 acceptance fixtures (junior/mid/senior, rows 1/3/8) must show monotonically increasing market salary expectations — junior <50k CZK/mo, mid 70–110k, senior 130–200k — so the §5.4 non-overlap test has real signal to discriminate against.

## Eval corpus runner — `scripts/eval_corpus.py` (~45 min)

User-facing gauging tool, separate from pytest:

```
uv run python scripts/eval_corpus.py
```

- Iterates over all 10 fixtures (PDFs and DOCX).
- Runs each through the **live** pipeline end-to-end (real MiniMax + real DDG) — true e2e smoke, not VCR replay.
- Writes per-CV report to `reports/<cv_name>.md` (the same Markdown the Gradio UI would render, plus a header line with file format and timing).
- Writes `reports/SUMMARY.md` — a table:

  | # | CV | Format | Score | Salary (CZK/mo) | Confidence | Top growth action | Cost (USD) | Latency (s) |
  |---|---|---|---|---|---|---|---|---|

- Total wall time logged so user can sanity-check the 60s SLA on real data.
- Exit non-zero if any CV failed to produce a report (so it doubles as a reliability smoke test).

---

## Verification Plan (how we prove it works)

1. **Unit-level**: pytest green on every module.
2. **Integration**: `pytest tests/test_pipeline.py` runs end-to-end against the three fixture CVs using VCR-cached APIs (deterministic in CI; live on demand).
3. **Acceptance**: `pytest tests/test_acceptance.py` directly encodes PRD §5 — if this passes, the submission meets the brief's quality bar.
4. **Failure paths**: `pytest tests/test_failures.py` proves §4.6 graceful degradation.
5. **Hallucination guard**: `test_all_claims_substring_verified()` walks every report and asserts every `anchor_quote` is in its source CV.
6. **End-to-end manual**: Open the hosted URL, upload each of the 3 fixture CVs, screenshot the reports for the README. Repeat with one personal CV (round-2 simulation).
7. **Cold-start**: time the hosted URL from a fresh browser session — first byte to first stage event should be <5s, full report <60s. If not, pre-warm or downgrade the redactor to regex-only.

---

## Risks & Mitigations (v2)

| Risk | Mitigation |
|---|---|
| HF Space cold start (§8) | **GitHub Actions warm-keeper cron every 5 min** keeps the Space hot through review window (incl. round-2). README leads with "first request may take ~20s if the Space is asleep" so expectation is set. |
| Per-run latency busts 60s SLA | Latency budget table costed before build; L4a/L4b run via `asyncio.gather`; L4a collapsed to one structured call; L0.5 spike validates p50; downgrade-to-`MiniMax-M2.7-highspeed` path documented if M1 is too slow. |
| DDG rate-limits on HF Spaces shared egress | **Fail-fast** (max 2 retries, short backoff), trip §4.6 "Insufficient market data" quickly rather than burning the latency budget. |
| MiniMax structured-output unreliable | L0.5 capability spike with hard gates (≥70% literal-quote rate, ≥90% JSON-mode survival). Documented swap path to Claude Sonnet 4.6 if gates fail. `llm.py` interface designed for swap. |
| Confidence judge rubber-stamps the estimator | **Recompute-then-compare protocol** (Step A computes tier from sources alone before Step B sees the range) + structural signature isolation + temperature 0. _Different-model isolation degraded post-2026-05 (M2.x highspeed-only); revisit in T12._ |
| Hallucinated quotes pass `verify_quote` by chance | ≥6 words AND positionally unique, OR ≥8 words; section-locality where applicable. |
| Growth plan goes generic across CVs | Verbatim-repeat test + **Jaccard 4-gram overlap test** + per-action anchor-uniqueness test + runtime n-gram smoke check. Anti-slop rules in the system prompt explicitly enumerate forbidden recommendations (PhD, found-a-company, generic). |
| Salary data sparse | §4.6 path: confidence Low + "insufficient market data" copy, rest of report renders. |
| L4c crashes when L4b failed | L6 orchestrator **short-circuits**: skip judge, render Low directly. L5 short-circuits if both L4a+L4b failed. Asserted in `test_partial_failure_streaming`. |
| Anonymized CVs hide surprise PII | Manual review during fixture authoring; redactor runs over fixtures in test setup; audit log asserted to cover name+email per fixture. |
| L1 only tested against clean LaTeX PDFs → round-2 surprise | At least one fixture is a messy real-world Word→PDF export. |
| Build budget overrun | L0.5 spike + L4a single-call + asyncio L4a/L4b recover budget. Latency-budget table is the early-warning system: re-cost after L0.5 and cut a stage if over. |

---

## Decisions (confirmed)

- **Framework + hosting**: Gradio on Hugging Face Spaces.
- **LLM**: MiniMax via OpenAI-compatible API (user's token plan), `MiniMax-M2.7-highspeed` for L3/L4a/L4b/L5, **`MiniMax-M2.7-highspeed` for L4c** (different model breaks same-distribution self-grading). L2 is regex-only by default. Documented Claude Sonnet 4.6 fallback path if L0.5 spike fails.
- **Search**: DuckDuckGo via `ddgs` (no API key; fail-fast policy on rate-limits).
- **Test CVs**: real anonymized public CVs, three levels, ≥1 messy real-world Word→PDF, sourcing logged in `tests/fixtures/cvs/SOURCES.md`.

## Deferred nits (acknowledged, not addressed in v2)

These were raised in review but didn't make the cut for the build budget. Listed so they're not silently dropped:

- Adversarial CV in eval set (deliberate paraphrase bait to exercise `verify_quote`).
- Prompt-version hash in `Report` for prompt-regression traceability.
- Per-run cost telemetry expanded to per-stage cost waterfall in the UI footer (currently just total).
- Triangulating salary with a public dataset (e.g., HF Hub) on top of DDG snippets.

## Keep model layers explicit

`CLAUDE.md` and `.claude/agents/*` distinguish the two model layers: Claude/Opus is the coding-agent infrastructure used to build and review the repo; MiniMax is the application runtime provider used by the submitted app. Claude Sonnet 4.6 is only an application fallback if the T05 MiniMax capability spike fails.

---

## Execution kickoff (user-directed sequence)

The user wants the planning artifacts in the repo first, then a granular task decomposition that agents can pick up in parallel. Order of operations on exit:

**Step 1 — Land the design doc in the repo (~5 min, sequential).**
- Copy this entire plan file to `tasks/PLAN.md`. Reviewers and round-2 share-screen get the full architecture context from the repo, not from a hidden home-directory file.
- The `~/.claude/plans/...` file remains the planning workspace; `tasks/PLAN.md` is the source of truth from now on.

**Step 2 — Decompose into discrete pickup-able task files in `tasks/` (~20 min, sequential).**

Every task is its own `tasks/T<NN>_<name>.md` file with a uniform shape so any agent can grab one without prior context:

```
# T<NN> — <title>
Status: todo | wip | done
Owner: software-engineer | ux-engineer | ai-ml-engineer | qa-engineer | (unassigned)
Depends on: T<NN>, T<NN>
Unblocks: T<NN>, T<NN>
Estimate: ~Nh

## Goal
<1–2 sentences>

## Inputs (contract from upstream tasks)
- <type/file/symbol the task can rely on>

## Outputs (contract for downstream tasks)
- <files created, public functions exported, schema fields delivered>

## Deliverables
- [ ] <file or change>
- [ ] <test added>

## Verification
- <how the task confirms it's done — pytest target, manual run, etc.>

## Reference
- tasks/PLAN.md §<section>
```

**Task DAG** (each entry is a separate file):

| ID | Title | Depends on | Parallel-ready after |
|---|---|---|---|
| **T00** | Project bootstrap — pyproject, uv, dirs, .gitignore, .env.example | — | start |
| **T01** | Schemas + StageFailure (contracts everything else compiles against) | T00 | T00 |
| **T02** | Cross-cutting utils — `verify`, `obs`, `errors`, `llm` async client | T01 | T01 |
| **T03** | CI + pre-commit scaffolds — `ci.yml`, `warm-keeper.yml`, `.pre-commit-config.yaml` | T00 | T00 (parallel with T01/T02) |
| **T04** | CV corpus part 1 — synthesize + render CV #1 (junior) and #8 (senior) | T00 | T00 (parallel) |
| **T05** | MiniMax capability spike — `scripts/spike_minimax.py`, hard gates, swap path | T02, T04 | after T02 + T04 |
| **T06** | CV corpus part 2 — synthesize + render CVs #2–7, #9, #10 + `SOURCES.md` | T04 | after T04 (parallel with T05+) |
| **T07** | L1 ingestion — pypdf/pdfplumber/python-docx + scanned-PDF detection | T02 | after T05 (gate) |
| **T08** | L2 PII redaction — regex-only default + audit log | T02 | after T05 |
| **T09** | L3 profile extract — single M1 JSON-mode call + verify_quote | T02 | after T05 |
| **T10** | L4a seniority scorer — single structured call + calibration | T02 | after T05 |
| **T11** | L4b salary search + estimate — DDG fail-fast + CZ localization | T02 | after T05 |
| **T12** | L4c confidence judge — recompute-then-compare + MiniMax-M2.7-highspeed | T02 | after T05 |
| **T13** | L5 growth plan — anti-slop prompt + Jaccard runtime smoke | T02 | after T05 |
| **T14** | L6 report renderer (`report.py`) — markdown + tracker HTML | T01 | after T01 (parallel) |
| **T15** | L6 pipeline orchestrator (`pipeline.py`) — async iterator, conditional flow | T07–T13 | after T07–T13 |
| **T16** | L7 Gradio UI (`app.py`, `ui.py`) — stage tracker pills + streaming | T14 | after T14 (mock pipeline first) |
| **T17** | L8 acceptance tests — spread, non-overlap, Jaccard, calibration, anchor uniqueness, cost budget | T15 | after T15 |
| **T18** | L8 failure-path + partial-failure-streaming tests | T15 | after T15 |
| **T19** | L8 confidence-judge tests — structural isolation + recompute golden | T12 | after T12 |
| **T20** | L8 bias smoke test — CZ school prestige pair-test | T15, T06 | after T15 + T06 |
| **T21** | `scripts/eval_corpus.py` — 10-CV live runner + `SUMMARY.md` | T15, T06 | after T15 + T06 |
| **T22** | L9 HF Space + secrets wiring | T16 | after T16 |
| **T23** | L9 README incl. load-bearing Decisions section | T17–T22 | end |

**Step 3 — Begin execution.**
- T00 → T01 → T02 sequentially (foundation has no parallelism inside it).
- **T03 + T04 can run in parallel** with T01/T02 (CI scaffolds and first 2 CVs don't depend on schemas).
- After T02 + T04 land, fire **T05 (spike)** as a gate.
- If spike passes, **T06–T14 can run in parallel** (8 tasks). This is the high-parallelism phase. Worktree-isolated agents (`isolation: "worktree"` in the Agent tool) prevent stomping.
- T15 (orchestrator) is the integration choke-point.
- T16 onwards is the last mile.

**Per-task agent assignment** is decided at pickup-time based on which agents are free; the task file's `Owner` field is a recommendation, not a constraint.

**`tasks/lessons.md`** already exists; appended whenever a user correction yields a durable rule (per CLAUDE.md §4).
