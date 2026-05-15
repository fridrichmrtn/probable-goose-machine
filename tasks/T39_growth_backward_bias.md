# T39 — Growth backward-bias + salary role-mismatch (Profile.pdf rerun)

Status: implemented — final private Profile.pdf rerun pending explicit approval
Owner: ai-ml-engineer
Depends on: —
Unblocks: T40 verification (Martin CV rerun)
Estimate: ~90 min

## Goal

Real run on the Martin Fridrich CV (Senior Manager AI & Data Science → joined a stealth startup Jan 2026, ~10y total) surfaced two structural defects in the pipeline output:

**Growth (L5) — backward-looking actions.** 3 of 4 generated actions targeted past employers, including one targeting Alza (left 2021, 5 years stale): "Own and scale the recommendation engine stack you prototyped at Alza — rebuild the ALS + Embeddings recommendation system." Root cause is in [src/gander/prompts/growth.md:30](../src/gander/prompts/growth.md#L30): rule 1 forces the *what* itself to anchor on a verbatim CV element, conflating evidence-of-capability with subject-of-action. The schema has no field for "gap-anchored" actions even though the prose claims they're allowed, and there's no signal distinguishing current from past employers. Result: model can only produce "rebuild/scale what you already shipped."

**Salary (L4b) — wrong benchmark band.** Output anchored on "research engineer" with software-engineer (59-166k) and systems-engineer (49-113k) IC benchmarks, producing 90-140k CZK for a Senior Manager with 10y. Root cause sits in [src/gander/extract.py:92-96](../src/gander/extract.py#L92-L96): `experience_titles` is built in LLM-extraction order and never re-sorted before passing to `normalize_role`. The candidate's "Research Engineer" personal-projects sub-entry can win the canonical-role race against "Senior Manager AI & Data Science" depending on extraction order. [src/gander/normalize.py:124-138](../src/gander/normalize.py#L124-L138) already picks the highest-seniority title in the recovery path — but only when `detected_role` itself trips the denylist; when the LLM picks a market-token-valid-but-wrong title like "Research Engineer," recovery never runs.

Outcome target: actions that propose *forward* moves at the *current* role (or genuine new capability acquisition) anchored to evidence of underlying capability; salary band that reflects the candidate's actual senior/management track.

## Approach

**Plan A (prompt-only) for growth** + **minimal extract-side reorder for salary**. Both are evidence-driven, low-blast-radius changes that preserve PRD §4.4's anti-slop discriminators (`_BAN_PHRASES`, `verify_quote`) and don't collide with in-flight T36. If a re-run on the Martin CV still shows past-employer anchoring after Plan A, escalate to Plan B (schema split) as a follow-up task.

## Critical files

- [src/gander/prompts/growth.md](../src/gander/prompts/growth.md) — rule rewrite + counter-example
- [src/gander/growth.py](../src/gander/growth.py) — payload extension + `_extract_current_employer_hint` helper
- [src/gander/extract.py](../src/gander/extract.py) — sort experience_titles by seniority before normalizer
- [src/gander/normalize.py](../src/gander/normalize.py) — expose ranking function for reuse
- [src/gander/tenure.py](../src/gander/tenure.py) — reuse `work_experience_slice` and `_PRESENT_TOKENS`
- [tests/test_growth_unit.py](../tests/test_growth_unit.py) — payload assertions + Martin-class fixture
- [tests/test_extract.py](../tests/test_extract.py) — title-ordering test
- [tests/test_normalize.py](../tests/test_normalize.py) — Research-Engineer-sub-entry case

## Step-by-step changes

### 1. Growth prompt rewrite — [src/gander/prompts/growth.md](../src/gander/prompts/growth.md)

- Rewrite rule 1 (line 30): the *anchor* must reference a CV element, but the *what* must be a forward deliverable. Past-employer scaling is non-conformant.
- New rule (insert after line 30): "Actions MUST NOT instruct the candidate to redo, rebuild, scale, or own work attributed to a *past* employer. A past employer is any employer named in `redacted_cv` whose role does NOT appear in `current_employer_hint`. Past-employer work is evidence; it is not a target. If `current_employer_hint` is empty, treat the top entry of the work-experience section as current."
- New rule: "At least one action MUST address a `dropped_components[*]` entry or a `components[*]` whose `score_0_100 < 60`. The anchor for that action proves adjacent capability; the *what* names the new capability or platform move."
- Add counter-example pair after the existing fraud-detection example (around line 60): a *bad* "rebuild your prior-employer ALS recommender" action, and a *good* "stand up the LLM eval harness at the current role, anchored to the present-tense work line" action.
- Add a payload-fields paragraph documenting the two new keys (`current_employer_hint`, `dropped_components`).

### 2. Growth payload + heuristic — [src/gander/growth.py](../src/gander/growth.py)

- New helper `_extract_current_employer_hint(redacted: RedactedCV, profile: Profile) -> list[str]` near line 115:
  1. Reuse [src/gander/tenure.py](../src/gander/tenure.py)'s `work_experience_slice` to get the work-experience block.
  2. For each `profile.experience` ProfileItem, locate `anchor.quote` inside that slice; check ±200 chars around the match for any `_PRESENT_TOKENS` value (e.g. "Present", "současnost", "now") OR a date range whose end token is in `_PRESENT_TOKENS`.
  3. Return deduplicated `ProfileItem.text` values. Empty list when nothing matches — prompt fallback handles it.
- Extend `_build_user_message` (lines 115-138): add `dropped_components: list[str]` (currently `[c.value for c in score.dropped]`; carries enum names since reasons aren't surfaced yet — flagged for Plan B follow-up) and `current_employer_hint: list[str]`.
- No schema change. `_BAN_PHRASES` untouched. `verify_quote` remains the sole anchor discriminator.

### 3. Extract title-ordering fix — [src/gander/extract.py](../src/gander/extract.py)

- Around line 92-96 where `experience_titles` is assembled: sort the resulting list by `(seniority_rank_desc, original_index_asc)` before passing to `normalize_role`. Use a small helper exposed from [src/gander/normalize.py](../src/gander/normalize.py) (e.g. `seniority_rank(title: str) -> int`) so the same ranking table backs both the recovery path and the pre-normalization sort.
- This makes "Senior Manager AI & Data Science" beat "Research Engineer" deterministically when both are present, regardless of LLM extraction order.

### 4. Normalize ranking helper — [src/gander/normalize.py](../src/gander/normalize.py)

- Extract the inline rank lookup in `_recover_from_titles` (lines 124-138) into a public `seniority_rank(title: str) -> int` function (returning a comparable rank with 0 for unrecognized). Re-use it both there and in extract.py's new sort.

### 5. Tests

- [tests/test_growth_unit.py](../tests/test_growth_unit.py): two new tests — `test_user_message_includes_current_employer_hint` (CV with "Present" token in an experience anchor produces non-empty hint) and `test_user_message_includes_dropped_components`. Existing 27 tests unaffected (payload widened, not narrowed).
- [tests/test_extract.py](../tests/test_extract.py): new test — Martin-class CV (current "Senior Manager" + earlier "Research Engineer" personal-projects sub-entry, with the Research Engineer entry returned first by the mocked LLM) produces `canonical_role` matching the senior management role.
- [tests/test_normalize.py](../tests/test_normalize.py): new fixture covering "Research Engineer" sub-entry + management roles to lock in the tie-break. Per [tasks/lessons.md](lessons.md) "≥3 fixtures per class" rule, also add a parallel CZ-language case.
- Re-run T30 EN-triplet acceptance and capture a new `growth_baseline.json` (currently `[]`, so nothing breaks).

### 6. Out of scope (documented, not changed)

- `Score.dropped` enriched with reasons + justifications (Plan B).
- `Anchor` schema split into evidence + target (Plan B).
- Salary stage `confidence=Low` downgrade when canonical_role differs from highest-seniority title — small tightening, queue as separate task once Plan A salary fix is verified.
- Coordination with T36 (senior fixture education-anchor verify): orthogonal, no conflict.

## Verification

End-to-end:
1. `uv run pytest tests/test_growth_unit.py tests/test_extract.py tests/test_normalize.py` — all pass.
2. `uv run pytest tests/test_pipeline_smoke.py` — smoke still green.
3. Run the full pipeline against Profile.pdf (the Martin CV) via `uv run python app.py` (or whatever the CLI invocation is): inspect output for
   - **Growth**: zero actions whose anchor quote sits inside a past-employer slice; ≥1 action addresses a dropped/weak component; at least one action targets the current stealth-startup role.
   - **Salary**: `canonical_role` resolves to the management title (not "Research Engineer"); benchmarks include manager-track queries; band reflects senior/management scale.
4. Re-run T30 EN-triplet acceptance test and refresh `src/gander/data/growth_baseline.json`.
5. Diff growth output for the existing EN/CZ fixtures against the Martin CV to confirm the past-employer suppression generalizes (per lessons.md, don't harden against one fixture).

Falsifiability gate: if step 3's growth output still shows past-employer anchoring on the Martin CV, escalate to Plan B (schema split + structured target field) as a new task before declaring done.

## Risks

- Heuristic `current_employer_hint` is fragile when CV uses neither a present-token nor a date range ending in 2024-2026; documented fallback (top of work-experience section) handled in prompt prose.
- Reordering `experience_titles` by seniority could affect other downstream consumers — audit reveals only `normalize_role` uses it; safe.
- Re-baselining `growth_baseline.json` is required; current file is `[]` so cost is just one CI run.
- T36 is in flight on adjacent code; this plan doesn't touch `verify_quote` or score-stage anchors, so no merge collision expected.

## Outcome

Implemented the fast-verifiable pieces:
- `normalize.seniority_rank()` plus a narrow `experience_recovery` path so a valid-but-low side-entry role such as "Research Engineer" cannot beat a higher-seniority work title.
- `extract_profile()` now sorts title candidates by seniority before role normalization.
- Growth payload now includes `current_employer_hint` and `dropped_components`; prompt rules now distinguish evidence anchors from forward-looking action targets and forbid past-employer redo/scale actions.
- `verify_quote(section=...)` now keeps employer subheaders inside known parent
  CV sections such as `Pracovní zkušenosti`, so VLM transcripts with `## TD
  SYNNEX` under work experience no longer drop valid experience/soft-signal
  score anchors before growth can run.
- Role recovery now extracts clean title prefixes from Profile.pdf-style
  summaries such as `Senior Manager AI at TD SYNNEX, ...` and rejects
  duration-shaped candidates such as `Research Engineer, 10 years ...` as the
  salary canonical role.

Verified:
- `uv run pytest tests/test_normalize.py tests/test_extract.py -m fast -v`
- `uv run pytest tests/test_growth_unit.py -m fast -v`
- full fast suite: `350 passed, 57 deselected`
- `uv run pytest tests/test_verify.py tests/test_score.py -m fast --strict-markers -v` — 32 passed, 3 deselected
- `uv run pytest tests/test_normalize.py tests/test_extract.py tests/test_salary.py -m fast --strict-markers -v` — 68 passed, 13 deselected

Live Profile.pdf observations on 2026-05-15:
- Text ingest reproduced the known Profile.pdf fragility: `score=failed`, salary/confidence completed, growth cascaded.
- App-default vision ingest plus OpenRouter downstream stages initially exposed
  the section-slicing bug (`score=failed` because work-experience quotes lived
  under employer subheaders).
- After the section fix, the app handler reached `profile/score/salary/confidence/growth=done`;
  growth produced current/future-role actions with no Alza/rebuild/redo target,
  and the UI stream rendered sensibly. The same run exposed the remaining
  salary-role bug: canonical role was still `research engineer, 10 years 7
  months tenure` with a 60-90k CZK/month band.
- The role-prefix recovery fix is fast-verified, but the final private
  Profile.pdf rerun after that fix was blocked by the execution environment
  because it would resend local private CV contents to external LLM services.

Still pending before checking T39 done:
- Final app-default Profile.pdf rerun after explicit user approval for sending
  the private local PDF to MiniMax/OpenRouter, confirming salary no longer
  resolves to Research Engineer and growth still has zero past-employer targets.
- T30 EN-triplet live acceptance / growth baseline refresh if the live output changes.
