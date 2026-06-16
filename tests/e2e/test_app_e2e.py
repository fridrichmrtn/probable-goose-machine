"""Browser e2e tests for the Gander Gradio UI.

All tests are sync (not async) to avoid conflicts between pytest-asyncio's
event loop and the Gradio server thread. The `page` fixture from
pytest-playwright is synchronous; the Gradio server runs in its own thread
launched by `demo.launch(prevent_thread_lock=True)`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests._fakes import _LONG_EVIDENCE_QUOTE

pytestmark = pytest.mark.e2e

# Generous timeout for the full pipeline streaming run. Stages each sleep 50ms
# (e2e_delays=True in conftest), so the full run takes ~350ms; 30s leaves
# ample headroom for SSE delivery latency and DOM update cycles.
_STREAM_TIMEOUT = 30_000  # ms


def test_page_loads(page: Page, live_app_url: str) -> None:
    """The page renders the hero heading, tagline, and file upload control."""
    page.goto(live_app_url)

    # Hero heading and tagline from _HERO_HTML in app.py.
    expect(page.get_by_role("heading", name="Gander")).to_be_visible()
    expect(page.get_by_text("Take a closer look at any CV.")).to_be_visible()

    # The file input is present (Gradio renders it inside a label).
    expect(page.locator("input[type=file]")).to_be_attached()


def test_analyze_button_gating(page: Page, live_app_url: str, cv_fixture_path: Path) -> None:
    """Analyze CV is disabled until a file is chosen, then becomes enabled."""
    page.goto(live_app_url)

    analyze_btn = page.get_by_role("button", name="Analyze CV")
    expect(analyze_btn).to_be_disabled()

    # Set the file on the hidden <input type=file> inside the gr.File component.
    page.locator("input[type=file]").set_input_files(str(cv_fixture_path))

    expect(analyze_btn).to_be_enabled(timeout=5_000)


def test_happy_path(page: Page, live_app_url: str, cv_fixture_path: Path) -> None:
    """End-to-end: upload a CV, run analysis, verify all report sections render."""
    page.goto(live_app_url)

    page.locator("input[type=file]").set_input_files(str(cv_fixture_path))
    expect(page.get_by_role("button", name="Analyze CV")).to_be_enabled(timeout=5_000)
    page.get_by_role("button", name="Analyze CV").click()

    # Wait for the score number to appear — signals the full report is rendered.
    expect(page.locator(".gander-score-num")).to_be_visible(timeout=_STREAM_TIMEOUT)

    # Component cards.
    expect(page.locator(".gander-component").first).to_be_visible(timeout=_STREAM_TIMEOUT)

    # The FULL multi-sentence evidence quote must appear verbatim — no truncation.
    # _LONG_EVIDENCE_QUOTE is the exact string from fake_score(); using has_text
    # with the full value proves the renderer emits the complete quote, not a
    # truncated version.
    expect(page.locator(".gander-component-quote", has_text=_LONG_EVIDENCE_QUOTE)).to_be_visible(
        timeout=_STREAM_TIMEOUT
    )

    # Salary range.
    expect(page.locator(".gander-salary-range")).to_be_visible(timeout=_STREAM_TIMEOUT)

    # Confidence chip.
    expect(page.locator(".gander-chip").first).to_be_visible(timeout=_STREAM_TIMEOUT)

    # Growth plan list (growth runs concurrently with confidence; wait with full timeout).
    expect(page.locator(".gander-plan")).to_be_visible(timeout=_STREAM_TIMEOUT)

    # About disclosure is present and CLOSED (no `open` attribute).
    about = page.locator("details.gander-about")
    expect(about).to_be_attached(timeout=_STREAM_TIMEOUT)
    assert about.get_attribute("open") is None, "About disclosure must be collapsed by default"

    # Download button becomes visible after the run completes.
    expect(page.get_by_role("button", name="Download report (.md)")).to_be_visible(
        timeout=_STREAM_TIMEOUT
    )


def test_structure_regression(page: Page, live_app_url: str, cv_fixture_path: Path) -> None:
    """Report body renders as real DOM nodes, not escaped HTML text, and CSS is applied.

    Guards against a regression where the HTML output was escaped and shown as
    literal tag text, or where the global stylesheet was not injected so class
    rules had no effect.
    """
    page.goto(live_app_url)

    page.locator("input[type=file]").set_input_files(str(cv_fixture_path))
    expect(page.get_by_role("button", name="Analyze CV")).to_be_enabled(timeout=5_000)
    page.get_by_role("button", name="Analyze CV").click()

    expect(page.locator(".gander-score-num")).to_be_visible(timeout=_STREAM_TIMEOUT)

    # The score number and component cards must exist as real DOM elements.
    assert page.locator(".gander-score-num").count() >= 1, (
        ".gander-score-num not found as a DOM node — HTML may have been escaped"
    )
    assert page.locator(".gander-component").count() >= 1, (
        ".gander-component not found as a DOM node"
    )

    # The global STYLE sets `.gander-score-num { font-size: 3rem }`.
    # 3rem at the browser default of 16px = 48px. Assert >= 32px to give a
    # generous margin for zoom/density differences while still catching
    # a "font-size: initial" regression (which would be ~16px).
    raw_font_size: str = page.eval_on_selector(
        ".gander-score-num",
        "el => getComputedStyle(el).fontSize",
    )
    # raw_font_size is a string like "48px"
    assert raw_font_size.endswith("px"), f"Unexpected font-size unit: {raw_font_size!r}"
    font_size_px = float(raw_font_size.removesuffix("px"))
    assert font_size_px >= 32, (
        f".gander-score-num computed font-size is {raw_font_size!r} "
        f"(expected >= 32px); STYLE may not be applied"
    )


def test_plan_paragraphs_render_as_blocks(
    page: Page, live_app_url: str, cv_fixture_path: Path
) -> None:
    """Plan action title and mechanism stack as separate lines, not one inline run.

    Regression guard: Gradio's bundled prose CSS ships
    `.prose li > p, .prose ul > p { display: inline }`. Because the report renders
    inside that `.prose` container, plan paragraphs placed as direct `li > p`
    children collapsed to a single inline run ("…inference.Transitioning…"). The
    fix wraps each <li>'s content in a block <div> so the selector no longer
    matches. This asserts the *computed* display, which only a browser can prove —
    unit tests check the markup but not Gradio's cascade.
    """
    page.goto(live_app_url)
    page.locator("input[type=file]").set_input_files(str(cv_fixture_path))
    expect(page.get_by_role("button", name="Analyze CV")).to_be_enabled(timeout=5_000)
    page.get_by_role("button", name="Analyze CV").click()

    expect(page.locator(".gander-plan")).to_be_visible(timeout=_STREAM_TIMEOUT)

    for selector in (".gander-plan-title", ".gander-plan-mech"):
        display = page.eval_on_selector(selector, "el => getComputedStyle(el).display")
        assert display == "block", (
            f"{selector} computed display is {display!r} (expected 'block'); "
            "Gradio's `.prose li > p` inline reset may be collapsing plan paragraphs"
        )

    # Title and mechanism must occupy different vertical positions (not the same line).
    title_box = page.locator(".gander-plan-title").first.bounding_box()
    mech_box = page.locator(".gander-plan-mech").first.bounding_box()
    assert title_box is not None and mech_box is not None
    assert mech_box["y"] >= title_box["y"] + title_box["height"] - 1.0, (
        f"plan mechanism does not sit below its title: title={title_box}, mech={mech_box}"
    )

    # Numbering fix: each step is numbered by a CSS counter pinned to
    # `.gander-plan-item::before`, NOT the native <ol> marker — which sits in the
    # list's outside gutter, detaches from the block wrapper, and floats above the
    # text. Suppressing it requires `.gander-output ol.gander-plan` (0,2,1 — plain
    # `ol.gander-plan` is only 0,1,1) to match and out-order Gradio's
    # `.prose ol { list-style: decimal }`. Only a browser proves this cascade.
    list_style = page.eval_on_selector("ol.gander-plan", "el => getComputedStyle(el).listStyleType")
    assert list_style == "none", (
        f"ol.gander-plan computed list-style-type is {list_style!r} (expected 'none'); "
        "Gradio's `.prose ol` decimal marker may be re-floating the step number"
    )
    step_content = page.eval_on_selector(
        ".gander-plan-item", "el => getComputedStyle(el, '::before').content"
    )
    assert step_content not in ("", "none", "normal", None), (
        f"plan step ::before generated content is {step_content!r} "
        "(expected the step counter); the numeral may not be rendering"
    )


def test_report_typography_uses_design_tokens(
    page: Page, live_app_url: str, cv_fixture_path: Path
) -> None:
    """The report's type tokens AND heading layout win over Gradio's `.prose`.

    The report renders inside Gradio's `.prose` container, whose `.prose h2`,
    `.prose h3`, and `.prose blockquote` rules out-specify our single-class design
    tokens. Symptoms this guards against:
      - the "Overall score" eyebrow (an <h2 class="gander-score-label">) rendered at
        ~22px instead of the intended 0.8rem (~12.8px) — the most visible break;
      - section <h2>/<h3> ignored the type scale (22px / 16px vs 20px / 14.4px);
      - heading *layout* leaked too: `.prose h2`/`.prose h3` forced 16px/8px margins
        onto the score eyebrow (meant to hug the score) and component-card headings
        (meant to have no extra space), and the <h2> divider lost its token spacing;
      - the short-quote <blockquote> picked up prose's 5px border, 8px padding and a
        `!important` 24px margin, so it looked nothing like the long-quote <span>.

    These are computed-style facts only a browser proves — unit tests see the markup
    but not Gradio's cascade. Font-size thresholds are derived from the live root
    font-size so they stay valid if the base rem size changes (tokens are in `rem`).
    """
    page.goto(live_app_url)
    page.locator("input[type=file]").set_input_files(str(cv_fixture_path))
    expect(page.get_by_role("button", name="Analyze CV")).to_be_enabled(timeout=5_000)
    page.get_by_role("button", name="Analyze CV").click()
    expect(page.locator(".gander-score-num")).to_be_visible(timeout=_STREAM_TIMEOUT)

    # Tokens are defined in rem, so derive expected px from the live root font-size
    # rather than hardcoding — keeps the guard valid if the base rem size changes.
    root_px: float = page.evaluate(
        "() => parseFloat(getComputedStyle(document.documentElement).fontSize)"
    )

    def font_px(selector: str) -> float:
        raw: str = page.eval_on_selector(selector, "el => getComputedStyle(el).fontSize")
        return float(raw.removesuffix("px"))

    # Eyebrow label: token --g-text-xs is 0.8rem. The regression rendered it at ~22px
    # (prose h2). Allow a little headroom below the next token up (--g-text-sm 0.9rem).
    label_px = font_px(".gander-score-label")
    assert label_px <= 0.85 * root_px, (
        f".gander-score-label is {label_px}px (expected ~{0.8 * root_px:.1f}px, "
        f"token 0.8rem); Gradio's `.prose h2` font-size may be overriding the token"
    )

    # Section heading token --g-text-lg is 1.25rem; the prose override pushed it
    # to ~22px (1.375rem). Assert it stays at/below the token, with px tolerance.
    h2_px = font_px(".gander-h2")
    assert h2_px <= 1.25 * root_px + 1.0, (
        f".gander-h2 is {h2_px}px (expected ~{1.25 * root_px:.1f}px, token 1.25rem); "
        "prose h2 override"
    )

    # Heading layout must use the report's tokens, not prose's 16px/8px margins.
    def box_metrics(selector: str) -> dict[str, float]:
        return page.eval_on_selector(
            selector,
            "el => { const c = getComputedStyle(el); return {"
            "mt: parseFloat(c.marginTop), mb: parseFloat(c.marginBottom),"
            "pt: parseFloat(c.paddingTop)}; }",
        )

    # Score eyebrow: margin 0 (hugs the score). Regression was margin-top 16px.
    label_m = box_metrics(".gander-score-label")
    assert label_m["mt"] <= 1.0 and label_m["mb"] <= 1.0, (
        f".gander-score-label margins are {label_m} (expected ~0); "
        "Gradio's `.prose h2` margin may be pushing the eyebrow off the score"
    )

    # Component-card heading: margin 0 (no extra space in the card). Regression 16/8.
    name_m = box_metrics(".gander-component-name")
    assert name_m["mt"] <= 1.0 and name_m["mb"] <= 1.0, (
        f".gander-component-name margins are {name_m} (expected ~0); "
        "Gradio's `.prose h3` margin may be padding out the card heading"
    )

    # Section <h2> divider: token spacing margin 2rem top / padding-top 1.25rem.
    h2_m = box_metrics(".gander-h2")
    assert abs(h2_m["mt"] - 2.0 * root_px) <= 1.0, (
        f".gander-h2 margin-top is {h2_m['mt']}px (expected ~{2.0 * root_px:.1f}px, "
        "token 2rem); prose h2 16px margin may be overriding it"
    )
    assert abs(h2_m["pt"] - 1.25 * root_px) <= 1.0, (
        f".gander-h2 padding-top is {h2_m['pt']}px (expected ~{1.25 * root_px:.1f}px, "
        "token 1.25rem)"
    )

    # Short-quote <blockquote> must match the long-quote <span>: 3px border, 0 margin.
    # `.prose blockquote` sets a 5px border and a `!important` 24px margin.
    bq = page.locator("blockquote.gander-component-quote").first
    metrics = bq.evaluate(
        "el => { const c = getComputedStyle(el); return {"
        "mt: parseFloat(c.marginTop), border: parseFloat(c.borderLeftWidth)}; }"
    )
    assert metrics["mt"] <= 1.0, (
        f"blockquote quote margin-top is {metrics['mt']}px (expected 0); "
        "Gradio's `.prose blockquote` `!important` margin may be leaking through"
    )
    assert abs(metrics["border"] - 3.0) <= 0.5, (
        f"blockquote quote border-left is {metrics['border']}px (expected 3px); "
        "Gradio's `.prose blockquote` 5px border may be overriding the token"
    )


def test_action_buttons_aligned(page: Page, live_app_url: str, cv_fixture_path: Path) -> None:
    """Analyze CV and Cancel share the same baseline and height during a run.

    Regression guard for an 8px vertical offset: a global
    `button.primary { margin-top: 0.5rem }` rule pushed the primary Analyze CV
    button down while the secondary Cancel button stayed at the row top. Fixed by
    moving the spacing onto the action row (.gander-actions) and centering it.
    """
    page.goto(live_app_url)
    page.locator("input[type=file]").set_input_files(str(cv_fixture_path))
    expect(page.get_by_role("button", name="Analyze CV")).to_be_enabled(timeout=5_000)
    page.get_by_role("button", name="Analyze CV").click()

    # Cancel is visible only while the pipeline streams; read both boxes then.
    cancel = page.get_by_role("button", name="Cancel")
    expect(cancel).to_be_visible(timeout=_STREAM_TIMEOUT)
    analyze_box = page.get_by_role("button", name="Analyze CV").bounding_box()
    cancel_box = cancel.bounding_box()
    assert analyze_box is not None and cancel_box is not None

    assert abs(analyze_box["y"] - cancel_box["y"]) <= 1.0, (
        f"Action buttons vertically misaligned: Analyze y={analyze_box['y']}, "
        f"Cancel y={cancel_box['y']}"
    )
    assert abs(analyze_box["height"] - cancel_box["height"]) <= 1.0, (
        f"Action buttons differ in height: {analyze_box['height']} vs {cancel_box['height']}"
    )


def test_long_evidence_clamps_and_expands(
    page: Page, live_app_url: str, cv_fixture_path: Path
) -> None:
    """A long evidence quote is visually clamped behind a disclosure that reveals
    the full text on click. The full quote is always in the DOM (no truncation);
    only the *visual* height is clamped, so cards stay uniform. This is the only
    place the clamp CSS is actually exercised (unit tests don't run a browser).
    """
    page.goto(live_app_url)
    page.locator("input[type=file]").set_input_files(str(cv_fixture_path))
    expect(page.get_by_role("button", name="Analyze CV")).to_be_enabled(timeout=5_000)
    page.get_by_role("button", name="Analyze CV").click()

    # Only the long Skills quote (from _LONG_EVIDENCE_QUOTE) exceeds the clamp
    # threshold, so exactly one disclosure renders, collapsed by default.
    details = page.locator("details.gander-evidence")
    expect(details).to_be_attached(timeout=_STREAM_TIMEOUT)
    assert details.count() == 1, f"expected one evidence disclosure, got {details.count()}"
    assert details.get_attribute("open") is None, "evidence disclosure must start collapsed"

    # The full quote text is present in the DOM even while visually clamped.
    quote = details.locator(".gander-component-quote")
    expect(quote).to_contain_text(_LONG_EVIDENCE_QUOTE)

    # Collapsed: content overflows its clamped box (rendered height < full height).
    collapsed = quote.evaluate("el => ({client: el.clientHeight, scroll: el.scrollHeight})")
    assert collapsed["scroll"] > collapsed["client"] + 4, (
        f"expected a clamped quote (scrollHeight > clientHeight), got {collapsed}"
    )

    # Expand via the summary; the box grows to show the full quote with no overflow.
    details.locator("summary").click()
    expect(details).to_have_attribute("open", "")
    expanded = quote.evaluate("el => ({client: el.clientHeight, scroll: el.scrollHeight})")
    assert expanded["client"] > collapsed["client"], (
        f"expanded quote should be taller than collapsed: {expanded} vs {collapsed}"
    )
    assert expanded["scroll"] <= expanded["client"] + 4, (
        f"expanded quote should not overflow: {expanded}"
    )
