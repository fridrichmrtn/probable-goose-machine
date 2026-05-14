# /dev Report — T19

**Task:** L8 confidence-judge tests — six tests proving §4.3 independent-judge protocol (signature isolation, Step A tier rubric across 3 cases, Step B cannot rubber-stamp Step A Low, Step B prompt leakage absent). Plus a small SUT refactor extracting `_render_step_b` from `judge()` to make the leakage surface testable.
**Branch:** dev/T19-judge-tests
**Worktree:** /home/mf/GitHub/probable-goose-machine/.worktrees/T19-judge-tests
**Stack:** py, precommit

## Files touched

- `src/gander/confidence.py` — extracted `_render_step_b(tier, low, high, currency, period)` from inlined f-string in `judge()`; byte-identical output, no behaviour change.
- `tests/test_confidence_judge.py` — new file. 6 tests: 2 `@pytest.mark.fast` (signature isolation + Step B prompt leakage) and 4 `@pytest.mark.live` gated on `MINIMAX_API_KEY` (3-agree High, 1-source Low, disagreement Low, Step B cannot override Low).

## Commits

- `5e08337` — initial implementation (2 files, 152 insertions, 3 deletions)
- `a8034d5` — heal: tighten Step B leakage scan to `_STEP_B_PROMPT`, add `confidence_step_b` event check on the "cannot override Low" test, assert no `**kwargs`/`*args` on signature, assert `not isinstance(result, StageFailure)` before tier checks on all 4 live tests

## Checks

| Command | Initial (after `5e08337`) | After heal (`a8034d5`) |
|---|---|---|
| `uv run pre-commit run --all-files` | pass | pass |
| `uv run mypy src` | pass (14 files) | pass (14 files) |
| `uv run pytest -m fast -q` | pass (171 passed, 46 deselected) | pass (171 passed, 46 deselected) |
| `uv run pytest -m fast tests/test_confidence_judge.py -v` | pass (2 passed, 4 live deselected) | pass (2 passed, 4 live deselected) |

Live tests (`uv run pytest -m live tests/test_confidence_judge.py -v`): **not exercised this run** — `MINIMAX_API_KEY` not present in the orchestrator's environment. The 4 live tests are decorated `@pytest.mark.skipif(not os.environ.get("MINIMAX_API_KEY"), reason="needs MINIMAX_API_KEY")` and will skip cleanly. First live exercise will validate the Step A tier rubric against real MiniMax. Cost: 2 MiniMax calls per live test × 4 tests = 8 cheap-model calls per full run (logged in backlog as a should-fix to budget in §Outcome).

## Review findings

### Must-fix (resolved this run)

- [qa-engineer + ai-ml-engineer + hiring-manager] tests/test_confidence_judge.py — Step B leakage test originally only inspected `_render_step_b` output, not `_STEP_B_PROMPT` (the system prompt that is the actual leakage channel). Heal extended the test to scan `_STEP_B_PROMPT` for "estimator" and "profile" (kept "reasoning" check on user-message channel only, since the system prompt legitimately refers to Step A as a "reasoning step" — meta-reference, not estimator content; documented inline).
- [ai-ml-engineer + qa-engineer + codex] tests/test_confidence_judge.py — `test_step_b_cannot_override_step_a_low` was near-tautological (`_LOW_FALLBACK_RATIONALE` contains "insufficient" AND the prompt instructs the model to use those words). Heal added `with subscribe(events.append):` and an assertion that a `confidence_step_b` event was emitted, with inline note that the regenerate-or-fallback path makes the keyword check insufficient on its own.
- [ai-ml-engineer] tests/test_confidence_judge.py:72 — signature isolation now also asserts no `VAR_KEYWORD`/`VAR_POSITIONAL` kinds so `**kwargs` cannot quietly reopen a leakage channel.
- [hiring-manager] tests/test_confidence_judge.py — all 4 live tests now `assert not isinstance(result, StageFailure)` before the `Confidence` assertion, so MiniMax flakes surface their `user_message` instead of being masked.

### Must-fix (remaining — exhaustion)

None.

### Should-fix (deferred — see `tasks/backlog.md` T19 block)

- [ai-ml-engineer] parametrize the Step B render leakage check over `Low|Medium|High`.
- [hiring-manager] `_render_step_b` private/contract ambiguity — drop underscore or add docstring.
- [ai-ml-engineer] budget MiniMax cost in §Outcome after first live run.
- [hiring-manager] flag the `Confidence | StageFailure` widening in §Outcome.

### Nits

- count: 3 (not listed — see backlog `T19-judge-tests` block).

### Invalid (dropped after verification)

- [qa-engineer + ai-ml-engineer] "live tests silently no-op without `@pytest.mark.asyncio`" — verified `pyproject.toml` sets `asyncio_mode = "auto"`; tests execute normally.

## Hiring grade

**on-bar** — all five reviewers (ai-ml-engineer, product-owner, hiring-manager, qa-engineer, codex) converged on on-bar. Tests cover the right contract surface; the round-1 nits (leakage surface, tautology) were caught in review and addressed in heal. Small, surgical PR (~150 lines, 1 SUT refactor + 6 tests). No abstractions added beyond what the task needs.

## Cleanup

When you're done with this work:
```
git worktree remove .worktrees/T19-judge-tests
git branch -D dev/T19-judge-tests
```
Or, to land it:
```
git checkout main
git merge --no-ff dev/T19-judge-tests
```
Or to ship as a PR:
```
git -C .worktrees/T19-judge-tests push -u origin dev/T19-judge-tests
gh pr create --base main --head dev/T19-judge-tests --title "T19: L8 confidence-judge tests"
```
