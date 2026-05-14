# T14 dev-report — report renderer (tracker + body)

Branch: `feat/block-c-corpus-render`
Status: done

## Scope shipped

- `src/gander/report.py` (new module, ~240 lines incl. CSS): two pure functions, `render_tracker(report) -> str` and `render_body(report) -> str`. No I/O, no globals, no logging.
- `tests/test_render.py` (new, 27 `@pytest.mark.fast` tests): covers tracker pills, body sections, failure branches, escape boundaries, Czech diacritic survival.
- Single `<style>` block at the top of `render_tracker` output. CSS classes namespaced (`.tracker`, `.pill`, `.gander-callout`, `.gander-components`). `@media (prefers-reduced-motion: reduce)` disables transitions.
- HTML escape via `html.escape(text, quote=True)` applied to every user-controllable string: `Component.justification`, `Anchor.quote`, `Source.snippet`, `Confidence.rationale`, `SalaryEstimate.reasoning`, `GrowthAction.what`, `GrowthAction.mechanism`, `StageFailure.user_message`, tracker `title` tooltip.

## Spec drift resolved (schema wins)

Two drifts between `tasks/T14_render.md` and `src/gander/schemas.py`:

1. **Status keys.** T14 spec listed tracker pills `Parse · Redact · Score · Salary · Plan` and a top-level failure check on `report.statuses["ingest"]` / `["redact"]`. Schema's `StageName = Literal["profile", "score", "salary", "confidence", "growth"]` and `Report._require_exact_status_keys` rejects unknown keys. Resolution: map the 5 pills to the actual schema stages with display labels:

   | Display label | Schema key   |
   | ------------- | ------------ |
   | Profile       | `profile`    |
   | Score         | `score`      |
   | Salary        | `salary`     |
   | Confidence    | `confidence` |
   | Plan          | `growth`     |

   Top-level short-circuit: `isinstance(report.profile, StageFailure)` (profile is the first L2 stage downstream of ingest+redact, so a `profile` StageFailure faithfully represents "ingestion or redaction failed").

2. **Cost / latency footer.** Spec referenced "cost+latency totals from `report` (added in T15)". Those fields are not yet on the schema. Renderer emits placeholder `_(cost / latency totals — populated by T15)_` rather than inventing fields.

Both drifts documented in `tasks/backlog.md` under `## t14-heal — 2026-05-10`.

## Review verdicts (4 agents + codex)

- product-owner: **strong**
- hiring-manager: **strong**
- ai-ml-engineer: **on-bar**
- qa-engineer: **on-bar**
- codex (gpt-5.5, xhigh): **on-bar**

Zero `[must-fix]` findings. Should-fixes consolidated into a single heal pass.

## Heal-pass items (folded into the single T14 commit)

- **H1** — Tracker pill fallback tooltip when `statuses[stage] == "failed"` but the block is not a `StageFailure` (codex schema-consistency).
- **H2** — Three new inline-failure tests covering `score` / `confidence` / `growth` StageFailure branches (qa).
- **H3** — Confidence badge parametrized across `High` / `Medium` / `Low` tiers (qa + ai-ml).
- **H4** — Footer asserts `35%` / `30%` / `20%` / `15%` weight percentages (qa + product-owner).
- **H5** — Empty growth list renders `_(no actions)_` marker (qa).
- **H6** — Czech diacritic survival test (qa). Justification + anchor populated with `áčďéěíňóřšťúůýž`.
- **H7** — Escape-boundary tests extended to `Confidence.rationale`, `SalaryEstimate.reasoning`, `GrowthAction.what` / `mechanism` (qa + ai-ml).
- **H8** — Tracker test for inconsistent-state `failed` pill (H1 coverage).
- **H9** — `typing.cast(StageName, ...)` replaces `# type: ignore[index]` in test fixture (hiring-manager nit).

## Verification

```text
uv run pytest -m fast tests/test_render.py -v     → 27 passed
uv run pytest -m fast -q                           → 67 passed, 1 deselected
uv run ruff check .                                → clean
uv run ruff format --check .                       → clean
uv run mypy src/                                   → 7 files, no issues
uv run pre-commit run --all-files                  → all hooks Passed
```

## Backlog deferrals (not addressed in this PR)

Six items under `## t14-heal — 2026-05-10` in `tasks/backlog.md`:

1. **Anchor / justification visual separation** — `report.py:163-170`. ai-ml flagged flat hierarchy between `<p>justification` and `<blockquote>quote`. Polish belongs to T16 (CSS host).
2. **PRD §4.6 strings not pinned as constants** — ai-ml flagged that the renderer faithfully surfaces user_message but no test pins the §4.6 wording. Cross-task: stage workers (T07 ingest, T11 salary, T12 confidence, T13 growth) own those strings; centralization belongs there.
3. **Top-level callout MD vs HTML inconsistency** — `report.py:245`. ai-ml flagged that profile-short-circuit returns HTML while every other failure path is markdown. Works under Gradio markdown but is a footgun; revisit when T16 wires the UI host.
4. **`Source.domain` not validated against `]`** — ai-ml flagged that a `]` in `domain` could fake a bracket close in `[domain] — "snippet"` source rendering. Low risk; cross-task to T01 or T11.
5. **Footer callout CSS glyph** — product-owner nit `report.py:98`. CSS `::before` prepends `⚠`; markdown variant already includes it. Verify no double-glyph in T16.
6. **Cost / latency footer placeholder** — `report.py:222-234`. Waiting on T15 to add `Report.total_cost_usd` / `total_duration_ms`. Cross-referenced with existing `t01-schemas` backlog entry.

## Risks / unverified

- Renderer verified by string-level assertions only — no in-browser visual check. The CSS is structured to degrade gracefully without JS, but live look-and-feel is observable only after T16 wires it into a Gradio `gr.HTML` / `gr.Markdown` host.
- The `profile`-as-top-level-failure mapping assumes ingest/redact failures propagate to `profile = StageFailure(stage="profile" or "ingest" or "redact", ...)`. The renderer escapes whatever `user_message` arrives — if upstream stages set a misleading stage label, the user-facing copy is still faithful, but the section heading (rendered as `Profile`) may not match the actual originating stage. Acceptable; revisit if T07 / T08 surface a different convention.
