"""L7 Gradio UI — file upload, stage tracker, streaming markdown report.

The UI is a pure function of `Report` state: every yield from `pipeline.run`
re-renders both the tracker HTML and the body markdown. No UI-side state.

`_initial_report()` placeholder blocks are never rendered. `render_tracker`
only reads `.statuses`, and the `gr.Markdown` body is initialised with a
static "Upload a CV…" string — never with `render_body(_initial_report())`.
Calling `render_body` on this report would short-circuit to a `StageFailure`
callout because `report.profile` is a failure (see `report.py` line 290).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import gradio as gr

from jobfit.errors import StageFailure
from jobfit.pipeline import run as pipeline_run
from jobfit.report import render_body, render_tracker
from jobfit.schemas import Profile, Report


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


with gr.Blocks(title="Job Fit & Salary Estimator") as demo:
    gr.Markdown(
        "# Job Fit & Salary Estimator\n"
        "*Upload a CV — PDF or DOCX, max 10 MB. Not retained after processing.*"
    )
    file_in = gr.File(file_types=[".pdf", ".docx"], label="CV", type="filepath")
    run_btn = gr.Button("Generate report", variant="primary")
    tracker_html = gr.HTML(value=render_tracker(_initial_report()))
    report_md = gr.Markdown(value="*Upload a CV and click Generate report.*")

    async def handle(file_path: str | None) -> AsyncIterator[tuple[str, str]]:
        if file_path is None:
            yield (
                render_tracker(_initial_report()),
                "*No file selected. Upload a PDF or DOCX (max 10 MB) and click Generate report.*",
            )
            return
        try:
            file_bytes = await asyncio.to_thread(Path(file_path).read_bytes)
        except OSError:
            yield (
                render_tracker(_initial_report()),
                "*Could not read uploaded file. Please try again.*",
            )
            return
        filename = Path(file_path).name

        # Acknowledge the click before pipeline_run yields its first state — cold-start
        # silence reads as breakage (PRD §8).
        reading_report = _initial_report()
        reading_report.statuses["profile"] = "running"
        yield render_tracker(reading_report), "*Reading file…*"

        async for report in pipeline_run(file_bytes, filename):
            # render_body short-circuits to a failure callout when profile is still a
            # StageFailure placeholder; hold neutral copy until profile is a real Profile.
            body = (
                render_body(report)
                if isinstance(report.profile, Profile)
                else "*Generating report — stages running…*"
            )
            yield render_tracker(report), body

    run_btn.click(handle, inputs=[file_in], outputs=[tracker_html, report_md])


if __name__ == "__main__":
    demo.queue().launch(max_file_size="10mb")
