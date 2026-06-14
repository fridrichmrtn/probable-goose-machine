"""WCAG contrast guards for the colour pairs fixed in P2.1.

Pure-Python relative-luminance math (WCAG 2.x SC 1.4.3) so the contrast of the
disabled-button and skipped-pill colours is regression-checked locally without a
browser. Each test also asserts the exact hex pair is wired into the CSS source,
so changing the CSS colour without re-checking contrast fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_APP_CSS = (_REPO_ROOT / "app.py").read_text(encoding="utf-8")
_REPORT_PY = (_REPO_ROOT / "src" / "gander" / "report.py").read_text(encoding="utf-8")

# WCAG AA minimum for normal-size text.
_AA_NORMAL = 4.5


def _channel(c: int) -> float:
    s = c / 255
    return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4


def _relative_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def _contrast_ratio(fg: str, bg: str) -> float:
    lighter, darker = sorted((_relative_luminance(fg), _relative_luminance(bg)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _resolve_light_token(css: str, name: str) -> str:
    """Resolve a CSS custom property from the light `:root` block.

    The light `:root { … }` is the first one in the stylesheet; dark overrides
    live in the later `body.dark` block (the single dark-theme source), so the
    first match is the light value the math composites over white.
    """
    root = re.search(r":root\s*\{([^}]*)\}", css)
    assert root is not None, "no :root block found"
    m = re.search(rf"{re.escape(name)}:\s*(#[0-9a-fA-F]{{6}})", root.group(1))
    assert m is not None, f"{name} not defined in light :root"
    return m.group(1)


@pytest.mark.fast
def test_contrast_helper_matches_known_reference() -> None:
    # Black on white is the canonical 21:1 reference.
    assert round(_contrast_ratio("#000000", "#ffffff"), 1) == 21.0
    # The old failing disabled-button pair, as documentation of what we replaced.
    assert _contrast_ratio("#ffffff", "#fdba74") < 2.0


@pytest.mark.fast
def test_light_disabled_button_meets_aa() -> None:
    fg, bg = "#7c2d12", "#fed7aa"
    assert _contrast_ratio(fg, bg) >= _AA_NORMAL
    # Scope to the *light* disabled-button rule block specifically. The dark
    # rules reuse these same two hexes inverted (#7c2d12 background, #fed7aa
    # text), so an unscoped substring check would pass on the wrong rule. The
    # light block is the only `:disabled` selector anchored at column 0.
    m = re.search(r"^button\.primary:disabled,.*?\{(.*?)\}", _APP_CSS, re.MULTILINE | re.DOTALL)
    assert m is not None
    block = m.group(1)
    assert f"color: {fg}" in block
    assert f"background: {bg}" in block


@pytest.mark.fast
def test_skipped_pill_meets_aa() -> None:
    # The skipped/pending pill colour is token-driven (`var(--g-fg-subtle)`), so
    # resolve the token from the light :root and check the *resolved* value. Pill
    # background is transparent; in light mode it composites over white.
    fg = _resolve_light_token(_REPORT_PY, "--g-fg-subtle")
    bg = "#ffffff"
    assert _contrast_ratio(fg, bg) >= _AA_NORMAL
    # Scope to the `.pill.skipped` rule block and assert it follows the token.
    # Hardcoding a hex here (bypassing the token) would slip past the resolved
    # contrast check above, so require the `var(--g-fg-subtle)` reference; any
    # token change is then re-checked through _resolve_light_token + the ratio.
    m = re.search(r"\.pill\.skipped\s*\{([^}]*)\}", _REPORT_PY)
    assert m is not None
    assert "color: var(--g-fg-subtle)" in m.group(1)


def _fg_on_light_page_under_os_dark(css: str) -> str:
    """`--g-fg` as it computes on a LIGHT Gradio page while the OS prefers dark.

    `report.STYLE` only ever renders inside Gradio, whose rendered theme is the
    `body.dark` class. A light page has no `body.dark`, so the text colour must
    resolve to the light `:root` value even under a dark OS. If a second,
    OS-keyed `@media (prefers-color-scheme: dark) :root` override exists it wins
    on a light page (equal `:root` specificity, later in source) and washes the
    text out. So: return that override if present, else the light value.
    """
    light = _resolve_light_token(css, "--g-fg")
    media = re.search(r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*:root\s*\{([^}]*)\}", css)
    if media:
        inner = re.search(r"--g-fg:\s*(#[0-9a-fA-F]{6})", media.group(1))
        if inner:
            return inner.group(1)
    return light


@pytest.mark.fast
def test_hero_text_readable_on_light_page_under_os_dark() -> None:
    """Dark-OS viewer of a LIGHT Gradio page still gets dark-on-light text.

    Regression for PR #46: the hero/report consumed `--g-fg`, but an OS-keyed
    `@media (prefers-color-scheme: dark)` copy of the tokens flipped `--g-fg` to
    near-white whenever the OS preferred dark — even while Gradio rendered the
    light page — leaving washed-out text on a light background. The fix makes
    `body.dark` the single dark-theme source; this guards the mismatched quadrant.
    """
    fg = _fg_on_light_page_under_os_dark(_REPORT_PY)
    surface = _resolve_light_token(_REPORT_PY, "--g-surface")  # light page background
    assert _contrast_ratio(fg, surface) >= _AA_NORMAL, (
        f"--g-fg resolves to {fg} on a light page under OS-dark — unreadable over {surface}"
    )


@pytest.mark.fast
def test_report_dark_theme_is_single_source() -> None:
    """The report's dark tokens live only under `body.dark`, never an OS media query.

    A second, OS-keyed signal (`@media (prefers-color-scheme: dark)`) desyncs from
    Gradio's rendered theme on the light-page/dark-OS quadrant. Lock the single
    source in so the dual-signal model cannot silently return.
    """
    assert "@media (prefers-color-scheme: dark)" not in _REPORT_PY, (
        "report.STYLE must not redefine --g-* tokens via prefers-color-scheme; "
        "body.dark is the single dark-theme source"
    )
    body_dark = re.search(r"body\.dark\s*\{([^}]*)\}", _REPORT_PY)
    assert body_dark is not None and "--g-fg: #f4f4f5" in body_dark.group(1), (
        "body.dark must carry the dark --g-fg token (the one remaining dark source)"
    )
