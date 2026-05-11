# /dev Report — T13 L5 growth-plan generator

**Task:** Implement T13 — L5 growth-plan generator with anti-slop enforcement. Deliverables: prompts/growth.md, growth.py, test_growth_unit.py. Hard contract: 3-5 verified anti-slop actions per CV, anchored back to source text via verify_quote, with a 5-phrase ban list as the central discriminator per PRD §4.4.
**Branch:** `feat/block-b-late-stages` (no sub-worktree — `--no-worktree --prefix T13`)
**Worktree:** `/home/mf/GitHub/probable-goose-machine/.worktrees/block-b`
**Stack:** py, gradio, precommit
**Status:** clean (single heal pass resolved all 10 must-fix items first try)

## Files touched

- `src/jobfit/growth.py` — punctuation-stripped ban-phrase match; top-level `try/except Exception` wraps the stage body so PRD §4.6 copy surfaces from every escape path; `growth_actions_truncated` event added on the 7→5 path (gated on `len(survivors) > 5`); two clarifying comments (temperature determinism, deterministic strongest-first ordering); unreachable mypy-only return after the `async with` block.
- `tests/test_growth_unit.py` — 13 new fast tests: punctuation-dotted PhD, whitespace-broken `learn\nmore`, parametrized coverage for the 4 other ban phrases, exactly-3 and exactly-5 boundary cases, 7→5 truncation-event assertion, baseline-missing event, possible-boilerplate event, invalid-LLM-output stage_failure, unexpected-error stage_failure, plus three pinned substrings in the user-payload test.
- `src/jobfit/prompts/growth.md` — not modified this run; ban-list bullet at line 34 verified to survive verbatim.
- `tasks/T13_growth.md` — Status `todo` → `done`, Outcome paragraph appended.
- `tasks/T13_dev-report.md` — this file.
- `tasks/backlog.md` — T13 block appended.

## Checks

| Command | Initial (Phase 2) | After heal (Phase 4) |
|---|---|---|
| `uv run ruff format --check src/jobfit/growth.py tests/test_growth_unit.py` | pass | pass |
| `uv run ruff check src/jobfit/growth.py tests/test_growth_unit.py` | pass | pass |
| `uv run mypy src/jobfit/growth.py` | pass | pass |
| `uv run pytest -q -m fast tests/test_growth_unit.py` | pass (9) | pass (22) |
| `uv run pre-commit run --all-files` | pass | pass |

(`ruff format --check` does not check `.md`; the prompt file is verified by `grep` for the surviving ban-list bullet at `src/jobfit/prompts/growth.md:34`.)

## Review findings

### Must-fix (resolved this run, single heal iteration)

- **[ai-ml-engineer]** `_check_ban_phrase` `src/jobfit/growth.py:100-108` — added punctuation strip on the lowercased haystack so `"Ph.D."` → `"phd"` matches; new fast test `test_plan_growth_drops_ban_phrase_phd_dotted` pins the exact `"Complete a Ph.D. in ML"` case.
- **[ai-ml-engineer]** `growth_actions_truncated` event `src/jobfit/growth.py:232-239` — emit only when `len(survivors) > 5` with `count_before`/`count_after`/`dropped`; positive-path test asserts 7→5 fires correctly, two new boundary tests (3 and 5 survivors) assert it does NOT fire.
- **[product-owner]** Top-level `try/except Exception` `src/jobfit/growth.py:144-273` — wraps the entire stage body so any escape (e.g., a `verify_quote` crash) surfaces PRD §4.6 `_FAILURE_MSG` with `stage_failure.reason="unexpected_error"`. The pre-existing fine-grained excepts on `complete_json` are preserved. New test `test_plan_growth_returns_stage_failure_on_unexpected_error` monkeypatches `growth_mod.verify_quote` to raise and pins both the user-message and the structured reason.
- **[qa-engineer]** 4-of-5 unverified ban phrases `tests/test_growth_unit.py` — parametrized `test_plan_growth_drops_each_ban_phrase` covers `found a startup`, `improve communication`, `learn more`, `network more` with natural English sentences; each case verifies the anchor and pins `drop_evt["phrase"]`.
- **[qa-engineer]** `growth_baseline_missing` event coverage `tests/test_growth_unit.py` — new test points `growth_mod._BASELINE_PATH` at a non-existent `tmp_path` file and asserts the event fires.
- **[qa-engineer]** `growth_actions_returned` event coverage `tests/test_growth_unit.py` — both new boundary tests (3 and 5 survivors) assert `count == len(survivors)`.
- **[qa-engineer]** `stage_failure` with `reason="invalid_llm_output"` `tests/test_growth_unit.py` — new test monkeypatches `complete_json` to return a plain `dict`, asserts the failure user_message and the structured reason.
- **[qa-engineer]** `growth_possible_boilerplate` event coverage `tests/test_growth_unit.py` — new test writes a baseline JSON whose entry matches a survivor's `what` verbatim (Jaccard = 1.0), points `_BASELINE_PATH` at it, asserts the event fires with `max_overlap == 1.0`.
- **[qa-engineer]** Exactly-3 boundary `tests/test_growth_unit.py::test_plan_growth_returns_exactly_three_when_three_verify` — pins `len(result) == 3`, `growth_actions_returned.count == 3`, no `growth_actions_truncated`.
- **[qa-engineer]** Exactly-5 boundary `tests/test_growth_unit.py::test_plan_growth_keeps_five_when_five_verify` — pins `len(result) == 5`, `growth_actions_returned.count == 5`, no `growth_actions_truncated`.
- **[hiring-manager]** `redacted_cv` and profile-metadata pinning `tests/test_growth_unit.py:418` — extended user-payload test to assert `"fraud-detection service"` (from `_CV_TEXT`), `"Senior Data Engineer"` (`detected_role`), and `"Prague"` (`detected_location`) flow into the prompt.
- **[hiring-manager]** Temperature divergence `src/jobfit/growth.py:150` — kept at `0.0` (consistent with T10/T11/T12) with the comment `# temperature=0.0 for determinism — matches T10/T11/T12 stages.` immediately above the `complete_json` call.
- **[hiring-manager]** Deterministic truncation rationale `src/jobfit/growth.py:240` — comment added: `# Order preserved from the model's emitted list — prompt instructs "strongest-first".`

