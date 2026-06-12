"""PII must never leak into obs events (PRD §4.8: size and type, not content)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from gander import obs
from gander.redact import redact


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
