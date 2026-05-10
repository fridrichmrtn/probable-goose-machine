# /dev Report

**Task:** Implement the approved plan at `/home/mf/.claude/plans/plan-adding-qa-engineer-deep-lemon.md` — add `qa-engineer` agent + dev-skill integration + project-tracking updates.
**Branch:** `dev/add-qa-engineer`
**Worktree:** `/home/mf/GitHub/probable-goose-machine/.worktrees/add-qa-engineer`
**Stack:** py, precommit, gradio

## Files touched
- `.claude/agents/qa-engineer.md` — NEW. New subagent spec; mirrors `product-owner.md`/`hiring-manager.md` template; PRD §5/§4.6/§4.8 anchors verified.
- `.claude/skills/dev/SKILL.md` — EDIT. Frontmatter description + Phase 3 prose + new reviewer-table row + `[source]` enumeration extended to include `qa-engineer`.
- `CLAUDE.md` — EDIT. `qa-engineer` added to `Available local subagents` + `Common routes`.
- `tasks/PLAN.md` — EDIT. `qa-engineer` added to `Owner:` enumeration in the task-file shape.
- `tasks/todo.md` — EDIT. New `QA01` tracking entry; healed to `[ ]` unchecked after review (audit is a stub).
- `tasks/qa_audit.md` — NEW. Audit findings (provenance: written by orchestrator as a stub — see banner in file; needs re-run via real `qa-engineer` once the agent is registered).
- `tasks/dev-plan.md` — NEW. Implementation checklist produced in Phase 1.

## Checks

| Command | Initial | After heal |
|---|---|---|
| `python -c "yaml.safe_load(...)"` (frontmatter parse) | pass | n-a |
| `rg -c "qa-engineer" .claude/skills/dev/SKILL.md` | pass (4 hits) | n-a |
| `rg -c "qa-engineer" CLAUDE.md` | pass (2 hits) | n-a |
| `pre-commit run --all-files` | pass | pass |
| `pytest -q` | pass (32 passed, 1 skipped) | pass (32 passed, 1 skipped) |
| `ls -la tasks/qa_audit.md` | pass (12 KB, 115 lines) | n-a |

## Review findings

### Must-fix (resolved this run)
- `[codex] tasks/todo.md:36` — `QA01` was checked `[x]` despite the audit being a self-disclosed stub. Healed: changed to `[ ]` and updated label to `QA01 — QA audit of plan + task testability (stub at \`tasks/qa_audit.md\`; re-run via real \`qa-engineer\` after merge)`. Commit `fbd29a6`.

### Must-fix (remaining — exhaustion)
None.

### Should-fix (deferred → backlog)
- `[ai-ml-engineer] qa-engineer.md:17` — §5(4) differentiation eval lane overlap with `ai-ml-engineer`. Tighten to test-presence vs eval-design.
- `[ai-ml-engineer] qa-engineer.md:17` — substring-grounded bar reads as inviting QA to grade grounding logic. Reword to "a test asserts every claim passes substring check".
- `[product-owner] SKILL.md:192` — qa-engineer fires every run; on docs/prompt-only diffs that's burst-token spend with low ROI. Consider gating on diff signal.
- `[product-owner] qa-engineer.md:33` — lane-overlap risk with product-owner / ai-ml-engineer; add an explicit "do not duplicate findings" line.
- `[product-owner] qa_audit.md:3` — stub disclosure is honest but creates ambiguity; real qa-engineer re-run required before findings are actioned.
- `[product-owner] PLAN.md:531` — no decision rationale captured for adding a 5th reviewer; add a 1–2 line rationale.
- `[hiring-manager] SKILL.md:192` — burst-size arithmetic ambiguous. Reword: "with UI = 5-agent burst, without = 4 (qa-engineer always fires)".
- `[hiring-manager] qa_audit.md:1` — surface stub disclosure into dev-report (done here) + add `[STUB]` tag in audit H1.
- `[codex] SKILL.md:192` — duplicate of the hiring-manager arithmetic finding above; one-line wording fix.

### Nits
- count: 7 (recorded in `tasks/backlog.md` under `## add-qa-engineer — 2026-05-10T15:44Z`).

## Hiring grade

**on-bar** — hiring-manager: "Lane separation, PRD-anchored bars, and failure-test taste are real. Held back from `strong` by the burst-size arithmetic slip in SKILL.md:192 and by the audit-stub disclosure living only in `qa_audit.md` rather than surfacing into the dev-report." Codex returned `below-bar` independently — its verdict is *not* the hiring grade per dev-skill convention, but its single must-fix (QA01 checkbox status vs stub provenance) was healed.

## Provenance note (audit stub disclosure)

`tasks/qa_audit.md` was authored by the orchestrator, **not** by a real `qa-engineer` subagent invocation, because the new agent isn't registered in this session's agent registry yet (registry is loaded at session start; a worktree-local agent file isn't picked up retroactively). The audit content is sourced from a static read of `PRD.md`, `tasks/PLAN.md`, `tasks/todo.md`, and the T07–T23 task files — its findings are concrete and actionable but should be re-validated by a real `qa-engineer` run in a follow-up session before any are treated as binding. The `QA01` tracker entry in `tasks/todo.md` was healed to `[ ]` unchecked to reflect this. The audit's banner at `tasks/qa_audit.md:3` discloses this inline.

## Cleanup

When you're done with this work:
```
git worktree remove .worktrees/add-qa-engineer
git branch -D dev/add-qa-engineer
```
Or, to land it:
```
git checkout main
git merge --no-ff dev/add-qa-engineer
```
