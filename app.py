"""L7 Gradio UI — file upload, stage tracker, streaming markdown report.

The UI is a pure function of `Report` state: every yield from `pipeline.run`
re-renders both the tracker HTML and the body markdown. No UI-side state.

`_initial_report()` placeholder blocks are never rendered. `render_tracker`
only reads `.statuses`, and the `gr.Markdown` body is initialised empty —
never with `render_body(_initial_report())`. Calling `render_body` on this
report would short-circuit to a `StageFailure` callout because
`report.profile` is a failure (see `report.py` line 290). The tracker is
also initialised empty so the 5-pill row only appears once the user clicks
Analyze CV (the handler's first yield calls `render_tracker(reading_report)`).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import gradio as gr

from gander.errors import StageFailure
from gander.llm import check_env
from gander.pipeline import run as pipeline_run
from gander.report import render_body, render_tracker
from gander.schemas import Profile, Report


def _initial_report() -> Report:
    return Report(
        profile=StageFailure(stage="profile", user_message="pending"),
        score=StageFailure(stage="score", user_message="pending"),
        salary=StageFailure(stage="salary", user_message="pending"),
        confidence=StageFailure(stage="confidence", user_message="pending"),
        growth=StageFailure(stage="growth", user_message="pending"),
        statuses={
            "profile": "pending",
            "score": "pending",
            "salary": "pending",
            "confidence": "pending",
            "growth": "pending",
        },
    )


def _read_error_report(user_message: str) -> Report:
    """Report for pre-pipeline read failures (no file selected, OSError).

    Profile is marked failed with the user-facing message; downstream stages
    stay skipped so the tracker shows where the pipeline stopped.
    """
    failure = StageFailure(stage="profile", user_message=user_message)
    return Report(
        profile=failure,
        score=None,
        salary=None,
        confidence=None,
        growth=None,
        statuses={
            "profile": "failed",
            "score": "skipped",
            "salary": "skipped",
            "confidence": "skipped",
            "growth": "skipped",
        },
    )


# Best-effort handle to the previous run's download artifact. Each completed run
# writes a temp .md that must outlive `_write_report_md` (Gradio streams it from
# disk on the download click), so it can't be auto-deleted; without cleanup /tmp
# would grow one file per run on a long-lived Space. We unlink the PRIOR path
# when writing a new one — the file for the run that just finished is always
# intact. This is process-wide state: on the rare concurrent-session path a
# second run can unlink a file the first user hasn't downloaded yet, which is
# acceptable for a no-persistence prototype.
_last_report_path: str | None = None


def _write_report_md(body: str) -> str:
    """Materialize the already-rendered report `body` to a temp .md file.

    Takes the body the streaming loop already rendered rather than re-rendering
    from the `Report`, so a completed run renders its markdown exactly once.
    `delete=False` because Gradio's DownloadButton streams the file from disk
    after this returns. May raise OSError (disk full, read-only temp dir); the
    caller degrades to no-download rather than letting it break completion.
    """
    global _last_report_path
    previous = _last_report_path
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", prefix="gander-report-", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(body)
        path = handle.name
    _last_report_path = path
    if previous is not None:
        # Best-effort reap of the prior run's temp file — already gone / a
        # read-only temp dir is not worth failing the new download over.
        with contextlib.suppress(OSError):
            os.unlink(previous)
    return path


_HERO_CSS = """<style>
#gander-app { max-width: 72ch; margin-inline: auto; }
.gander-hero {
  margin: 1rem 0 2.5rem; font-family: system-ui, sans-serif;
  display: flex; flex-wrap: wrap; align-items: center; gap: 1.25rem;
}
.gander-hero .mascot { width: 64px; height: 64px; flex-shrink: 0; color: #344054; }
.gander-hero .text { display: flex; flex-direction: column; gap: 0.4rem; }
.gander-hero h1 {
  margin: 0; font-size: 2.125rem; line-height: 1.2;
  font-weight: 600; letter-spacing: -0.01em;
}
.gander-hero p  { margin: 0; color: #475467; font-size: 1.0625rem; line-height: 1.5; }
.gander-caption { color: #667085; font-size: 0.85rem; margin: 0.75rem 0 1.25rem; }
.gradio-container button.primary { margin-top: 0.5rem !important; }
button.primary, .gradio-container button.primary {
  background: #92400e !important; border-color: #92400e !important; color: #ffffff !important;
}
button.primary:hover, .gradio-container button.primary:hover {
  background: #7c2d12 !important; border-color: #7c2d12 !important;
}
button.primary:focus-visible { outline: 2px solid #1d4ed8; outline-offset: 2px; }
button.primary:disabled,
.gradio-container button.primary:disabled {
  /* Light disabled state: #7c2d12 on #fed7aa ~6.5:1 (was #fff on #fdba74 = 1.69:1,
     WCAG 1.4.3 fail). opacity stays 1 so the rendered ratio matches the raw pair —
     blending against the page would erode it. The lighter peach + not-allowed
     cursor still reads as disabled. */
  background: #fed7aa !important; border-color: #fed7aa !important;
  color: #7c2d12 !important; cursor: not-allowed; opacity: 1;
}
@keyframes ganderPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }
.pill.running { animation: ganderPulse 1.2s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) { .pill.running { animation: none; } }
@media (prefers-color-scheme: dark) {
  .gander-hero h1 { color: #f4f4f5; }
  .gander-hero p { color: #d4d4d8; }
  .gander-hero .mascot { color: #d4d4d8; }
  .gander-caption { color: #a1a1aa; }
  button.primary:disabled,
  .gradio-container button.primary:disabled {
    background: #7c2d12 !important; border-color: #7c2d12 !important;
    color: #fed7aa !important; opacity: 0.7;
  }
}
body.dark .gander-hero h1 { color: #f4f4f5; }
body.dark .gander-hero p { color: #d4d4d8; }
body.dark .gander-hero .mascot { color: #d4d4d8; }
body.dark .gander-caption { color: #a1a1aa; }
body.dark button.primary:disabled,
body.dark .gradio-container button.primary:disabled {
  background: #7c2d12 !important; border-color: #7c2d12 !important;
  color: #fed7aa !important; opacity: 0.7;
}
</style>"""

_HERO_HTML = """
<div class="gander-hero">
  <svg class="mascot" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none"
       stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"
       role="img" aria-label="Gander logo: a goose with a monocle">
    <title>Gander</title>
    <circle cx="34" cy="22" r="11"/>
    <path d="M45 19 L 58 22 L 45 26"/>
    <path d="M28 32 C 22 38, 30 46, 22 52 C 18 55, 14 56, 11 57"/>
    <circle cx="34" cy="22" r="1.4" fill="currentColor" stroke="none"/>
    <path d="M43 30 Q 45 35 41 38" stroke-dasharray="1.5 2"/>
  </svg>
  <div class="text">
    <h1>Gander</h1>
    <p>Take a closer look at any CV.</p>
  </div>
</div>
"""


# Fail fast at MODULE scope, not in __main__: the README front-matter is
# `sdk: gradio` / `app_file: app.py`, so the HF Spaces runtime IMPORTS this
# module and serves the module-level `demo` itself — `python app.py` (and so
# `__main__`) never runs on the real deploy path. A missing OPENROUTER_API_KEY
# must surface here, before the UI is built, instead of as a confusing 401 on
# the first request. `GANDER_SKIP_ENV_CHECK=1` lets keyless tooling import the
# module (e.g. `python -c "import app"` smoke checks); unit tests never import
# `app`, and constructing LLMClient stays cheap and key-free.
if os.environ.get("GANDER_SKIP_ENV_CHECK") != "1":
    check_env()


with gr.Blocks(title="Gander · CV analysis") as demo:
    with gr.Column(elem_id="gander-app"):
        gr.HTML(_HERO_CSS + _HERO_HTML)
        file_in = gr.File(file_types=[".pdf", ".docx"], label="Your CV", type="filepath")
        gr.HTML(
            '<p class="gander-caption">PDF or DOCX, max 10 MB. PDFs are uploaded '
            "to OpenRouter/Gemini as page images for transcription; DOCX is read "
            "locally. Salary data is fetched via DuckDuckGo search. "
            "Uploads are not retained by Gander.</p>"
        )
        with gr.Row():
            run_btn = gr.Button("Analyze CV", variant="primary", interactive=False)
            cancel_btn = gr.Button("Cancel", variant="secondary", visible=False)
        tracker_html = gr.HTML(value="", visible=False, elem_classes=["gander-output"])
        report_md = gr.Markdown(value="", visible=False, elem_classes=["gander-output"])
        download_btn = gr.DownloadButton(
            "Download report (.md)", visible=False, elem_classes=["gander-output"]
        )

    def _on_file_change(
        file_path: str | None,
    ) -> tuple[Any, Any, Any, Any, Any]:
        # Toggle the run button and clear any prior run's output so a stale
        # report can't sit under a freshly chosen file. Also hide a dangling
        # Cancel button if the user picks a new file mid-run.
        return (
            gr.Button(interactive=file_path is not None),
            gr.update(value="", visible=False),
            gr.update(value="", visible=False),
            gr.update(value=None, visible=False),
            gr.update(visible=False),
        )

    # NOTE: the `file_in.change(...)` wiring is registered *after* `run_event`
    # below so it can pass `cancels=[run_event]` — choosing a new file mid-run
    # must abort the in-flight pipeline (A2 then propagates the cancel into its
    # child tasks), not just clear the UI while the old run keeps streaming the
    # previous CV's report into the download button.

    # Yield order matches the run_btn.click outputs list below:
    # (tracker_html, report_md, download_btn, cancel_btn).
    _DOWNLOAD_IDLE = gr.update(visible=False)
    _CANCEL_SHOWN = gr.update(visible=True)
    _CANCEL_HIDDEN = gr.update(visible=False)

    async def handle(
        file_path: str | None,
    ) -> AsyncIterator[tuple[Any, Any, Any, Any]]:
        if file_path is None:
            failed = _read_error_report("Select a CV first.")
            yield (
                gr.update(visible=True, value=render_tracker(failed)),
                gr.update(visible=True, value=render_body(failed)),
                _DOWNLOAD_IDLE,
                _CANCEL_HIDDEN,
            )
            return
        try:
            file_bytes = await asyncio.to_thread(Path(file_path).read_bytes)
        except OSError:
            failed = _read_error_report(
                "Unable to read this file. Please upload a valid PDF or DOCX."
            )
            yield (
                gr.update(visible=True, value=render_tracker(failed)),
                gr.update(visible=True, value=render_body(failed)),
                _DOWNLOAD_IDLE,
                _CANCEL_HIDDEN,
            )
            return
        filename = Path(file_path).name

        # Acknowledge the click before pipeline_run yields its first state — cold-start
        # silence reads as breakage (PRD §8). Show Cancel for the duration of the run.
        reading_report = _initial_report()
        reading_report.statuses["profile"] = "running"
        reading_copy = (
            "*Transcribing PDF…*" if filename.lower().endswith(".pdf") else "*Reading DOCX…*"
        )
        yield (
            gr.update(visible=True, value=render_tracker(reading_report)),
            gr.update(visible=True, value=reading_copy),
            _DOWNLOAD_IDLE,
            _CANCEL_SHOWN,
        )

        last_report: Report | None = None
        async for report in pipeline_run(file_bytes, filename):
            last_report = report
            # render_body short-circuits to a failure callout when profile is still a
            # StageFailure placeholder; hold neutral copy until profile is a real Profile.
            if isinstance(report.profile, Profile):
                body = render_body(report)
            elif report.statuses["profile"] == "running" and not report.redacted_cv_text:
                body = reading_copy
            elif report.statuses["profile"] == "running":
                body = "*Extracting profile…*"
            else:
                body = "*Generating report…*"
            yield (
                gr.update(visible=True, value=render_tracker(report)),
                gr.update(visible=True, value=body),
                _DOWNLOAD_IDLE,
                _CANCEL_SHOWN,
            )

        # Offer the download only for a report that actually rendered a body
        # (profile resolved to a real Profile, not a top-level failure callout).
        # `body` here is the final loop iteration's render — when last_report's
        # profile is a real Profile, that branch took `body = render_body(report)`,
        # so it equals the finished report's markdown (no re-render needed).
        # Tracker and body keep their last values; only reveal the download and
        # hide Cancel now that the run is done.
        if last_report is not None and isinstance(last_report.profile, Profile):
            try:
                download = gr.update(visible=True, value=_write_report_md(body))
            except OSError:
                # A disk failure writing the artifact must not break graceful
                # completion — degrade to no-download, report stays on screen.
                download = _DOWNLOAD_IDLE
        else:
            download = _DOWNLOAD_IDLE
        yield (gr.update(), gr.update(), download, _CANCEL_HIDDEN)

    run_event = run_btn.click(
        handle,
        inputs=[file_in],
        outputs=[tracker_html, report_md, download_btn, cancel_btn],
        show_progress="hidden",
    )

    def _on_cancel() -> tuple[Any, Any, Any, Any, Any]:
        # `cancels=[run_event]` kills the generator before its final yield, so
        # the tracker/report freeze mid-run with the Cancel button dangling and
        # no "cancelled" signal. Settle the UI explicitly: clear the stale
        # tracker, replace the partial body with a clear cancelled message, hide
        # the (never-populated) download and Cancel buttons, and re-enable Run.
        # Outputs order: tracker_html, report_md, download_btn, cancel_btn, run_btn.
        return (
            gr.update(value="", visible=False),
            gr.update(value="_Run cancelled. The partial output was discarded._", visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.Button(interactive=True),
        )

    cancel_btn.click(
        _on_cancel,
        inputs=None,
        outputs=[tracker_html, report_md, download_btn, cancel_btn, run_btn],
        cancels=[run_event],
    )

    # Registered last so it can cancel `run_event`: a new upload mid-run aborts
    # the in-flight pipeline before clearing the UI, otherwise the old generator
    # keeps streaming and would repopulate the download with the prior CV's
    # report. Mirrors how `cancel_btn.click` cancels the same event above.
    file_in.change(
        _on_file_change,
        inputs=[file_in],
        outputs=[run_btn, tracker_html, report_md, download_btn, cancel_btn],
        show_progress="hidden",
        cancels=[run_event],
    )


if __name__ == "__main__":
    # check_env() already ran at module scope above (the import path HF uses).
    # Free HF Space: 2 concurrent pipeline runs, 4 queued — caps LLM-budget
    # blast radius from simultaneous users rather than CPU.
    demo.queue(max_size=4, default_concurrency_limit=2).launch(max_file_size="10mb")
