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
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import gradio as gr

from gander.errors import StageFailure
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
        raw_cv_text="",
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
        raw_cv_text="",
    )


_HERO_CSS = """<style>
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
  background: #fdba74 !important; border-color: #fdba74 !important;
  color: #ffffff !important; cursor: not-allowed; opacity: 0.85;
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


with gr.Blocks(title="Gander · CV analysis") as demo:
    gr.HTML(_HERO_CSS + _HERO_HTML)
    file_in = gr.File(file_types=[".pdf", ".docx"], label="Your CV", type="filepath")
    gr.HTML(
        '<p class="gander-caption">PDF or DOCX, max 10 MB. Text-based PDFs only — '
        "scanned/image PDFs aren't supported. Not retained after processing.</p>"
    )
    run_btn = gr.Button("Analyze CV", variant="primary", interactive=False)
    tracker_html = gr.HTML(value="", visible=False, elem_classes=["gander-output"])
    report_md = gr.Markdown(value="", visible=False, elem_classes=["gander-output"])

    file_in.change(
        lambda f: gr.Button(interactive=f is not None),
        inputs=[file_in],
        outputs=[run_btn],
        show_progress="hidden",
    )

    async def handle(
        file_path: str | None,
    ) -> AsyncIterator[tuple[dict[str, Any], dict[str, Any]]]:
        if file_path is None:
            failed = _read_error_report("Select a CV first.")
            yield (
                gr.update(visible=True, value=render_tracker(failed)),
                gr.update(visible=True, value=render_body(failed)),
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
            )
            return
        filename = Path(file_path).name

        # Acknowledge the click before pipeline_run yields its first state — cold-start
        # silence reads as breakage (PRD §8).
        reading_report = _initial_report()
        reading_report.statuses["profile"] = "running"
        yield (
            gr.update(visible=True, value=render_tracker(reading_report)),
            gr.update(visible=True, value="*Reading file…*"),
        )

        async for report in pipeline_run(file_bytes, filename):
            # render_body short-circuits to a failure callout when profile is still a
            # StageFailure placeholder; hold neutral copy until profile is a real Profile.
            body = (
                render_body(report)
                if isinstance(report.profile, Profile)
                else "*Generating report…*"
            )
            yield (
                gr.update(visible=True, value=render_tracker(report)),
                gr.update(visible=True, value=body),
            )

    run_btn.click(
        handle,
        inputs=[file_in],
        outputs=[tracker_html, report_md],
        show_progress="hidden",
    )


if __name__ == "__main__":
    demo.queue().launch(max_file_size="10mb")
