"""L6 report renderer — pure functions producing tracker, report, and status HTML.

The renderer is a pure function of a `Report`. Every yield in the L6 pipeline
re-renders its surfaces from the same model; no UI state lives here.

Two content renderers, one model:

- `render_html(report)` — the on-screen report, ONE self-contained HTML fragment
  fed to a `gr.HTML` block. No markdown. This is the source of truth for what the
  reviewer sees, so all styling rides on classes defined in the global `STYLE`.
- `render_markdown(report)` — a clean, portable markdown archive for the download
  button. No HTML grid/cards — just headings, bold, lists, and `>` blockquotes.

Styling is centralized in `STYLE` (a single `<style>` block) and injected ONCE
globally by `app.py`. `render_tracker`/`render_html`/`render_status` emit only
class-bearing markup; they never carry their own `<style>`. This makes styling
deterministic and immune to per-component HTML sanitization.

Status-key mapping (display label -> schema key): the authoritative
`schemas.StageName` literal is `("profile", "score", "salary", "confidence",
"growth")` and the `_require_exact_status_keys` model validator rejects anything
else. The renderer maps the 5 schema stages to readable labels (`Profile /
Score / Salary / Confidence / Plan`) and treats `report.profile = StageFailure`
as the short-circuit "ingestion failed" case, since profile is the first stage
gated on a successful ingest+redact (PLAN L2). See tasks/T14_dev-plan.md.
"""

from __future__ import annotations

from html import escape

from gander.errors import StageFailure
from gander.schemas import (
    COMPONENT_WEIGHTS,
    REPORT_STAGE_NAMES,
    Component,
    Confidence,
    GrowthAction,
    Report,
    SalaryEstimate,
    Score,
    Source,
    StageName,
    StageStatus,
)

# Display label for each schema stage. Reviewer-facing copy lives here, not in
# the data layer. Order mirrors REPORT_STAGE_NAMES so the tracker reads
# left-to-right in pipeline order.
_LABEL_BY_STAGE: dict[StageName, str] = {
    "profile": "Profile",
    "score": "Score",
    "salary": "Salary",
    "confidence": "Confidence",
    "growth": "Plan",
}

# Status glyphs guarantee meaning carries without colour (WCAG SC 1.4.1).
_GLYPH_BY_STATUS: dict[StageStatus, str] = {
    "pending": "∘",  # ring operator
    "running": "⋯",  # midline horizontal ellipsis
    "done": "✓",  # check
    "failed": "✗",  # ballot x
    "skipped": "—",  # em dash
}

# Order matters: the component grid renders in this stable reading order.
_COMPONENT_ORDER: tuple[str, ...] = ("skills", "experience", "education", "soft_signals")
_COMPONENT_DISPLAY: dict[str, str] = {
    "skills": "Skills",
    "experience": "Experience",
    "education": "Education",
    "soft_signals": "Soft",
}

_CONFIDENCE_BADGE: dict[str, str] = {
    "High": "High",
    "Medium": "Medium",
    "Low": "Low",
}

