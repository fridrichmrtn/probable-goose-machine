# T50 dev plan — growth-stage hardening

Branch: `dev/t50-growth-stage-hardening`. Five ordered commits, each leaving the suite green.
Source findings: review run output (33 confirmed findings, F0–F32). PRD §4.4/§4.5/§4.6 binding.

## Locked contracts (do not violate in any commit)

- `PRD.md` is the spec. Read-only. Never edit.
- `_BAN_PHRASES` tuple in `src/gander/growth.py` is contractual. Do not add, remove, or
  reword entries. Only the *matching* of `"phd"` changes (word boundary).
- §4.6 failure copy `"Could not generate this section reliably"` (`_FAILURE_MSG`) is reserved
  for: 0 pooled survivors after retry, and LLM transport/parse error or invalid output when the
  survivor pool is empty. A 1–2 action result is a *degraded success*, not a failure.
  DEVIATION (orchestrator-approved during implementation): an attempt-2 LLM error or invalid
  output with a non-empty pool degrades to the pooled survivors (`growth_attempt_error` +
  `growth_degraded`) instead of failing — StageFailure is reserved for attempt-1 errors and a
  zero pool. Shipped pins: `test_plan_growth_degrades_when_second_attempt_raises`,
  `test_plan_growth_degrades_when_second_attempt_returns_invalid_output`.
- Runtime LLM: OpenRouter + Gemini (2.5 Flash primary / Flash-Lite fallback on the `reasoning`
  slot). No Anthropic-specific features.
- `src/gander/verify.py` (`verify_quote` rules: <6 words False; 6–7 exactly-once; ≥8 count≥1)
  is NOT modified anywhere in this train.
- mypy strict on `src/gander`; ruff E/F/I/UP/B/SIM, line-length 100. No live tests — all new
  tests mocked per `tests/test_growth_unit.py` conventions (`monkeypatch.setenv("OPENROUTER_API_KEY",
  "test-stub")`, `monkeypatch.setattr(LLMClient, "complete_json", ...)`, `obs.subscribe`).
- Per-commit checks (run all three before committing):
  ```
  pre-commit run --all-files
  uv run mypy src/
  uv run pytest -q -m "not live"
  ```

## Process deliverables placement

- `tasks/T50_growth_stage_hardening.md` (T39 house style: Goal, Approach, Critical files,
  Step-by-step changes, Verification, Risks, Outcome) — **created in commit 1**, status updated
  to done in **commit 5**.
- `tasks/INDEX.md`: **no update.** Its table only lists T00–T31; T39/T47 task files are not
  listed, so T50 follows the same convention.
- `README.md`: **no update.** Its only growth mentions (pipeline diagram, lines ~47/54) describe
  the stage generically; nothing in this train contradicts them.
- `reports/SUMMARY.md` is generated output of `scripts/eval_corpus.py`. Commit 4 changes its
  *format*; do not hand-edit the checked-in artifact — it regenerates on the next live eval run.
- `tasks/T50_dev-report.md` is written by the orchestrator. Out of scope here.

---

## Commit 1 — surgical heuristic fixes (timeline, ban-phrase, employer candidates, shared-token inversion)

Findings: F0, F1, F2, F3, F16, F17, F26.

### Files

- Modify: `src/gander/timeline.py`, `src/gander/growth.py`
- Modify: `tests/test_timeline.py`, `tests/test_growth_unit.py`
- Create: `tasks/T50_growth_stage_hardening.md`

### 1a. `timeline.py` — `is_current` for end-year ≥ current year and open-ended ranges (F17)

Today (line ~110): `is_current = bool(_PRESENT_TOKEN_RE.search(_normalize(right_of_dash)))`.
Replace with three ordered signals on the RHS of the first dash:

1. Present-token regex match (unchanged).
2. Empty RHS after strip → `is_current = True` (open-ended ranges: `"2022 -"`, `"2022 –"`,
   `"2022—"`, post-redaction `"[YEAR] -"`).
3. Bare-year comparison: `years = [int(m) for m in re.findall(r"\b(?:19|20)\d{2}\b", right_of_dash)]`;
   if `years and max(years) >= date.today().year` → `is_current = True`.

Add `from datetime import date` import. Module-level compiled regex `_BARE_YEAR_RE` next to the
existing patterns. No signature changes; `_is_date_range_line` untouched.

Production-reach note (verified against `redact.py`): `_YEAR_WITH_CONTEXT` only swallows year
ranges joined by hyphen/en-dash (`[-–]`). Em-dash ranges (`2022 — 2026`) and open-ended ranges
(`2022 -`) survive redaction with digits intact, so signals 2 and 3 both fire on real redacted
input. Closed hyphen/en-dash ranges become `[YEAR] - [YEAR]` and remain classified closed —
documented limitation, NOT fixable here (redact.py out of scope).

Known accepted edge: a short bullet line like `"- Shipped 2026 roadmap"` already false-positives
as a date-range line today; signal 3 now also marks it current. Pre-existing false-positive
class, blast radius unchanged (one extra hint entry). Note in task file, do not chase.

Tests (`tests/test_timeline.py`, all `@pytest.mark.fast`):

- `test_scan_marks_current_when_end_year_reaches_current_year` — text
  `f"## Work Experience\nPlatform Lead — Berry s.r.o.\n2022 - {date.today().year}\n"` →
  one entry, `is_current is True`. (F17 verbatim repro shape; year built dynamically so the
  test does not rot in 2027.)
