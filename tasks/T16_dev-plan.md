# T16 — L7 Gradio UI + stage tracker — dev plan

Owner: ux-engineer (Phase 2)
Branch: `dev/t16-gradio-ui-stage-tracker`
Contract: `tasks/T16_ui.md`
Parallel dependency: T15 (`jobfit.pipeline.run`) — not present in this worktree; the plan accommodates a local throwaway stub.

## 0. Pre-flight reads (Phase 2 must skim, not re-read in full)

- `tasks/T16_ui.md` — contract, lines 15–46 (deliverables), 47–54 (manual smoke; ignore 50–54).
- `src/jobfit/report.py:149–170` (`render_tracker` — reads only `report.statuses` + tooltip from `StageFailure.user_message` on failed pills) and `:282–300` (`render_body` — top-level short-circuit on `StageFailure` in `report.profile`).
- `src/jobfit/schemas.py:139–157` (`Report` shape + `_require_exact_status_keys` validator) and `:16–26` (status / stage literals + `REPORT_STAGE_NAMES`).
- `src/jobfit/errors.py:12–16` (`StageFailure` shape: `stage`, `user_message`, `debug_detail`).
- `pyproject.toml:8` (`gradio>=6.14.0`) — Gradio 6.14 surface is what we target.
- `tests/test_render.py:32–141` for reference fixture constructors (`_profile`, `_score`, `_salary`, etc.). Do not import test code; use as a shape reference for the stub's final yield.

## 1. Files to create or modify

Touch as few files as possible. Target = 1 file modified, 0 new files.

| Path | Action | Purpose |
| --- | --- | --- |
| `app.py` | replace stub | Gradio Blocks app, `_initial_report()`, throwaway `_stub_pipeline_run()`, fallback import of `jobfit.pipeline.run`, async handler. |

Do NOT create:

- `src/jobfit/pipeline.py` — owned by T15.
- `src/jobfit/ui.py` — contract mentions it as an option for `_initial_report` but the simpler placement is inside `app.py` for this round. T15 may relocate if needed.
- Any test file — task explicitly defers UI coverage to T21.

## 2. `_initial_report()` design

Returns a `Report` with:

- `statuses = {"profile": "pending", "score": "pending", "salary": "pending", "confidence": "pending", "growth": "pending"}` — drives the 5 grey pills.
- All five data blocks = `StageFailure(stage=<name>, user_message="pending", debug_detail=None)`.
- `raw_cv_text = ""`.

Invariant the implementer must preserve (single comment in code):

> `_initial_report()` placeholder blocks are never rendered. `render_tracker` only reads `.statuses`, and the `gr.Markdown` body component is initialised with the static "Upload a CV…" string — never with `render_body(_initial_report())`. If you ever call `render_body` on this report, you will see five `StageFailure` callouts because `report.profile` is a failure (short-circuits to the profile callout per `report.py:290`).

Why this shape: `Report.profile` is `Profile | StageFailure` and non-Optional. Constructing a `Profile` with all-empty lists technically works, but `StageFailure` is cheaper, mypy-clean, and clearly signals "no data yet" to any future caller. Schema evolution (adding a real `pending` sentinel) is T15's call.

## 3. `_stub_pipeline_run()` design

Signature mirrors T15's expected contract:

```
async def _stub_pipeline_run(file_bytes: bytes, filename: str) -> AsyncIterator[Report]: ...
```

Mark with a one-line comment: `# Throwaway: replaced by jobfit.pipeline.run once T15 lands.`

Yields, in order, with `await asyncio.sleep(~0.4s)` between yields so the reviewer can actually see the pills transition:

1. `profile = running`, rest `pending`. Blocks: all `StageFailure("…", "pending")`.
2. `profile = done` (real `Profile`), `score = running`, rest `pending`. `Profile` from `tests/test_render.py` shape — minimal but valid.
3. `score = done` (real `Score`), `salary = running`, rest `pending`.
4. `salary = done` (real `SalaryEstimate`), `confidence = running`, rest `pending`.
5. `confidence = done` (real `Confidence`), `growth = running`.
6. Final: all `done` with real `Profile`, `Score`, `SalaryEstimate`, `Confidence`, `list[GrowthAction]`. `raw_cv_text = "stub CV text"`.

Block shape minimums (copy from `tests/test_render.py:32–108` — do NOT import, just mirror values):

