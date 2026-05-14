# /dev Report

**Task:** Implement the approved plan at `/home/mf/.claude/plans/i-want-ux-engineer-jolly-wadler.md` — UI polish pass 2: kill streaming overlay, fix dead gap, add disabled-button state, shift primary color, responsive hero, dark-mode handling, report-body max-width, scanned-PDF caption.
**Branch:** `dev/ui-polish-pass-2`
**Worktree:** `/home/mf/GitHub/probable-goose-machine/.worktrees/ui-polish-pass-2`
**Stack:** py, precommit, gradio

## Files touched
- `app.py` — EDIT. `show_progress="hidden"` on `file_in.change` + `run_btn.click`; `gr.HTML`/`gr.Markdown` outputs start `visible=False` with `elem_classes=["gander-output"]`; all 4 `handle()` yields rewritten to `gr.update(visible=..., value=...)`; primary `#b54708` → `#92400e` (hover `#7c2d12`); new `button.primary:disabled` rule (`#fdba74`, `cursor: not-allowed`); `.gander-hero` got `flex-wrap: wrap`; new `@media (prefers-color-scheme: dark)` block; caption updated with scanned-PDF clause; `_read_error_report()` helper added so file-read failures surface a failed `profile` pill + PRD §4.6 copy.
- `src/gander/report.py` — EDIT. Appended `_CSS` rules: `.gander-output { max-width: 72ch; margin-inline: auto }`; `.gander-output table` borders + centering; full dark-mode override block (pill palette, callout, table borders). Heal pass tightened selector from `.gander-output .prose, .gander-output .md` to `.gander-output` (the `prose` and our class are siblings on the same element, not parent-child).
- `tasks/dev-plan.md` — NEW. Phase 1 implementation checklist (92 lines): files to modify, ordered step-by-step edits, explicit "no test changes", risks, pre-merge gates.

## Checks

| Command | Initial | After heal |
|---|---|---|
| `uv run ruff format --check .` | pass | pass |
| `uv run ruff check .` | pass | pass |
| `uv run mypy src/gander` (15 files) | pass | pass |
| `uv run pytest -m fast` (196 tests) | pass | pass |
| `uv run pre-commit run --all-files` | pass | pass |

## Review findings

### Must-fix (resolved this run)
- `[ux-engineer] src/gander/report.py:96-97` — Dead CSS selector. `.gander-output .prose, .gander-output .md` cannot match because Gradio renders `<div class="prose ${elem_classes}...">` — i.e., `.prose` and `.gander-output` land on the SAME element as siblings, not parent-child. Verified by reading the Gradio frontend svelte chunk. Healed: replaced with `.gander-output { max-width: 72ch; margin-inline: auto }`. Commit `7ec8466`.
- `[product-owner] app.py error branches` — No-file and OSError branches yielded only an italic markdown error string with the tracker hidden, leaving the reviewer with no failed-stage signal. PRD §4.6 specifies the exact copy `"Unable to read this file. Please upload a valid PDF or DOCX."` and §4.8 expects the tracker to show the failed stage. Healed: added `_read_error_report(user_message)` helper that constructs a `Report` with `profile=StageFailure` + `statuses["profile"]="failed"`; both error branches now yield the visible failed tracker + the PRD §4.6 string. Commit `7ec8466`.

### Must-fix (remaining — exhaustion)
None.

### Should-fix (deferred → backlog)
12 items captured in `tasks/backlog.md` under `## ui-polish-pass-2 — 2026-05-14T09:46Z`. Headline ones:
- `[ux-engineer]` dark-mode `.pill.running` `#fbbf24` reads as warning, not progress.
- `[product-owner]` `handle()` lacks `try/finally` around the `async for`; unexpected exceptions still surface as Gradio toast stack traces.
- `[product-owner]` `app.py:1-13` module docstring is now partially stale (still says body is "initialised empty").
- `[hiring-manager]` `button.primary` selector pairs `!important` AND the `.gradio-container`-prefixed override — pick one.
- `[hiring-manager]` cool-blue focus ring `#1d4ed8` against warm `#92400e` button is visually jarring; derive ring from brand.
- `[hiring-manager]` dark-mode disabled `#7c2d12` collides with light-mode primary `:hover` of the same color — two distinct states sharing a tone.
- `[qa-engineer]` no unit test on `handle()` async-iterator yield shape; a forgotten `visible=True` ships untested.
- `[qa-engineer]` no contract test pins the PRD §4.6 error strings; string drift ships untested.
- `[codex]` `dict[str, Any]` typing on `gr.update()` return is more specific than Gradio's actual contract.

### Nits
- count: 6 (recorded in `tasks/backlog.md` under the same heading).

## Hiring grade

**on-bar** — Consensus across `ux-engineer`, `product-owner`, `hiring-manager`, and `qa-engineer`. The change is focused, well-scoped, and every gate is green; the heal pass closed both must-fixes without expanding scope. Held back from `strong` by the specificity-cargo-cult in the CSS overrides (double `!important` + `.gradio-container` prefix), the cool-blue focus ring on a warm button, and the dark-mode disabled color collision with light-mode hover — all polish-level, none load-bearing. Codex independently returned `strong`; its verdict is *not* the hiring grade per dev-skill convention, but the convergence is a useful signal that the design intent reads cleanly.

## Cleanup

When you're done with this work:
```
git worktree remove .worktrees/ui-polish-pass-2
git branch -D dev/ui-polish-pass-2
```
Or, to land it:
```
git checkout main
git merge --no-ff dev/ui-polish-pass-2
```