# Single global stylesheet for tracker + report + status surfaces. Injected once
# by app.py alongside the hero CSS; no renderer emits its own `<style>`. Colours
# are CSS custom-property tokens overridden for OS dark (`prefers-color-scheme`)
# AND Gradio's `body.dark` theme toggle — only the ~13 token values repeat across
# those two blocks, not every rule, which is what keeps the dark path in sync.
STYLE = """<style>
:root {
  --g-fg: #1d2939;
  --g-fg-muted: #475467;
  --g-fg-subtle: #667085;
  --g-border: #e4e7ec;
  --g-border-strong: #d0d5dd;
  --g-surface: #ffffff;
  --g-surface-2: #f9fafb;
  --g-accent: #92400e;
  --g-ok: #12b76a;
  --g-warn: #f59e0b;
  --g-err: #f04438;
  --g-err-bg: #fef3f2;
  --g-err-fg: #7a271a;
  /* Type scale — 6 steps; theme-independent */
  --g-text-xs:   0.8rem;
  --g-text-sm:   0.9rem;
  --g-text-base: 1rem;
  --g-text-lg:   1.25rem;
  --g-text-xl:   1.75rem;
  --g-text-2xl:  3rem;
  /* Corner radius — 3 steps; theme-independent */
  --g-radius-sm:   4px;
  --g-radius-md:   8px;
  --g-radius-pill: 999px;
}
/* Dark theme is driven solely by `body.dark` (Gradio's rendered-theme class) — the
   single source of truth. A prior OS-keyed `prefers-color-scheme: dark` copy of these
   tokens desynced from Gradio: a dark-OS viewer of a LIGHT Gradio page got near-white
   tokens on a light background. report.STYLE only ever renders inside Gradio (the
   download artifact is markdown), so no no-JS consumer needs the OS query. Do not
   reintroduce an OS media query here — it re-splits the theme into two signals. */
body.dark {
  --g-fg: #f4f4f5;
  --g-fg-muted: #d4d4d8;
  --g-fg-subtle: #a1a1aa;
  --g-border: #3f3f46;
  --g-border-strong: #52525b;
  --g-surface: #18181b;
  --g-surface-2: #27272a;
  --g-accent: #fdba74;
  --g-ok: #22c55e;
  --g-warn: #f59e0b;
  --g-err: #ef4444;
  --g-err-bg: #450a0a;
  --g-err-fg: #fecaca;
}

/* ---- Stage tracker ---- */
.tracker {
  display: flex; gap: 0.5rem; flex-wrap: wrap; justify-content: center;
  font-family: system-ui, sans-serif; margin: 0 0 1rem 0;
}
/* Visually hidden but exposed to assistive tech (standard clip pattern). Carries
   the single live announcement so screen readers hear one stage transition per
   yield instead of the whole pill row re-read. */
.gander-sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
.pill {
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.2rem 0.65rem 0.2rem 0.55rem;
  border-radius: var(--g-radius-pill);
  border: 1px solid var(--g-border);
  border-left: 3px solid var(--g-border-strong);
  background: transparent; color: var(--g-fg-subtle);
  font-size: var(--g-text-xs); line-height: 1.25;
  transition: border-color 120ms ease, color 120ms ease;
}
.pill::before { content: attr(data-glyph); font-weight: 700; opacity: 0.95; }
/* .pill.skipped/.pill.pending use var(--g-fg-subtle) = #667085 in light mode,
   ~4.84:1 on the transparent (white) pill bg (was #98a2b3 = 2.58:1). line-through
   + the em-dash glyph keep "skipped" legible without colour (WCAG 1.4.1). Token-
   driven so dark mode inherits automatically; the resolved value is contrast-
   guarded in tests/test_a11y_contrast.py. */
.pill.pending { border-left-color: var(--g-border-strong); color: var(--g-fg-subtle); }
.pill.running { border-left-color: var(--g-warn); color: var(--g-fg);
                animation: ganderPulse 1.2s ease-in-out infinite; }
.pill.done    { border-left-color: var(--g-ok);  color: var(--g-fg); }
.pill.failed  { border-left-color: var(--g-err); color: var(--g-fg); }
.pill.skipped { border-left-color: var(--g-border-strong); color: var(--g-fg-subtle);
                text-decoration: line-through; }
@keyframes ganderPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.55; } }
@media (prefers-reduced-motion: reduce) {
  .pill { transition: none; }
  .pill.running { animation: none; }
}

/* ---- Working / status block ---- */
.gander-status {
  display: flex; align-items: center; gap: 0.55rem;
  font-family: system-ui, sans-serif; color: var(--g-fg-muted);
  font-size: var(--g-text-sm); margin: 0.5rem 0;
}
.gander-status-dot {
  width: 0.6rem; height: 0.6rem; border-radius: var(--g-radius-pill);
  background: var(--g-warn); flex-shrink: 0;
  animation: ganderPulse 1.2s ease-in-out infinite;
}
.gander-status-neutral { color: var(--g-fg-subtle); }
.gander-status-neutral .gander-status-dot { background: var(--g-border-strong); animation: none; }
@media (prefers-reduced-motion: reduce) { .gander-status-dot { animation: none; } }

/* ---- Report shell ---- */
.gander-output { font-family: system-ui, sans-serif; color: var(--g-fg); }
.gander-h2 {
  margin: 2rem 0 0.75rem; padding-top: 1.25rem;
  border-top: 1px solid var(--g-border);
  font-size: var(--g-text-lg); font-weight: 600; color: var(--g-fg);
}
.gander-h3 {
  margin: 1.25rem 0 0.5rem; font-size: var(--g-text-sm);
  font-weight: 600; color: var(--g-fg-muted);
}

/* ---- Score headline (the lede) ---- */
.gander-score-section { margin: 0.25rem 0 0.5rem; }
.gander-score-label {
  margin: 0; padding: 0; border: 0;
  font-size: var(--g-text-xs); font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase; color: var(--g-fg-subtle);
}
.gander-score {
  display: flex; align-items: baseline; gap: 0.5rem;
  margin: 0.15rem 0 0; flex-wrap: wrap;
}
.gander-score-num {
  font-size: var(--g-text-2xl); font-weight: 700; line-height: 1; color: var(--g-fg);
}
.gander-score-denom { font-size: var(--g-text-lg); font-weight: 500; color: var(--g-fg-subtle); }
.gander-tier-chip {
  align-self: center; margin-left: 0.25rem;
  font-size: var(--g-text-xs); font-weight: 600;
  padding: 0.2rem 0.6rem; border-radius: var(--g-radius-pill); white-space: nowrap;
  background: var(--g-surface-2); border: 1px solid var(--g-border);
  color: var(--g-fg-muted);
}
.gander-score-note {
  margin: 0.5rem 0 0; font-size: var(--g-text-sm); font-style: italic; color: var(--g-fg-subtle);
}
.gander-visually-hidden {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
}

/* ---- Component grid ---- */
.gander-components-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(min(22rem, 100%), 1fr));
  gap: 1rem; align-items: stretch; margin: 1rem 0;
}
.gander-component {
  display: flex; flex-direction: column;
  border: 1px solid var(--g-border); border-radius: var(--g-radius-md);
  padding: 0.9rem 1rem; background: var(--g-surface-2);
}
.gander-component-head {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 0.5rem; margin-bottom: 0.4rem;
}
.gander-component-name {
  margin: 0; font-size: var(--g-text-sm); font-weight: 600; color: var(--g-fg);
}
.gander-component-score {
  font-size: var(--g-text-base); font-weight: 700; color: var(--g-fg); white-space: nowrap;
}
.gander-component-score-max {
  font-size: var(--g-text-xs); font-weight: 500; color: var(--g-fg-subtle);
}
.gander-component-just {
  margin: 0 0 0.5rem; font-size: var(--g-text-sm); line-height: 1.5; color: var(--g-fg-muted);
}
.gander-component-quote {
  display: block; margin: 0; padding-left: 0.7rem;
  border-left: 3px solid var(--g-border-strong);
  color: var(--g-fg-muted); font-size: var(--g-text-sm); line-height: 1.5;
  font-style: italic;
}
.gander-component-cite {
  display: block; margin-top: 0.3rem; font-size: var(--g-text-xs);
  font-style: normal; color: var(--g-fg-subtle);
}
/* Long-quote disclosure: clamp the preview to a few lines and reveal the rest
   on click. The quote lives inside <summary> (phrasing-only: a <span>, never a
   block <blockquote>) so the clamped preview stays visible while collapsed; the
   full text is always in the DOM, so screen readers always get it. */
.gander-evidence { margin: 0; }
.gander-evidence-summary { cursor: pointer; list-style: none; display: block; }
.gander-evidence-summary::-webkit-details-marker { display: none; }
.gander-evidence-summary::after {
  content: "Show full evidence"; display: inline-block; margin-top: 0.4rem;
  font-size: var(--g-text-xs); font-weight: 600; color: var(--g-accent);
  text-decoration: underline;
}
.gander-evidence[open] .gander-evidence-summary::after { content: "Show less"; }
.gander-evidence-summary:focus-visible {
  outline: 2px solid var(--g-accent); outline-offset: 2px; border-radius: var(--g-radius-sm);
}
.gander-evidence:not([open]) .gander-component-quote {
  display: -webkit-box; -webkit-box-orient: vertical;
  -webkit-line-clamp: 4; overflow: hidden;
}

/* ---- Salary ---- */
.gander-salary-context {
  font-size: var(--g-text-sm); color: var(--g-fg-subtle); margin: 0 0 0.1rem; line-height: 1.4;
}
.gander-salary-range {
  font-size: var(--g-text-xl); font-weight: 700; margin: 0.25rem 0 0.5rem; color: var(--g-fg);
  line-height: 1.2; overflow-wrap: break-word;
}
.gander-salary-unit {
  font-size: var(--g-text-sm); font-weight: 500; color: var(--g-fg-subtle); white-space: nowrap;
}
.gander-salary-reasoning {
  margin: 0.5rem 0; line-height: 1.6; color: var(--g-fg-muted);
}
.gander-sources { margin: 0.25rem 0; padding-left: 1.1rem; }
.gander-sources li { margin: 0.3rem 0; font-size: var(--g-text-sm); color: var(--g-fg-muted); }
.gander-source-domain { font-weight: 600; color: var(--g-fg); }

/* ---- Chips ---- */
.gander-chip {
  display: inline-block; font-size: var(--g-text-xs); font-weight: 600;
  padding: 0.15rem 0.6rem; border-radius: var(--g-radius-pill);
  border: 1px solid var(--g-border); background: var(--g-surface-2);
  color: var(--g-fg-muted); margin-bottom: 0.35rem;
}
/* Confidence chip: tint the leading edge by tier so the rating reads at a
   glance, mirroring the `.pill` border-left convention. */
.gander-chip.is-high { border-left: 3px solid var(--g-ok); }
.gander-chip.is-medium { border-left: 3px solid var(--g-warn); }
.gander-chip.is-low { border-left: 3px solid var(--g-err); }

/* ---- Plan ---- */
/* Each step is numbered by a CSS counter, not the native <ol> marker. The
   native marker sits in the list's outside gutter and detaches from the block
   `.gander-plan-item` wrapper, leaving the digit floating above the text. A
   counter rendered into `.gander-plan-item::before` keeps the numeral pinned to
   its content. Suppressing the native marker needs `ol.gander-plan` (0,2,1) to
   out-rank Gradio's `.prose ol { list-style: decimal }` on document order —
   the same tactic as the .prose-neutralization block below. */
.gander-output ol.gander-plan { list-style: none; padding-left: 0; margin: 0.5rem 0; }
.gander-plan { counter-reset: gander-step; }
.gander-plan li { counter-increment: gander-step; }
.gander-plan li + li { margin-top: 1.1rem; }
.gander-plan-item { position: relative; padding-left: 2rem; }
.gander-plan-item::before {
  content: counter(gander-step) "."; position: absolute; left: 0; top: 0;
  width: 1.4rem; text-align: right;
  font-size: var(--g-text-base); font-weight: 600; line-height: 1.4;
  color: var(--g-fg-subtle);
}
.gander-plan-title { margin: 0 0 0.3rem; font-weight: 600; color: var(--g-fg); }
.gander-plan-mech { margin: 0; line-height: 1.55; color: var(--g-fg-muted); }
.gander-plan .gander-chip { margin: 0.5rem 0 0; }

/* ---- Failure callout ---- */
.gander-callout {
  border-left: 4px solid var(--g-err); background: var(--g-err-bg); color: var(--g-err-fg);
  padding: 0.6rem 0.8rem; margin: 0.6rem 0; border-radius: var(--g-radius-md); line-height: 1.5;
}
.gander-callout::before { content: "⚠"; margin-right: 0.45rem; }

/* ---- About / How-scored disclosures ---- */
.gander-about, .gander-howscored { margin: 1.25rem 0 0; }
.gander-about > summary, .gander-howscored > summary {
  cursor: pointer; font-weight: 600; color: var(--g-fg-muted);
  padding: 0.6rem 0; list-style-position: inside;
  min-height: 2.75rem; box-sizing: border-box;
}
.gander-about > summary:hover, .gander-howscored > summary:hover { color: var(--g-fg); }
.gander-about > summary:focus-visible, .gander-howscored > summary:focus-visible {
  outline: 2px solid var(--g-accent); outline-offset: 2px; border-radius: var(--g-radius-sm);
}
.gander-about p, .gander-about li,
.gander-howscored p, .gander-howscored li {
  font-size: var(--g-text-sm); line-height: 1.55; color: var(--g-fg-muted);
}
.gander-about strong { color: var(--g-fg); }
.gander-totals { font-size: var(--g-text-sm); color: var(--g-fg-subtle); }
.gander-totals-note { font-size: var(--g-text-xs); font-style: italic; color: var(--g-fg-subtle); }
.gander-report-notice {
  font-size: var(--g-text-sm); color: var(--g-fg-muted);
  border-left: 3px solid var(--g-warn); padding-left: 0.6rem; margin: 0.5rem 0;
}
.gander-empty { color: var(--g-fg-subtle); font-style: italic; }

/* ---- Gradio `.prose` neutralization ----
   The report renders inside Gradio's `.prose` container (the `.gander-output`
   element carries both classes). Gradio styles prose by element tag —
   `.gradio-container-<v> .prose h2 { font-size }`, `.prose h3`, `.prose blockquote
   { margin }` — at two-class specificity, which OUT-specifies our single-class
   design-token rules (`.gander-h2`, `.gander-score-label`, …). Symptom: the
   "Overall score" eyebrow (an <h2 class="gander-score-label"> meant to be a 0.8rem
   uppercase label) rendered at ~22px, and section headings ignored the type scale.

   Re-scoping our token rules as `.gander-output <tag>.<class>` lifts them to the
   same two-class specificity; our <style> is later in document order than Gradio's
   head CSS, so the tie resolves in our favour. Verified against the live Gradio DOM
   by the e2e computed-style guard (test_report_typography_uses_design_tokens). This
   is the typography analogue of the plan-item wrapper that dodges `.prose li > p`.

   Layout matters too: `.prose h2`/`.prose h3` also set margins (16px/8px), which
   defeat the base single-class margin/padding/border declarations. So these rules
   MIRROR the layout values from the base rules above (`.gander-h2` margins, the
   `.gander-score-label` margin/padding/border reset, `.gander-component-name`
   margin) at two-class specificity. The duplicated values are guarded by the e2e
   margin assertions in test_report_typography_uses_design_tokens — if a base value
   and its mirror here drift apart, that browser test fails. */
.gander-output h2.gander-h2 {
  font-size: var(--g-text-lg);
  margin: 2rem 0 0.75rem; padding-top: 1.25rem;
  border-top: 1px solid var(--g-border);
}
.gander-output h3.gander-h3 { font-size: var(--g-text-sm); margin: 1.25rem 0 0.5rem; }
.gander-output h3.gander-component-name { font-size: var(--g-text-sm); margin: 0; }
.gander-output h2.gander-score-label {
  font-size: var(--g-text-xs); font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase; color: var(--g-fg-subtle);
  margin: 0; padding: 0; border: 0;
}
/* `.prose blockquote` ALSO rewrites border-left (5px), padding-left (8px) and the
   block margin — only on the short-quote <blockquote>, not the long-quote <span>,
   so cards rendered inconsistently. A 3-class selector beats `.prose blockquote`
   for border/padding; its margin is declared `!important`, so the only correct way
   to restore parity with the <span> variant (margin 0) is a matching `!important`.
   This is the one `!important` in the report — it counters a vendor `!important`,
   not our own cascade. */
.gander-output .gander-component .gander-component-quote {
  margin: 0 !important;
  border-left: 3px solid var(--g-border-strong); padding-left: 0.7rem;
}

@media (max-width: 32rem) {
  /* The grid collapses to one column on its own (auto-fit + min(22rem, 100%)); only
     the score numeral needs a hand-tuned shrink at phone widths. */
  .gander-score-num { font-size: 2.5rem; }
}
</style>"""