- `Profile`: one `ProfileItem` per category, `detected_role="engineer"`, `detected_location=None`, `detected_years_experience=5`.
- `Score`: one `Component` per category in `("skills","experience","education","soft_signals")`, each with `Anchor(quote="…", section="Work Experience")`.
- `SalaryEstimate`: `low <= high`, `period="month"`, ≥1 `Source` with a valid `HttpUrl` (`https://platy.cz/path` works).
- `Confidence`: `tier="High"` or `"Medium"`, `rationale="stubbed"`.
- `list[GrowthAction]`: 2 actions, `time_horizon_months` in `[1, 24]`.

Total stub runtime: ~2s. Just enough to demonstrate streaming; no realism beyond schema validity.

Failure-injection hook: not required for T16. T18 owns the failure-rendering manual smoke; we just need the happy path to stream cleanly.

## 4. `app.py` structure

Top-of-file fallback import pattern (this is the only piece of "cleverness" — must be obvious at a glance):

```
try:
    from jobfit.pipeline import run as pipeline_run  # T15
except ImportError:
    pipeline_run = _stub_pipeline_run  # defined below; throwaway
```

The `try`/`except ImportError` must come AFTER `_stub_pipeline_run` is defined, OR use a deferred lookup inside `handle()`. Recommendation: define stub first, then do the try/except import at module level — keep it boring.

Layout (mirror `tasks/T16_ui.md` lines 21–39 with the corrections from §6 below):

- `gr.Blocks(title="Job Fit & Salary Estimator")` — no `theme=` arg unless the implementer wants the default soft theme; contract leaves it blank.
- `gr.Markdown` — header copy from contract verbatim.
- `gr.File(file_types=[".pdf", ".docx"], label="CV", type="filepath")` — `type="filepath"` is the Gradio 6.x default; making it explicit eliminates the ambiguity in the contract snippet that says `file.name`. The handler receives a `str | None` filepath, not a `NamedString` object.
- `gr.Button("Generate report", variant="primary")`.
- `gr.HTML(value=render_tracker(_initial_report()))` — bound to `tracker_html`.
- `gr.Markdown(value="*Upload a CV and click Generate report.*")` — bound to `report_md`. This static string is the reason `_initial_report()`'s placeholder failures never render.

Async handler:

```
async def handle(file_path: str | None):
    if file_path is None:
        yield render_tracker(_initial_report()), "*Please upload a CV first.*"
        return
    with open(file_path, "rb") as fh:
        file_bytes = fh.read()
    filename = Path(file_path).name
    async for report in pipeline_run(file_bytes, filename):
        yield render_tracker(report), render_body(report)
```

Notes:

- The contract uses `file.name`; in Gradio 6.14 with `type="filepath"`, the input is the string path directly. Use `Path(file_path).name` to get the basename for the pipeline call.
- `async for` over an async generator is Gradio-6-supported; the queue dispatches each yield as a streaming update. If the queue swallows intermediate yields in practice, see §6 risks.

Wiring + launch:

```
run_btn.click(handle, inputs=[file_in], outputs=[tracker_html, report_md])

if __name__ == "__main__":
    demo.queue().launch(max_file_size="10mb")
```

