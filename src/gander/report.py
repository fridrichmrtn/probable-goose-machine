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

# Order matters: leftmost component renders <details open> so the reviewer
# sees one verified quote on first paint.
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
  display: flex; gap: 0.5rem; flex-wrap: wrap;
  font-family: system-ui, sans-serif; margin: 0 0 0.75rem 0;
}
.pill {
  display: inline-flex; align-items: center; gap: 0.35rem;
  padding: 0.25rem 0.7rem; border-radius: 999px;
  border: 1px solid #d0d5dd; background: #f5f7fa; color: #344054;
  font-size: 0.875rem; line-height: 1.2;
  transition: background-color 120ms ease, border-color 120ms ease, color 120ms ease;
}
.pill::before { content: attr(data-glyph); font-weight: 600; }
.pill.pending { background: #f5f7fa; border-color: #d0d5dd; color: #667085; }
.pill.running { background: #fff4e5; border-color: #f5a524; color: #7a4a00; }
.pill.done { background: #ecfdf3; border-color: #12b76a; color: #027a48; }
.pill.failed { background: #fef3f2; border-color: #f04438; color: #b42318; }
.pill.skipped {
  background: #f5f7fa; border-color: #d0d5dd; color: #98a2b3;
  text-decoration: line-through;
}
.pill:focus-visible { outline: 2px solid #1d4ed8; outline-offset: 2px; }
.gander-callout {
  border-left: 4px solid #f04438; background: #fef3f2; color: #7a271a;
  padding: 0.5rem 0.75rem; margin: 0.5rem 0; border-radius: 4px;
}
.gander-callout::before { content: "⚠"; margin-right: 0.4rem; }
@media (prefers-reduced-motion: reduce) { .pill { transition: none; } }
.gander-output {
  max-width: 72ch; margin-inline: auto;
}
.gander-output table {
  border-collapse: collapse; margin: 0.5rem 0;
}
.gander-output th, .gander-output td {
  border: 1px solid #e4e7ec; padding: 0.4rem 0.6rem; text-align: center;
}
@media (prefers-color-scheme: dark) {
  .pill { background: #1f1f23; border-color: #3f3f46; color: #d4d4d8; }
  .pill.pending { background: #1f1f23; border-color: #3f3f46; color: #a1a1aa; }
  .pill.running { background: #422006; border-color: #f59e0b; color: #fbbf24; }
  .pill.done    { background: #052e16; border-color: #22c55e; color: #4ade80; }
  .pill.failed  { background: #450a0a; border-color: #ef4444; color: #fca5a5; }
  .pill.skipped { background: #1f1f23; border-color: #3f3f46; color: #71717a; }
  .gander-callout { background: #450a0a; color: #fecaca; border-left-color: #ef4444; }
  .gander-output th, .gander-output td { border-color: #3f3f46; }
}
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
        pills.append(_pill_html(_LABEL_BY_STAGE[stage], status, tooltip))
    return f'{_CSS}\n<div class="tracker" role="status" aria-live="polite">{"".join(pills)}</div>'


def _failure_callout_html(failure: StageFailure) -> str:
    return f'<div class="gander-callout" role="alert">{_esc(failure.user_message)}</div>'


def _failure_callout_md(failure: StageFailure) -> str:
    # Markdown blockquote; the warning glyph is literal U+26A0 per spec.
    # Every line of user_message is prefixed with `> ` so a multi-line message
    # cannot break out of the callout and inject headings/lists below it.
    lines = failure.user_message.splitlines() or [""]
    quoted = [f"> ⚠ {_md(lines[0])}"] + [f"> {_md(line)}" for line in lines[1:]]
    return "\n".join(quoted)


def _score_section(score: Score | StageFailure | None) -> str:
    if score is None:
        return ""
    if isinstance(score, StageFailure):
        return "## Score\n\n" + _failure_callout_md(score)

    # Build component lookup; schema guarantees one component per category.
    by_name: dict[str, Component] = {c.name: c for c in score.components}
    headers = "".join(f"<th>{_COMPONENT_DISPLAY[n]}</th>" for n in _COMPONENT_ORDER)
    cells = "".join(f"<td>{by_name[n].score_0_100}</td>" for n in _COMPONENT_ORDER)
    table = (
        '<table class="gander-components">'
        f"<thead><tr>{headers}</tr></thead>"
        f"<tbody><tr>{cells}</tr></tbody>"
        "</table>"
    )

    details_blocks: list[str] = []
    for idx, name in enumerate(_COMPONENT_ORDER):
        comp = by_name[name]
        open_attr = " open" if idx == 0 else ""
        quote = _esc(comp.anchor.quote)
        section = f" <em>({_esc(comp.anchor.section)})</em>" if comp.anchor.section else ""
        details_blocks.append(
            f"<details{open_attr}>"
            f"<summary>{_COMPONENT_DISPLAY[name]}: {comp.score_0_100}/100</summary>"
            f"<p>{_esc(comp.justification)}</p>"
            f"<blockquote>“{quote}”{section}</blockquote>"
            "</details>"
        )

    return f"## Score: {score.total}/100\n\n{table}\n\n" + "\n".join(details_blocks)


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
        f"**{_format_money(salary.low)} – {_format_money(salary.high)} "
        f"{_md(salary.currency)} / {period}**"
    )
    sources_md = "\n".join(_source_line(s) for s in salary.sources) or "_(no sources)_"
    return f"## Salary\n\n{range_line}\n\n{_md(salary.reasoning)}\n\n### Sources\n\n{sources_md}"


def _confidence_section(conf: Confidence | StageFailure | None) -> str:
    if conf is None:
        return ""
    if isinstance(conf, StageFailure):
        return "## Confidence\n\n" + _failure_callout_md(conf)
    badge = _CONFIDENCE_BADGE[conf.tier]
    return f"## Confidence\n\n**{badge}**: {_md(conf.rationale)}"


def _growth_section(growth: list[GrowthAction] | StageFailure | None) -> str:
    if growth is None:
        return ""
    if isinstance(growth, StageFailure):
        return "## Plan\n\n" + _failure_callout_md(growth)
    if not growth:
        return "## Plan\n\n_(no actions)_"
    lines: list[str] = []
    for idx, action in enumerate(growth, start=1):
        # Literal asterisks per spec: **What** *(N months)*: Mechanism.
        lines.append(
            f"{idx}. **{_md(action.what)}** "
            f"*({action.time_horizon_months} months)*: "
            f"{_md(action.mechanism)}"
        )
    return "## Plan\n\n" + "\n".join(lines)


def _footer(report: Report) -> str:
    weight_rows = "\n".join(
        f"- **{_COMPONENT_DISPLAY[name]}**: {int(weight * 100)}%"
        for name, weight in COMPONENT_WEIGHTS.items()
    )
    # Format with 4 decimals on cost (covers the 1e-4 USD floor of cheap-model
    # MiniMax calls); latency rendered in ms so the reviewer can compare to the
    # 60s budget without unit conversion.
    totals_line = (
        f"_Total cost: ${report.total_cost_usd:.4f} · "
        f"Total latency: {report.total_latency_ms:,} ms_"
    )
    return (
        "<details>"
        "<summary>How is this scored?</summary>\n\n"
        "Component weights:\n\n"
        f"{weight_rows}\n\n"
        f"{totals_line}\n\n"
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
        _score_section(report.score),
        _salary_section(report.salary),
        _confidence_section(report.confidence),
        _growth_section(report.growth),
        _footer(report),
    ]
    # Filter out empty sections so back-to-back blank lines don't accumulate
    # when intermediate blocks are still None.
    return "\n\n".join(s for s in sections if s)