# Markdown metacharacters that can break out of an inline context when
# interpolated mid-string. Backslash MUST come first so subsequent escapes are
# not re-escaped. Set chosen to neutralise: `](payload)` link injection,
# `*`/`_` emphasis, backtick code spans, `!` for `![alt](url)` images. Block-
# level metacharacters (`#`, `+`, `-`, `|`, fenced code, table pipes) only
# matter at line-start; `_md` collapses newlines + whitespace runs downstream
# so an LLM-controlled string cannot escape an inline context into a heading,
# list, table, or blockquote. Only the markdown download path uses these; the
# HTML display path escapes with `_esc`/`_html_inline`.
_MD_ESCAPE = str.maketrans(
    {
        "\\": "\\\\",
        "`": "\\`",
        "*": "\\*",
        "_": "\\_",
        "[": "\\[",
        "]": "\\]",
        "(": "\\(",
        ")": "\\)",
        "!": "\\!",
    }
)


def _esc(text: str) -> str:
    """HTML-escape only. Safe for interpolation inside HTML element bodies/attrs."""
    return escape(text, quote=True)


def _html_inline(text: str) -> str:
    """HTML-escape and collapse whitespace for content inside inline HTML blocks."""
    escaped = _esc(" ".join(text.split()))
    return (
        escaped.replace("[", "&#91;")
        .replace("]", "&#93;")
        .replace("(", "&#40;")
        .replace(")", "&#41;")
    )