CRITICAL: in Gradio 6.14, `max_file_size` is a kwarg of `launch()`, NOT `queue()` (verified via `inspect.signature` against the worktree's installed gradio). The contract on line 46 says "queue config (`max_file_size="10mb"`)" — that's outdated. Plan corrects it.

No CSS in `app.py`. `render_tracker` already emits `<style>…</style>` inline (see `report.py:72–100`). Re-defining CSS here would create a duplicate/conflicting rule set.

Imports needed in `app.py`:

- `asyncio` (for `sleep` in stub)
- `pathlib.Path`
- `gradio as gr`
- `from collections.abc import AsyncIterator`
- `from jobfit.errors import StageFailure`
- `from jobfit.report import render_body, render_tracker`
- `from jobfit.schemas import (Anchor, Component, Confidence, GrowthAction, Profile, ProfileItem, Report, SalaryEstimate, Score, Source)` for the stub
- Conditional `from jobfit.pipeline import run as pipeline_run`

Type the handler so mypy strict is happy: `async def handle(file_path: str | None) -> AsyncIterator[tuple[str, str]]`.

## 5. Manual smoke verification (Phase 2 evidence to capture)

Run from worktree root:

```
uv run python app.py &
APP_PID=$!
# give Gradio a moment to bind
until curl -sf http://localhost:7860/ > /dev/null; do sleep 1; done
echo "UI up"
# Phase 2: open localhost:7860 in a browser, upload tests/fixtures/cvs/03_ds_horak.pdf,
# click Generate, watch the 5 pills transition pending -> running -> done left-to-right,
# watch the markdown body populate after the final yield.
kill $APP_PID
```

Evidence to record in `tasks/T16_dev-report.md`:

- `curl http://localhost:7860/` returns 200 (server is up).
- Manual: pills cycle through `pending` (grey) → `running` (amber) → `done` (green) for each stage. Reduced-motion: spot-check by enabling OS reduced-motion or DevTools emulation; pills should still transition colour but without CSS transition animation (per `report.py:99`).
- Markdown body renders Score/Salary/Confidence/Plan/footer with no exceptions in the terminal.
- Total elapsed time on stub: ~2s. (Real pipeline target is ~60s — out of scope here.)
- Terminal: zero tracebacks across the run.

Skip (out of scope per caller): the deployed-Space smoke from `T16_ui.md:50–54` — T22 owns deployment, and the Space won't have T15/T16 until then.

## 6. What NOT to touch — red lines

- `src/jobfit/pipeline.py` — does not exist in this worktree; T15 owns it. Do not create.
- `src/jobfit/schemas.py` — do not add a "pending" variant to the block unions, do not change `Report`'s field types to Optional. Work around with `StageFailure` placeholders.
- `src/jobfit/report.py` — CSS, status labels, body short-circuit logic all owned by T14. No edits.
- `src/jobfit/errors.py` — `StageFailure` shape is fixed.
- Do not add a UI test under `tests/`. T21 (eval_corpus) covers end-to-end behaviour.

## 7. Open questions / risks (resolve before declaring done)

1. **Gradio 6.x async-generator streaming over the queue.** `demo.queue()` in 6.14 should dispatch each `yield` from an `async def` generator as a partial update to the bound outputs. Verified by signature, not by runtime. If intermediate yields don't appear in the browser (only the final one renders), the fallback is `time.sleep` inside a sync generator with `gr.Progress` — but that breaks the T15 async contract. **Action:** Phase 2 must visually confirm intermediate yields render. If not, file a follow-up — do NOT switch to sync.
2. **`max_file_size` on `launch()` vs `queue()`.** Resolved by signature probe: it lives on `launch()` in 6.14. Plan reflects this. Phase 2 should still spot-check that uploading a >10 MB file produces a clear client-side error rather than a backend crash.
3. **`gr.File` return type.** With `type="filepath"` (the default), the handler receives `str | None`, not a Gradio-internal object. Plan codifies `type="filepath"` explicitly to remove the contract's `file.name` ambiguity.
4. **Stub-vs-real import order.** The try/except import at module level only works if `_stub_pipeline_run` is defined before the try block. Cleaner alternative: import inside `handle()` (one-shot, no fallback indirection). Pick the option with the smaller diff. Recommendation: module-level try/except — keeps the handler hot path free of import logic.
5. **Pydantic HttpUrl for the stub Source.** The stub yields a real `SalaryEstimate` with a `Source(url=HttpUrl(...))`. Pydantic v2 coerces a string at construction; passing `"https://platy.cz/path"` is fine. If mypy strict complains, cast or use `HttpUrl("https://platy.cz/path")`.
6. **`Report.raw_cv_text` on intermediate yields.** Schema requires it. Stub passes `""` for early yields and `"stub CV text"` on the final yield. Renderer doesn't consume it, so the value is cosmetic.
7. **Reduced-motion verification.** Already covered by `report.py:99`'s `@media (prefers-reduced-motion: reduce)` rule. Spot-check via DevTools "Emulate CSS prefers-reduced-motion: reduce" rather than reimplementing.
8. **Theme.** Contract leaves `theme=…` as ellipsis. Skip the kwarg; default Gradio theme is fine. Do not invent a custom theme — that's decoration, not judgment-affecting.

## 8. Check set (Phase 2 must run all three)

```
pre-commit run --all-files
uv run mypy src/
uv run pytest -m fast --strict-markers
```

`mypy src/` deliberately excludes `app.py` (per `pyproject.toml:41` mypy `files = ["src/jobfit"]`). If the implementer wants type coverage on `app.py`, run a one-off `uv run mypy app.py` and fix anything strict flags — but do not change the mypy config scope.

## 9. Definition of done for T16

- `app.py` replaces the stub with the Blocks app described above.
- `uv run python app.py` starts; `curl localhost:7860/` returns 200.
- Manual smoke with `tests/fixtures/cvs/03_ds_horak.pdf` shows pills cycle and markdown body renders, no terminal traceback.
- All three checks in §8 pass.
- `tasks/T16_dev-report.md` written with the evidence from §5 plus any version quirks discovered.
