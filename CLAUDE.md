# CLAUDE.md

Team-shared instructions for Claude working in this repository. Personal overrides belong in `CLAUDE.local.md`; do not commit them.

## Project

- [PRD.md](PRD.md) is the product source of truth. Gander accepts a CV and produces a grounded seniority score, market salary range, and CV-specific growth plan.
- The application is Python 3.11+, managed with `uv`, with package code in `src/gander`, the Gradio entry point in `app.py`, and tests in `tests`.
- The runtime defaults to OpenRouter through an OpenAI-compatible client. Optional local routing is supported. `src/gander/llm.py` is the source of truth for providers, model routes, fallbacks, and environment variables; do not duplicate model IDs in agent guidance.
- Keep provider-specific application behavior behind `gander.llm`.
- This is a deliberately small candidate submission. Judgment, reliability, and end-to-end runnability matter more than breadth.

## Product invariants

- Treat model output as untrusted and validate structured responses.
- Redact PII before scoring. Never log raw CV text, prompts containing CV text, or extracted personal data; diagnostics may include only safe metadata such as file size and type.
- Ground candidate claims in programmatically verified source quotes. Drop unverifiable claims rather than rewriting or inventing them.
- Judge salary confidence independently from salary generation.
- Isolate stage failures so the rest of the report can render with the user-facing messages defined in PRD §4.6.
- Preserve structured stage telemetry: stage, duration, safe counters, and sanitized failure context.
- Keep authentication, persistence, batch processing, OCR, mobile UI, and broader localization out of scope unless the user explicitly changes scope.

## Working approach

1. Read the relevant code and tests, then inspect `git status` before editing.
2. Search for an existing implementation or pattern before adding one.
3. Fix root causes at the shared boundary and keep the diff as small as correctness allows.
4. Validate external input and model output; do not add defensive layers around trusted internal calls.
5. Do not add dependencies, abstractions, config, documentation, or task files for hypothetical future needs.
6. Preserve unrelated user changes in a dirty worktree.

Use a written plan only when ambiguity, risk, or coordination makes it useful. Small, obvious changes should be implemented and checked directly.

Use subagents only for focused work that benefits from separate context or real parallelism:

- `software-engineer`: implementation, infrastructure, and tests.
- `product-owner`: requirements, acceptance criteria, and scope.
- `ux-engineer`: user-facing behavior and accessibility.
- `ai-ml-engineer`: prompts, evals, grounding, and model behavior.
- `qa-engineer`: coverage, reproducibility, and quality evidence.
- `hiring-manager`: interview-style review and evaluation material.

Give each subagent one bounded task. Do not create orchestration ceremony for work that is cheaper to do directly.

## Verification

- Run the smallest relevant check that would fail on a regression, then expand checks in proportion to risk.
- Use `pyproject.toml`, `.pre-commit-config.yaml`, and CI as the source of truth for current commands and test markers.
- Do not run paid, live, or browser tests unless the task needs them and the required access is available.
- Never claim completion from a green command alone: connect the check to the behavior it proves.
- If a check cannot run, state exactly what was and was not verified.

## Communication

- Be direct and concise. Lead reviews with concrete risks and file locations.
- Resolve routine implementation details autonomously. Ask before destructive actions, credential use, architecture changes, or material product-scope changes.
- Final responses state what changed, what verified it, and any remaining risk.
