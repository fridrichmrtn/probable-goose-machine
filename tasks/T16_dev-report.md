# /dev Report — T16

**Task:** Implement T16 (L7 Gradio UI + stage tracker) per `tasks/T16_ui.md`. Replace the `app.py` stub with a Gradio Blocks app that streams `Report` state from `pipeline.run` (T15 stubbed locally — built in a parallel session).
**Branch:** `dev/t16-gradio-ui-stage-tracker`
**Worktree:** `/home/mf/GitHub/probable-goose-machine/.worktrees/t16-gradio-ui-stage-tracker`
**Stack:** py, gradio, precommit

## Files touched

- `app.py` — replaced bootstrap stub with Gradio Blocks app, `_initial_report()`, throwaway `_stub_pipeline_run()`, `find_spec`-gated import of `jobfit.pipeline.run`, async `handle()` with an immediate "Reading file…" transitional yield.
- `tasks/T16_dev-plan.md` — added during Phase 1 (the plan that Phase 2 implemented).
- `tasks/backlog.md` — appended block of should-fix + nit items (auto-unioned on merge via `.gitattributes`).
- `tasks/T16_dev-report.md` — this report.

Commits on the branch:
- `ba12056` — initial implementation (Phase 2)
- `ad50e81` — heal pass (Phase 4.2)

`src/jobfit/{pipeline,schemas,report,errors}.py` were NOT touched (red lines respected). No new tests added (UI coverage deferred to T21 per task contract).

## Checks

| Command | Initial (Phase 2) | After heal (Phase 4.2) |
|---|---|---|
| `pre-commit run --all-files` | pass (exit 0) | pass (exit 0) |
| `uv run mypy src/` | pass (exit 0, 14 files) | pass (exit 0, 14 files) |
| `uv run mypy app.py` (bonus) | pass (exit 0) | pass (exit 0) |
| `uv run pytest -m fast --strict-markers` | pass (169 passed, 42 deselected, 3.41s) | pass (169 passed, 42 deselected, 2.90s) |
| Smoke: `uv run python app.py` + `curl localhost:7860/` | 200 OK | 200 OK (uvicorn, content-length 18637, valid Gradio HTML) |
| Stub iteration: 6 yields with expected status progression | ✓ profile→score→salary→confidence→growth `pending→running→done` cascade | ✓ same; `handle(None)` yields the new empty-state copy |

## Manual smoke evidence

Per task contract `tasks/T16_ui.md:47-49`, manual smoke is the verification surface — no automated UI test was added (deferred to T21).

- **Server bind:** `curl -sf http://localhost:7860/` returned 200 with valid Gradio HTML body (18637 bytes). Server killed cleanly after the probe.
- **Stub iteration (orchestrator-friendly substitute for clicking Generate in a browser, since the harness cannot drive a GUI):**
  - 6 yields of type `Report` from `_stub_pipeline_run(b"fake", "cv.pdf")`.
  - Status progression matches plan §3:
    1. `profile=running`, rest `pending`
    2. `profile=done`, `score=running`
    3. `score=done`, `salary=running`
    4. `salary=done`, `confidence=running`
    5. `confidence=done`, `growth=running`
    6. all `done`
  - Final yield carries real `Profile / Score / SalaryEstimate / Confidence / list[GrowthAction]` with `raw_cv_text="stub CV text"`.
- **Render check:** `render_tracker` produced valid HTML for all 6 yields; `render_body` on the final yield produced ~1259 chars with `## Score / ## Salary / ## Confidence / ## Plan` sections; `render_tracker(_initial_report())` produced 5 pending pills.
- **Empty-upload:** `handle(None)` yields exactly one tuple whose body matches the new empty-state copy.
- **Terminal logs:** zero tracebacks across the run.

