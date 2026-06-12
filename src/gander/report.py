"""L6 report renderer — pure functions producing tracker HTML and body markdown.

The renderer is a pure function of a `Report`. Every yield in the L6 pipeline
re-renders both surfaces from the same model; no UI state lives here.

Status-key mapping (display label -> schema key): the T14 spec listed pill
labels `Parse / Redact / Score / Salary / Plan` and hooks on `statuses["ingest"]`
/ `statuses["redact"]`, but the authoritative `schemas.StageName` literal is
`("profile", "score", "salary", "confidence", "growth")` and the
`_require_exact_status_keys` model validator rejects anything else. Schema wins:
the renderer maps the 5 schema stages to readable labels (`Profile / Score /
Salary / Confidence / Plan`) and treats `report.profile = StageFailure` as the
short-circuit "ingestion failed" case, since profile is the first stage gated
on a successful ingest+redact (PLAN L2). See tasks/T14_dev-plan.md.
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
    "High": "[!] High",
    "Medium": "[~] Medium",
    "Low": "[?] Low",
}

_CSS = """<style>
.tracker {
  display: flex; gap: 0.5rem; flex-wrap: wrap; justify-content: center;
  font-family: system-ui, sans-serif; margin: 0 0 0.75rem 0;
}
.pill {
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.2rem 0.65rem 0.2rem 0.55rem;
  border-radius: 999px;
  border: 1px solid #e4e7ec;
  border-left: 3px solid #d0d5dd;
  background: transparent; color: #475467;
  font-size: 0.8125rem; line-height: 1.25;
  transition: border-color 120ms ease, color 120ms ease;
}
.pill::before { content: attr(data-glyph); font-weight: 600; opacity: 0.75; }
.pill.pending { border-left-color: #d0d5dd; color: #667085; }
.pill.running { border-left-color: #f59e0b; color: #344054; }
.pill.done    { border-left-color: #12b76a; color: #344054; }
.pill.failed  { border-left-color: #f04438; color: #344054; }
.pill.skipped { border-left-color: #d0d5dd; color: #98a2b3; text-decoration: line-through; }
.pill:focus-visible { outline: 2px solid #1d4ed8; outline-offset: 2px; }
.gander-callout {
  border-left: 4px solid #f04438; background: #fef3f2; color: #7a271a;
  padding: 0.5rem 0.75rem; margin: 0.5rem 0; border-radius: 4px;
}
.gander-callout::before { content: "⚠"; margin-right: 0.4rem; }
@media (prefers-reduced-motion: reduce) { .pill { transition: none; } }
.gander-output { padding-inline: 0.75rem; }
.gander-output h2 {
  margin-top: 2.5rem;
  padding-top: 1.25rem;
  border-top: 1px solid #e4e7ec;
  font-size: 1.375rem;
}
.gander-output > h2:first-child,
.gander-output h2:first-of-type {
  border-top: 0;
  padding-top: 0;
  margin-top: 0;
}
.gander-output h3 {
  margin-top: 1.5rem;
  font-size: 1rem;
  color: #475467;
}
.gander-output table.gander-components { border-collapse: collapse; margin: 0.5rem 0; }
.gander-output table.gander-components th,
.gander-output table.gander-components td {
  border: 1px solid #e4e7ec; padding: 0.4rem 0.6rem; text-align: center;
}
.gander-components-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
  margin: 0.75rem 0;
}
.gander-component {
  border: 1px solid #e4e7ec;
  border-radius: 6px;
  padding: 0.75rem 0.9rem;
}
.gander-output .gander-component-head {
  font-size: 0.95rem;
  margin: 0 0 0.25rem;
  color: inherit;
}
.gander-component-score { font-weight: 500; color: #667085; }
.gander-component-just { margin: 0.25rem 0 0.4rem; }
.gander-component-quote {
  margin: 0;
  padding-left: 0.6rem;
  border-left: 2px solid #e4e7ec;
  color: #475467;
  font-size: 0.875rem;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.gander-plan { list-style: decimal; padding-left: 1.25rem; }
.gander-plan li + li { margin-top: 1.25rem; }
.gander-plan-title { margin: 0.15rem 0 0.35rem; font-weight: 500; }
.gander-plan-mech { margin: 0; color: #475467; }
.gander-chip {
  display: inline-block;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.1rem 0.55rem;
  border-radius: 999px;
  border: 1px solid #e4e7ec;
  color: #475467;
  margin-bottom: 0.35rem;
}
.gander-salary-range {
  font-size: 1.5rem;
  font-weight: 600;
  margin: 0.5rem 0 0.75rem;
}
.gander-salary-unit {
  font-size: 0.875rem;
  font-weight: 500;
  color: #667085;
}
@media (max-width: 32rem) {
  .gander-components-grid { grid-template-columns: 1fr; }
}
@media (prefers-color-scheme: dark) {
  .pill {
    border-color: #3f3f46; border-left-color: #52525b;
    color: #a1a1aa; background: transparent;
  }
  .pill.pending { border-left-color: #52525b; color: #a1a1aa; }
  .pill.running { border-left-color: #f59e0b; color: #e4e4e7; }
  .pill.done    { border-left-color: #22c55e; color: #e4e4e7; }
  .pill.failed  { border-left-color: #ef4444; color: #e4e4e7; }
  .pill.skipped { border-left-color: #52525b; color: #71717a; }
  .gander-callout { background: #450a0a; color: #fecaca; border-left-color: #ef4444; }
  .gander-output h2 { border-top-color: #3f3f46; }
  .gander-output h3 { color: #a1a1aa; }
  .gander-output table.gander-components th,
  .gander-output table.gander-components td { border-color: #3f3f46; }
  .gander-component { border-color: #3f3f46; }
  .gander-component-quote { color: #a1a1aa; border-left-color: #3f3f46; }
  .gander-component-score { color: #a1a1aa; }
  .gander-chip { border-color: #3f3f46; color: #d4d4d8; }
  .gander-plan-mech, .gander-salary-unit { color: #a1a1aa; }
}
body.dark .pill {
  border-color: #3f3f46; border-left-color: #52525b;
  color: #a1a1aa; background: transparent;
}
body.dark .pill.pending { border-left-color: #52525b; color: #a1a1aa; }
body.dark .pill.running { border-left-color: #f59e0b; color: #e4e4e7; }
body.dark .pill.done    { border-left-color: #22c55e; color: #e4e4e7; }
body.dark .pill.failed  { border-left-color: #ef4444; color: #e4e4e7; }
body.dark .pill.skipped { border-left-color: #52525b; color: #71717a; }
body.dark .gander-callout { background: #450a0a; color: #fecaca; border-left-color: #ef4444; }
body.dark .gander-output h2 { border-top-color: #3f3f46; }
body.dark .gander-output h3 { color: #a1a1aa; }
body.dark .gander-output table.gander-components th,
body.dark .gander-output table.gander-components td { border-color: #3f3f46; }
body.dark .gander-component { border-color: #3f3f46; }
body.dark .gander-component-quote { color: #a1a1aa; border-left-color: #3f3f46; }
body.dark .gander-component-score { color: #a1a1aa; }
body.dark .gander-chip { border-color: #3f3f46; color: #d4d4d8; }
body.dark .gander-plan-mech, body.dark .gander-salary-unit { color: #a1a1aa; }
</style>"""


# Markdown metacharacters that can break out of an inline context when
# interpolated mid-string. Backslash MUST come first so subsequent escapes are
# not re-escaped. Set chosen to neutralise: `](payload)` link injection,
# `*`/`_` emphasis, backtick code spans, `!` for `![alt](url)` images. Block-
# level metacharacters (`#`, `+`, `-`, `|`, fenced code, table pipes) only
# matter at line-start; `_md` collapses newlines + whitespace runs downstream
# so an LLM-controlled string cannot escape an inline context into a heading,
# list, table, or blockquote.
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

    Use for any user-controllable string flowing into a markdown context
    (callouts, source lines, salary reasoning, confidence rationale, growth
    actions). Content nested inside an HTML block (`<details>`, `<blockquote>`,
    `<p>`) only needs `_esc` — CommonMark does not parse markdown inside HTML.

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


def render_tracker(report: Report) -> str:
    """Render the 5-stage tracker as a `<style>`+`<div>` HTML fragment.

    Reads `report.statuses[stage]` for each schema stage in pipeline order.
    Failed pills carry the originating `StageFailure.user_message` as a
    tooltip; non-failed pills get no tooltip.
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
    return f'{_CSS}\n<div class="tracker" role="status" aria-live="polite">{"".join(pills)}</div>'


# Copy grounded in PRD §4.7 and the README "Decisions"/"Bias And Limits"
# sections — no claims beyond what the system actually does. Keep these in sync
# if the bias posture changes.
_ABOUT_BANNER = (
    "<details open>"
    "<summary>About this report</summary>\n\n"
    "CV screening is classified as high-risk AI under the EU AI Act and is "
    "well documented to encode demographic bias. Read these results as "
    "**candidate hypotheses to validate, not authoritative judgments.**\n\n"
    "- Identifying details (name, contact info, age-implying dates) are "
    "redacted before scoring, which evaluates skills, experience, education, "
    "and role progression.\n"
    "- Some bias-encoding signals — school names, language patterns, employer "
    "prestige — cannot be fully removed without discarding legitimate signal, "
    "so they may still influence the result.\n"
    "- This system is **not validated for fairness across protected groups.**\n\n"
    "</details>"
)


def _about_banner() -> str:
    return _ABOUT_BANNER


def _failure_callout_html(failure: StageFailure) -> str:
    return f'<div class="gander-callout" role="alert">{_esc(failure.user_message)}</div>'


def _failure_callout_md(failure: StageFailure) -> str:
    # Markdown blockquote; the warning glyph is literal U+26A0 per spec.
    # Every line of user_message is prefixed with `> ` so a multi-line message
    # cannot break out of the callout and inject headings/lists below it.
    lines = failure.user_message.splitlines() or [""]
    quoted = [f"> ⚠ {_md(lines[0])}"] + [f"> {_md(line)}" for line in lines[1:]]
    return "\n".join(quoted)


def _score_section(score: Score | StageFailure | None, seniority_band: str | None = None) -> str:
    if score is None:
        return ""
    if isinstance(score, StageFailure):
        return "## Score\n\n" + _failure_callout_md(score)

    # T25: schema allows partial Score (experience-mandatory; others optional).
    # Render only surviving components as always-visible tiles — dropped
    # categories are listed in the footer below so the reviewer sees they were
    # zero-weighted, not omitted.
    by_name: dict[str, Component] = {c.name: c for c in score.components}
    surviving = [n for n in _COMPONENT_ORDER if n in by_name]

    tiles: list[str] = []
    for name in surviving:
        comp = by_name[name]
        quote = _html_inline(comp.anchor.quote)
        quote_title = _esc(" ".join(comp.anchor.quote.split()))
        heading_id = f"gander-score-{name}"
        section = f" <em>({_esc(comp.anchor.section)})</em>" if comp.anchor.section else ""
        tiles.append(
            f'<section class="gander-component" role="listitem" aria-labelledby="{heading_id}">'
            f'<h3 id="{heading_id}" class="gander-component-head">'
            f"{_COMPONENT_DISPLAY[name]} "
            f'<span class="gander-component-score">{comp.score_0_100}/100</span>'
            "</h3>"
            f'<p class="gander-component-just">{_html_inline(comp.justification)}</p>'
            f'<blockquote class="gander-component-quote" title="{quote_title}">"{quote}"'
            f"{section}</blockquote>"
            "</section>"
        )
    grid = '<div class="gander-components-grid" role="list">' + "".join(tiles) + "</div>"

    band = f" ({_esc(seniority_band)})" if seniority_band else ""
    body = f"## Score: {score.total}/100{band}\n\n{grid}"
    if score.dropped:
        # Italic single-line footer naming the dropped categories so the
        # reviewer sees why the total is depressed (drop-as-zero, no re-norm).
        names = ", ".join(_COMPONENT_DISPLAY[n] for n in score.dropped)
        body += (
            f"\n\n_Note: {len(score.dropped)} component(s) dropped ({names}): "
            "no anchor verified against CV text._"
        )
    return body


def _format_money(n: int) -> str:
    return f"{n:,}"


def _source_line(src: Source) -> str:
    # `[{domain}]: "{snippet}"` lives in a markdown context where a literal
    # `]` in domain or `](` in snippet would forge a link target. Route both
    # through `_md` so the brackets/parens stay inert text.
    snippet = _md(src.snippet)
    domain = _md(src.domain)
    return f'- [{domain}]: "{snippet}"'


def _salary_section(salary: SalaryEstimate | StageFailure | None) -> str:
    if salary is None:
        return ""
    if isinstance(salary, StageFailure):
        return "## Salary\n\n" + _failure_callout_md(salary)

    period = salary.period
    range_line = (
        '<p class="gander-salary-range">'
        f"<strong>{_format_money(salary.low)} - {_format_money(salary.high)}</strong> "
        f'<span class="gander-salary-unit">{_esc(salary.currency)} / {period}</span>'
        "</p>"
    )
    sources_md = "\n".join(_source_line(s) for s in salary.sources) or "_(no sources)_"
    return f"## Salary\n\n{range_line}\n\n{_md(salary.reasoning)}\n\n### Sources\n\n{sources_md}"


def _confidence_section(conf: Confidence | StageFailure | None) -> str:
    if conf is None:
        return ""
    if isinstance(conf, StageFailure):
        return "## Confidence\n\n" + _failure_callout_md(conf)
    badge = _CONFIDENCE_BADGE[conf.tier]
    return (
        "## Confidence\n\n"
        f'<p><span class="gander-chip" aria-label="Confidence: {conf.tier}">{badge}</span></p>'
        f"<p>{_html_inline(conf.rationale)}</p>"
    )


def _growth_section(growth: list[GrowthAction] | StageFailure | None) -> str:
    if growth is None:
        return ""
    if isinstance(growth, StageFailure):
        return "## Plan\n\n" + _failure_callout_md(growth)
    if not growth:
        return "## Plan\n\n_(no actions)_"
    lines: list[str] = []
    for action in growth:
        lines.append(
            "<li>"
            f'<span class="gander-chip" aria-label="Time horizon: {action.time_horizon_months} '
            f'months">{action.time_horizon_months} months</span>'
            f'<p class="gander-plan-title">{_html_inline(action.what)}</p>'
            f'<p class="gander-plan-mech">{_html_inline(action.mechanism)}</p>'
            "</li>"
        )
    return '## Plan\n\n<ol class="gander-plan">' + "".join(lines) + "</ol>"


def _footer(report: Report) -> str:
    weight_rows = "\n".join(
        f"- **{_COMPONENT_DISPLAY[name]}**: {int(weight * 100)}%"
        for name, weight in COMPONENT_WEIGHTS.items()
    )
    # Format with 4 decimals on cost; latency is rendered in ms so the reviewer
    # can compare to the 60s budget without unit conversion.
    totals_line = (
        f"_Total cost: ${report.total_cost_usd:.4f} · "
        f"LLM time (sum): {report.total_latency_ms:,} ms · "
        f"Total elapsed: {report.wall_clock_ms:,} ms_"
    )
    notices = "".join(
        f'<p class="gander-report-notice">{_html_inline(notice)}</p>' for notice in report.notices
    )
    return (
        notices + "<details>"
        "<summary>How is this scored?</summary>\n\n"
        "Component weights:\n\n"
        f"{weight_rows}\n\n"
        f"{totals_line}\n\n"
        "_LLM time can exceed total elapsed when provider calls run in parallel._\n\n"
        "</details>"
    )


def render_body(report: Report) -> str:
    """Render the report body as a markdown+HTML string.

    Top-level short-circuit: when `report.profile` is a `StageFailure`, returns
    ONLY the failure callout — the rest of the pipeline depends on profile, so
    rendering downstream blocks would be misleading. When `report.profile is
    None` (T15 pipeline initial state, before profile extraction completes),
    returns an empty string — the tracker carries the pending state.
    Stage failures further down render inline as warning callouts and the rest
    of the body continues.
    """
    if report.profile is None:
        return ""
    if isinstance(report.profile, StageFailure):
        return _failure_callout_html(report.profile)

    sections = [
        _about_banner(),
        _score_section(report.score, report.profile.seniority_band),
        _salary_section(report.salary),
        _confidence_section(report.confidence),
        _growth_section(report.growth),
        _footer(report),
    ]
    # Filter out empty sections so back-to-back blank lines don't accumulate
    # when intermediate blocks are still None.
    return "\n\n".join(s for s in sections if s)
