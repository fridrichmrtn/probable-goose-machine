# T47 — Current-Employer Fix: Implementation Checklist

> Plan-mode note: this file is the harness-mandated plan path. When plan mode exits, copy this verbatim to `/home/mf/GitHub/probable-goose-machine/.worktrees/t47-current-employer-fix/tasks/T47_dev-plan.md` before starting Workstream A.

## Goal

Stop the L5 growth-plan stage from targeting closed employers. Success means: on the failing `Profile_new.pdf`, the L5 payload carries Stealth Mode + Research Engineer headers in `current_employer_hint`, TD SYNNEX/Alza/DSV in `closed_employer_hint`, and every emitted growth action's `what` either names a current employer, uses a forward marker (e.g. "next role"), or is a capability artefact. Closed-targeted actions are dropped with a `growth_action_dropped reason=closed_employer_setting` event. Existing growth/snippet tests continue to pass. Total scope: one new module, one new test file, one prompt rewrite, one validator + verify-loop hook.

## Contract (locked, do not drift between workstreams)

### Types and signatures

```python
# src/gander/timeline.py  (NEW — Workstream A)
from dataclasses import dataclass

@dataclass(frozen=True)
class EmployerEntry:
    header: str       # e.g. "Stealth Mode Startup — Member of Staff"
    dates_raw: str    # e.g. "ledna [YEAR] - Present" (original casing, post-redaction)
    is_current: bool  # right-of-last-dash contains a _PRESENT_TOKENS word

def scan_employer_timeline(redacted_text: str) -> list[EmployerEntry]:
    """Deterministic scan over `work_experience_slice(redacted_text)`.
    Returns entries in CV order (top-down). Empty list when the slice is None
    or no date-range lines are found."""
```

### Growth payload shape (Workstream B)

```jsonc
{
  "...existing fields...": "...",
  "current_employer_hint": ["Stealth Mode Startup — Member of Staff", "..."],
  "closed_employer_hint":  ["TD SYNNEX — Senior Manager AI & Data Science", "..."]
}
```

Both are `list[str]` of `EmployerEntry.header` values. Order preserved from CV.

### Validator signature (Workstream C)

```python
# src/gander/growth.py
def _violates_forward_setting(
    action: GrowthAction,
    current_employers: list[str],
    closed_employers: list[str],
) -> str | None:
    """Returns a short reason string if action.what targets a closed employer, else None.

    Matching is lowercased + accent-stripped substring. Action PASSES if:
      - any current-employer header substring appears in `what`, OR
      - no closed-employer header substring appears in `what` (capability-mode),
        AND no banned-verb-near-closed-name pattern matches.
    """
```

---

## Workstream A — `gander.timeline` module

Owner: software-engineer subagent. Pure parser, no edits outside the two new files.

Files:
- create `src/gander/timeline.py`
- create `tests/test_timeline.py`

Implementation checklist (`src/gander/timeline.py`):

- [ ] Module docstring naming the responsibility: deterministic header/date-range scan over `work_experience_slice`.
- [ ] Import `work_experience_slice`, `_PRESENT_TOKENS`, `_MONTHS`, `_normalize`, `_strip_accents` from `gander.tenure`; import `_WORK_SECTION_ALIASES` and `_NON_WORK_SECTION_ALIASES` from `gander.tenure`; import `_contains_present_token` from `gander.growth` (or duplicate-by-reuse — prefer import to keep single source of truth).
- [ ] Define `@dataclass(frozen=True) class EmployerEntry` with fields `header: str`, `dates_raw: str`, `is_current: bool`.
- [ ] Internal helper `_is_date_range_line(line: str) -> bool`:
  - length ≤ 80 chars
  - contains one of `-`, `–`, `—`
  - AND at least one of: a `_PRESENT_TOKENS` word (matched on normalized form), `[YEAR]` redaction marker, 4-digit year `(19|20)\d{2}`, an English month from `_EN_MONTHS`, or a Czech month from `_CZ_MONTHS` (use `_MONTHS` for the union).
- [ ] Internal helper `_split_on_last_dash(line: str) -> tuple[str, str]` — split on the rightmost of `-`, `–`, `—`.
- [ ] Internal helper `_clean_header_line(line: str) -> str` — strip leading bullet glyphs (`-`, `*`, `•`, `–`, `—`) plus surrounding whitespace; return `""` for empty residue.
- [ ] `scan_employer_timeline(redacted_text)`:
  1. `slice = work_experience_slice(redacted_text)`; if `None`, return `[]`.
  2. Lines = `slice.split("\n")`. For each index `i`, if `_is_date_range_line(lines[i])`:
     a. Walk **upward** (`i-1, i-2, ...`) gathering header lines until: blank line, another date-range line, a section-heading-like line (`_is_heading_line(...)` against either alias set), or 3 lines collected.
     b. Clean each gathered line via `_clean_header_line`; drop empties; reverse to CV-top-down order; join with `" — "`.
     c. `right_of_dash = _split_on_last_dash(lines[i])[1]`; `is_current = _contains_present_token(right_of_dash)`.
     d. Emit `EmployerEntry(header=joined_header, dates_raw=lines[i].strip(), is_current=is_current)`.
  3. Return list in CV order.