- `test_scan_marks_current_when_end_year_in_future` — `f"2022 - {date.today().year + 1}"` → True.
- `test_scan_marks_current_for_open_ended_range` — parametrize RHS-empty variants:
  `"2022 -"`, `"2022 –"`, `"ledna 2022 -"` → True each.
- `test_scan_marks_current_for_open_ended_year_marker` — post-redaction `"[YEAR] -"` → True.
- Existing pins that must stay green unchanged:
  `test_scan_classifies_closed_when_only_years` (`"2018 - 2021"` → False) and
  `test_scan_handles_year_marker_post_redaction` (`"[YEAR] - [YEAR]"` → False).

### 1b. `growth.py` — `_check_ban_phrase` word-boundary for "phd" (F0)

Current: punctuation-deletion + plain substring over all phrases, so `"GraphDB"` →
`"graphdb"` contains `"phd"`. Fix: special-case the single-token phrase — match `"phd"` via
`re.search(r"(?<!\w)phd", haystack)` (module-level compiled `_PHD_RE`); all multi-word phrases
keep substring matching (contractual semantics unchanged). Trailing boundary deliberately open
so `"phds"`, `"phd."`, and dotted `"ph.d."` (post punctuation-deletion `"phd"`) still match.

Note: `"Improve communication-layer throughput"` still trips `"improve communication"` — that
is inherent substring behavior on a contractual phrase, not the F0 artifact. Do not "fix"; do
not add a test asserting it passes.

Tests (`tests/test_growth_unit.py`, fast, direct `_check_ban_phrase` calls):

- `test_ban_phrase_ignores_phd_inside_graphdb` —
  `_check_ban_phrase("Migrate the on-prem GraphDB knowledge graph to a managed service") is None`
  and `_check_ban_phrase("Consolidate the graph-database layer behind one API") is None`
  (both F0 verbatim repros).
- `test_ban_phrase_still_catches_phd_variants` — `"Start a PhD program"`, `"Pursue a Ph.D. in ML"`,
  `"Apply to PhDs abroad"` → all return `"phd"`.
- Existing `test_plan_growth_drops_ban_phrase_phd_dotted` and `test_plan_growth_drops_each_ban_phrase`
  must stay green (they cover the dotted and canonical forms e2e).

### 1c. `growth.py` — `_employer_match_candidates` emits only company-shaped candidates (F1, F3)

Restructure to inspect the ORIGINAL-CASE header before normalizing (all-caps detection is
impossible after `_normalize_for_match` lowercases). Split the original header on
`\s+[-–—]\s+` into parts; per part, tokenize on whitespace, strip `.,;:` edges per token.

New module-level constants:

