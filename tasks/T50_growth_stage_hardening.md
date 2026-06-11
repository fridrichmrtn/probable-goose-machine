# T50 — Growth-stage hardening (review-finding train)

Status: done
Owner: software-engineer
Depends on: T49 review run (33 confirmed findings F0–F32)
Unblocks: next live eval run with growth telemetry

## Goal

Close the verification gaps the T49 review found in the growth stage: false
drops (ban-phrase substring artifacts, title/location token leaks in the
closed-employer gate, shared-token suppression of same-company promotions),
false passes (stale `is_current` classification for end-year ≥ current year),
retry waste (per-attempt survivor reset discarding verified actions), and a
blind eval surface (no growth telemetry in `scripts/eval_corpus.py`).
PRD §4.4/§4.5/§4.6 binding throughout.

## Approach

Five-commit train, each commit leaving the suite green:

1. Surgical heuristic fixes — timeline `is_current` signals, `"phd"` word
   boundary, company-shaped candidate rule, shared-token inversion
   (F0, F1, F2, F3, F16, F17, F26).
2. Retry redesign — cross-attempt survivor pooling + degraded 1–2-action
   partial result instead of StageFailure (F6, F8, F18, F29 terminal-emit).
3. Prompt alignment (8-word anchor floor, section guidance) + softener
   enforcement (F7, F32, F13, F11).
4. Measurement — eval growth telemetry, missing tests, drop observability
   (F14, F20, F24, F25, F26 e2e, F27, F29 drop-event).
