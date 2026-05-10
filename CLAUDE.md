# CLAUDE.md

Project instructions for Claude working in this repository. Treat this file as the operating contract for each session.

This file is committed and team-shared. Personal overrides go in `CLAUDE.local.md` (gitignored). Shared permissions and env live in `.claude/settings.json`; per-user overrides live in `.claude/settings.local.json` (gitignored).

## Model Context

- Claude Code / subagent infrastructure: use the smallest model tier that can complete the work without increasing rework risk. This describes how repository agents do their work; it is not the application's runtime model choice.
  - Haiku: high-volume, mechanical, structured tasks with low judgment risk, such as tagging, classification, simple extraction, and checklist-style review.
  - Sonnet: scoped research, code exploration, synthesis, implementation planning, and ordinary multi-step engineering work.
  - Opus: only when stakes, ambiguity, and novelty all converge, such as architecture from a vague brief, subtle legacy debugging, or high-impact trade-off decisions.
  - These tier guidelines apply to subagents you spawn. The orchestrator's model is selected by the user at session start.
- Application runtime LLM: default to MiniMax via the OpenAI-compatible API, per `tasks/PLAN.md` (`MiniMax-M1` for reasoning-heavy stages, `abab6.5s-chat` for confidence/cheap/CI paths). Claude Sonnet 4.6 is a fallback only if the T05 MiniMax capability spike fails.
- Keep provider-specific app code behind `jobfit.llm`. Anthropic prompt caching applies only when the application fallback provider is actually Anthropic.
- Prefer concise execution for trivial edits; do not turn simple work into ceremony.
- Context controls live in `.claude/settings.json` (shared) with personal overrides in `.claude/settings.local.json`. Keep 1M context disabled and compact around 80% unless a task explicitly needs long-context work.

## Workflow Orchestration

### 1. Plan Mode Default

Enter Plan Mode for any non-trivial task:

- The task has 3 or more meaningful steps.
- The task involves architecture, data modeling, public APIs, agent behavior, or user-facing workflow decisions.
- The task has unclear requirements, hidden dependencies, or meaningful risk.
- The task needs verification beyond a quick syntax or formatting check.

Plan Mode expectations:

- Write a detailed spec before implementation when ambiguity would otherwise leak into code.
- Define the intended outcome, assumptions, acceptance criteria, implementation steps, and verification steps.
- If something goes sideways, stop immediately and re-plan. Do not keep pushing through a stale plan.
- Use Plan Mode for verification, not only for building.

Skip Plan Mode for truly simple, obvious fixes where planning would add friction without reducing risk.

### 2. Subagent Strategy

Use subagents when delegation keeps the main context clean or enables useful parallel work. Do not spawn subagents for tiny direct tasks where targeted local inspection is cheaper.

- Offload research, exploration, and parallel analysis to subagents.
- For complex problems, split independent research, review, and verification work across focused subagents.
- Give each subagent one task, one clear output format, and one decision surface.
- Do not ask multiple subagents to do the same work unless independent comparison is useful.
- Bring subagent results back into the main thread as concise conclusions, not full transcripts.
- Maximum spawn depth is 2: the orchestrator may spawn a subagent, which may spawn one further subagent. No deeper.
- Haiku-sized work never spawns further subagents. If it needs delegation, the task was sized wrong.
- If a subagent realizes it needs stronger reasoning, broader scope, or a product decision, it reports back to the parent instead of escalating itself.
- Match model tier to risk: Haiku for mechanical bulk work, Sonnet for ordinary scoped reasoning and synthesis, Opus only for high-stakes ambiguous novelty.

Available local subagents:

- `software-engineer`: default for backend, full-stack, infrastructure, testing, business logic, and general implementation.
- `product-owner`: requirements, product framing, acceptance criteria, scope control, and product review.
- `ux-engineer`: frontend, accessibility, responsive layouts, component quality, and interaction review.
- `ai-ml-engineer`: model selection, prompts, evals, RAG, agent design, and AI behavior review.
- `hiring-manager`: interview-style code review, hiring bar assessment, rubrics, and evaluation materials.

Common routes:

- Use `product-owner` before unclear feature work, scope negotiation, or acceptance-criteria writing.
- Use `software-engineer` for implementation planning, backend or full-stack work, and pragmatic code review.
- Use `ux-engineer` before completing user-facing UI, accessibility, responsive layout, or interaction changes.
- Use `ai-ml-engineer` for prompt changes, eval design, model choice, RAG, or agent/tool behavior.
- Use `hiring-manager` when the work needs an interview-style quality bar, rubric, or candidate-style assessment.

Use one task per subagent. Keep delegation narrow, explicit, and useful.

### 3. Context Hygiene

Keep the main thread focused on decisions and durable conclusions.

- Prefer targeted shell and text tools before loading broad context: `rg`, `sed`, `git diff`, `git show`, focused file reads, and narrow logs.
- Prefer `WebFetch` for public text pages. Use browser or dynamic-page tooling only when the page requires JavaScript, auth, or interaction.
- Prefer `pdftotext` or another text extractor for PDFs before feeding full documents into model context.
- When the same fetch, parse, or extract pattern repeats, wrap it as a reusable local command or script.
- Summarize long findings instead of pasting full transcripts.
- Quote only the log lines, stack traces, or file snippets needed to support a decision.
- Delegate noisy exploration to subagents when it can run independently.
- Bring back the conclusion, confidence level, and any remaining uncertainty.
- Prefer concise checkpoints over exhaustive narration.

