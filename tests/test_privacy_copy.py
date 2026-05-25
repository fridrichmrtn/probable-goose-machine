from __future__ import annotations

from pathlib import Path

import pytest

from gander import ingest

pytestmark = pytest.mark.fast
REPO_ROOT = Path(__file__).resolve().parent.parent


def test_pdf_ingest_default_and_privacy_copy_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GANDER_INGEST_MODE", raising=False)
    monkeypatch.delenv("GANDER_PDF_INGEST_MODE", raising=False)
    assert ingest._pdf_ingest_mode() == "vision"

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    app_py = (REPO_ROOT / "app.py").read_text(encoding="utf-8")

    assert "PDF pages are rendered to images and uploaded unredacted" in readme
    assert "GANDER_DOCX_INGEST_MODE=llm` also uploads unredacted DOCX text" in readme
    assert "PDFs are uploaded " in app_py
    assert "to OpenRouter/Gemini as page images for transcription" in app_py
    assert "DOCX is read " in app_py
    assert "locally. Uploads are not retained by Gander" in app_py