Tests (`tests/test_timeline.py`, all `@pytest.mark.fast`):

- [ ] `test_scan_returns_empty_when_no_work_experience_section`
- [ ] `test_scan_detects_present_token_current`
- [ ] `test_scan_detects_czech_present_variants` (covers `současnost`, `dosud`, `nyní`)
- [ ] `test_scan_classifies_closed_when_only_years`
- [ ] `test_scan_handles_year_marker_post_redaction` (covers `ledna [YEAR] - Present` and `[YEAR] - [YEAR]`)
- [ ] `test_scan_parallel_current_roles` (two consecutive `... - Present` entries, order preserved)
- [ ] `test_scan_does_not_treat_inline_paragraph_dates_as_entries` (sentence "...from 2019 - present on..." mid-paragraph not surfaced; length guard exercised)
- [ ] `test_scan_header_walks_up_at_most_three_lines`
- [ ] `test_scan_strips_bullet_glyphs_from_headers`
- [ ] `test_scan_bug_pdf_shape` — reduced fixture matching the failing CV; assert exact ordered headers and `is_current` flags for Stealth, Research Engineer, TD SYNNEX, Alza, DSV.

---

## Workstream B — prompt + payload wiring

Owner: ai-ml-engineer subagent. Prompt change is the central risk.

Files:
- edit `src/gander/prompts/growth.md`
- edit `src/gander/growth.py` (`_build_user_message` only)
- extend `tests/test_growth_unit.py`

Prompt edits (`src/gander/prompts/growth.md`):

- [ ] After line 9 (the `current_employer_hint` doc), insert:
  > `- closed_employer_hint`: experience entries whose date range has ended. Past evidence only — never the target of an action.
- [ ] Replace Rule 7 (line 38) verbatim with:
  > 7. Every action's `what` MUST point forward. The forward setting is one of: (a) an employer header from `current_employer_hint`, OR (b) the literal phrase "next role" or "next employer" (capability-acquisition aimed at a future move), OR (c) a capability artefact with no employer attached — open-source contribution, certification, paper, side project. NEVER name an employer from `closed_employer_hint` as the action's setting. Past-employer evidence MAY appear in `anchor.quote` to demonstrate capability, but the `what` must point forward. Only if BOTH hint lists are empty, treat the top work-experience entry as current.

Payload wiring (`src/gander/growth.py` `_build_user_message`, around line 200):

- [ ] Import `scan_employer_timeline` from `gander.timeline`.
- [ ] Compute hints once at the top of `_build_user_message`:
  ```python
  timeline = scan_employer_timeline(redacted.text)
  if timeline:
      current_hint = [e.header for e in timeline if e.is_current]
      closed_hint  = [e.header for e in timeline if not e.is_current]
  else:
      current_hint = _extract_current_employer_hint(redacted, profile)
      closed_hint  = []
  ```
- [ ] Replace the `"current_employer_hint": _extract_current_employer_hint(...)` payload entry with `"current_employer_hint": current_hint` and add `"closed_employer_hint": closed_hint`.
- [ ] Keep `_extract_current_employer_hint` (now a fallback for snippet-shaped CVs).
- [ ] Surface `current_hint` and `closed_hint` so `plan_growth` can pass the same lists to the validator (single source of truth — see Integration). Two options: return from `_build_user_message` as a tuple, or hoist computation into `plan_growth` and pass into `_build_user_message`. Pick the smaller diff; document the choice in the commit message.

Tests (`tests/test_growth_unit.py`, extend):

- [ ] `test_payload_includes_closed_employer_hint`
- [ ] `test_payload_uses_timeline_when_available`
- [ ] `test_payload_falls_back_to_anchor_heuristic_for_snippet_input`
- [ ] `test_payload_bug_pdf_shape` — reduced fixture from `Profile_new.pdf`; assert Stealth + Research Engineer in `current_employer_hint`, TD SYNNEX in `closed_employer_hint`.
- [ ] Verify existing tests at lines 149/188/227 of `test_growth_unit.py` still pass. They use `## Work Experience` heading with `... - Present` lines so the timeline path fires; assertion strings should match the new `EmployerEntry.header` shape ("Senior Manager AI and Data Science — Stealth Startup"). If the stricter header string differs, update the test with a one-line docstring note — do not weaken the new code.

---

## Workstream C — post-generation validator

Owner: software-engineer subagent.

Files:
- edit `src/gander/growth.py`
- extend `tests/test_growth_unit.py`

Implementation checklist (`src/gander/growth.py`):

- [ ] Add module-level constants near the existing `_BAN_PHRASES`:
  ```python
  _FORWARD_MARKERS: tuple[str, ...] = (
      "next role", "next employer", "next position",
      "open source", "open-source", "oss",
      "certification", "certificate",
      "paper", "publication",
      "side project", "side-project",
  )
  _BANNED_VERBS_NEAR_CLOSED = ("rebuild", "scale", "own", "redo", "lead at", "ship at")
  ```
