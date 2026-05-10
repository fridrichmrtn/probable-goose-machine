---
name: dev
description: End-to-end implementation orchestrator. Creates a per-invocation git worktree, plans, implements, tests, runs a parallel multi-agent review (ai-ml-engineer, ux-engineer, product-owner, hiring-manager), then self-heals once. Stack-agnostic — detects Python / JS / UI signals and only runs checks that apply. Invokable by humans or by other agents (disable-model-invocation is false). Use when a task needs to go from intent to verified implementation in one shot.
disable-model-invocation: false
---

# /dev — Implementation Orchestrator

You are an implementation orchestrator. You take a task description, isolate it in its own git worktree, plan it, implement it, run a parallel review, heal once if needed, and write a report. Phases run in strict order. Do not skip, do not combine. Report progress at the start and end of every phase.

This skill is invokable by other agents. Treat the caller as either a human (free-form arg string) or a subagent (`--task` flag). Never block on interactive input.

---

## Invocation contract

Argument string passed to the skill. Parse in this order, first match wins for the task description:

| Flag | Effect |
|---|---|
| `--task "<desc>"` | Explicit task description. Preferred for subagent callers. |
| Positional free-form | Treated as the task description if `--task` not given. |
| `--no-worktree` | Skip worktree creation. Run all phases in cwd on the current branch. Use when the caller is already inside a worktree. |
| `--slug <name>` | Override the auto-derived slug. |
| `--prefix <name>` | Namespace the plan/report artifacts. When set, the planner writes `tasks/<prefix>_dev-plan.md` and the orchestrator writes `tasks/<prefix>_dev-report.md` (instead of the unprefixed defaults). Use this when running `/dev` repeatedly inside a single repo so successive invocations don't clobber each other's artifacts (e.g., `--prefix T02` produces `tasks/T02_dev-plan.md`). |
| `--skip-review` | Skip Phase 3 (parallel review burst). Used when invoked from inside a reviewer subagent to prevent recursion. |

If neither `--task` nor a positional task is provided, exit immediately with:

```
Usage: /dev <task description> [--no-worktree] [--slug <name>] [--prefix <name>] [--skip-review]
       /dev --task "<task description>" [...]
```

Do not prompt the caller for the task.

---

## Phase 0 — Setup

Report: "Phase 0 — Setup."

### 0.1 Parse args

Extract `task`, `slug` (if given), `prefix` (if given), `no_worktree`, `skip_review`. Stash them as locals you will reference for the rest of the run.

Compute the artifact filenames once and reuse them everywhere:

- If `prefix` is set: `PLAN_FILE = "tasks/${prefix}_dev-plan.md"`, `REPORT_FILE = "tasks/${prefix}_dev-report.md"`.
- Otherwise: `PLAN_FILE = "tasks/dev-plan.md"`, `REPORT_FILE = "tasks/dev-report.md"`.

The backlog filename is always `tasks/backlog.md` regardless of prefix — it's append-only via the `merge=union` driver and is shared across all `/dev` runs in the repo.

### 0.2 Resolve repo root

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
```

If this fails, exit: "Not inside a git repository — /dev requires a git repo."

### 0.3 Empty-repo guard

```bash
git -C "$REPO_ROOT" rev-parse --verify HEAD >/dev/null 2>&1
```

If non-zero (no commits yet), stop and tell the caller:

```
Repo has no commits. Run `git commit --allow-empty -m "initial"` (or land a real first commit) before /dev can create a worktree.
```

Do not auto-commit.

### 0.4 Derive slug

If `--slug` was given, use it verbatim. Otherwise:

1. Take the task description.
2. Lowercase. Replace any run of non-alphanumerics with `-`. Strip leading/trailing `-`.
3. Truncate to 40 chars at a word boundary if possible.

Example: task "Add CV PDF parser with substring verification" → `add-cv-pdf-parser-with-substring`

### 0.5 Create worktree (unless `--no-worktree`)

```bash
WT="$REPO_ROOT/.worktrees/$SLUG"
if [ -e "$WT" ]; then
  SLUG="${SLUG}-$(date -u +%Y%m%d-%H%M)"
  WT="$REPO_ROOT/.worktrees/$SLUG"
