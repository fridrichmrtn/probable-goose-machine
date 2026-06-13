"""WCAG contrast guards for the colour pairs fixed in P2.1.

Pure-Python relative-luminance math (WCAG 2.x SC 1.4.3) so the contrast of the
disabled-button and skipped-pill colours is regression-checked locally without a
browser. Each test also asserts the exact hex pair is wired into the CSS source,
so changing the CSS colour without re-checking contrast fails here.
"""

from __future__ import annotations

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
    # The pair is actually wired into the disabled-button rule.
    assert f"color: {fg}" in _APP_CSS
    assert f"background: {bg}" in _APP_CSS


@pytest.mark.fast
def test_skipped_pill_meets_aa() -> None:
    # Pill background is transparent; in light mode it composites over white.
    fg, bg = "#667085", "#ffffff"
    assert _contrast_ratio(fg, bg) >= _AA_NORMAL
    assert ".pill.skipped" in _REPORT_PY
    assert f"color: {fg}" in _REPORT_PY
