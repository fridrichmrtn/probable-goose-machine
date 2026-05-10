# T16 — L7 Gradio UI + stage tracker

Status: todo
Owner: ux-engineer
Depends on: T14 (T15 needed for live, but mockable)
Unblocks: T22
Estimate: ~2h

## Goal

The user-facing Gradio app: file upload, generate button, stage tracker pills, streaming markdown report. UI is a pure function of `Report` state — every yield from `pipeline.run` re-renders both outputs.

## Deliverables

- [ ] `app.py` (replace bootstrap stub):
  ```python
  import gradio as gr
  from jobfit.pipeline import run as pipeline_run
  from jobfit.report import render_tracker, render_body

  with gr.Blocks(title="Job Fit & Salary Estimator", theme=...) as demo:
      gr.Markdown("# Job Fit & Salary Estimator\n*Upload a CV — PDF or DOCX, max 10 MB. Processed in-memory; not stored.*")
      file_in = gr.File(file_types=[".pdf", ".docx"], label="CV")
      run_btn = gr.Button("Generate report", variant="primary")
      tracker_html = gr.HTML(value=render_tracker(_initial_report()))
      report_md = gr.Markdown(value="*Upload a CV and click Generate report.*")

      async def handle(file):
          if file is None:
              yield render_tracker(_initial_report()), "*Please upload a CV first.*"
              return
          file_bytes = open(file.name, "rb").read()
          async for report in pipeline_run(file_bytes, file.name):
              yield render_tracker(report), render_body(report)

      run_btn.click(handle, inputs=[file_in], outputs=[tracker_html, report_md])

  if __name__ == "__main__":
      demo.queue().launch()
  ```
- [ ] `_initial_report()` helper — returns a `Report` with all statuses = `pending` and empty/None blocks (lives in `src/jobfit/ui.py` or `pipeline.py`).
- [ ] CSS lives inside `render_tracker`'s `<style>` block (already from T14):
  - 5 horizontal pills, evenly spaced.
  - States: `pending` (grey), `running` (blue, subtle pulse), `done` (green with ✓), `failed` (red with ⚠).
  - `@media (prefers-reduced-motion: reduce)` disables all transitions/animations.
- [ ] File-upload constraint: `file_types=[".pdf", ".docx"]`, max size enforced via Gradio's queue config (`max_file_size="10mb"`).
- [ ] Manual smoke (no automated test for the UI itself — Gradio's queue+stream interaction is hard to unit-test cleanly; rely on `eval_corpus.py` for end-to-end):
  - `uv run python app.py`
  - Open localhost:7860, upload `tests/fixtures/cvs/03_ds_horak.pdf`, click Generate, watch pills transition through states, watch markdown appear progressively, confirm no traceback in terminal.

## Verification

```bash
uv run python app.py &
APP_PID=$!
sleep 5
curl -sf http://localhost:7860/ > /dev/null && echo "UI up"
kill $APP_PID
```

Manual: upload each fixture once, screenshot for the README.

## Reference

- tasks/PLAN.md — § "L7 — UI / Gradio"

## Outcome

(fill in when done — note any Gradio-version quirks)