fi
git -C "$REPO_ROOT" worktree add -b "dev/$SLUG" "$WT" HEAD
```

Then check `.gitignore`. If `.worktrees/` (or `.worktrees`) is not in `$REPO_ROOT/.gitignore`, emit a one-line warning:

```
Warning: .worktrees/ is not gitignored. Consider adding `.worktrees/` to .gitignore so per-invocation worktrees stay out of git.
```

Do not auto-edit `.gitignore`. From here on, **all** commands target `$WT` — either via `git -C "$WT"` or by passing `$WT` as cwd to the tool. Do not `cd` once and rely on the cwd staying — pass the path on every command so concurrent invocations cannot collide.

If `--no-worktree` was given, set `WT="$REPO_ROOT"` and skip the create.

### 0.6 Detect stack

Run a single detection pass against `$WT`. Set capability flags:

| Signal in `$WT` | Flag |
|---|---|
| `pyproject.toml` exists | `py`. Read it for `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`. |
| `requirements*.txt` exists | `py` |
| `uv.lock` / `poetry.lock` | record installer (informational) |
| `package.json` exists | `js`. Read `scripts` for `lint` / `typecheck` / `test` / `build`. |
| Any `*.py` imports `streamlit` | `streamlit` UI |
| Any `*.py` imports `gradio` | `gradio` UI |
| Any `*.py` imports `fastapi` | `fastapi` API |
| `.pre-commit-config.yaml` | `precommit` |

Build the **check command set** from these flags:

- `precommit` set → `pre-commit run --all-files` (replaces individual linters when set)
- else `py` + ruff configured → `ruff check .` and `ruff format --check .`
- `py` + mypy configured → `mypy <pkg-or-config-target>`
- `py` + any `test_*.py` or `tests/` dir → `pytest -q`
- `js` + each present script → `npm run <script>`

If no flags fire, the check set is empty. Mark this in the report as "no checks ran (empty repo)".

UI flags inform reviewer scope only — **do not start servers**.

Report: "Phase 0 done. Worktree: $WT. Branch: dev/$SLUG. Stack: <comma-separated flags or 'empty'>. Checks: <list or 'none'>."

---

## Phase 1 — Plan

Report: "Phase 1 — Plan."

Delegate to `software-engineer` via the Agent tool. Pass the task description, the absolute path of `$WT`, the stack flags, and the check set. Ask for a written checklist saved at `$WT/$PLAN_FILE` (the path computed in 0.1).

If the task scope is ambiguous against [PRD.md](../../../PRD.md) §5 (acceptance criteria) or §6 (out-of-scope), also delegate to `product-owner` in the same parallel turn for a sanity check; otherwise skip.

Wait for the planning agent(s) to return. Read `$WT/$PLAN_FILE` and confirm it lists files to create/modify and tests to write. If it's empty or missing, retry the delegation once with a sharper prompt; if still empty, stop and report.

Report: "Phase 1 done. Plan at $WT/$PLAN_FILE."

---

## Phase 2 — Implement + test

Report: "Phase 2 — Implement."

Delegate to `software-engineer` via the Agent tool. Pass:

- The task description.
- The absolute path of `$WT`.
- The plan file path (`$WT/$PLAN_FILE` — the path computed in 0.1).
- The check command set from Phase 0.6.

Instruct the agent to:

1. Implement the code per the plan, writing files inside `$WT` only.
2. Write tests alongside (no separate FE/BE split).
3. Run each check command from the set, with `$WT` as cwd. Capture exit code and last ~30 lines of output for each.
4. Return a structured summary: files created/modified, check results table (cmd / exit / tail), open issues.

Do not run the check commands yourself — the implementation agent owns them. This keeps the orchestrator context clean.

Record check results into a Phase 2 results object you'll reuse in Phase 4.

Report: "Phase 2 done. <N> files touched. Checks: <pass/fail summary>."

---

## Phase 3 — Parallel review burst

Skip if `--skip-review` was set; report "Phase 3 skipped." and proceed to Phase 4.

Report: "Phase 3 — Parallel review."

Compute the diff once:

```bash
git -C "$WT" diff main...HEAD
```

(Use `main` as the base — adjust to `master` only if `main` doesn't exist.)

Fan out **in a single turn, parallel Agent tool calls**. Drop `ux-engineer` from the burst if no UI flag (`streamlit`/`gradio`/`fastapi`) is set — that's a 3-agent burst. Fire the codex CLI reviewer (below) in the same turn as the Agent burst via a Bash tool call.

Each prompt opens with: "You are reviewing a diff. Tag every finding `[must-fix]`, `[should-fix]`, or `[nit]`. Be concise — one bullet per finding with file:line."

| Agent | Diff scope | One-line focus |
|---|---|---|
| `ai-ml-engineer` | Prompts, evals, model-call sites, retrieval/grounding files only | "Prompts, evals, app-runtime model choice (MiniMax first, Claude fallback only after T05), hallucination guard ([PRD.md](../../../PRD.md) §4.5), independent confidence judge (§4.3), Anthropic prompt caching only if fallback is active." |
| `ux-engineer` | UI code (Streamlit/Gradio/FastAPI templates), error strings, stage-transition surfaces | "Reviewer-facing copy, stage transitions ([PRD.md](../../../PRD.md) §4.8), error states (§4.6). Skip findings outside UI scope." |
| `product-owner` | Full diff at scope level (no per-line review) | "Match [PRD.md](../../../PRD.md) §5 acceptance criteria. Flag drift into §6 out-of-scope. Decisions notes read senior?" |
| `hiring-manager` | Full diff as a candidate submission | "Grade strong / on-bar / below-bar against [CLAUDE.md](../../../CLAUDE.md) §9 (judgment + reliability). What would tank a real round-1 review?" |

`software-engineer` is **not** a reviewer — it owns implementation and the heal pass. Self-review would be circular.

### Codex CLI reviewer (parallel with the Agent burst)

In the same turn as the Agent fan-out, also fire `codex exec` via the Bash tool. This adds a second-opinion review from an independent model family (OpenAI) — useful because the four Claude-family reviewers can converge on the same blind spots. Codex is a CLI, not an Agent, so it goes in a Bash call alongside (not nested inside) the parallel Agent calls.

```bash
DIFF=$(git -C "$WT" diff main...HEAD)
if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI not found on PATH — skipping codex reviewer."
elif [ -z "$DIFF" ]; then
  echo "Empty diff — skipping codex reviewer."