def _md(text: str) -> str:
    """Escape for markdown interpolation: HTML-escape, neutralise md metacharacters,
    and collapse whitespace so block-level tokens cannot appear at line-start.

    Use for any user-controllable string flowing into the markdown download
    (callouts, source lines, salary reasoning, confidence rationale, growth
    actions). The HTML display path never calls this — it uses `_esc` /
    `_html_inline`.

    Newlines (and runs of whitespace) collapse to a single space so an
    LLM-controlled value like ``"ok\\n# Pwned"`` cannot inject a heading,
    list, table, or fenced code block. ``_failure_callout_md`` splits its
    input on newlines BEFORE calling ``_md`` per line, so multi-line failure
    messages are preserved through that path.
    """
    escaped = escape(text, quote=True).translate(_MD_ESCAPE)
    return " ".join(escaped.split())


def _pill_html(label: str, status: StageStatus, tooltip: str | None) -> str:
    glyph = _GLYPH_BY_STATUS[status]
    title_attr = f' title="{_esc(tooltip)}"' if tooltip else ""
    aria = f' aria-label="{_esc(label)}: {status}"'
    return (
        f'<span class="pill {status}" data-glyph="{glyph}"{title_attr}{aria}>{_esc(label)}</span>'
    )


def _label_for_stage(report: Report, stage: StageName) -> str:
    if stage == "profile" and report.statuses[stage] == "running" and not report.redacted_cv_text:
        return "Ingest"
    return _LABEL_BY_STAGE[stage]