### Must-fix (remaining — exhaustion)

None. Single heal iteration closed all 10 items.

### Should-fix (deferred to backlog)

Captured in `tasks/backlog.md` under the `## T13 — 2026-05-11T…Z` block. Highlights: `model="reasoning"` resolves to MiniMax-M2.7-highspeed under current `_PROFILE_MODELS` — no genuinely-distinct cheap-tier provider yet (same drift documented for T12); `growth_baseline.json` fixture content remains owned by T17 — the runtime smoke check is wired but silent until T17 lands; cross-stage telemetry naming (`growth_actions_truncated.dropped` vs. `growth_anti_slop_check.dropped`) reuses `dropped` with different semantics (truncation overflow vs. ban/verify drops) — audit before T15 wires the renderer.

### Nits

4 minor: (1) the unreachable `return StageFailure(...)` after the `async with` block exists solely for mypy — a comment justifies it; (2) `_BAN_PHRASES` substring-matches inside longer English words is intentional and documented in the module docstring; (3) `_BASELINE_PATH` resolves via `parents[2]` which is fragile if the file is ever moved out of `src/jobfit/` (deliberate, simplest path resolution); (4) the parametrized ban-phrase test reuses the same three non-banned actions in every parameter case — extracting a helper would tighten the test code but the duplication aids readability of what each case is exercising.

## Hiring grade

on-bar after heal. The single below-bar verdict (qa-engineer) was driven by the event-assertion gap (4 of 5 ban phrases untested, 4 emitted events unverified, no boundary tests at exactly 3 or exactly 5). The heal pass closed all gaps in one iteration; the new test count moved from 9 to 21 with every previously-silent emit path now observed by at least one fast test. The non-qa must-fixes (punctuation-stripped match, top-level exception handler, temperature comment) were small surgical changes that didn't require redesign.

## Codex reviewer note

Codex CLI (gpt-5.5, OpenAI) initially appeared to time out during the burst — its 300s budget went into reading source files. The completed output became available after the heal closed; codex independently flagged the same ban-phrase normalization defect at `src/jobfit/growth.py:100` (verdict: below-bar), converging with ai-ml-engineer's must-fix at the same file:line — two independent model families at the same defect is the strongest signal we get. Codex's one extra concern beyond the Claude-family burst was that the heal's punctuation strip didn't cover whitespace edge cases (`"learn\nmore"` would still slip through). Closed surgically post-heal by collapsing whitespace via `" ".join(...split())` in `_check_ban_phrase` at `src/jobfit/growth.py:104`, plus a new `test_plan_growth_drops_ban_phrase_split_by_newline` fast test pinning the `"learn more"` ban catches the newline-broken variant. Final count: 22 fast tests. The 4 Claude-family reviewers (ai-ml-engineer, ux-engineer, product-owner, hiring-manager) plus qa-engineer carried the burst; ux-engineer is N/A because T13 is non-UI. Codex's other findings (softener ban not code-enforced; table-driven test variants) were [should-fix] and overlap with the heal's parametrized ban-phrase test (item #4) or are intentionally prompt-scoped — captured in `tasks/backlog.md`.

## What this run does NOT prove

- Live MiniMax behavior on the prompt (deferred to T19 golden tests). The prompt's anti-slop hard-rules are tested at the ban-list layer; whether MiniMax-M2.7-highspeed actually emits banned phrases at temp=0.0 (and how often the ban list catches what slips through the prompt) is a T19 question.
- `growth_baseline.json` content (T17 owns the fixture). The runtime smoke check is wired and the event is emitted; the actionability of the threshold depends on T17 populating the baseline with real cross-CV growth-plan items.
- Cross-stage telemetry naming consistency (T15 renderer wiring will surface drift). `growth_actions_truncated.dropped` and `growth_anti_slop_check.dropped` use the same key with different semantics — names should be audited when T15 wires events into the renderer.

## Cleanup

Block B uses a single shared worktree across T10–T13. Do not remove until all four tasks land.
