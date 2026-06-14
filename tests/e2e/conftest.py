"""Conftest for browser e2e tests.

GANDER_SKIP_ENV_CHECK is set at module top, before any app import, so importing
this module never triggers check_env() — mirroring tests/test_app_download.py.

App imports and playwright fixtures are deferred into fixture bodies so that
`uv run pytest -m fast --co -q` never imports app or requires chromium at
collection time.
"""

from __future__ import annotations

import os
import socket

# Must precede any import of app or gander.llm. setdefault (not a hard set) so a
# caller that deliberately exercises the real env check can override it — matches
# tests/test_app_download.py.
os.environ.setdefault("GANDER_SKIP_ENV_CHECK", "1")

from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch


@pytest.fixture(scope="session", autouse=True)
def _require_chromium() -> None:
    """Skip the whole e2e suite if Chromium isn't installed.

    The `e2e` suite is local-only and opt-in (`-m e2e`). On a box that never ran
    `playwright install chromium`, an explicit `-m e2e` should skip with a helpful
    message, not crash inside pytest-playwright's browser launch. This is an
    autouse *fixture* (not a collection hook) so it runs only when an e2e test
    actually executes — a `-m fast` run never imports playwright here, preserving
    the deferred-import contract above.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed (run: uv sync --group dev)")
    with sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip("Chromium not installed (run: uv run playwright install chromium)")


def _find_free_port() -> int:
    """Bind to port 0, let the OS assign a free port, return it.

    Gradio's launch(server_port=0) does not correctly propagate the OS-assigned
    port into local_url (it constructs 'http://127.0.0.1:0/'), so the built-in
    health check fails with ConnectionRefused. We grab a free port here, close
    the socket, then hand the number to Gradio — the same technique used by
    pytest-asyncio and other testing harnesses.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_app_url():
    """Launch the Gradio app in-process with all pipeline stages stubbed.

    Uses a session-scoped MonkeyPatch so the stubs outlive individual tests.
    Finds a free port explicitly (see _find_free_port docstring) and yields
    the local URL.
    """
    # Import here, not at module top, so collection of non-e2e tests never
    # pays the cost of importing app or building the Gradio Blocks.
    from tests._fakes import patch_pipeline_stages

    mp = MonkeyPatch()
    # e2e_delays=True adds 50 ms per stage so Gradio's SSE streaming has time
    # to deliver each intermediate update to the browser. Without delays the
    # pipeline completes in ~35 ms and Gradio coalesces SSE events, leaving the
    # browser frozen on an early "Extracting profile…" state even though the
    # download button appears (from a later yield that did propagate).
    patch_pipeline_stages(mp, e2e_delays=True)

    import app as _app

    port = _find_free_port()
    _app.demo.launch(prevent_thread_lock=True, server_port=port, quiet=True)
    url = _app.demo.local_url
    # Gradio appends a trailing slash; strip it so tests get a clean base URL.
    yield url.rstrip("/")

    _app.demo.close()
    mp.undo()


@pytest.fixture(scope="session")
def cv_fixture_path() -> Path:
    """Absolute path to a real .docx CV fixture.

    The stubbed extract_text ignores file bytes; only the .docx extension
    matters for the gr.File type filter to accept the upload.
    """
    path = Path(__file__).parent.parent / "fixtures" / "cvs" / "01_junior_da_novotny.docx"
    assert path.exists(), f"CV fixture not found: {path}"
    return path
