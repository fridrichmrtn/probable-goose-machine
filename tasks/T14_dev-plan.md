# T14 — L6 report renderer — dev plan

Status: planned
Owner: ux-engineer
Branch: feat/block-c-corpus-render
Worktree: /home/mf/GitHub/probable-goose-machine/.worktrees/block-c

## Intended outcome

`src/jobfit/report.py` exports two pure functions, `render_tracker(report) -> str` and
`render_body(report) -> str`, that consume `jobfit.schemas.Report` and emit
deterministic, escaped HTML / markdown strings. No I/O, no globals, no logging, no
new dependencies. `tests/test_render.py` covers the four UI states (empty/loading
is not in scope; we handle done/failed/skipped/short-circuit) plus HTML-escape
behaviour for user-controlled fields.

## Spec drift resolution (contract first)

The T14 spec references status keys (`ingest`, `redact`) and pill labels
(`Parse · Redact · Score · Salary · Plan`) that do not exist in the canonical
`schemas.StageName` literal `("profile", "score", "salary", "confidence",
"growth")`. The schema's `_require_exact_status_keys` validator rejects unknown
keys. **Schema wins.**

Status-key mapping (display label → schema key):

| Display label | Schema key   | Rationale                                                  |
| ------------- | ------------ | ---------------------------------------------------------- |
| Profile       | `profile`    | L2 stage; closest analogue to "Parse + Redact" combined.   |
| Score         | `score`      | Direct.                                                    |
| Salary        | `salary`     | Direct.                                                    |
| Confidence    | `confidence` | Replaces nothing the spec named, but it is a real stage.    |
| Plan          | `growth`     | "Plan" reads better in tracker; growth is the schema name. |

The renderer carries one `_LABEL_BY_STAGE` mapping at module top with a
one-line comment documenting this choice for future readers. Underlying
`report.statuses` lookup uses schema keys; only the pill text is the label.

Top-level short-circuit: the schema has no `ingest`/`redact` stages, so the
closest analogue is `isinstance(report.profile, StageFailure)` — profile is the
first L2 gate after ingest+redact, and if it failed, the rest of the body is
meaningless. When `report.profile` is a `StageFailure`, `render_body` returns
**only** the failure callout. Per-stage StageFailures elsewhere render inline
as a `> ⚠ <user_message>` blockquote but the rest of the report continues.

## Failure-handling decision tree

```
render_body(report):
  if isinstance(report.profile, StageFailure):
      return failure_callout(report.profile)          # short-circuit
  body = [score_section(report.score),
          salary_section(report.salary),
          confidence_section(report.confidence),
          growth_section(report.growth),
          footer_section()]
  return "\n\n".join(body)

score_section(score):
  if isinstance(score, StageFailure): return failure_callout(score)
  # else render table + <details> blocks

salary_section(salary):    # same pattern
confidence_section(c):     # same pattern
growth_section(growth):    # same pattern
```

Per-stage failures are visually distinct (warning blockquote) and use
`StageFailure.user_message` directly (PRD §4.6 copy is the owner's
responsibility upstream).

## Cost/latency footer

The schema does not yet carry totals (per t01-schemas backlog "Should-fix"; T15
will add `total_cost_usd` / `total_duration_ms`). The footer renders
`COMPONENT_WEIGHTS` from `schemas.py` plus a literal placeholder line
`(cost / latency totals — populated by T15)`. Do not invent fields.

## File layout — `src/jobfit/report.py`

Sections in order:

1. Module docstring + imports (stdlib `html`, `jobfit.schemas` types, `StageFailure`).
2. `_LABEL_BY_STAGE` mapping with the spec-drift note (comment).
3. `_CSS` constant (single `<style>` block, ~30 lines, includes
   `@media (prefers-reduced-motion: reduce) { ... transition: none; }`).