def _tracker_announcement(report: Report) -> str:
    """One concise status line for the screen-reader live region.

    The visual `.tracker` re-renders every pipeline yield; putting `aria-live` on
    the whole pill row makes a screen reader re-announce all six pills each time.
    Instead this returns a single string describing the *current* state. A polite
    live region only fires when its text changes, so as the run advances
    (Profile → Score → …) the reader hears one transition per stage.

    Priority: the running stage, else the first failure, else — while stages are
    still pending (the initial all-pending yield, and the gap after profile
    finishes before score/salary start) — the next waiting stage. "Analysis
    complete" is reserved for when every stage is terminal (done/failed/skipped),
    so a screen reader is never told the run finished while pills still show
    pending work.
    """
    failed_label: str | None = None
    pending_label: str | None = None
    for stage in REPORT_STAGE_NAMES:
        status = report.statuses[stage]
        if status == "running":
            return f"{_label_for_stage(report, stage)}: in progress"
        if status == "failed" and failed_label is None:
            failed_label = _label_for_stage(report, stage)
        if status == "pending" and pending_label is None:
            pending_label = _label_for_stage(report, stage)
    if failed_label is not None:
        return f"{failed_label}: failed"
    if pending_label is not None:
        return f"{pending_label}: waiting"
    return "Analysis complete"


def render_tracker(report: Report) -> str:
    """Render the 5-stage tracker as a single class-bearing `<div>` (no `<style>`).

    Styling rides on the global `STYLE` block injected once by app.py (no inline
    `<style>`). Reads `report.statuses[stage]` for each schema stage in pipeline
    order. Failed pills carry the originating `StageFailure.user_message` as a
    tooltip; non-failed pills get no tooltip. The pill row is a labelled group
    (not a live region) so the per-pill `aria-label`s stay navigable; a separate
    visually-hidden polite region (`_tracker_announcement`) carries incremental
    spoken updates.
    """
    pills: list[str] = []
    for stage in REPORT_STAGE_NAMES:
        status = report.statuses[stage]
        tooltip: str | None = None
        if status == "failed":
            block = getattr(report, stage)
            if isinstance(block, StageFailure):
                tooltip = block.user_message
            else:
                # Schema doesn't enforce status<->block consistency: a "failed"
                # status with a populated block is legal but uninformative.
                # Surface the inconsistency rather than render a tooltip-less pill.
                tooltip = "Stage marked failed but no failure message available."
        pills.append(_pill_html(_label_for_stage(report, stage), status, tooltip))
    announcement = _esc(_tracker_announcement(report))
    return (
        '<div class="tracker" role="group" aria-label="Pipeline progress">'
        f"{''.join(pills)}</div>"
        f'<p class="gander-sr-only" role="status" aria-live="polite">{announcement}</p>'
    )


def render_status(message: str, *, working: bool = True) -> str:
    """Render a small status block (cold-start "working" or a neutral notice).

    Replaces the bare ``*italic*`` cold-start/cancel copy with a class-bearing
    HTML block so the body slot is always a styled `gr.HTML`, never markdown.
    `working=True` pulses an amber dot (respecting `prefers-reduced-motion`);
    `working=False` shows a static neutral dot for terminal states like cancel.
    """
    cls = "gander-status" if working else "gander-status gander-status-neutral"
    return (
        f'<div class="{cls}" role="status" aria-live="polite">'
        '<span class="gander-status-dot" aria-hidden="true"></span>'
        f"<span>{_esc(message)}</span>"
        "</div>"
    )


# Copy grounded in PRD §4.7 and the README "Decisions"/"Bias And Limits"
# sections — no claims beyond what the system actually does. Collapsed and
# demoted below the score (P0-2): the bias disclosure is one click away, not the
# first thing that buries the result. Keep these in sync if the posture changes.
_ABOUT_BANNER_HTML = (
    '<details class="gander-about">'
    "<summary>About this report &amp; its limits</summary>"
    "<p>CV screening is classified as high-risk AI under the EU AI Act and is "
    "well documented to encode demographic bias. Read these results as "
    "<strong>candidate hypotheses to validate, not authoritative judgments.</strong></p>"
    "<ul>"
    "<li>Identifying details (name, contact info, age-implying dates) are "
    "redacted before scoring, which evaluates skills, experience, education, "
    "and role progression.</li>"
    "<li>Some bias-encoding signals — school names, language patterns, employer "
    "prestige — cannot be fully removed without discarding legitimate signal, "
    "so they may still influence the result.</li>"
    "<li>This system is <strong>not validated for fairness across protected groups.</strong></li>"
    "</ul>"
    "</details>"
)

_ABOUT_BANNER_MD = (
    "## About this report\n\n"
    "CV screening is classified as high-risk AI under the EU AI Act and is "
    "well documented to encode demographic bias. Read these results as "
    "**candidate hypotheses to validate, not authoritative judgments.**\n\n"
    "- Identifying details (name, contact info, age-implying dates) are "
    "redacted before scoring, which evaluates skills, experience, education, "
    "and role progression.\n"
    "- Some bias-encoding signals — school names, language patterns, employer "
    "prestige — cannot be fully removed without discarding legitimate signal, "
    "so they may still influence the result.\n"
    "- This system is **not validated for fairness across protected groups.**"
)


def _failure_callout_html(failure: StageFailure) -> str:
    return f'<div class="gander-callout" role="alert">{_esc(failure.user_message)}</div>'


def _failure_callout_md(failure: StageFailure) -> str:
    # Markdown blockquote; the warning glyph is literal U+26A0 per spec.
    # Every line of user_message is prefixed with `> ` so a multi-line message
    # cannot break out of the callout and inject headings/lists below it.
    lines = failure.user_message.splitlines() or [""]
    quoted = [f"> ⚠ {_md(lines[0])}"] + [f"> {_md(line)}" for line in lines[1:]]
    return "\n".join(quoted)