- [ ] Add helper `_normalize_for_match(text: str) -> str` (NFKD + lowercased + accent-stripped + whitespace-collapsed). Reuse existing `unicodedata` import.
- [ ] Add `_violates_forward_setting(action, current_employers, closed_employers) -> str | None` per the locked contract. Pass conditions:
  - any current-employer header substring is in normalized `what` → pass.
  - no closed-employer header substring in normalized `what` → pass (capability mode).
  - closed-employer hit AND no current hit AND a `_FORWARD_MARKERS` token present in normalized `what` → pass.
  - else: return `"forward_setting_targets_closed_employer:" + closed_hits[0][:40]`.
- [ ] Wire into `plan_growth` (after the verify-quote check at line ~277, before `survivors.append`):
  ```python
  forward_violation = _violates_forward_setting(action, current_hint, closed_hint)
  if forward_violation is not None:
      emit("growth", "growth_action_dropped",
           reason="closed_employer_setting", what=action.what[:80],
           detail=forward_violation)
      dropped += 1
      continue
  ```
  Use the same `current_hint` / `closed_hint` computed in `_build_user_message` (passed through, not re-derived). The validator must run after the anchor-verify so already-failing actions don't double-count, and before survival counting so closed-targeted actions feed `insufficient_verified_actions` if there are too many.

Tests (`tests/test_growth_unit.py`, extend):

- [ ] `test_validator_passes_action_targeting_current_employer`
- [ ] `test_validator_passes_capability_mode_action_with_no_employer_named`
- [ ] `test_validator_drops_action_targeting_closed_employer`
- [ ] `test_validator_allows_closed_employer_when_forward_marker_present` (e.g. "Use TD SYNNEX experience to land next role at a CZ-market data leader.")
- [ ] `test_validator_normalizes_accents_for_match` (closed employer `Alza.cz a.s.` vs action `Rebuild the recommender at alza.cz`)
- [ ] `test_validator_drop_emits_observability_event` (patch `emit`, assert event name + reason + detail fields)
- [ ] `test_plan_growth_drops_closed_targeted_action_then_succeeds_with_remaining` (LLMClient stub returns 5 actions, 1 targets closed; assert 4 survive and the dropped one is logged)

---

## Integration (final small commit, after A/B/C land)

- [ ] `_build_user_message` imports `scan_employer_timeline` from `gander.timeline` (no stubs left over from parallel dev).
- [ ] `plan_growth` reads `current_hint` / `closed_hint` from the same place the payload uses them — single source of truth, no re-derivation inside the verify loop.
- [ ] Run full suite + smoke: `uv run pytest -q -m fast tests/test_timeline.py tests/test_growth_unit.py tests/test_pipeline_smoke.py`.
- [ ] End-to-end on `Profile_new.pdf`: inspect L5 payload + emitted actions; confirm `growth_action_dropped reason=closed_employer_setting` is reachable (or not triggered if the LLM already complies) and `growth_actions_returned count >= 3`.
- [ ] `pre-commit run --all-files` clean.
- [ ] Update `tasks/todo.md` review section with verification evidence + remaining risks (Czech-blind redact `_YEAR_WITH_CONTEXT` is filed as out-of-scope follow-up).

Suggested commit boundaries:

1. Workstream A — `gander/timeline.py` + `tests/test_timeline.py`.
2. Workstream B — `growth.md` rewrite + `_build_user_message` payload wiring + payload tests.
3. Workstream C — `_violates_forward_setting` + verify-loop wiring + validator tests.
4. Integration — e2e PDF smoke + `tasks/todo.md` review section.

## Verification commands

```bash
pre-commit run --all-files
uv run pytest -q -m fast
uv run pytest -q -m fast tests/test_timeline.py
uv run pytest -q -m fast tests/test_growth_unit.py
uv run pytest -q tests/test_pipeline_smoke.py
```

## Files touched (final list)

New:
- `src/gander/timeline.py`
- `tests/test_timeline.py`

Modified:
- `src/gander/growth.py` (imports + `_build_user_message` payload + `_FORWARD_MARKERS`/`_BANNED_VERBS_NEAR_CLOSED` + `_normalize_for_match` + `_violates_forward_setting` + verify-loop wiring)
- `src/gander/prompts/growth.md` (field doc + Rule 7 rewrite)
- `tests/test_growth_unit.py` (extended)
- `tasks/todo.md` (review section after integration)

Reused, NOT modified:
- `src/gander/tenure.py` (`_PRESENT_TOKENS`, `_MONTHS`, `_EN_MONTHS`, `_CZ_MONTHS`, `work_experience_slice`, `_normalize`, `_strip_accents`, `_WORK_SECTION_ALIASES`, `_NON_WORK_SECTION_ALIASES`, `_is_heading_line`)
- `src/gander/growth.py::_contains_present_token` (line 117)
- `src/gander/schemas.py::GrowthAction` (matched by the validator)
