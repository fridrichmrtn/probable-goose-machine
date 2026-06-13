"""Tests for the report-download artifact lifecycle in `app._write_report_md`.

Importing `app` builds the Gradio Blocks and runs the module-scope `check_env()`
gate, so the skip flag is set *before* the import. No unit test imports `app`
otherwise, so this file owns that coupling.
"""

from __future__ import annotations

import os

os.environ.setdefault("GANDER_SKIP_ENV_CHECK", "1")

from pathlib import Path  # noqa: E402  (import after the env flag is set)

import app  # noqa: E402
import pytest  # noqa: E402

pytestmark = pytest.mark.fast


def test_write_report_md_roundtrips_body(monkeypatch: pytest.MonkeyPatch) -> None:
    # The artifact holds exactly the pre-rendered body it was handed — no
    # re-render — so the download matches what streamed on screen.
    monkeypatch.setattr(app, "_last_report_path", None)
    path = app._write_report_md("# Report\n\nbody text")
    try:
        assert Path(path).read_text(encoding="utf-8") == "# Report\n\nbody text"
        assert path.endswith(".md")
    finally:
        Path(path).unlink(missing_ok=True)


def test_write_report_md_unlinks_previous_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    # /tmp must not grow one file per run: writing a new artifact unlinks the
    # prior one, while the just-written file survives for the download click.
    monkeypatch.setattr(app, "_last_report_path", None)
    first = app._write_report_md("first")
    assert Path(first).exists()
    second = app._write_report_md("second")
    try:
        assert not Path(first).exists()  # previous cleaned up
        assert Path(second).read_text(encoding="utf-8") == "second"  # current intact
    finally:
        Path(second).unlink(missing_ok=True)


def test_write_report_md_survives_unlinkable_previous(monkeypatch: pytest.MonkeyPatch) -> None:
    # Best-effort cleanup: if the prior path is already gone, the new write still
    # succeeds (the OSError from unlink is swallowed, not propagated).
    monkeypatch.setattr(app, "_last_report_path", "/nonexistent/gander-report-gone.md")
    path = app._write_report_md("body")
    try:
        assert Path(path).read_text(encoding="utf-8") == "body"
    finally:
        Path(path).unlink(missing_ok=True)