def _h2(text: str) -> str:
    # `text` is always a literal section label here, never user-controlled.
    return f'<h2 class="gander-h2">{text}</h2>'


def _format_money(n: int) -> str:
    return f"{n:,}"


def _source_line(src: Source) -> str:
    # `[{domain}]: "{snippet}"` lives in a markdown context where a literal
    # `]` in domain or `](` in snippet would forge a link target. Route both
    # through `_md` so the brackets/parens stay inert text.
    snippet = _md(src.snippet)
    domain = _md(src.domain)
    return f'- [{domain}]: "{snippet}"'


def _source_line_html(src: Source) -> str:
    domain = _html_inline(src.domain)
    snippet = _html_inline(src.snippet)
    return f'<span class="gander-source-domain">{domain}</span> "{snippet}"'


# --------------------------------------------------------------------------- #
# HTML display renderer (on-screen report — one self-contained HTML fragment).
# --------------------------------------------------------------------------- #


# Raw-character length past which an evidence quote is visually clamped to a few
# lines with an accessible "Show full evidence" disclosure, so one verbose quote
# cannot balloon its card far past its row-neighbours. Shorter quotes render
# inline. The full text always stays in the DOM (screen readers read it through
# the clamp); the disclosure only governs the *visual* truncation for sighted
# users. Tuned so genuinely long anchors (multi-sentence) clamp while ordinary
# one-line quotes do not.
_QUOTE_CLAMP_CHARS = 220


def _component_tile_html(name: str, comp: Component) -> str:
    quote = _html_inline(comp.anchor.quote)
    heading_id = f"gander-score-{name}"
    cite = (
        f'<cite class="gander-component-cite">— {_html_inline(comp.anchor.section)}</cite>'
        if comp.anchor.section
        else ""
    )
    head = (
        '<div class="gander-component-head">'
        f'<h3 id="{heading_id}" class="gander-component-name">{_COMPONENT_DISPLAY[name]}</h3>'
        f'<span class="gander-component-score">{comp.score_0_100}'
        '<span class="gander-component-score-max">/100</span></span>'
        "</div>"
        f'<p class="gander-component-just">{_html_inline(comp.justification)}</p>'
    )
    if len(comp.anchor.quote) > _QUOTE_CLAMP_CHARS:
        # Long quote: clamp via CSS and wrap in <details> so the full text is one
        # keyboard- and screen-reader-accessible click away (the cite stays
        # visible above the toggle). The quote/cite live in the <summary> so the
        # clamped preview itself is the disclosure target. `<summary>` accepts
        # phrasing content only, so the quote is a `<span>` (CSS `display: block`
        # keeps the blockquote look) — a block `<blockquote>` here is invalid HTML.
        evidence = (
            '<details class="gander-evidence">'
            '<summary class="gander-evidence-summary">'
            f'<span class="gander-component-quote">"{quote}"</span>'
            f"{cite}"
            "</summary>"
            "</details>"
        )
    else:
        evidence = f'<blockquote class="gander-component-quote">"{quote}"{cite}</blockquote>'
    return (
        f'<section class="gander-component" role="listitem" aria-labelledby="{heading_id}">'
        f"{head}{evidence}"
        "</section>"
    )


def _score_section_html(
    score: Score | StageFailure | None, seniority_band: str | None = None
) -> str:
    if score is None:
        return ""
    if isinstance(score, StageFailure):
        return _h2("Score") + _failure_callout_html(score)

    # T25: schema allows partial Score (experience-mandatory; others optional).
    # Render only surviving components as always-visible tiles — dropped
    # categories are named in the footer note so the reviewer sees they were
    # zero-weighted, not omitted.
    by_name: dict[str, Component] = {c.name: c for c in score.components}
    surviving = [n for n in _COMPONENT_ORDER if n in by_name]
    tiles = "".join(_component_tile_html(n, by_name[n]) for n in surviving)
    grid = f'<div class="gander-components-grid" role="list">{tiles}</div>'

    # Collapse whitespace so a band value carrying a newline can't disrupt
    # layout; `_esc` keeps it inert as an attribute-free text node.
    band_text = " ".join(seniority_band.split()) if seniority_band else ""
    chip = (
        f'<span class="gander-tier-chip" aria-hidden="true">{_esc(band_text)}</span>'
        if band_text
        else ""
    )

    # Screen readers announce the heading ("Overall score") then this one phrase
    # as the value; the decorative numeral/denominator/chip spans are aria-hidden
    # so the lede reads as a single figure, not three loose tokens.
    sr_value = f"{score.total} out of 100"
    if band_text:
        sr_value += f", {_esc(band_text)} tier"

    headline = (
        '<section class="gander-score-section" aria-labelledby="gander-score-h">'
        '<h2 id="gander-score-h" class="gander-score-label">Overall score</h2>'
        '<div class="gander-score">'
        f'<span class="gander-visually-hidden">{sr_value}</span>'
        f'<span class="gander-score-num" aria-hidden="true">{score.total}</span>'
        '<span class="gander-score-denom" aria-hidden="true">/100</span>'
        f"{chip}"
        "</div>"
        "</section>"
    )

    out = headline + grid
    if score.dropped:
        names = ", ".join(_COMPONENT_DISPLAY[n] for n in score.dropped)
        out += (
            f'<p class="gander-score-note">Note: {len(score.dropped)} component(s) '
            f"dropped ({_esc(names)}): no anchor verified against CV text.</p>"
        )
    return out


def _salary_context_line(role: str | None, location: str | None) -> str:
    """Caption naming the role + market the range is anchored to (P2.2).

    The estimate is for a *canonical* role (gander.normalize) in a detected
    market — surfacing it above the number stops the range reading as a generic
    figure. Both values are LLM-derived → `_html_inline`. Degrades gracefully:
    no role → no caption; role but no location → role only.
    """
    role_text = _html_inline(role) if role and role.strip() else ""
    if not role_text:
        return ""
    location_text = _html_inline(location) if location and location.strip() else ""
    body = f"{role_text} · {location_text}" if location_text else role_text
    return f'<p class="gander-salary-context">{body}</p>'


