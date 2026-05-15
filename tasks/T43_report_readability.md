# T43 — Report readability: visual breaks, Plan typography, Score component grid

Status: planned
Owner: ux-engineer (impl) + software-engineer (test updates)
Depends on: none (purely renderer + CSS; pipeline + schemas untouched)
Unblocks: better first-impression UX for live `app.py` demos and Profile.pdf reruns
Estimate: ~90 min (D1 ~15 min, D2 ~30 min, D3 ~30 min, D4 ~15 min) + test refit ~30 min

## Goal

The current report body reads as one undifferentiated wall of text. Three concrete complaints from a 2026-05-15 live rerun against `Profile.pdf`:

1. **No visual breaks between sections.** `## Score`, `## Salary`, `## Confidence`, `## Plan` H2s sit flush against the prior section's content. No rule, no tint, no extra margin.
2. **Plan items are walls of bold.** Each of the 3 items leads with a 2–3-line bold "what" sentence. Bold loses its emphasis role when it swallows whole sentences; the 3 stacked = a wall.
3. **Score `<details>` asymmetry.** Experience opens by default (leftmost-open design from T14), Education + Soft stay collapsed. The user finds the uneven stack jarring — especially because the dropped-components italic footer lands right under it.

Plus two adjacent readability wins the UX review surfaced:

4. **Salary range doesn't read as a headline.** It's a bare `**150k – 210k CZK / month**` paragraph indistinguishable from body bold.
5. **Confidence badge looks like a continuation of Salary.** `**[?] Low**: rationale…` runs as one sentence with no visual separator.

