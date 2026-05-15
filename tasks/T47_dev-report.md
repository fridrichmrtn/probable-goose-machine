# /dev Report

**Task:** Fix L5 growth-plan stage targeting CLOSED jobs — three-layer fix (deterministic employer-timeline parser + tightened prompt + post-generation validator).
**Branch:** dev/t47-current-employer-fix
**Worktree:** /home/mf/GitHub/probable-goose-machine/.worktrees/t47-current-employer-fix
**Stack:** py + precommit

## Files touched
- `src/gander/timeline.py` — NEW. `EmployerEntry` frozen dataclass + `scan_employer_timeline(redacted_text) -> list[EmployerEntry]` deterministic parser over `work_experience_slice`; classifies each entry's `is_current` from the right-of-last-dash side. Heal pass tightened the date-range detector to require a year-shape (`(19|20)\d{2}` or `[YEAR]`) alongside the dash so headers like `Machine Learning Engineer — May Mobility` don't get misclassified.
- `src/gander/growth.py` — `_FORWARD_MARKERS` (word-boundary regex via `_FORWARD_MARKER_RE`), `_normalize_for_match`, `_employer_match_candidates`, `_violates_forward_setting`, `_compute_employer_hints`. `_build_user_message` now emits `closed_employer_hint`. `plan_growth` shares one hint source between payload + verify loop and drops closed-targeted actions with `reason=closed_employer_setting`.
- `src/gander/prompts/growth.md` — Added `closed_employer_hint` field doc. Rule 7 rewrite: forward-setting contract (current employer / forward marker / capability artefact) with carve-out allowing closed-employer mention as past-experience evidence motivating a forward action.
- `tests/test_timeline.py` — NEW. 14 fast-marked tests (post-heal): empty section, present-token, Czech variants, year-only closed, `[YEAR]` post-redaction, parallel current roles, inline paragraph guard, 3-line header walk, bullet stripping, bug-PDF fixture, frozen dataclass, header-with-inline-month regression.
- `tests/test_growth_unit.py` — Extended with 4 payload tests + 7 validator tests + 3 word-boundary regression tests added in heal.
- `tasks/T47_dev-plan.md` — Implementation plan artefact (from Phase 1).
- `tasks/backlog.md` — Appended T47 block (should-fix + remaining must-fix + nits).

## Checks
| Command | Initial (Phase 2) | After heal (Phase 4) |
|---|---|---|
| `pre-commit run --all-files` | pass | pass |
| `pytest -q -m fast` (MINIMAX_API_KEY=stub) | pass (425) | pass (429) |
| `pytest -q tests/test_timeline.py tests/test_growth_unit.py` | pass (51) | pass (55) |

## Review findings
### Must-fix (resolved this run)
- [codex] `src/gander/timeline.py:56` — date-range detector over-triggered on header lines containing English month names (e.g. `Machine Learning Engineer — May Mobility`). Fixed: require year-shape on at least one side of the dash. Regression test `test_scan_does_not_flag_header_with_inline_month_name` added.
- [codex / ai-ml / product-owner] `src/gander/growth.py` `_FORWARD_MARKERS` — raw `in` substring match let `oss` hit `loss/across/boss` and `paper` hit `newspaper`. Fixed: compiled word-boundary regex `_FORWARD_MARKER_RE`; dropped `oss`; broadened markers (added `new role/employer/position`, `future role`, `interview`, `land a role`, `land a job`, `job hunt`, `certify`, `certified`, `publish`). 3 regression tests added.
- [qa-engineer] Prompt Rule 7 vs validator semantic clash — prompt said "NEVER name an employer from `closed_employer_hint` as the action's setting" while validator allowed naming with a forward marker (plan-intended rescue path). Fixed: Rule 7 rewritten to make the carve-out explicit ("MAY appear in `what` ONLY as past-experience evidence motivating a forward action — MUST NOT be the setting of the action itself").

### Must-fix (remaining — exhaustion)
- [codex] `tests/test_salary.py:201` — fast tests instantiate `LLMClient()` before mocked `complete_json`; without `MINIMAX_API_KEY` the constructor raises. Pre-existing on `main`, predates this branch. Out of T47 scope; recorded in `tasks/backlog.md` for a separate ticket. T47 ran fast tests with `MINIMAX_API_KEY=stub` to match the existing test-suite pattern.

### Should-fix (deferred to backlog.md)
- 14 items spanning validator robustness (current-token leak rescue, Czech-blind stopwords, legal-form suffixes, generic-name stopword overstrip), observability (`current_count`/`closed_count` on drop events), test coverage (>3 drops → StageFailure path, 3-letter acronym DSV validator case, true-accent fixture), API hygiene (`_build_user_message` optional-hint dead branch), and 2 codex out-of-scope salary findings.

### Nits
- count: 7 (not listed — see `tasks/backlog.md`).

## Hiring grade
**on-bar** — Per hiring-manager: implementation is sound, plan-to-impl deviations (optional-hint params, dropping `_BANNED_VERBS_NEAR_CLOSED`) are defensible minimal-diff choices, test coverage hits real edge cases, comment discipline holds. The flagged should-fix items are robustness improvements, not correctness bugs. Codex's `below-bar` verdict is driven by salary-stage findings outside T47 scope (per /dev skill: codex's verdict is not the hiring grade).

## Commits in this branch
```
83533c4 T47 (heal): clarify growth Rule 7 vs validator semantics
6adaf71 T47 (heal): word-boundary forward markers, broader list
fde5133 T47 (heal): tighten timeline date-range detector
c607e26 feat(T47): closed-employer hint + forward-setting validator in L5 growth
db9f50c feat(T47): scan_employer_timeline parses redacted work-experience slice
```

## Cleanup
When you're done with this work:
```
git worktree remove .worktrees/t47-current-employer-fix
git branch -D dev/t47-current-employer-fix
```
Or, to land it:
```
git checkout main
git merge --no-ff dev/t47-current-employer-fix
```