def _salary_section_html(
    salary: SalaryEstimate | StageFailure | None,
    role: str | None = None,
    location: str | None = None,
) -> str:
    if salary is None:
        return ""
    if isinstance(salary, StageFailure):
        return _h2("Salary") + _failure_callout_html(salary)

    context_line = _salary_context_line(role, location)
    range_line = (
        f"{context_line}"
        '<p class="gander-salary-range">'
        f"{_format_money(salary.low)}–{_format_money(salary.high)} "
        f'<span class="gander-salary-unit">{_esc(salary.currency)} / {salary.period}</span>'
        "</p>"
    )
    sources = (
        "".join(f"<li>{_source_line_html(s)}</li>" for s in salary.sources)
        or '<li class="gander-empty">(no sources)</li>'
    )
    return (
        _h2("Salary")
        + range_line
        + f'<p class="gander-salary-reasoning">{_html_inline(salary.reasoning)}</p>'
        + '<h3 class="gander-h3">Sources</h3>'
        + f'<ul class="gander-sources">{sources}</ul>'
    )


def _confidence_section_html(conf: Confidence | StageFailure | None) -> str:
    if conf is None:
        return ""
    if isinstance(conf, StageFailure):
        return _h2("Confidence") + _failure_callout_html(conf)
    badge = _CONFIDENCE_BADGE[conf.tier]
    return (
        _h2("Confidence") + f'<p><span class="gander-chip is-{conf.tier.lower()}" '
        f'aria-label="Confidence: {conf.tier}">'
        f"{_esc(badge)}</span></p>"
        + f'<p class="gander-confidence-rationale">{_html_inline(conf.rationale)}</p>'
    )


def _growth_section_html(growth: list[GrowthAction] | StageFailure | None) -> str:
    if growth is None:
        return ""
    if isinstance(growth, StageFailure):
        return _h2("Plan") + _failure_callout_html(growth)
    if not growth:
        return _h2("Plan") + '<p class="gander-empty">No actions.</p>'
    items: list[str] = []
    for action in growth:
        # Title first so the step counter numbers the action; the time-horizon
        # chip trails as a meta line (styled by `.gander-plan .gander-chip`).
        #
        # The title/mechanism paragraphs are wrapped in a block <div>, NOT placed
        # as direct children of <li>. Gradio's bundled prose CSS ships a
        # `.prose li > p, .prose ul > p { display: inline }` reset; our gr.HTML
        # report renders inside that `.prose` container, so direct `li > p`
        # children collapse to one inline run ("inference.Transitioning…"). The
        # wrapper breaks the `li > p` relationship so the paragraphs stay block,
        # without a version-pinned specificity war against Gradio's selector.
        items.append(
            '<li><div class="gander-plan-item">'
            f'<p class="gander-plan-title">{_html_inline(action.what)}</p>'
            f'<p class="gander-plan-mech">{_html_inline(action.mechanism)}</p>'
            f'<span class="gander-chip" aria-label="Time horizon: {action.time_horizon_months} '
            f'months">{action.time_horizon_months} months</span>'
            "</div></li>"
        )
    return _h2("Plan") + '<ol class="gander-plan">' + "".join(items) + "</ol>"


def _footer_html(report: Report) -> str:
    weight_rows = "".join(
        f"<li><strong>{_COMPONENT_DISPLAY[name]}</strong>: {int(weight * 100)}%</li>"
        for name, weight in COMPONENT_WEIGHTS.items()
    )
    totals_line = (
        f"Total cost: ${report.total_cost_usd:.4f} · "
        f"LLM time (sum): {report.total_latency_ms:,} ms · "
        f"Total elapsed: {report.wall_clock_ms:,} ms"
    )
    notices = "".join(
        f'<p class="gander-report-notice">{_html_inline(notice)}</p>' for notice in report.notices
    )
    return (
        notices + '<details class="gander-howscored">'
        "<summary>How is this scored?</summary>"
        "<p>Component weights:</p>"
        f"<ul>{weight_rows}</ul>"
        f'<p class="gander-totals">{totals_line}</p>'
        '<p class="gander-totals-note">LLM time can exceed total elapsed when '
        "provider calls run in parallel.</p>"
        "</details>"
    )


def render_html(report: Report) -> str:
    """Render the on-screen report as ONE self-contained HTML fragment.

    Top-level short-circuit: when `report.profile` is a `StageFailure`, returns
    ONLY the failure callout — the rest of the pipeline depends on profile, so
    rendering downstream blocks would be misleading. When `report.profile is
    None` (T15 pipeline initial state, before profile extraction completes),
    returns an empty string — the tracker carries the pending state. Stage
    failures further down render inline as warning callouts and the rest of the
    body continues.

    Section order (P0-2): Score is the lede; the bias disclosure is collapsed
    and demoted below it, with the scoring methodology last.
    """
    if report.profile is None:
        return ""
    if isinstance(report.profile, StageFailure):
        return _failure_callout_html(report.profile)

    # A whitespace-only canonical_role is falsy for caption purposes — strip
    # before the fallback so a blank LLM value yields detected_role, not a
    # caption suppressed by `_salary_context_line`'s own empty-after-strip check.
    salary_role = (report.profile.canonical_role or "").strip() or report.profile.detected_role
    sections = [
        _score_section_html(report.score, report.profile.seniority_band),
        _salary_section_html(
            report.salary,
            role=salary_role,
            location=report.profile.detected_location,
        ),
        _confidence_section_html(report.confidence),
        _growth_section_html(report.growth),
        _ABOUT_BANNER_HTML,
        _footer_html(report),
    ]
    return "\n".join(s for s in sections if s)