Constraints (must hold):
- Streaming-safe: every section may render alone (e.g. only Score has yielded). No separator artifacts above the first section.
- Dark mode must work — match existing `@media (prefers-color-scheme: dark)` + `body.dark` patterns in [src/gander/report.py:105-129](../src/gander/report.py#L105-L129).
- WCAG SC 1.4.1: meaning cannot rely on color alone. Glyphs stay for status pills.
- Pure CSS in the `_CSS` string. No JS, no external deps, no Gradio theme changes.
- Renderer remains a pure function of `Report`. No new state, no new schema fields.

## Deliverables

### D1 — Section visual breaks  ([src/gander/report.py:72-129](../src/gander/report.py#L72-L129))

Add an H2-level hairline + margin inside `.gander-output`, with a first-child reset so a lone Score section (streaming mid-pipeline) does not render an orphan top border.

```css
.gander-output h2 {
  margin-top: 2.5rem;
  padding-top: 1.25rem;
  border-top: 1px solid #e4e7ec;
  font-size: 1.375rem;
  letter-spacing: -0.005em;
}
.gander-output > h2:first-child,
.gander-output h2:first-of-type {
  border-top: 0; padding-top: 0; margin-top: 0;
}
.gander-output h3 { margin-top: 1.5rem; font-size: 1rem; color: #475467; }
@media (prefers-color-scheme: dark) {
  .gander-output h2 { border-top-color: #3f3f46; }
  .gander-output h3 { color: #a1a1aa; }
}
body.dark .gander-output h2 { border-top-color: #3f3f46; }
body.dark .gander-output h3 { color: #a1a1aa; }
```

Rationale: 1px rule + 2.5rem margin reads as a deliberate beat in both light and dark, costs zero JS, and degrades cleanly mid-stream. Card-style sections were considered and rejected — they fight Gradio's own container chrome and look heavy when a single section is on screen.

### D2 — Plan section redesign  ([src/gander/report.py:308-323](../src/gander/report.py#L308-L323))

Replace the bold-everything markdown list with an inline-HTML `<ol class="gander-plan">` where each item is: a time-horizon **chip**, a normal-weight title, a secondary-color mechanism paragraph. Bold disappears from plan items entirely; visual weight comes from layout, not type weight.

New emitted shape per item:

```html
<ol class="gander-plan">
  <li>
    <span class="gander-chip">6 months</span>
    <p class="gander-plan-title">Take full ownership of moving the LLM &amp; agentic initiative from contributed tooling to a production-deployed system at TD SYNNEX…</p>
    <p class="gander-plan-mech">End-to-end ownership of a production LLM/agentic system is the strongest promotion signal in the CZ AI market for 2024–2025…</p>
  </li>
  …
</ol>
```

CSS additions:

```css
.gander-plan { list-style: decimal; padding-left: 1.25rem; }
.gander-plan li + li { margin-top: 1.25rem; }
.gander-plan-title { margin: 0.15rem 0 0.35rem; font-weight: 500; }
.gander-plan-mech  { margin: 0; color: #475467; }
.gander-chip {
  display: inline-block; font-size: 0.75rem; font-weight: 600;
  padding: 0.1rem 0.55rem; border-radius: 999px;
  border: 1px solid #e4e7ec; color: #475467; margin-bottom: 0.35rem;
}
@media (prefers-color-scheme: dark) {
  .gander-chip { border-color: #3f3f46; color: #d4d4d8; }
  .gander-plan-mech { color: #a1a1aa; }
}
body.dark .gander-chip { border-color: #3f3f46; color: #d4d4d8; }
body.dark .gander-plan-mech { color: #a1a1aa; }
```

Implementation notes:
- `_growth_section` switches from markdown list to inline HTML. Content still flows through `_md`/`_esc` for injection safety — note that values interpolated inside HTML elements only need `_esc`, per the existing comment in [src/gander/report.py:166-168](../src/gander/report.py#L166-L168).
- The literal `**What** *(N months)*: Mechanism.` spec wording from T14 is superseded — record in this task's review section that the bold-everything shape was retired for readability.
- Empty list and `StageFailure` paths keep their current callout shapes; only the success branch changes.

### D3 — Score components: always-visible grid, no `<details>`  ([src/gander/report.py:225-268](../src/gander/report.py#L225-L268))

Replace the 4-col HTML table + 4 `<details>` blocks with a single 2×2 grid (or 1-col stack on narrow viewports) of always-visible component tiles. Each tile shows: name + score, justification (1–2 lines, no clamp), quote (clamped to 2 lines via `-webkit-line-clamp`). The leftmost-open semantic from T14 — "one verified quote on first paint" — is preserved by making *every* tile show its quote.

New shape:

```html
<h2>Score: 54/100</h2>
<div class="gander-components-grid">
  <div class="gander-component">
    <div class="gander-component-head"><strong>Experience</strong> · 85/100</div>
    <p class="gander-component-just">Over 10 years…</p>
    <blockquote class="gander-component-quote">"Led marketing and commercial excellence data streams…" <em>(Pracovní zkušenosti)</em></blockquote>
  </div>
  … Education, Soft, (Skills if not dropped) …
</div>
```

CSS additions:

```css
.gander-components-grid {
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem; margin: 0.75rem 0;
}
@media (max-width: 32rem) { .gander-components-grid { grid-template-columns: 1fr; } }
.gander-component {
  border: 1px solid #e4e7ec; border-radius: 6px; padding: 0.75rem 0.9rem;
}
.gander-component-head { font-size: 0.95rem; margin-bottom: 0.25rem; }
.gander-component-just { margin: 0.25rem 0 0.4rem; }
.gander-component-quote {
  margin: 0; padding-left: 0.6rem; border-left: 2px solid #e4e7ec;
  color: #475467; font-size: 0.875rem;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}
@media (prefers-color-scheme: dark) {
  .gander-component { border-color: #3f3f46; }
  .gander-component-quote { color: #a1a1aa; border-left-color: #3f3f46; }
}
body.dark .gander-component { border-color: #3f3f46; }
body.dark .gander-component-quote { color: #a1a1aa; border-left-color: #3f3f46; }
```

Implementation notes:
- Drop the 4-col summary table at the top of Score — per-tile score in each `.gander-component-head` makes it redundant.
- `_COMPONENT_ORDER` + the `surviving = [n for n in _COMPONENT_ORDER if n in by_name]` filter from T25 stays; tiles render in the same order, dropped components remain footer-listed.
- Dropped-components italic footer keeps its current text but reads more naturally now that all surviving tiles are equal-weight.
- This is the load-bearing fix for complaint #3 — the asymmetry goes away because there is no toggle state to be asymmetric about.

### D4 — Salary headline + Confidence chip  ([src/gander/report.py:284-305](../src/gander/report.py#L284-L305))

Two small shape changes that ride on the same CSS additions:

Salary range becomes a real headline number, not a bold paragraph:

```html
<p class="gander-salary-range"><strong>150,000 – 210,000</strong> <span class="gander-salary-unit">CZK / month</span></p>
```

```css
.gander-salary-range { font-size: 1.5rem; font-weight: 600; letter-spacing: -0.01em; margin: 0.5rem 0 0.75rem; }
.gander-salary-unit  { font-size: 0.875rem; font-weight: 500; color: #667085; }
@media (prefers-color-scheme: dark) { .gander-salary-unit { color: #a1a1aa; } }
body.dark .gander-salary-unit { color: #a1a1aa; }
```

Confidence badge becomes a chip on its own line above the rationale (reuses `.gander-chip` from D2):

```html
<p><span class="gander-chip">[?] Low</span></p>
<p>Confidence in this estimate is Low…</p>
```

The literal glyph `[!] / [~] / [?]` from `_CONFIDENCE_BADGE` carries the meaning-without-color contract. Color tint on the chip is optional and deferred.

## Out of scope (deliberate)

- Pipeline, schemas, prompts, eval behavior. This task is renderer-only.
- New schema fields for "chip kicker" or "quote summary" — derive from existing `GrowthAction` / `Component` fields.
- Hero/upload area redesign in `app.py`. The hero is already tighter than the body; complaint #4 is sections-and-below.
- Mobile breakpoints beyond the single `.gander-components-grid` collapse at 32rem.
- Print stylesheet.

## Verification

1. `uv run pytest tests/test_render.py tests/test_report.py tests/test_partial_failure_streaming.py -x` — all green. Expect to update a small set of assertions:
   - [tests/test_render.py:222-223](../tests/test_render.py#L222-L223) and [:241](../tests/test_render.py#L241) — `<details open>` will no longer appear in Score output. Replace with assertions on `.gander-component` + `.gander-component-quote` presence, and on the quote text appearing for *every* surviving component (not just the leftmost).
   - Plan-section tests that assert on `**…**` literal bold for the "what" need to switch to asserting `<p class="gander-plan-title">` + the `.gander-chip` containing `"N months"`.
   - Salary-range test (if any pins the exact `**…**` shape) updates to the new `<p class="gander-salary-range">` + `<span class="gander-salary-unit">` markup.
2. `uv run pytest -q` — full fast suite green.
3. UI smoke against the synthetic senior fixture, light + dark mode:
   ```bash
   uv run python app.py
   # upload tests/fixtures/synthetic_senior.pdf (or Profile.pdf), inspect:
   #   - Score section: 4 (or 3) tiles, each shows quote, no <details> toggle
   #   - Plan section: each item has a chip ("6 months"), title is not bold-shouted
   #   - H2 separators visible between Score / Salary / Confidence / Plan
   #   - Streaming: when only Score has yielded, no orphan border above it
   #   - Dark mode (browser DevTools "Emulate prefers-color-scheme: dark"): borders + chips legible
   ```
4. Visual diff: screenshot before/after on the same `Profile.pdf` run and attach to the PR description.

## Risks

- **Test churn.** Several `tests/test_render.py` assertions hardcode the current markup (e.g. `<details open>`, the `**What**` bold prefix). All updates land in this task; the test set is small and the assertions are narrow.
- **Gradio Markdown sanitizer.** Inline HTML elements we already use (`<details>`, `<table>`, `<blockquote>`) pass through. New tags (`<ol class>`, `<span class>`, `<div class>`, `<p class>`) are also standard CommonMark-allowed HTML — verify in the UI smoke. If a class attribute is stripped, fall back to inline `style=""` on the affected element.
- **Line-clamp.** `-webkit-line-clamp` is widely supported (caniuse: 97%+) but a quote longer than 2 lines collapses with no "expand" affordance. Acceptable — the full quote stays in the DOM for accessibility (screen readers read past `overflow: hidden`); a future task can add a click-to-expand if reviewers ask for it.
- **First-of-type selector and streaming.** `h2:first-of-type` resolves against the current rendered DOM. As later sections stream in, the *original* first H2 keeps its reset and the new H2s get the separator. Verified mentally against the streaming yield pattern in [app.py:196-207](../app.py#L196-L207); confirm in UI smoke.

## Review checklist (fill in on completion)

- [ ] All four deliverables shipped; CSS + renderer changes contained to `src/gander/report.py`.
- [ ] `tests/test_render.py` + `tests/test_report.py` updated; full `uv run pytest -q` green.
- [ ] UI smoke run on Profile.pdf in light + dark mode; before/after screenshots attached.
- [ ] No new dependencies; no schema changes; no pipeline changes.
- [ ] PRD §8 cold-start ack still intact (handler's first yield in `app.py` unchanged).
- [ ] Lessons updated if any user correction landed during impl.
