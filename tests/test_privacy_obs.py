"""PII must never leak into obs events (PRD §4.8: size and type, not content)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from gander import obs, pipeline
from gander.redact import redact
from gander.schemas import RedactedCV


@pytest.mark.fast
def test_pii_never_in_obs_events() -> None:
    email = "jane.smith@example.com"
    phone = "+420 777 999 888"
    name = "Jane Smith"
    cv_text = f"{name}\n{email}\n{phone}\nSenior Data Engineer with 8 years."

    events: list[dict[str, Any]] = []
    with obs.subscribe(events.append):
        redact(cv_text)

    assert events
    for evt in events:
        payload = json.dumps(evt, default=str)
        assert email not in payload, f"raw email in obs event: {evt}"
        assert phone not in payload, f"raw phone in obs event: {evt}"
        assert name not in payload, f"raw name in obs event: {evt}"


@pytest.mark.fast
async def test_filename_stem_never_in_pipeline_obs_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The raw upload filename (which embeds the candidate name) must not reach obs.

    Fails against the pre-fix `pipeline_start` emit that passed `filename=` through.
    """

    # Stub the first stage so no network/LLM runs; pipeline_start fires before it.
    async def _ingest_ok(file_bytes: bytes, filename: str) -> RedactedCV:
        from gander.errors import StageFailure

        return StageFailure(stage="profile", user_message="stop here")

    monkeypatch.setattr(pipeline, "extract_text", _ingest_ok)

    stem = "Zzqxwv Pseudonym"
    filename = f"{stem} CV.pdf"

    events: list[dict[str, Any]] = []
    with obs.subscribe(events.append):
        async for _ in pipeline.run(b"%PDF-1.4 stub", filename):
            pass

    assert events
    assert any(e["event"] == "pipeline_start" for e in events)
    for evt in events:
        payload = json.dumps(evt, default=str)
        assert stem not in payload, f"raw filename stem in obs event: {evt}"
