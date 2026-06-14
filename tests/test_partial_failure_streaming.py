"""T18 — streaming-state guarantees during a partial-failure run.

The L7 Gradio UI re-renders on every yield from `pipeline.run`. If any yield
produces a `Report` that the renderer cannot consume — or leaves a stage in
`running` after the iterator is exhausted — the UI shows a permanent spinner.
This file pins those guarantees against the corrupt-PDF path (the simplest
non-trivial failure: ingest fails immediately, cascading to every downstream
stage).

Companion to `tests/test_failures.py` which asserts the user-facing message
content; this file asserts the rendering and traceback contract.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from gander import pipeline
from gander.report import render_html
from gander.schemas import Report

# Random bytes with `.pdf` suffix → `extract_text` returns CORRUPT_MSG, the
# pipeline cascades, and we get a few yields (initial pending, profile
# running, profile failed + cascade). Every fixture here uses the same input.
_CORRUPT_BYTES = b"\x00\x01not a pdf\xff\xfe" * 16
_CORRUPT_NAME = "broken.pdf"


async def _collect(it: Any) -> list[Report]:
    return [r async for r in it]


@pytest.mark.fast
async def test_every_yield_is_renderable_without_exception() -> None:
    """Each intermediate `Report` must round-trip through `render_html`
    without raising. The initial yield (profile=None) renders to an empty
    string; once profile becomes a StageFailure, the renderer short-circuits
    to a single failure callout. Neither path may raise — a Gradio re-render
    loop swallowing a traceback would silently stall the UI."""
    reports = await _collect(pipeline.run(_CORRUPT_BYTES, _CORRUPT_NAME))
    assert len(reports) >= 2, "pipeline must yield at least an initial + final report"
    for i, r in enumerate(reports):
        try:
            out = render_html(r)
        except Exception as exc:
            pytest.fail(f"render_html raised on yield #{i}: {type(exc).__name__}: {exc}")
        assert isinstance(out, str)


@pytest.mark.fast
async def test_final_report_has_no_running_statuses() -> None:
    """When the iterator exhausts, every stage must have settled.

    `running` is the transient state used during a yield to drive the UI's
    spinner — leaking it past the final yield would lock the spinner. The
    contract: every status is `pending`, `done`, or `failed`.
    """
    reports = await _collect(pipeline.run(_CORRUPT_BYTES, _CORRUPT_NAME))
    final = reports[-1]
    for stage, status in final.statuses.items():
        assert status != "running", f"final yield left {stage}={status!r}"
        assert status in {"pending", "done", "failed"}, f"unexpected status {stage}={status!r}"


@pytest.mark.fast
async def test_no_traceback_on_stderr_during_corrupt_run(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Even when ingest fails on truly corrupt input, the pipeline must not
    let a Python traceback escape to stderr.

    `stage_boundary` already converts exceptions to `StageFailure` and routes
    diagnostics through `obs.emit` (structured JSON to stdout). A traceback
    on stderr would mean an exception escaped a stage boundary — usually
    fatal for the Gradio worker.
    """
    sys.stderr.flush()
    reports = await _collect(pipeline.run(_CORRUPT_BYTES, _CORRUPT_NAME))
    sys.stderr.flush()
    captured = capfd.readouterr()

    assert "Traceback (most recent call last)" not in captured.err, (
        f"unexpected traceback on stderr:\n{captured.err}"
    )
    # Sanity: we still ran the pipeline and produced a terminal report.
    assert len(reports) >= 2