### 4. Self-Improvement Loop

After any correction from the user:

- Update `tasks/lessons.md` with the correction pattern.
- Write a concrete rule that would prevent the same mistake next time.
- Review relevant lessons at the start of future sessions.
- Keep lessons sharp and actionable; delete or rewrite lessons that become vague, stale, or noisy.

Use this entry format:

```md
- Date:
- Correction:
- Pattern:
- Rule:
```

If `tasks/lessons.md` does not exist yet, create it when the first lesson is needed.

### 5. Verification Before Done

Never mark a task complete without proving it works.

- Run the relevant tests, checks, linters, or type checks.
- Check logs or error output when debugging.
- Demonstrate correctness with concrete evidence.
- Diff behavior between `main` and the current change when behavior changes are meaningful.
- For user-facing work, run the system end-to-end from a clean path before declaring done. Setup friction or runtime breakage in a fresh environment is a defect, not a deployment problem.
- Ask: "Would a staff engineer approve this?"

If full verification is impossible, clearly state what was verified, what was not verified, and why.

### 6. Definition of Done

A task is done only when:

- The requested implementation or documentation change is complete.
- Relevant tests, checks, reviews, or manual verification have been run.
- Remaining risks, limitations, and unverified areas are named.
- `tasks/todo.md`, `tasks/lessons.md`, or other docs are updated when the task requires them.
- The final response includes what changed and the evidence that it works.

### 7. Demand Elegance, Balanced

For non-trivial changes, pause before finalizing and ask whether there is a simpler or more elegant solution.

- If the current solution feels hacky, rework it from the perspective: "Knowing everything I know now, implement the elegant solution."
- Prefer small, direct, maintainable changes over clever abstractions.
- Challenge the work before presenting it.
- Skip this step for simple, obvious fixes where deeper design review would be over-engineering.

### 8. Autonomous Bug Fixing

When given a bug report, own the fix.

- Reproduce or identify the failure from logs, errors, tests, or code paths.
- Fix the root cause without asking the user for hand-holding.
- Go fix failing CI tests without being told how.
- Ask for help only when blocked by missing access, missing secrets, destructive decisions, or product ambiguity that cannot be resolved from context.

### 9. AI-Engineering Rigor

When the work involves LLM prompts, evals, or model behaviour:

- Treat model output as untrusted. Validate structure programmatically. Ground claims to source text the system actually has.
- Separate generation from grading. The model that produced a number should not also judge whether the number is trustworthy.
- Prefer eval sets over single-example checks. A prompt that works once is not verified.
- Iterate prompts against representative inputs before declaring done. Note what failed and what changed.
- Default to `ai-ml-engineer` for prompt design, eval construction, and agent behaviour review.

## Task Management

Use `tasks/todo.md` only for work that spans multiple meaningful steps, multiple sessions, or decision-heavy implementation. Do not create task tracking for tiny edits or obvious fixes.

For tracked non-trivial tasks:

- Plan first: write the plan to `tasks/todo.md` with checkable items.
- Verify the plan: check in before implementation only when the plan affects architecture, product behavior, irreversible work, or broad code paths.
- Track progress: mark items complete as work moves forward.
- Explain changes: provide high-level summaries at meaningful milestones.
- Document results: add a review section to `tasks/todo.md` with verification evidence and remaining risks.
- Capture lessons: update `tasks/lessons.md` after user corrections.

If `tasks/` does not exist, create it only when task tracking or lessons are actually needed.

## Engineering Principles

- Simplicity first: make every change as simple as possible.
- Respect the budget. If a sub-task would consume disproportionate time relative to the stated build window, flag the trade-off and seek direction before continuing.
- Reliability beats breadth. Cut decoration before adding features. Anything that does not serve judgment or reliability is decoration.
- Root cause over patches: no temporary fixes unless explicitly requested and documented.
- Minimal impact: touch only what is necessary for the task.
- Consistency matters: follow existing project patterns before introducing new ones.
- Tests should protect behavior users or maintainers care about.
- Instrument by default. Pipeline stages should emit structured signals (stage, duration, key counters). A silent stage is a debt.
- Failures surface as useful messages, not stack traces. A failed stage isolates its blast radius — the rest of the system continues to render.
- When prompts or evals interpret personal data, audit for demographic-correlated signals before shipping. Default to evidence-based attributes (skills, experience, role progression) over surface ones (names, schools, language patterns).
- Do not hide uncertainty. State assumptions, risks, and unverified areas plainly.

## Communication Style

- Be direct, concise, and useful.
- Do not ask the user to make routine implementation decisions Claude can safely resolve.
- Ask before architecture changes, destructive actions, irreversible migrations, credential use, broad product decisions, or major scope changes.
- Proceed autonomously for routine implementation, bug fixing, local investigation, and safe verification.
- Keep summaries focused on what changed, why it changed, and how it was verified.
- Do not invent specifics in prompts, copy, commit messages, or PR descriptions. Quote sources or mark uncertainty plainly.
- When reviewing, lead with risks and concrete findings before general commentary.

## Session Start Checklist

At the start of a meaningful session:

- Read this file.
- Read `tasks/lessons.md` if it exists.
- Inspect current git status before editing.
- Identify the relevant subagent strategy if the task is non-trivial.
- Create or update `tasks/todo.md` only when the task warrants durable tracking.