- `_LEGAL_SUFFIXES = {"a.s", "s.r.o", "sro", "spol", "k.s", "v.o.s", "b.v", "n.v", "inc",
  "llc", "ltd", "corp", "corporation", "gmbh", "plc", "kft"}` (compared against the
  normalized, edge-stripped token). Suffixes qualify a part but are NEVER emitted as
  candidates ("a.s." matching another company's suffix is a real false-hit vector).
- Extend `_COMPANY_STOPWORDS` with location tokens: `"czech", "republic", "prague", "praha",
  "brno", "ostrava"`. (Allowlist-shaped fix per lessons.md would be ideal, but the stopword
  set already exists; extending it is the consistent minimal change.)

A part **qualifies** as company-shaped iff it has at least one shape-evidence token, or it
contains zero stopword tokens:

- shape evidence: legal-suffix token, OR token containing a digit or internal dot
  (`alza.cz`, `O2`, `2N`), OR original-case all-caps alpha token of length ≥ 2 that is not a
  stopword (`ČSOB`, `IBM`, `TD`, `SYNNEX` — use `token.isupper()`).
- zero-stopword catch-all keeps plain-name companies ("Stealth Mode Startup", bare "Alza")
  while excluding title parts ("Lead Data Scientist" — all stopwords; "Machine Learning
  Engineer" — contains stopword "engineer") and location parts ("Prague, Czech Republic" —
  all stopwords after the extension).

From each qualifying part, emit (normalized):

- the multi-word phrase (current behavior: `len >= 4`, contains space);
- tokens that are NOT stopwords and NOT legal suffixes, where the token is: dotted/digit-bearing
  of length ≥ 2 (`alza.cz`, `o2`), or original-all-caps of length ≥ 2 (`csob`, `td`), or plain
  length ≥ 3 (`skoda`, `auto`, `stealth`);
- dot-split subtokens of length ≥ 3 that clear stopwords (`alza.cz` → `alza`; F3's
  "at Alza" / "at O2" false negatives).

Non-qualifying parts emit nothing — this kills the F1 leaks: `"lead data scientist"` phrase,
`"machine"`/`"learning"` tokens, `"czech"`/`"prague"`/`"republic"` tokens.

`_token_in`'s `(?<!\w)…(?!\w)` boundary already handles 2-char candidates like `o2` safely.

### 1d. `growth.py` — `_violates_forward_setting` shared-token inversion (F2, F16, F26)

Current bug (line ~346): current-employer candidates are filtered with
`c not in closed_set`, so any token shared between a current and a closed entry (same-company
promotion) can never rescue the action. Invert:

```python
current_candidates = {c for h in current_employers for c in _employer_match_candidates(h)}
closed_candidates = [
    c
    for h in closed_employers
    for c in _employer_match_candidates(h)
    if c not in current_candidates
]
```

A token appearing in any CURRENT entry can never count as a closed hit. Then, as today:
no closed hit → None; forward marker → None; any current hit → None; else violation
`"forward_setting_targets_closed_employer:" + hit`. `"independent"`/`"freelance"` are already
stopwords, so the inversion loses no protection there.

Tests (fast, direct `_violates_forward_setting` calls; these are interim — commit 5 deletes
this function and re-expresses the *behaviors* as declared-setting tests):

- `test_validator_ignores_title_phrase_from_closed_header` — F1 repro a:
  what `"Step into the lead data scientist track and own the ML platform roadmap"`,
  current `["Member of Staff — Stealth Mode Startup"]`,
  closed `["Lead Data Scientist — Alza.cz a.s."]` → `None`.
- `test_validator_ignores_title_tokens_from_closed_header` — F1 repro b:
  what `"Own the machine learning roadmap for the analytics platform"`, current `[]`,
  closed `["Machine Learning Engineer — CSOB"]` → `None`.
- `test_validator_ignores_location_tokens_from_closed_header` — F1 repro c:
  what `"Mentor two MSc graduates through a Czech university mentoring scheme"`, current `[]`,
  closed `["Data Analyst — O2 Czech Republic"]` → `None`.
- `test_validator_matches_bare_company_subtoken` — F3 repro a:
  what `"Own and scale the recommendation engine stack you prototyped at Alza"`,
  current `["Member of Staff — Stealth Mode Startup"]`,
  closed `["Lead Data Scientist — Alza.cz a.s."]` → violation containing `"alza"`.
- `test_validator_matches_two_char_digit_company` — F3 repro b:
  what `"Rebuild the churn model you owned at O2 with the latest stack"`, current `[]`,
  closed `["Data Analyst — O2"]` → violation containing `"o2"`.
- `test_validator_allows_same_company_promotion` — F2/F16 repro:
  what `"Lead the fraud platform rollout at CSOB and take the tech-lead slot"`,
  current `["Senior Data Scientist — CSOB"]`, closed `["Data Scientist — CSOB"]` → `None`.
- `test_validator_allows_same_company_promotion_dotted` — F26 verbatim repro:
  what `"Ship the realtime pricing model at Alza.cz within two quarters"`,
  current `["Data Lead — Alza.cz"]`, closed `["Junior Analyst — Alza.cz"]` → `None`.

Existing validator tests that must stay green with the new candidate rule (verified by
dry-running the algorithm): `test_validator_passes_action_targeting_current_employer`,
`test_validator_passes_capability_mode_action_with_no_employer_named`,
`test_validator_drops_action_targeting_closed_employer` (TD SYNNEX all-caps),
`test_validator_allows_closed_employer_when_forward_marker_present`,
`test_validator_does_not_match_oss_inside_loss_or_across`,
`test_validator_does_not_match_paper_inside_newspaper`,
`test_validator_matches_certify_verb_form`,
`test_validator_normalizes_accents_for_match` ("Škoda Auto a.s." qualifies via legal suffix;
emits `skoda`, `auto` tokens — the "at skoda" hit survives),
`test_validator_does_not_bypass_via_generic_current_token` ("Research Engineer — Independent"
emits nothing: both parts are all-stopword with no shape evidence),
`test_validator_does_not_match_inc_inside_increase` ("Acme Inc" qualifies via suffix; emits
`acme` only; "inc" is suffix-excluded — strictly better than relying on `_token_in` boundary),
`test_plan_growth_drops_closed_targeted_action_then_succeeds_with_remaining`.

### 1e. Create `tasks/T50_growth_stage_hardening.md`

T39 house style. Goal: close the verification gaps the T49 review found in the growth stage
(false drops, false passes, retry waste, blind eval). Approach: 5-commit train as in this plan.
Critical files: `growth.py`, `timeline.py`, `prompts/growth.md`, `schemas.py`,
`scripts/eval_corpus.py`. Status: in progress (flipped in commit 5).

---

## Commit 2 — retry redesign: cross-attempt survivor pooling + degraded partial result

Findings: F6, F8, F18, F29 (terminal-emit part).

### Files

- Modify: `src/gander/growth.py`, `tests/test_growth_unit.py`

### Design

`plan_growth` keeps its signature and its LLM-error/invalid-output handling (`complete_json`
exception or wrong-type return → `StageFailure` with `_FAILURE_MSG`, reasons
`llm_error`/`invalid_llm_output`). As shipped, this holds only while the survivor pool is
empty — see the DEVIATION in the locked-contracts block for the non-empty-pool degraded path.

Replace the per-attempt `survivors: list` (reset at the top of the loop, the F6 bug) with a
cross-attempt pool:

```python
pool: dict[str, GrowthAction] = {}          # insertion-ordered; attempt-0 survivors first

def _action_key(action: GrowthAction) -> str:
    def norm(s: str) -> str:
        return " ".join(s.casefold().split())
    return norm(action.what) + "\x00" + norm(action.anchor.quote)
```

Extract the per-action gate loop (ban phrase → verify_quote → forward setting) into a helper so
drop details exist for the retry message:

```python
class _Drop(NamedTuple):
    index: int
    what: str
    reason: str        # "ban_phrase" | "unverified_anchor" | "closed_employer_setting" | ...
    detail: str | None # matched phrase / employer token
    quote: str | None  # rejected anchor quote, unverified_anchor only

def _filter_actions(
    actions: list[GrowthAction],
    redacted_text: str,
    current_employers: list[str],
    closed_employers: list[str],
) -> tuple[list[GrowthAction], list[_Drop], dict[str, int]]:
```

`_filter_actions` owns the existing `growth_action_dropped` emits (payloads unchanged in this
commit; commit 4 adds the quote field). Pure mechanical extraction of the current loop body —
no gate-order or behavior change.

Per attempt (`for attempt in range(_GROWTH_LOGICAL_MAX_RETRIES + 1)`):

1. Call LLM (attempt 0: base user message; attempt ≥ 1: top-up message, see below).
2. `attempt_survivors, drops, drop_reasons = _filter_actions(...)`.
3. Merge: `for a in attempt_survivors: pool.setdefault(_action_key(a), a)` — dedup on
   normalized `what` + anchor quote, first occurrence wins, ordering preserved.
4. Emit `growth_anti_slop_check` as today (returned / dropped / survived = attempt survivors),
   plus new key `pooled=len(pool)`.
5. `if len(pool) >= 3: break`.
6. If attempts remain: emit `growth_retry` with `survived=len(pool)` (the gate-relevant pooled
   count — for single-attempt pools this equals today's value, so the existing event shape is
   preserved), `returned`, `dropped`, `drop_reasons`; rebuild the user message as a top-up.

Top-up retry message — `_build_retry_user_message` is rewritten:

```python
def _build_retry_user_message(
    base_user_message: str,
    *,
    kept: list[GrowthAction],
    drops: list[_Drop],
    needed: int,
) -> str:
```

Content, appended to the base message:

- "Of your previous actions, {len(kept)} passed verification and are KEPT — do not repeat or
  rephrase them:" followed by each kept `what`.
- "These actions FAILED verification:" then per drop: `action {index}: "{what[:80]}" — {reason}`.
  For `unverified_anchor` include the exact rejected quote and the instruction: the anchor
  quote was not found verbatim in `redacted_cv`; copy at least 8 consecutive words
  character-for-character from one CV section. For `ban_phrase` / `closed_employer_setting`
  name the matched phrase/token from `detail`.
- "Return a JSON object with exactly {needed} NEW action(s) in the same schema. Do not include
  the kept actions."

`needed = 3 - len(pool)`. The model returns only new actions; step 3's pooling merges them and
the dedup key absorbs any disobedient re-sends of kept actions.

Terminal handling after the loop:

- `len(pool) >= 3` → existing success path unchanged (truncate to 5 with
  `growth_actions_truncated`, baseline boilerplate check, `growth_actions_returned`, `done`).
- `len(pool) in (1, 2)` → emit new event `growth_degraded` (stage `"growth"`) with
  `count=len(pool)`, `returned` (last attempt's raw count), `drop_reasons` (last attempt's),
  then fall through to the same success path and RETURN the pooled list. PRD §4.5 licenses
  "a shorter list … not a placeholder". No report-renderer change: `report._growth_section`
  renders any list length (verified), `pipeline.py` statuses key off `isinstance(…, list)`
  (verified), acceptance `_require_growth` asserts list-ness only (verified).
- `len(pool) == 0` → `StageFailure` with `_FAILURE_MSG`, reason `insufficient_verified_actions`,
  as today — and the terminal `stage_failure` emit gains `drop_reasons` and `returned`
  (F29: today it omits them, hiding why everything died).

### Tests

Rewrites of existing tests:

- `test_plan_growth_returns_stage_failure_when_fewer_than_three_verified` → renamed
  `test_plan_growth_degrades_to_partial_list_when_fewer_than_three_verified`. Same fixture
  (both attempts return 1 verifiable action — identical payload, deduped to pool of 1). New
  assertions: result is `list` of length 1 (not `StageFailure`); `growth_degraded` event fired
  with `count == 1`; `complete_json` called exactly twice; one `growth_retry` event present
  (F27's retry-contract gap: this fails if `_GROWTH_LOGICAL_MAX_RETRIES` is set to 0).
- `test_plan_growth_retries_when_too_few_actions_verify` — same scenario (attempt 0: 1
  survivor; attempt 1: 3 actions, one a duplicate of the kept survivor). Pool = kept 1 + 2 new
  = 3; result length 3 with the kept action FIRST. Update message assertions to the new top-up
  copy: second user message contains the kept action's `what`, the literal rejected quote of
  the dropped action, and `"exactly 2 NEW action"`. Keep the
  `growth_anti_slop_check` attempts `[0, 1]` assertion; retry event `survived == 1` unchanged.

New tests:

- `test_plan_growth_pools_survivors_across_attempts` — F6/F8 core: attempt 0 returns 2
  verifiable actions, attempt 1 returns 2 *different* verifiable actions (use `_QUOTE_FRAUD` /
  `_QUOTE_ONCALL` / `_QUOTE_MIGRATION` / `_QUOTE_EDUCATION` fixtures). Old code: StageFailure
  ("only 2 verified"). New: result is list of length 4, attempt-0 actions first; no
  `stage_failure` event; no `growth_degraded` event.
- `test_plan_growth_dedups_pooled_survivors_on_what_and_quote` — attempt 1 re-sends a kept
  action with different surrounding whitespace/case in `what` → pool does not double-count;
  result length reflects unique actions only.
- `test_plan_growth_degraded_event_payload` — covered by the renamed test above (assert
  `count`, `drop_reasons` keys present); fold into it rather than a separate test.

Kept as-is (still green by design): `test_plan_growth_returns_stage_failure_when_complete_json_raises`,
`test_plan_growth_returns_stage_failure_on_invalid_llm_output`,
`test_plan_growth_returns_stage_failure_on_unexpected_error`,
`test_plan_growth_user_message_includes_salary_midpoint_and_components` (both attempts return
`actions=[]` → pool 0 → StageFailure path; test only inspects the captured user message).

---

## Commit 3 — prompt alignment + softener enforcement

Findings: F7, F32, F13, F11 (softener part).

### Files

- Modify: `src/gander/prompts/growth.md`, `src/gander/growth.py`, `tests/test_growth_unit.py`

### 3a. `prompts/growth.md` — anchor length truth (F7/F32)

Both mentions change from 6 to 8 consecutive words:

- Schema block (line ~23): `"quote": "<verbatim substring of the CV, at least 8 consecutive words>"`.
- HARD RULES rule 4 (line ~36): "at least 8 consecutive words copied character-for-character".

`verify.py` is untouched — 6–7-word quotes still pass when they appear exactly once, so
existing fixtures keep verifying; the prompt simply stops advertising the flaky floor.
Precedent: `extract.md:20` and `score.md:48` already instruct the 8-word form.

### 3b. `prompts/growth.md` — section guidance in main prompt (F13)

Add to the schema block's `section` line and/or rule 4: "copy the visible CV section header
exactly as printed (do not translate it), or set `section` to null if uncertain." This text
currently only appears in the retry message — after commit 2's rewrite, keep the
unverified_anchor drop hint in the top-up message short (rejected quote + 8-word rule) since
the main prompt now carries the section rule.

### 3c. `growth.py` — enforce rule 6 softeners (F11)

New drop reason `"softener_phrase"`:

```python
_SOFTENER_RE = re.compile(r"\b(?:consider|explore|look into)\b", re.IGNORECASE)
```

Scope: `action.what` ONLY. Rationale: rule 6 governs the action's imperative phrasing;
`mechanism` legitimately uses explanatory language ("...employers pay for engineers who explore
new markets...") and dropping on it would create false drops with no rule-6 backing. Record the
decision in the task file.

Check order inside `_filter_actions`: ban phrase → softener → verify_quote → forward setting
(lexical checks first, cheapest to most expensive). Emits `growth_action_dropped` with
`reason="softener_phrase"` and the matched phrase as detail. Word-boundary regex means
"considering", "considerable", "explores", "exploration" do NOT match.

Note: rules 2 (mechanism quality) and 8 (weak-component linkage) remain prompt-only after this
commit — accepted residual, named in the task file; the HARD RULES header is no longer false
for rule 6.

### Tests

- `test_plan_growth_drops_softener_action` — payload with 4 actions, one
  `what="Consider exploring a managed Kubernetes migration for the payments stack"` with a
  valid ≥8-word anchor (would pass every other gate). Assert: dropped, result length 3,
  `growth_action_dropped` event with `reason == "softener_phrase"`.
- `test_softener_regex_respects_word_boundaries` — fast, direct regex checks:
  `"Deliver considerable latency gains in the ingestion path"` no match; `"Look into Kafka"`
  match; `"Considering the runway"` no match; `"Explore the pricing API"` match (case-insensitive).
- Prompt-sync greps in tests: extend (or add, if none exists) a fast test asserting
  `prompts/growth.md` contains `"at least 8 consecutive words"` and does NOT contain
  `"6 consecutive words"` — same class of pin as the ban-list/prompt mirror, keeps prompt and
  validator from drifting apart again (F32's root cause).

---

## Commit 4 — measurement: eval growth telemetry + missing tests + drop observability

Findings: F14, F20, F24, F25, F26 (e2e), F27, F29 (drop-event part).

### Files

- Modify: `scripts/eval_corpus.py`, `src/gander/growth.py`,
  `tests/test_eval_corpus.py`, `tests/test_growth_unit.py`

### 4a. `growth.py` observability

- `unverified_anchor` drop emit gains `quote=action.anchor.quote[:120]` (F14). Other reasons
  keep their current payload (+ `what[:80]`).
- `_compute_employer_hints` emits a new event after resolving hints (F20):
  `obs.emit("growth", "growth_employer_hints", source="timeline"|"anchor_fallback",
  current_count=len(current), closed_count=len(closed))`. The anchor-fallback branch returning
  `closed=[]` silently disabled the closed-employer gate — this makes that visible per run.
  Note: tests that monkeypatch `_compute_employer_hints` never see this event; the event tests
  below must call the real function.

Tests (lessons.md rule: every new obs event needs a payload-asserting test via `obs.subscribe`):

- `test_compute_employer_hints_emits_timeline_event` — real `_compute_employer_hints` on the
  `test_payload_bug_pdf_shape` text (2 current / 3 closed) → event with `source == "timeline"`,
  `current_count == 2`, `closed_count == 3`.
- `test_compute_employer_hints_emits_fallback_event` — snippet input with no timeline entries
  (reuse `test_payload_falls_back_to_anchor_heuristic_for_snippet_input` fixture) → event with
  `source == "anchor_fallback"`, `closed_count == 0`.
- `test_unverified_anchor_drop_event_includes_quote` — plan_growth with one bad-anchor action →
  `growth_action_dropped` event carries `quote` equal to the rejected quote (truncated to 120).

### 4b. The four named missing tests (`tests/test_growth_unit.py`)

- `test_validator_passes_current_employer_override` — F25, the never-taken branch (closed hit
  present + no forward marker + genuine current hit → None). Direct call:
  what `"Bring the TD SYNNEX pricing playbook to Stealth Mode Startup as a quarterly
  cost-model deliverable"`, current `["Member of Staff — Stealth Mode Startup"]`, closed
  `["Senior Manager — TD SYNNEX"]` → `None`. Works under commit 1's candidate rule: closed hits
  via all-caps `td synnex`; current part "Stealth Mode Startup" qualifies via zero-stopword
  catch-all and emits the phrase `stealth mode startup`, which `_token_in` finds in `what`.
- `test_plan_growth_keeps_current_employer_override_action` — same scenario e2e through
  `plan_growth` with `fake_hints` monkeypatch (pattern at test_growth_unit.py:1385) and a valid
  ≥8-word anchor: action survives, no `growth_action_dropped` event for it.
- `test_plan_growth_keeps_same_company_promotion` — F26 e2e: fake hints
  current `["Data Lead — Alza.cz"]` / closed `["Junior Analyst — Alza.cz"]`, action
  `"Ship the realtime pricing model at Alza.cz within two quarters"` + valid anchor → survives.
- `test_plan_growth_fails_after_both_attempts_produce_zero_survivors` — F27: both attempts
  return only unverifiable-anchor actions → `StageFailure` with message exactly
  `"Could not generate this section reliably"`; `complete_json` called exactly twice; events
  include one `growth_retry` and a terminal `stage_failure` whose payload carries
  `drop_reasons` (commit 2's enrichment) — this is the test that pins retries actually firing.
- `test_plan_growth_degrades_when_second_attempt_raises` (shipped name; the planned
  `test_plan_growth_fails_when_second_attempt_raises` followed the pre-deviation contract) —
  F27: attempt 0 returns 1 verifiable action, attempt 1 raises → degraded list of the pooled
  survivor, `growth_attempt_error` (reason `llm_error`) + `growth_degraded`, no StageFailure
  (see DEVIATION in the locked-contracts block). Sibling pin
  `test_plan_growth_degrades_when_second_attempt_returns_invalid_output` covers the
  invalid-output branch (reason `invalid_llm_output` with `got_type` payload).

### 4c. `scripts/eval_corpus.py` growth telemetry (F24)

- `_run_one` subscribes to obs around `pipeline.run` (exact pattern: `tests/test_acceptance.py:75-88`),
  filtering events `growth_action_dropped`, `growth_retry`, `growth_degraded`. Returns
  `(report, growth_events)` — adjust the single call site.
- New pure helper `_summarize_growth(report, growth_events) -> GrowthStats` (small dataclass or
  TypedDict): `status` (`"ok"` if list len ≥ 3, `"degraded"` if list len < 3, `"failed"` if
  `StageFailure`/None), `drops_by_reason: dict[str, int]`, `retries: int`.
- SUMMARY.md: two new columns appended — `Growth status` and `Growth drops` (rendered
  `reason:count` comma-joined, `-` when empty). Update `_write_summary` header/row builders.
- Corpus-level aggregate appended under the table: total drop counts per reason, retry total,
  and `growth failure rate: X/N (P%)`.
- Exit code: new module constant `GROWTH_FAILURE_RATE_MAX = 0.25`. In `_run_corpus`'s exit
  logic: if `failed_growth / total > GROWTH_FAILURE_RATE_MAX` → exit 1 (same severity as the
  existing top-level-failure exit; degraded does NOT count as failed). Update the module
  docstring's exit-code table. `eval_corpus.py` is operator-run only — no `.github/workflows`
  reference exists (verified), so CI semantics are unaffected; note this in the task file.

Tests (`tests/test_eval_corpus.py`, fast, pure-helper level — no pipeline run):

- `test_summarize_growth_ok_degraded_failed` — three synthetic inputs: list of 3 → `"ok"`;
  list of 2 + `growth_degraded` event → `"degraded"`; `StageFailure` → `"failed"`; drop events
  aggregate by reason.
- `test_growth_failure_exit_threshold` — whatever small pure function carries the decision
  (e.g. `_growth_exit_code(stats_list)`): 1 failure of 4 → 0; 2 of 4 → 1 (0.5 > 0.25);
  exactly 25% (1 of 4) → 0 (strictly-greater semantics).

---

## Commit 5 — Plan B schema split (T39's deferred design)

Finding: F19. Net ~−400 lines. Prerequisite interplay: commit 1's timeline fix and hint
computation SURVIVE (hints feed the prompt and the declared-target validation); commit 1's
`_employer_match_candidates` restriction and the `_violates_forward_setting` inversion are
DELETED here. Accepted churn — the train stays revert-friendly and green at every commit.

### Files

- Modify: `src/gander/schemas.py`, `src/gander/growth.py`, `src/gander/prompts/growth.md`,
  `tests/test_growth_unit.py`, `tests/test_schemas.py`, `tests/test_render.py`,
  `tests/test_failures.py`, `tests/test_pipeline_fast.py`, `tasks/T50_growth_stage_hardening.md`

### 5a. `schemas.py`

```python
class GrowthAction(BaseModel):
    what: str
    time_horizon_months: int = Field(ge=1, le=24)
    mechanism: str
    setting: Literal["current_employer", "future_role", "capability_artifact"]
    target_employer: str | None = None
    anchor: Anchor
```

`setting` is REQUIRED (no default) — the declaration is the contract; `llm.complete_json`'s
ValidationError-retry self-heals a model that omits it. `target_employer` defaults to None.
Report rendering does not change (fields are validation-internal).

Construction-site fallout (every site gains `setting=` and, where relevant, `target_employer=`):
`tests/test_growth_unit.py` `_action()` helper (add params
`setting: str = "capability_artifact"`, `target_employer: str | None = None` — one edit covers
~40 tests), `tests/test_pipeline_fast.py:86`, `tests/test_render.py:95,101,691,779,788,880,896`,
`tests/test_failures.py:85`, `tests/test_schemas.py:72,157,164,171`. No `GrowthAction(`
constructions exist in `src/` outside `schemas.py` or in `app.py`/`scripts/` (verified by grep).

### 5b. `growth.py` validation collapse

DELETE: `_FORWARD_MARKERS`, `_FORWARD_MARKER_RE`, `_COMPANY_STOPWORDS`, `_LEGAL_SUFFIXES`
(commit 1 addition), `_token_in`, `_employer_match_candidates`, `_violates_forward_setting`.
KEEP: `_normalize_for_match` — it is reused by the new check (NFKD accent-strip + casefold +
whitespace collapse), so the "delete if unused" clause does not trigger.

Replacement check inside `_filter_actions` (gate order: ban → softener → verify_quote →
setting check):

```python
def _setting_violation(action: GrowthAction, current_employers: list[str]) -> str | None:
    if action.setting != "current_employer" or not current_employers:
        return None
    if not action.target_employer:
        return "missing_target"
    target = _normalize_for_match(action.target_employer)
    for header in current_employers:
        hint = _normalize_for_match(header)
        if target in hint or hint in target:
            return None
    return action.target_employer[:40]
```

Drop reason: `"unverified_target_employer"` (new name — semantics changed from the old
`closed_employer_setting`, and eval aggregation in commit 4 is reason-key-generic so nothing
else moves). Decisions locked here:

- Fuzzy match = normalized substring in either direction. "Stealth Mode Startup" ⊂
  "member of staff — stealth mode startup" ✓; "Skoda Auto" ⊂ "lead data scientist — škoda auto
  a.s." after accent-strip ✓. Cheap, transparent, good enough — no edit distance.
- Empty current-hint list → check skipped entirely (mirrors today's fallback behavior where
  `closed=[]` disabled the gate; commit 4's `growth_employer_hints` event keeps it observable).
- Declared `current_employer` with `target_employer=None` and non-empty hints → drop
  (`unverified_target_employer` with detail `missing_target`).
- `future_role` / `capability_artifact` → no employer check at all. Residual risk (model writes
  a backward-looking `what` but declares `future_role`) is monitored via live acceptance
  fixtures, NOT by regrowing keyword lists — that is the entire point of Plan B.
- `closed_employers` still computed and still fed to the prompt as evidence-only guidance;
  validation no longer consumes it.

Retry top-up message: `unverified_target_employer` drops list the declared target and the
available current-employer hints so the model can self-correct.

### 5c. `prompts/growth.md`

- Schema block gains:
  `"setting": "current_employer | future_role | capability_artifact"` and
  `"target_employer": "<copy the employer verbatim from current_employer_hint when setting is
  current_employer; otherwise null>"`.
- Rule 7 rewritten: declare where the action happens via `setting`. If `current_employer`, copy
  `target_employer` from the current-employer hint. Past employers may appear only as evidence
  ("the pipeline you built at X") with `setting` `future_role` or `capability_artifact`. If the
  hint list is empty, prefer `future_role`/`capability_artifact`.
- All one-shot example actions (lines ~42–81) gain the two fields, at least one per setting
  value so the model sees each variant.

### 5d. Test rewrites

DELETE (token-machinery tests, function gone): `test_validator_does_not_match_oss_inside_loss_or_across`,
`test_validator_does_not_match_paper_inside_newspaper`, `test_validator_matches_certify_verb_form`,
`test_validator_does_not_match_inc_inside_increase`,
`test_validator_does_not_bypass_via_generic_current_token`,
`test_validator_allows_closed_employer_when_forward_marker_present`, and commit 1's seven
candidate-rule tests (1d list).

REWRITE as declared-setting behavior tests (direct `_setting_violation` + e2e where marked):

- `test_setting_check_passes_matching_current_target` — setting `current_employer`,
  target `"Stealth Mode Startup"`, hints `["Member of Staff — Stealth Mode Startup"]` → None.
- `test_setting_check_normalizes_accents` — target `"Skoda Auto"`, hints
  `["Lead Data Scientist — Škoda Auto a.s."]` → None (carries the old accent test's intent).
- `test_setting_check_drops_non_current_target` — target `"TD SYNNEX"`, hints
  `["Member of Staff — Stealth Mode Startup"]` → violation (carries
  `test_validator_drops_action_targeting_closed_employer`'s intent).
- `test_setting_check_drops_missing_target` — setting `current_employer`, target None,
  non-empty hints → `"missing_target"`.
- `test_setting_check_skipped_when_no_current_hints` — empty hints → None regardless of target.
- `test_setting_check_ignores_future_role_and_capability` — both settings, `what` freely naming
  closed employers ("Rebuild the churn model you owned at O2…") → None (replaces the
  forward-marker rescue test; the declaration IS the rescue now).
- e2e: `test_plan_growth_drops_unverified_target_employer` — plan_growth with fake hints,
  action declaring `current_employer` + target `"TD SYNNEX"` while current is Stealth → dropped,
  `growth_action_dropped` event `reason == "unverified_target_employer"`; and
  `test_plan_growth_keeps_current_employer_override_action` /
  `test_plan_growth_keeps_same_company_promotion` (commit 4) get updated to declare
  `setting="current_employer"` with matching `target_employer` — their behavioral assertion
  (action survives) is unchanged.

UPDATE: prompt-sync test from commit 3 extends to assert `growth.md` mentions all three
setting literals (drift pin between schema and prompt).

`tasks/T50_growth_stage_hardening.md`: Outcome section filled in, status → done.

---

## Risks

1. **1–2-action render path (commit 2).** Verified ahead: `report._growth_section` renders any
   list length; `pipeline.py` status check is `isinstance(…, list)`; `app.py` consumes statuses
   only; acceptance `_require_growth` asserts list-ness, and the dedup/jaccard acceptance tests
   iterate whatever length exists. Residual: a degraded report shows a short list with no
   user-facing caveat — accepted for now (PRD §4.5 allows it); revisit only if reviewers flag it.
2. **Candidate-rule regression surface (commit 1).** The shape heuristic is the riskiest edit:
   a company that is title-case, multi-word, AND contains a role stopword (e.g. "Lead
   Ventures") emits nothing → gate silently off for that employer. Mitigation: the
   zero-stopword catch-all covers most plain names; commit 4's `growth_employer_hints` +
   per-reason drop telemetry make silent-off observable in eval; commit 5 deletes the whole
   mechanism anyway. Do not grow the stopword list beyond the named location tokens.
3. **Commit 5 schema break.** `setting` required ⇒ every `GrowthAction(` construction breaks at
   once; the enumerated site list (5a) is the checklist. Model-side: Gemini must emit the new
   fields — `complete_json`'s validation-retry plus prompt examples cover it; live acceptance
   (next live CI run) is the real gate. If live runs show chronic `missing_target` drops,
   the fallback lever is prompt examples, not schema defaults.
4. **eval_corpus exit semantics (commit 4).** Not CI-wired (verified: no reference under
   `.github/`), so the new exit-1 path only affects operators; docstring updated. Checked-in
   `reports/SUMMARY.md` stays stale-format until the next live eval run — harmless, noted in
   task file.
5. **Timeline year heuristic (commit 1).** `date.today()` makes classification time-dependent:
   a CV listing `2022 - 2026` flips to closed on 2027-01-01. Correct behavior (the range *is*
   closed then), but tests must build years dynamically — never hardcode the current year.
6. **Cross-commit churn.** Commit 1 hardens code commit 5 deletes. Accepted deliberately:
   commits 1–4 are independently shippable if commit 5's live verification stalls, and each
   commit is revertible without orphaning the others. The task file records which commit-1
   fixes survive (timeline, hints) vs die (candidate rule, inversion).

## Verification matrix

| Commit | Proof obligations |
|---|---|
| 1 | `pre-commit run --all-files`; `uv run mypy src/`; `uv run pytest -q -m "not live"`; targeted: `uv run pytest -q tests/test_timeline.py tests/test_growth_unit.py` — 4 new timeline tests, 2 ban-phrase tests, 7 validator-repro tests green; all 13 pre-existing validator/ban tests green unchanged |
| 2 | full check trio; targeted: pooling test proves 2+2 cross-attempt union returns 4 (fails on pre-commit-2 code); degraded test proves 1 survivor → list + `growth_degraded`, not StageFailure; zero-survivor path still emits §4.6 copy verbatim; retry test asserts top-up message contains kept `what` + rejected quote + "exactly N NEW" |
| 3 | full check trio; `grep -n "consecutive words" src/gander/prompts/growth.md` → only "8"; softener e2e drop test + boundary negatives green |
| 4 | full check trio; new obs-event tests assert documented payloads via `obs.subscribe` (lessons.md rule); F25 override branch now covered (was never-taken); both-attempts-fail test breaks if `_GROWTH_LOGICAL_MAX_RETRIES=0`; attempt-2 error/invalid-output with a non-empty pool pinned as degraded, not StageFailure (shipped: `test_plan_growth_degrades_when_second_attempt_raises`, `test_plan_growth_degrades_when_second_attempt_returns_invalid_output` — see DEVIATION); eval helpers unit-tested without any pipeline run |
| 5 | full check trio; `grep -rn "_FORWARD_MARKER\|_COMPANY_STOPWORDS\|_token_in\|_employer_match_candidates\|_violates_forward_setting" src/ tests/` → empty; prompt-sync test pins 3 setting literals; line-count delta noted in task file (~−400 expected) |
| train | after commit 5: `git rebase --exec 'uv run pytest -q -m "not live"' …` equivalent — or minimally re-run the trio at HEAD; live acceptance + `scripts/eval_corpus.py` run deferred to the orchestrator's live verification pass (requires `OPENROUTER_API_KEY`); state plainly in the dev-report what was and was not live-verified |

## Files touched per commit (summary)

- **C1:** `src/gander/timeline.py`, `src/gander/growth.py`, `tests/test_timeline.py`,
  `tests/test_growth_unit.py`, `tasks/T50_growth_stage_hardening.md` (new)
- **C2:** `src/gander/growth.py`, `tests/test_growth_unit.py`
- **C3:** `src/gander/prompts/growth.md`, `src/gander/growth.py`, `tests/test_growth_unit.py`
- **C4:** `scripts/eval_corpus.py`, `src/gander/growth.py`, `tests/test_eval_corpus.py`,
  `tests/test_growth_unit.py`
- **C5:** `src/gander/schemas.py`, `src/gander/growth.py`, `src/gander/prompts/growth.md`,
  `tests/test_growth_unit.py`, `tests/test_schemas.py`, `tests/test_render.py`,
  `tests/test_failures.py`, `tests/test_pipeline_fast.py`, `tasks/T50_growth_stage_hardening.md`