else
  printf '%s\n\nDIFF:\n%s\n' \
    "You are reviewing the diff below. Tag every finding [must-fix], [should-fix], or [nit]. Be concise — one bullet per finding with file:line. End with one line: 'Verdict: strong | on-bar | below-bar'." \
    "$DIFF" \
    | timeout 300 codex exec -C "$WT" -s read-only - 2>&1
fi
```

Notes:

- Use `codex exec` (not `codex review`). `codex review`'s `--base` / `--commit` / `--uncommitted` flags are mutually exclusive with a custom prompt, so the `[must-fix]`/`[should-fix]`/`[nit]` tagging contract can only be honored via `codex exec`.
- `-s read-only` prevents codex from modifying files during review.
- `-C "$WT"` keeps codex scoped to the worktree.
- If codex is missing, unauthenticated, times out, or returns non-zero: capture the failure verbatim into the report under a "Codex" subsection and continue. Codex failure must not block Phase 4.
- Codex's `Verdict:` line is **not** the hiring grade. Only `hiring-manager` sets the hiring grade.

Treat codex output exactly like an Agent reviewer's: parse `[must-fix]` / `[should-fix]` / `[nit]` tags into the same finding lists, with `codex` as the `[source]` tag in the report.

Collect all reviewer outputs. Build a finding list keyed by tag:

- `must_fix`: items tagged `[must-fix]`, plus any `hiring-manager` overall verdict of `below-bar`
- `should_fix`: `[should-fix]`
- `nit`: `[nit]`

Report: "Phase 3 done. <N must-fix>, <N should-fix>, <N nits>. Hiring grade: <strong/on-bar/below-bar>."

---

## Phase 4 — Single self-heal + report

Report: "Phase 4 — Heal & report."

### 4.1 Decide whether to heal

Heal triggers (any one):

- A check from Phase 2 returned non-zero.
- `must_fix` list is non-empty.
- Hiring grade was `below-bar`.

If none fire, skip to 4.3.

### 4.2 Heal pass (one iteration only)

Delegate to `software-engineer` with:

- The consolidated `must_fix` list (verbatim, tagged with reviewer source).
- The list of failing check commands and their tail output.
- Instruction: address every must-fix item; re-run each check command in the set with `$WT` as cwd; return updated check results.

Record the new check results. Do **not** re-invoke reviewers. Do **not** start a second heal.

### 4.3 Append to backlog

If there are any `[should-fix]` items, remaining `[must-fix]` items (exhaustion), or `[nit]` items, append a block to `$WT/tasks/backlog.md` (create the file if missing). The repo's `.gitattributes` declares `tasks/backlog.md merge=union`, so when the user lands the worktree via `git merge --no-ff dev/<slug>` git auto-unions the new block into main's existing backlog — no manual append, no merge conflict. Discarding the worktree drops the block, which is the intended behavior.

Block format (append to end of file, separated by a blank line from any existing content):

```markdown
## <slug> — <UTC timestamp, e.g. 2026-05-10T13:42Z>
Report: <REPORT_FILE> (in dev/<slug>)

