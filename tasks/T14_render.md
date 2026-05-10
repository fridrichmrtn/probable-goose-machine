# T14 — L6 report renderer

Status: todo
Owner: ux-engineer
Depends on: T01
Unblocks: T16
Estimate: ~45 min

Can run in parallel with stage worker tasks — only needs schemas.

## Goal

Pure functions that render a `Report` to (a) the stage-tracker HTML and (b) the report-body markdown. UI is a pure function of state — every yield in the pipeline re-renders both from the same `Report`.

## Deliverables

- [ ] `src/jobfit/report.py`:
  - `def render_tracker(report: Report) -> str` — HTML for the stage-tracker pills:
    - 5 pills: `Parse · Redact · Score · Salary · Plan`.
    - Each pill carries class `pending | running | done | failed` from `report.statuses[stage]`.
    - All CSS lives in this file (one `<style>` block, ~30 lines). `prefers-reduced-motion` query disables transitions.
    - Failed pills show the user-facing message in a tooltip.
  - `def render_body(report: Report) -> str` — Markdown for the main body:
    - **Score block**: top-line number; component table (`| Skills | Experience | Education | Soft |`); each component's justification + anchor quote in a `<details>` element. First component `<details open>` so the reviewer sees one verified quote immediately.
    - **Salary block**: `123,000 – 165,000 CZK / month` formatted with thousands separator; confidence badge `[!] High` / `[~] Medium` / `[?] Low` + rationale; sources rendered as `[domain.com] — "snippet excerpt"` (NOT bare URLs).
    - **Growth plan**: numbered list, `**What** — *N months* — Mechanism`.
    - **Failure blocks**: rendered inline as a callout (`> ⚠ <user_message>`), the rest of the report continues.
    - **Top-level failures**: if `report.statuses["ingest"] == "failed"` or `["redact"] == "failed"`, return only the failure callout (no other content).
    - **Footer**: collapsible "How is this scored?" panel showing `COMPONENT_WEIGHTS` from `schemas.py` and the cost+latency totals from `report` (added in T15).
- [ ] `tests/test_render.py` (`@pytest.mark.fast`):
  - `render_tracker` produces 5 `<span class="pill">` elements; pill classes match the input statuses.
  - `render_body` with a fully-populated Report contains "CZK", the score number, all four component names, and the first source's domain.
  - `render_body` with a `StageFailure` in the salary block keeps the score block and shows the failure callout.
  - `render_body` with a top-level ingest failure shows ONLY the failure message.

## Verification

```bash
uv run pytest -m fast tests/test_render.py -v
```

## Reference

- tasks/PLAN.md — § "L7 — UI / Gradio (renderers)"

## Outcome

(fill in when done)
