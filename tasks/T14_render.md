# T14 — L6 report renderer

Status: done
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

Shipped `src/jobfit/report.py` with two pure renderers — `render_tracker` (returns a `<style>` block + 5 `<span class="pill {status}">` pills with glyph + `aria-label`, `prefers-reduced-motion` media query, and `title=` tooltips on failed pills) and `render_body` (markdown body with HTML `<details>` blocks, first component `<details open>`, salary block formatted `low,000 – high,000 CCY / period`, bracketed-glyph confidence badges, numbered growth list, `> ⚠ <msg>` callouts inline for per-stage failures, and a `<details>` footer listing `COMPONENT_WEIGHTS` with a `(cost / latency totals — populated by T15)` placeholder). All user-controlled strings are escaped via `html.escape(quote=True)`. Resolved spec drift against `schemas.StageName`: tracker maps schema keys (`profile / score / salary / confidence / growth`) to display labels (`Profile / Score / Salary / Confidence / Plan`); `report.profile = StageFailure` triggers the top-level short-circuit (returns only the failure callout). Drift logged in `tasks/backlog.md` under `t14-heal`.

Tests: `tests/test_render.py` — 27 `@pytest.mark.fast` tests (parametrised across all 5 stage statuses and 3 confidence tiers) covering 5-pill emission, status-class matching, `prefers-reduced-motion` presence, tooltip surfacing + HTML escaping (including the failed-status-without-StageFailure fallback path), fully-populated body, inline failure callouts for `score`/`salary`/`confidence`/`growth`, profile-failure short-circuit, Czech-diacritic survival, footer weight assertions (35%/30%/20%/15%), empty-growth marker, and HTML-escape defence across `Component.justification`, `Anchor.quote`, `Source.snippet`, `Confidence.rationale`, `SalaryEstimate.reasoning`, and both `GrowthAction.what` / `mechanism`.

Verification: `uv run pytest -m fast tests/test_render.py -v` (27 pass), `uv run pytest -m fast -q` (67 pass, 1 deselected, no regressions), `uv run ruff check .` (clean), `uv run ruff format --check .` (clean), `uv run mypy src/` (clean), `uv run pre-commit run --all-files` (all hooks pass). Plan: `tasks/T14_dev-plan.md`. Heal pass on PR #1 reviews: `tasks/T14_dev-report.md` (heal section).

T15 follow-up (2026-05-12): the footer placeholder line `(cost / latency totals — populated by T15)` has been replaced with `_Total cost: $… · Total latency: … ms_` interpolating the new `Report.total_cost_usd` / `Report.total_latency_ms` fields. Section helpers also gained `if block is None: return ""` guards so the renderer can be called on intermediate streaming snapshots (the pipeline yields a partial Report after every state change). Three new tests in `tests/test_render.py` lock the footer string and the None=skip behaviour. No regressions in the original 27 tests.