5. Plan B schema split — `setting`/`target_employer` declared by the model,
   keyword validation machinery deleted (F19, T39's deferred design).

Cross-commit churn is deliberate: commit 1 hardens code commit 5 deletes
(candidate rule, forward-setting inversion), so commits 1–4 stay independently
shippable if commit 5's live verification stalls. Commit 1 fixes that SURVIVE
commit 5: timeline `is_current`, employer-hint computation, `"phd"` boundary.
Fixes that are DELETED by commit 5: `_employer_match_candidates` shape rule,
`_violates_forward_setting` inversion (re-expressed as declared-setting tests).

## Critical files

- `src/gander/growth.py` — ban-phrase boundary, candidate rule, validator
  inversion; later pooling, softener gate, declared-setting check
- `src/gander/timeline.py` — `is_current` for end-year ≥ current year and
  open-ended ranges
- `src/gander/prompts/growth.md` — anchor length truth, section guidance,
  setting/target_employer schema (commit 5)
- `src/gander/schemas.py` — `GrowthAction.setting` / `target_employer`
  (commit 5)
- `scripts/eval_corpus.py` — growth telemetry columns + failure-rate exit
  (commit 4)
- `tests/test_growth_unit.py`, `tests/test_timeline.py`,
  `tests/test_eval_corpus.py` — regression pins per finding

## Step-by-step changes

### Commit 1 (this commit)

- `timeline.py`: `is_current` now fires on three ordered signals — present
  token (unchanged), empty RHS after the first dash (open-ended ranges
  `"2022 -"`, post-redaction `"[YEAR] -"`), and bare end-year ≥
  `date.today().year` (F17). Known accepted edge: a short bullet like
  `"- Shipped 2026 roadmap"` already false-positives as a date-range line
  today; the year signal now also marks it current — pre-existing
  false-positive class, blast radius unchanged (one extra hint entry).
  Documented limitation: closed hyphen/en-dash year ranges become
  `[YEAR] - [YEAR]` after redaction and stay classified closed; em-dash and
  open-ended ranges survive redaction with digits intact, so the new signals
  fire on real redacted input (redact.py out of scope).
- `growth.py` `_check_ban_phrase`: `"phd"` matches via `(?<!\w)phd` so
  "GraphDB"/"graph-database" no longer trip the ban (F0); trailing boundary
  stays open for "phds"/dotted "ph.d.". `_BAN_PHRASES` tuple unchanged
  (contractual). Residual: "Improve communication-layer throughput" still
  trips "improve communication" — inherent substring behavior on a
  contractual phrase, not the F0 artifact.
- `growth.py` `_employer_match_candidates`: only company-shaped header parts
  emit candidates. Shape evidence = legal suffix (`_LEGAL_SUFFIXES`, never
  emitted), digit/dot token (`alza.cz`, `O2`), or original-case all-caps
  token (`CSOB`, `TD`); zero-stopword catch-all keeps plain-name companies.
  `_COMPANY_STOPWORDS` extended with CZ location tokens. Kills the F1 leaks
  (title phrases, `machine`/`learning`, `czech`/`prague`) and adds the F3
  dot-split subtokens (`alza.cz` → `alza`).
- `growth.py` `_violates_forward_setting`: shared-token exclusion inverted —
  a token appearing in any CURRENT entry can never count as a closed hit, so
  same-company promotions are no longer suppressed (F2, F16, F26).

### Commits 2–5

See `tasks/T50_dev-plan.md` for the full per-commit specification; the
Outcome section below is filled in at commit 5.

## Verification

Per commit: `uv run pre-commit run --all-files`, `uv run mypy src/`,
`uv run pytest -q -m "not live"`. Environmental baseline: 32 pre-existing
failures from unresolved Git LFS fixture pointers (git-lfs not installed in
this environment) — failure set must not grow.

Commit 1 targeted: `uv run pytest -q tests/test_timeline.py
tests/test_growth_unit.py` — 5 new timeline tests, 4 ban-phrase tests
(2 test functions), 7 validator-repro tests green; all pre-existing
validator/ban pins green unchanged.

Live acceptance + `scripts/eval_corpus.py` run deferred to the orchestrator's
live verification pass (requires `OPENROUTER_API_KEY`).

## Risks

- Candidate-rule regression surface: a title-case multi-word company
  containing a role stopword ("Lead Ventures") emits nothing → gate silently
  off for that employer. Mitigated by the zero-stopword catch-all, commit 4's
  `growth_employer_hints` + per-reason drop telemetry, and commit 5 deleting
  the mechanism entirely. Stopword list not to grow beyond the named
  location tokens.
- Timeline year heuristic is time-dependent by design: `2022 - 2026` flips
  to closed on 2027-01-01 (correct — the range *is* closed then). Tests
  build years dynamically.
- Commit 5 schema break (`setting` required) touches every `GrowthAction(`
  construction; the enumerated site list in the dev plan is the checklist.
  Gemini must emit the new fields; `complete_json` validation-retry plus
  prompt examples cover it, live acceptance is the real gate.
- `eval_corpus.py` exit semantics (commit 4) are operator-only — no
  `.github/workflows` reference exists, CI unaffected. Checked-in
  `reports/SUMMARY.md` stays stale-format until the next live eval run.

## Outcome

Five-commit train landed on `dev/t50-growth-stage-hardening`; each commit left
pre-commit, mypy strict, and the non-live suite green (modulo the 32-failure
LFS-pointer environmental baseline, which never grew).

1. Surgical heuristic fixes — timeline `is_current` (present token, open-ended
   range, end-year ≥ current year), `"phd"` word boundary, company-shaped
   candidate rule, shared-token inversion (F0, F1, F2, F3, F16, F17, F26).
2. Retry redesign — cross-attempt survivor pooling keyed on normalized
   what+quote; degraded 1–2-action partial result with `growth_degraded`
   instead of StageFailure; `growth_attempt_error` keeps a failed top-up call
   from discarding pooled survivors (F6, F8, F18, F29). Deviation from the
   plan, by orchestrator decision: an attempt-2 LLM error with a non-empty
   pool degrades instead of failing; StageFailure is reserved for attempt-1
   errors and a zero pool.
3. Prompt alignment (8-word anchor floor, verbatim section-header guidance) +
   `_SOFTENER_RE` enforcement with `softener_phrase` drops (F7, F11, F13, F32).
4. Measurement — `growth_employer_hints` event, drop-event quote payloads,
   eval growth telemetry (GrowthStats, SUMMARY columns, 25% failure-rate exit
   gate), e2e pins for override/promotion keeps (F14, F20, F24, F25, F27, F29).
5. Plan B — `GrowthAction.setting` (required literal) + `target_employer`;
   `_setting_violation` validates the model's declaration
   (`unverified_target_employer` drops); the keyword machinery
   (`_FORWARD_MARKERS`, `_COMPANY_STOPWORDS`, `_employer_match_candidates`,
   `_violates_forward_setting`, …) deleted; prompt schema/rule-7/examples
   rewritten with all three settings; validator tests re-expressed as
   declared-setting tests (F19, T39's deferred design).

Not verified here: live acceptance and `scripts/eval_corpus.py` against real
model output (needs `OPENROUTER_API_KEY`) — Gemini actually emitting
`setting`/`target_employer` is gated on that run.
