# T50 — Growth-stage hardening (review-finding train)

Status: implemented — live verification pending (Gemini setting/target_employer emission + eval_corpus rerun)
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
tests/test_growth_unit.py` — 4 new timeline tests, 4 ban-phrase cases
(2 test functions) green; all pre-existing validator/ban pins green
unchanged. Commit 1's validator-repro tests were deleted in commit 5 along
with the keyword machinery; their behaviors are re-pinned by the
declared-setting `_setting_violation` tests in `tests/test_growth_unit.py`.

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

## PR review round (2026-06-11)

Inputs: 6 external comments on PR #39 (3 Copilot, 2 Codex, 1 author) plus a
multi-agent self-review (26 findings). Consolidated into one fix plan; the
rest deferred to `tasks/backlog.md`.

What changed:

- `timeline.py` — endpoint-only end-year rule: the first year-shaped token
  after the dash decides `is_current` (`[YEAR]` → closed, bare year compared
  to today, none → closed). Annotation years ("(extension option 2026)") no
  longer flip closed entries. Timeline tests rewritten to redaction-realistic
  shapes (em-dash ranges survive `redact.py`; hyphen/en-dash ranges become
  `[YEAR] - [YEAR]`).
- `growth.py` `_setting_violation` rework — dash-split hint segments plus the
  full header, token-sequence containment matching (fixes O2-style short
  employers and ING-vs-Consulting substring false matches), a >=2-alnum
  degenerate gate, a new `closed_employer_target` drop reason with its own
  retry-message branch, and silent `target_employer` sanitization on
  non-current settings.
- Drop/retry mechanics — `_action_key` on normalized `what` only (re-anchored
  duplicates dedup); `_QUOTE_SNIPPET_LIMIT = 120` applied to both the emit
  and the `_Drop` record; retry asks for "{needed} to {max_new} NEW
  action(s)" headroom instead of "exactly N".
- `eval_corpus.py` — captures `growth_attempt_error` and `stage_failure`
  events; `GrowthStats` gains `attempt_errors`/`failure_reason`; new
  "skipped" status for upstream-cascade StageFailures (user_message prefix
  "Cannot generate growth plan without"); the failure-rate gate and SUMMARY
  exclude skipped rows from both sides; drops column renders attempt errors,
  retries, and failure reason.
- `prompts/growth.md` — rule 5 states the actual ban-phrase scan scope
  (what + mechanism), `current_employer_hint` description matches timeline
  semantics, rule 7 notes closed-employer targets are rejected
  programmatically.
- Tests — schema pins for required `setting`; growth-unit regressions for
  every behavior above; eval-corpus tests for skipped detection, gate
  exclusion, and the new telemetry columns.

Verification: pre-commit, mypy strict on `src/`, and `pytest -m "not live"`
against the 32-failure LFS baseline (environmental, unchanged). `verify.py`,
`_BAN_PHRASES`, and the §4.6 failure string untouched.

Heal round (same day, adversarial verification of the review fixes): the
endpoint rule now anchors on the LAST dash preceded by a year-shaped token, so
compound one-line entries ("Berry s.r.o. — 2022 — 2026") read the end year
instead of the start year; `_setting_violation` rejects a target token-equal
to a closed FULL header before current-segment matching, closing the
shared-title rubber-stamp ("Senior Manager — TD SYNNEX" passing via a current
"Senior Manager — ..." title); the growth cascade prefix is now the public
`pipeline.GROWTH_CASCADE_PREFIX` with the cascade messages built from it
(rendered text byte-identical) and eval_corpus importing it; and
`_summarize_growth` also classifies ingest/redact cascades as "skipped" when
the profile is StageFailure-shaped too, so upstream parse failures no longer
count against the growth gate.

A second verification pass on the heal itself caught two regressions, both
fixed: the endpoint re-anchor walked into annotation inner ranges
("2018 - 2026 (parental leave 2020 - 2021)" read closed) — a dash now only
re-anchors when its prefix holds exactly one year token; and the
verbatim-closed-header guard dropped rehire and company-only-closed-header
targets unrecoverably — token equality with a current segment now exempts
the guard.

A third (final) verification pass caught one more endpoint regression:
multi-stint rehire lines ("2014 - 2016, 2019 - 2026") read closed because
the second stint's dash was treated as annotation. A dash now also
re-anchors when the text after the last list separator is a lone year token
with balanced parens in the prefix — parenthesised commas
("(maternity leave, 2021 - 2022)") stay annotations. Self-heal budget
(three iterations) is now exhausted; the residual accepted ambiguity is the
dash-joined annotation pathology ("2018 - 2021 - extension 2026" reads
current), pinned nowhere and listed in the backlog.