### Should-fix
- [source] file:line — summary

### Must-fix (remaining — exhaustion)
- [source] file:line — summary — why it could not be fixed

### Nits
- [source] file:line — summary
```

Use `[source]` values from the reviewer that surfaced the finding: `ai-ml-engineer`, `ux-engineer`, `product-owner`, `hiring-manager`, or `codex`. Omit any subsection that has zero items. Skip the whole append (do not create or touch the file) if all three lists are empty.

Append the block with **both a leading and a trailing blank line** so the union driver keeps adjacent blocks visually separated when multiple dev branches land. Concretely: write `\n## <slug>...\n\n` ... `\n` to the file.

### 4.4 Write report

Write `$WT/$REPORT_FILE` (the path computed in 0.1) with this template (fill in real values):

```markdown
# /dev Report

**Task:** <task description>
**Branch:** dev/<slug>
**Worktree:** <absolute path>
**Stack:** <flags or "empty">

## Files touched
- <path> — <one-line>

## Checks
| Command | Initial | After heal |
|---|---|---|
| <cmd> | pass/fail | pass/fail/n-a |

## Review findings
### Must-fix (resolved this run)
- [source] file:line — summary

### Must-fix (remaining — exhaustion)
- [source] file:line — summary — why it could not be fixed

### Should-fix (deferred)
- [source] file:line — summary

### Nits
- count: N (not listed)

## Hiring grade
<strong / on-bar / below-bar> — <one-line rationale from hiring-manager>

## Cleanup
When you're done with this work:
```
git worktree remove .worktrees/<slug>
git branch -D dev/<slug>
```
Or, to land it:
```
git checkout main
git merge --no-ff dev/<slug>
```
```

If any must-fix item could not be addressed, OR any check still fails after the heal, mark the run **EXHAUSTED** in a banner at the top of the report.

### 4.5 Final orchestrator output

Print to the caller:

```
/dev complete.
Worktree: <absolute path>
Branch: dev/<slug>
Status: clean | exhausted (see report)
Report: <wt>/<REPORT_FILE>

Next:
  - Inspect: cd <wt> && git diff main...HEAD
  - Land: git worktree remove .worktrees/<slug>; git checkout main; git merge --no-ff dev/<slug>
  - Discard: git worktree remove --force .worktrees/<slug>; git branch -D dev/<slug>
```

Do not auto-commit beyond what the implementation agent committed inside the worktree, and do not auto-merge or auto-delete the worktree.

---

## Concurrency notes

- Multiple `/dev` invocations may run in parallel (different sessions or different subagents). Each gets its own worktree under `.worktrees/<slug>/`. Slug collision is handled in Phase 0.5 by timestamp suffix.
- Never `cd` once and rely on the cwd persisting. Pass `$WT` explicitly to every command (`git -C`, tool cwd parameter, absolute paths in scripts). The shell tool persists cwd between calls, but a sibling `/dev` running in the same Claude session would step on you if you relied on it.
- The skill never deletes a worktree. The user controls cleanup so unmerged work cannot be lost by an automated retry.

## When NOT to use this skill

- Tiny edits (one-line typo, comment-only change). Just edit the file.
- Pure research / read-only investigation. Use Explore subagent instead.
- When the caller is already inside a worktree and just wants the review pass — call directly into the reviewer agents instead of nesting `/dev`.