# --------------------------------------------------------------------------- #
# Markdown serializer (portable text archive for the download button).
# --------------------------------------------------------------------------- #


def _score_section_md(score: Score | StageFailure | None, seniority_band: str | None = None) -> str:
    if score is None:
        return ""
    if isinstance(score, StageFailure):
        return "## Score\n\n" + _failure_callout_md(score)

    by_name: dict[str, Component] = {c.name: c for c in score.components}
    surviving = [n for n in _COMPONENT_ORDER if n in by_name]

    band_text = " ".join(seniority_band.split()) if seniority_band else ""
    band = f" ({_md(band_text)})" if band_text else ""
    parts = [f"## Score: {score.total}/100{band}"]
    for name in surviving:
        comp = by_name[name]
        cite = f" — {_md(comp.anchor.section)}" if comp.anchor.section else ""
        parts.append(
            f"### {_COMPONENT_DISPLAY[name]} — {comp.score_0_100}/100\n\n"
            f"{_md(comp.justification)}\n\n"
            f'> "{_md(comp.anchor.quote)}"{cite}'
        )
    body = "\n\n".join(parts)
    if score.dropped:
        names = ", ".join(_COMPONENT_DISPLAY[n] for n in score.dropped)
        body += (
            f"\n\n_Note: {len(score.dropped)} component(s) dropped ({names}): "
            "no anchor verified against CV text._"
        )
    return body


def _salary_context_line_md(role: str | None, location: str | None) -> str:
    """Markdown analogue of `_salary_context_line` (P2.2 download parity).

    Emits an italic `_role · market_` caption above the range so the portable
    archive names the role/market the estimate is anchored to, matching the HTML
    display. Both values are LLM-derived → `_md`. Degrades gracefully: no role →
    no caption; role but no location → role only.
    """
    role_text = _md(role) if role and role.strip() else ""
    if not role_text:
        return ""
    location_text = _md(location) if location and location.strip() else ""
    body = f"{role_text} · {location_text}" if location_text else role_text
    return f"_{body}_"


def _salary_section_md(
    salary: SalaryEstimate | StageFailure | None,
    role: str | None = None,
    location: str | None = None,
) -> str:
    if salary is None:
        return ""
    if isinstance(salary, StageFailure):
        return "## Salary\n\n" + _failure_callout_md(salary)

    context_line = _salary_context_line_md(role, location)
    caption = f"{context_line}\n\n" if context_line else ""
    range_line = (
        f"**{_format_money(salary.low)} – {_format_money(salary.high)} "
        f"{_md(salary.currency)} / {salary.period}**"
    )
    sources_md = "\n".join(_source_line(s) for s in salary.sources) or "_(no sources)_"
    return (
        f"## Salary\n\n{caption}{range_line}\n\n{_md(salary.reasoning)}\n\n"
        f"### Sources\n\n{sources_md}"
    )


def _confidence_section_md(conf: Confidence | StageFailure | None) -> str:
    if conf is None:
        return ""
    if isinstance(conf, StageFailure):
        return "## Confidence\n\n" + _failure_callout_md(conf)
    badge = _CONFIDENCE_BADGE[conf.tier]
    return f"## Confidence\n\n**{badge}**\n\n{_md(conf.rationale)}"


def _growth_section_md(growth: list[GrowthAction] | StageFailure | None) -> str:
    if growth is None:
        return ""
    if isinstance(growth, StageFailure):
        return "## Plan\n\n" + _failure_callout_md(growth)
    if not growth:
        return "## Plan\n\n_(no actions)_"
    items: list[str] = []
    for i, action in enumerate(growth, 1):
        items.append(
            f"{i}. **{_md(action.what)}** _({action.time_horizon_months} months)_\n\n"
            f"   {_md(action.mechanism)}"
        )
    return "## Plan\n\n" + "\n\n".join(items)


def _footer_md(report: Report) -> str:
    weight_rows = "\n".join(
        f"- **{_COMPONENT_DISPLAY[name]}**: {int(weight * 100)}%"
        for name, weight in COMPONENT_WEIGHTS.items()
    )
    totals_line = (
        f"_Total cost: ${report.total_cost_usd:.4f} · "
        f"LLM time (sum): {report.total_latency_ms:,} ms · "
        f"Total elapsed: {report.wall_clock_ms:,} ms_"
    )
    notices = "".join(f"{_md(notice)}\n\n" for notice in report.notices)
    return (
        notices + "## How is this scored?\n\n"
        "Component weights:\n\n"
        f"{weight_rows}\n\n"
        f"{totals_line}\n\n"
        "_LLM time can exceed total elapsed when provider calls run in parallel._"
    )


def render_markdown(report: Report) -> str:
    """Render the report as a clean, portable markdown archive (download button).

    Mirrors `render_html`'s short-circuits and section order, but emits plain
    markdown (headings, `**bold**`, `-` lists, `>` blockquotes) with every
    user-controllable string routed through `_md`. No grid/cards — this is the
    text archive, independent of the on-screen HTML.
    """
    if report.profile is None:
        return ""
    if isinstance(report.profile, StageFailure):
        return _failure_callout_md(report.profile)

    # Mirror render_html's caption anchor: blank canonical_role falls back to
    # detected_role so the markdown salary caption matches the HTML display.
    salary_role = (report.profile.canonical_role or "").strip() or report.profile.detected_role
    sections = [
        _score_section_md(report.score, report.profile.seniority_band),
        _salary_section_md(
            report.salary,
            role=salary_role,
            location=report.profile.detected_location,
        ),
        _confidence_section_md(report.confidence),
        _growth_section_md(report.growth),
        _ABOUT_BANNER_MD,
        _footer_md(report),
    ]
    return "\n\n".join(s for s in sections if s)