**Browser-side gaps (not verifiable without a GUI driver — orchestrator limitation):**
- Whether Gradio 6.14 actually streams each `async def` generator yield as a partial queue update (plan §7.1). Signature analysis says yes; runtime observation requires a human or a Playwright probe. Open as a should-fix in the backlog.
- Reduced-motion CSS spot-check (plan §7.7). T14's `@media (prefers-reduced-motion: reduce)` rule at `src/jobfit/report.py:99` is present and correctly disables the pill colour-transition. Visual verification deferred.
- Mid-stream `render_body` callouts: the stub uses `StageFailure("pending")` as a placeholder for not-yet-run blocks. `render_body` short-circuits on `profile=StageFailure`, so intermediate yields would show "Profile failed: pending" until the final yield. Captured as a should-fix in the backlog — likely T15 absorbs the fix when it introduces real None-blocks via the planned schema tweak.

## Review findings

### Must-fix (resolved this run)

1. **[codex]** `app.py:244` — Broad `except ImportError` masks import-time bugs inside real `jobfit.pipeline`. Replaced with `importlib.util.find_spec("jobfit.pipeline")` gate. Real import errors now propagate.
2. **[ux-engineer]** `app.py:262` — Empty-upload copy lacked file-format constraint and recovery path. Replaced with `"*No file selected. Upload a PDF or DOCX (max 10 MB) and click Generate report.*"`.
3. **[ux-engineer]** `app.py:267` — No yield before `pipeline_run`'s first state; the button click looked dead during cold start (PRD §8). Added an immediate transitional yield (`"*Reading file…*"`) with `statuses["profile"]="running"` before iterating the pipeline.

### Must-fix (remaining — exhaustion)

None.

### Should-fix (deferred — see `tasks/backlog.md` for the full list)

15 items spanning: stub mid-stream callouts (codex), copy misleading-ness (codex), file-type/size affordance (ux), button re-click prevention (ux), accessible labels (ux), blocking I/O in async handler (ux/po/hm/qa), OSError handling (po), file extension validation (po), `type: ignore` on stub Source URL (po/hm), stub copy-paste density (hm), pipeline-run async-iterable assert (hm), browser-side streaming evidence gap (hm/qa), contract bugs in `tasks/T16_ui.md` (qa/hm), unfalsifiable manual smoke language (qa), README bootstrap stub (qa, pre-existing).

### Nits

count: 6 (see `tasks/backlog.md`).

## Hiring grade

**on-bar** — Plan was unusually strong: pre-empted three Gradio 6.x version traps (`max_file_size` on `launch()` not `queue()`, `gr.File(type="filepath")` resolving the `file.name` ambiguity, `StageFailure` placeholders to avoid schema churn) and correctly delegated schema evolution to T15. Implementation papered over two judgment calls (the `except ImportError` was too broad — healed; the stub is 186 lines of copy-paste where a loop would have been ~30 — flagged for backlog) but is correct, type-clean, and ships with verifiable evidence for the non-GUI surface. The runtime streaming risk Plan §7.1 named is unresolved due to the orchestrator's no-browser constraint; that gap is the only thing keeping this below "strong."

Codex reviewer flagged below-bar; its concerns map to the one must-fix (broad ImportError — healed) plus two should-fix items now on the backlog (stub mid-stream callouts, "in-memory" copy vs filepath temp file). Per the /dev contract, only the hiring-manager's grade sets the hiring bar.

## Cleanup

When you're done with this work:

```
git worktree remove .worktrees/t16-gradio-ui-stage-tracker
git branch -D dev/t16-gradio-ui-stage-tracker
```

Or, to land it (preserves the 2-commit train: Phase 2 + heal):

```
git checkout main
git merge --no-ff dev/t16-gradio-ui-stage-tracker
```

Or, via GitHub PR (matches the post-Block-train workflow):

```
git -C .worktrees/t16-gradio-ui-stage-tracker push -u origin dev/t16-gradio-ui-stage-tracker
gh pr create --title "T16: L7 Gradio UI + stage tracker (pipeline stubbed pending T15)" --body ...
gh pr merge <num> --merge   # use --merge, NOT --squash, to preserve the commit train
```

Coordination note: T15 is being built in a parallel session. When T15 lands `src/jobfit/pipeline.py`, the `find_spec` gate in `app.py` will switch to the real `run` automatically; the `# type: ignore[import-not-found]` on the import line should be dropped at that point (mypy will warn "unused type: ignore").
