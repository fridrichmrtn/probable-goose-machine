# Prod-readiness & refactor plan

Prioritized roadmap from the prod-readiness review, reevaluated against main on
2026-06-12 (post T46/T49/T50, PR #40). Refactor/hygiene items from the bloat
audit are folded in as the R-series with explicit dispositions. Constraint in
effect: prototype budget — no paid services; engineering-time fixes only.

P0.1–P0.5 and R1 implemented on `dev/prod-readiness-p0` (T51); run report in
`tasks/T51_dev-report.md`, review-burst leftovers in `tasks/backlog.md`
(`prod-readiness-p0` block).

Status legend: `[ ]` open · `[x]` done · `[~]` partially done.

## Already closed (for the record)

- [x] LLM timeouts on all request paths (`_llm_timeout_s` deadlines, T49).
- [x] Vision fan-out cap (`GANDER_VISION_MAX_PAGES`, default 8) + vision concurrency semaphore.
- [x] `detected_country` no longer defaults to "CZ"; salary stage is multi-market (T46) with configurable DDG backends + auto fallback.
- [x] Growth anchor-survival flake root-caused: survivors pool across retries, stage degrades to partial instead of failing (T50). CI `--reruns 1` remains — see P2.3.
- [x] Deploy gated behind full CI + post-deploy health check (PR #40).
- [x] Pre-upload disclosure names OpenRouter/Gemini and retention (gap: DDG not named — closed by P0.5).
- [x] EN-triplet acceptance suite in CI + CZ-language suite (fixtures 11–13).
- [x] Dark-mode disabled-button contrast (light mode still failing — P2.1).

## P0 — before any prod exposure

- [x] **P0.1 — MarketSpec: growth/market coherence** *(top item — escalated)*
  `prompts/growth.md` was hardcoded to "Czech-market candidate"/CZ-market
  mechanics/CZK examples while salary resolves 50+ markets (T46). Done (T51,
  70f13b7 + heal ac4e43e): frozen `MarketSpec` (country, country_name,
  currency, period, resolution provenance `cv_explicit|inferred|default`) in
  new `market.py` with a single `_COUNTRY_INFO` source-of-truth table;
  `_resolve_country`/currency/period hoisted out of `salary.py`; growth prompt
  templated from the spec; provenance feeds the confidence floor (`default`
  caps at Medium). Absorbed the R2 salary.py restructure.
- [x] **P0.2 — Adversarial-input bundle** *(T51, c7d63a0)*
  - Untrusted-data instruction in `extract.md`, `score.md`, `salary.md`
    (heal: growth.md guard hoisted to top placement, salary.md guard
    broadened to "evidence only").
  - Prompt-injection regression tests (`tests/test_adversarial.py`).
  - Magic-byte validation (`%PDF`, `PK\x03\x04`) before parsers in
    `ingest.py`.
  - Input-length cap `GANDER_MAX_INPUT_CHARS` (default 50,000, truncate not
    reject) before LLM stages.
- [x] **P0.3 — Event-loop & concurrency hygiene (remainder)** *(T51, 7679023)*
  - `asyncio.to_thread` around sync pypdf/docx/vision-render parsing.
  - Shared `LLMClient` via `get_client()` (`lru_cache`), 8 callsites swapped.
  - Gradio queue limits: `max_size=4`, `default_concurrency_limit=2`.
- [x] **P0.4 — Salary search: cache + honest messaging** *(T51, b9065ab +
  heal ac4e43e; free-tier only)*
  - In-memory DDG cache, `GANDER_DDG_CACHE_TTL_S` (default 7 days), 512-entry
    FIFO cap.
  - Typed `_RateLimitError` → rate-limit-specific user copy and
    `reason="ratelimited"` obs event.
  - No paid search APIs; optional self-hosted SearXNG later if scraping pain
    becomes chronic. Backlog: lock around the cache's read-check-write.
- [x] **P0.5 — PII posture (remainder)** *(T51, 855e7d4)*
  - `tests/test_privacy_obs.py` asserts CV text/PII never reaches `obs`
    events (scope: redact stage; backlog: extend to LLM stages).
  - `Report.raw_cv_text` dropped; UI gates on `redacted_cv_text`.
  - Redaction widened: US paren/dot phone formats, header-zone street
    addresses (first 20 lines).
  - DDG named as a processor in the pre-upload disclosure.

## P1 — first weeks

- [ ] **P1.1 — Honest AI framing in UI**: "About this report" banner
  (AI-generated estimate, bias limitation per PRD §4.7); render
  `seniority_band` next to the 0–100 score.
- [ ] **P1.2 — Keep/redo results**: Markdown download; clear stale report on
  new upload (`file_in.change` only toggles the button); cancel button.
- [ ] **P1.3 — Operability**: `run_id` (uuid4) threaded through every
  `obs.emit`; validate env vars at boot instead of first request — also fixes
  the T47 backlog item that tests need a stub `OPENROUTER_API_KEY` because
  `LLMClient()` raises in its constructor; add a Dockerfile.
- [ ] **P1.4 — Eval breadth (remainder)**: non-tech, career-changer, and
  non-CZ-market fixtures asserting graceful degradation; pin model slugs to
  dated versions.
- [ ] **P1.5 — Verify semantic gap**: `verify_quote` proves quote existence,
  not claim–quote compatibility ("Led a team" anchors to "Joined a team") —
  add a cheap-slot or lexical-overlap justification check + deliberately
  mismatched eval cases.

## P2 — fast follows

- [ ] **P2.1 — Accessibility**: light-mode disabled-button contrast (1.69:1);
  skipped-pill contrast (2.58:1); `aria-live` tracker re-announcing all pills
  every yield.
- [ ] **P2.2 — Salary context**: render canonical role + location above the
  range (verify whether T43 already covers this).
- [ ] **P2.3 — Drop the rerun crutch**: remove `--reruns 1` from
  `openrouter-live` and measure the post-T50 flake rate; keep only if data
  says so, with an updated comment.
- [ ] **P2.4 — Provider resilience**: second provider behind `gander.llm`;
  populate `MODEL_PRICES` then (OpenRouter path already uses
  provider-reported cost). Avoid `:free` model variants for CV content —
  data-use policies conflict with the privacy posture.

## R — refactor & hygiene (from the bloat audit, 2026-06-12)

Audit verified factually accurate (function sizes, MiniMax residue, LFS
state). Dispositions:

- [x] **R1 — MiniMax spike cleanup** *(T51, 4b46f38)*
  Deleted `scripts/spike_minimax.py` and `scripts/spikes/*` (OpenRouter-only
  since T41; findings recorded in `tasks/` spike reports — git history is the
  archive). Removed `extend-exclude = ["scripts/spikes"]` from
  `pyproject.toml`; fixed dangling references in docs.
- [~] **R2 — Oversized stage functions** *(fold into behavior changes — no
  standalone refactor PRs)*
  `salary.py` restructured as part of P0.1 (market resolution hoisted to
  `market.py`). `plan_growth` (202 ln), `score_profile` (200), `pipeline.run`
  (192) remain; `growth.py` is freshly T50-hardened — do not churn it without
  a behavior reason. Extract helpers opportunistically when a change next
  touches each file.
- [ ] **R3 — Split `LLMClient`** *(deferred)* 526 lines, but T49 just
  hardened it. Revisit only when P2.4 (second provider) forces the seam.
- ~~**R4 — type-ignore residue**~~ *(won't do)* ~7 ignores in all of `src/`,
  cited sites are comment-justified.
- ~~**R5 — LFS/repo hygiene**~~ *(already done)* README documents
  `git lfs pull`; CI checks out with `lfs: true`. Local checkouts may hold
  pointer text until `git lfs pull`.