4. Helpers: `_esc`, `_pill_html`, `_failure_callout_md`, `_failure_callout_html`,
   `_format_money`, `_confidence_badge`, `_score_table`, `_score_details`,
   `_salary_section`, `_confidence_section`, `_growth_section`, `_footer`.
5. Public `render_tracker(report) -> str` — returns `<style>...</style><div
   class="tracker">…pills…</div>`.
6. Public `render_body(report) -> str` — orchestrates per-section helpers with
   the short-circuit at the top.

Pure functions only. No printing, no logging, no file I/O.

## Style / accessibility

- Pills are `<span class="pill {status}" title="…">Label</span>`. Status
  class is one of `pending | running | done | failed | skipped` (matches
  `StageStatus` Literal). The container is `<div class="tracker"
  role="status" aria-live="polite">` so screen readers announce stage transitions.
- CSS distinguishes the 5 statuses by border, background, AND a glyph (∘ ⋯ ✓ ✗ —)
  so colour is never the sole carrier of meaning (WCAG SC 1.4.1).
- `prefers-reduced-motion` query disables any transition on the pill state change.
- Score block uses an HTML `<table>` (so `<details>` after the table is clean).
  First `<details open>` so reviewer sees one verified quote on first paint.
- Salary block: markdown with `f"{n:,}"`; confidence badge with bracketed
  glyph (`[!] High`, `[~] Medium`, `[?] Low`) per spec.
- Sources rendered as `[domain] — "snippet excerpt"`, NOT bare URLs.
- Growth: numbered markdown list, literal asterisks `**What** — *N months* —
  Mechanism`.
- HTML-escape `justification`, `anchor.quote`, `Source.snippet`, every
  `StageFailure.user_message`, and any string interpolated into an HTML
  attribute or body. `html.escape(text, quote=True)` from stdlib.

## Fixture construction strategy (tests)

Build a fully-valid `Report` via direct schema instantiation. Re-use the shape
from `tests/test_schemas.py` (`_profile`, `_score`, `_salary`, `_confidence`,
`_growth`, `_statuses`). Local helpers live in the test module — no shared
conftest needed for a single test file.

Tests (all `@pytest.mark.fast`):

1. `test_render_tracker_emits_five_pills_with_status_classes` — parameterise
   across all 5 `StageStatus` values; assert each pill `<span>` exists and
   carries the right class.
2. `test_render_tracker_includes_prefers_reduced_motion` — assert the literal
   `prefers-reduced-motion` substring appears in the output.
3. `test_render_tracker_failed_pill_includes_tooltip_with_user_message`
   — parameterise; assert escaped `title="…"` attribute carries the failure
   message and that raw HTML in the message is escaped (insurance against
   tag injection).
4. `test_render_body_populated_contains_score_salary_components_and_source` —
   assert "CZK", the int score number, all four component names, the first
   source's domain, and `<details open>` appear once.
5. `test_render_body_with_salary_failure_keeps_score_and_shows_callout` — assert
   the score block still renders and the salary section shows the callout.
6. `test_render_body_with_profile_failure_short_circuits` — assert ONLY the
   callout is returned; "CZK", any component name, and any growth content
   are absent.
7. `test_render_body_escapes_html_in_user_content` — fixture sets
   `Component.justification` or `Anchor.quote` to a string containing
   `<script>alert(1)</script>` and asserts the raw `<script>` does NOT appear
   in output.

## Verification

- `uv run pytest -m fast tests/test_render.py -v`
- `uv run pytest -m fast -q`  (regression sweep across full fast suite)
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src/`
- `uv run pre-commit run --all-files`

## Out of scope

- T15 cost/latency aggregate fields (only a placeholder footer line).
- T16 Gradio wiring; this module is rendering-only.
- Mobile, RTL, OCR (PRD §6).

## Backlog follow-up

Append a `## t14-heal — 2026-05-10` block to `tasks/backlog.md` capturing the
spec drift documented above (status keys `ingest`/`redact` and the
`Parse·Redact·Score·Salary·Plan` labels). Owner: T14 spec author.
