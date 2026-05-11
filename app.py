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
from jobfit.report import render_body, render_tracker
from jobfit.schemas import (
    Anchor,
    Component,
    Confidence,
    GrowthAction,
    Profile,
    ProfileItem,
    Report,
    SalaryEstimate,
    Score,
    Source,
)


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


# Throwaway: replaced by jobfit.pipeline.run once T15 lands.
async def _stub_pipeline_run(file_bytes: bytes, filename: str) -> AsyncIterator[Report]:
    def _pending(stage: str) -> StageFailure:
        return StageFailure(stage=stage, user_message="pending")

    def _profile_item() -> ProfileItem:
        return ProfileItem(text="python", anchor=Anchor(quote="Python"))

    def _profile() -> Profile:
        item = _profile_item()
        return Profile(
            skills=[item],
            experience=[item],
            education=[item],
            soft_signals=[item],
            detected_role="engineer",
            detected_location=None,
            detected_years_experience=5,
        )

    def _score() -> Score:
        return Score(
            components=[
                Component(
                    name="skills",
                    score_0_100=80,
                    justification="ok",
                    anchor=Anchor(quote="quote for skills", section="Work Experience"),
                ),
                Component(
                    name="experience",
                    score_0_100=60,
                    justification="ok",
                    anchor=Anchor(quote="quote for experience", section="Work Experience"),
                ),
                Component(
                    name="education",
                    score_0_100=40,
                    justification="ok",
                    anchor=Anchor(quote="quote for education", section="Work Experience"),
                ),
                Component(
                    name="soft_signals",
                    score_0_100=70,
                    justification="ok",
                    anchor=Anchor(quote="quote for soft_signals", section="Work Experience"),
                ),
            ]
        )

    def _salary() -> SalaryEstimate:
        return SalaryEstimate(
            low=80_000,
            high=120_000,
            currency="CZK",
            period="month",
            sources=[
                Source(
                    url="https://platy.cz/path",  # type: ignore[arg-type]
                    snippet="median CZK 95k",
                    domain="platy.cz",
                )
            ],
            reasoning="stub market data",
        )

    def _confidence() -> Confidence:
        return Confidence(tier="Medium", rationale="stubbed")

    def _growth() -> list[GrowthAction]:
        return [
            GrowthAction(
                what="learn rust",
                time_horizon_months=6,
                mechanism="ship a small CLI",
                anchor=Anchor(quote="C++ background"),
            ),
            GrowthAction(
                what="lead a project",
                time_horizon_months=12,
                mechanism="volunteer for cross-team work",
                anchor=Anchor(quote="senior engineer"),
            ),
        ]

    step_delay = 0.4

    yield Report(
        profile=_pending("profile"),
        score=_pending("score"),
        salary=_pending("salary"),
        confidence=_pending("confidence"),
        growth=_pending("growth"),
        statuses={
            "profile": "running",
            "score": "pending",
            "salary": "pending",
            "confidence": "pending",
            "growth": "pending",
        },
        raw_cv_text="",
    )
    await asyncio.sleep(step_delay)

    yield Report(
        profile=_profile(),
        score=_pending("score"),
        salary=_pending("salary"),
        confidence=_pending("confidence"),
        growth=_pending("growth"),
        statuses={
            "profile": "done",
            "score": "running",
            "salary": "pending",
            "confidence": "pending",
            "growth": "pending",
        },
        raw_cv_text="",
    )
    await asyncio.sleep(step_delay)

    yield Report(
        profile=_profile(),
        score=_score(),
        salary=_pending("salary"),
        confidence=_pending("confidence"),
        growth=_pending("growth"),
        statuses={
            "profile": "done",
            "score": "done",
            "salary": "running",
            "confidence": "pending",
            "growth": "pending",
        },
        raw_cv_text="",
    )
    await asyncio.sleep(step_delay)

    yield Report(
        profile=_profile(),
        score=_score(),
        salary=_salary(),
        confidence=_pending("confidence"),
        growth=_pending("growth"),
        statuses={
            "profile": "done",
            "score": "done",
            "salary": "done",
            "confidence": "running",
            "growth": "pending",
        },
        raw_cv_text="",
    )
    await asyncio.sleep(step_delay)

    yield Report(
        profile=_profile(),
        score=_score(),
        salary=_salary(),
        confidence=_confidence(),
        growth=_pending("growth"),
        statuses={
            "profile": "done",
            "score": "done",
            "salary": "done",
            "confidence": "done",
            "growth": "running",
        },
        raw_cv_text="",
    )
    await asyncio.sleep(step_delay)

    yield Report(
        profile=_profile(),
        score=_score(),
        salary=_salary(),
        confidence=_confidence(),
        growth=_growth(),
        statuses={
            "profile": "done",
            "score": "done",
            "salary": "done",
            "confidence": "done",
            "growth": "done",
        },
        raw_cv_text="stub CV text",
    )


try:
    from jobfit.pipeline import run as pipeline_run  # type: ignore[import-not-found]  # T15
except ImportError:
    pipeline_run = _stub_pipeline_run


with gr.Blocks(title="Job Fit & Salary Estimator") as demo:
    gr.Markdown(
        "# Job Fit & Salary Estimator\n"
        "*Upload a CV — PDF or DOCX, max 10 MB. Processed in-memory; not stored.*"
    )
    file_in = gr.File(file_types=[".pdf", ".docx"], label="CV", type="filepath")
    run_btn = gr.Button("Generate report", variant="primary")
    tracker_html = gr.HTML(value=render_tracker(_initial_report()))
    report_md = gr.Markdown(value="*Upload a CV and click Generate report.*")

    async def handle(file_path: str | None) -> AsyncIterator[tuple[str, str]]:
        if file_path is None:
            yield render_tracker(_initial_report()), "*Please upload a CV first.*"
            return
        with open(file_path, "rb") as fh:
            file_bytes = fh.read()
        filename = Path(file_path).name
        async for report in pipeline_run(file_bytes, filename):
            yield render_tracker(report), render_body(report)

    run_btn.click(handle, inputs=[file_in], outputs=[tracker_html, report_md])


if __name__ == "__main__":
    demo.queue().launch(max_file_size="10mb")
