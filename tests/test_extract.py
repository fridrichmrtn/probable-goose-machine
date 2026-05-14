from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from gander.errors import StageFailure
from gander.extract import extract_profile, load_prompt
from gander.ingest import extract_text
from gander.llm import LLMClient
from gander.obs import subscribe
from gander.redact import redact
from gander.schemas import Anchor, Profile, ProfileItem, RedactedCV
from gander.verify import verify_quote

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cvs"

_UNIQUE_14W_QUOTE = (
    "Built dashboards in Looker covering four product categories on PostgreSQL "
    "15 across the analytics team"
)
_UNIQUE_EXP_QUOTE = (
    "Owned the weekly executive readout for sales and operations from January through June"
)


def _redacted_with_anchors() -> RedactedCV:
    text = (
        "## Experience\n"
        "Junior Data Analyst — Some Retailer, Prague\n"
        f"{_UNIQUE_EXP_QUOTE}.\n"
        "\n"
        "## Skills\n"
        f"{_UNIQUE_14W_QUOTE}.\n"
    )
    return RedactedCV(text=text, audit_log=[])


@pytest.mark.fast
def test_load_prompt_reads_extract_md() -> None:
    body = load_prompt("extract.md")
    assert body.strip()
    assert "copy the EXACT supporting substring" in body


@pytest.mark.fast
async def test_paraphrased_anchor_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    redacted = _redacted_with_anchors()

    synthetic = Profile(
        skills=[
            ProfileItem(
                text="dashboards in Looker",
                anchor=Anchor(quote=_UNIQUE_14W_QUOTE, section=None),
            ),
            ProfileItem(
                text="paraphrased item",
                anchor=Anchor(
                    quote=("Wrote some Python scripts for various ad-hoc analyses on retail data"),
                    section=None,
                ),
            ),
        ],
        experience=[
            ProfileItem(
                text="executive readout owner",
                anchor=Anchor(quote=_UNIQUE_EXP_QUOTE, section=None),
            ),
        ],
        education=[],
        soft_signals=[],
        detected_role="Junior Data Analyst",
        detected_location="Prague",
        detected_years_experience=1,
    )

    async def _fake_complete_json(
        self: LLMClient,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        model: str = "reasoning",
        **kwargs: Any,
    ) -> BaseModel:
        return synthetic

    monkeypatch.setattr(LLMClient, "complete_json", _fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await extract_profile(redacted)

    assert isinstance(result, Profile)
    assert len(result.skills) == 1
    assert result.skills[0].anchor.quote == _UNIQUE_14W_QUOTE
    assert len(result.experience) == 1
    assert result.detected_role == "Junior Data Analyst"
    assert result.detected_location == "Prague"
    assert result.detected_years_experience == 1

    verify_events = [e for e in events if e["event"] == "verify" and e["stage"] == "extract"]
    assert len(verify_events) == 1
    assert verify_events[0]["dropped"] == 1
    assert verify_events[0]["kept"] == 2


@pytest.mark.fast
async def test_stage_failure_returned_when_llm_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")

    async def _boom(
        self: LLMClient,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        model: str = "reasoning",
        **kwargs: Any,
    ) -> BaseModel:
        raise RuntimeError("synthetic extract failure")

    monkeypatch.setattr(LLMClient, "complete_json", _boom)

    pii_email = "jan.novotny@example.com"
    pii_name = "Jan Novotný"
    redacted = RedactedCV(
        text=f"{pii_name}\n{pii_email}\nJunior Data Analyst",
        audit_log=[],
    )

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await extract_profile(redacted)

    # T18 owns the curated-message contract; T09 only pins that stage_boundary captures
    # stage+message+debug_detail.
    assert isinstance(result, StageFailure)
    assert result.stage == "extract"
    assert result.user_message == "synthetic extract failure"
    assert result.debug_detail is not None
    assert result.debug_detail.startswith("RuntimeError(")

    errors = [e for e in events if e["event"] == "error" and e["stage"] == "extract"]
    assert errors, f"expected error event for extract stage, got {events!r}"
    assert errors[0]["exc_type"] == "RuntimeError"
    assert pii_email not in errors[0]["exc_message"]
    assert pii_name not in errors[0]["exc_message"]

    verify_events = [e for e in events if e["event"] == "verify" and e["stage"] == "extract"]
    assert not verify_events, "verify event must not fire on the failure path"


@pytest.mark.fast
async def test_validation_error_from_llm_becomes_stage_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PRD §4.6 model-output parse failure: bad-shape JSON → StageFailure, not crash."""
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")

    try:
        Profile.model_validate({})
    except ValidationError as e:
        captured_validation_error = e

    async def _bad_shape(
        self: LLMClient,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        model: str = "reasoning",
        **kwargs: Any,
    ) -> BaseModel:
        raise captured_validation_error

    monkeypatch.setattr(LLMClient, "complete_json", _bad_shape)

    redacted = RedactedCV(text="Junior Data Analyst", audit_log=[])

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await extract_profile(redacted)

    assert isinstance(result, StageFailure)
    assert result.stage == "extract"
    assert result.debug_detail is not None
    assert "validation error" in result.debug_detail

    errors = [e for e in events if e["event"] == "error" and e["stage"] == "extract"]
    assert errors, f"expected error event for extract stage, got {events!r}"
    assert errors[0]["exc_type"] == "ValidationError"

    verify_events = [e for e in events if e["event"] == "verify" and e["stage"] == "extract"]
    assert not verify_events, "verify event must not fire on the failure path"


_LIVE_FIXTURES = sorted(list(_FIXTURE_DIR.glob("*.pdf")) + list(_FIXTURE_DIR.glob("*.docx")))


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("MINIMAX_API_KEY") is None,
    reason="live tests require MINIMAX_API_KEY",
)
def test_live_corpus_is_present() -> None:
    """Copilot PR #2: when MINIMAX_API_KEY is set, surface a missing/empty
    fixture corpus or an unresolved LFS pointer as a loud failure instead of
    a silently-empty parametrized test."""
    fixtures = sorted(list(_FIXTURE_DIR.glob("*.pdf")) + list(_FIXTURE_DIR.glob("*.docx")))
    assert fixtures, (
        f"No .pdf/.docx fixtures in {_FIXTURE_DIR}. Run `git lfs pull` "
        "(CI uses `actions/checkout@v4` with `lfs: true`)."
    )
    for p in fixtures:
        head = p.read_bytes()[:60]
        assert not head.startswith(b"version https://git-lfs.github.com/"), (
            f"{p.name} is an unresolved LFS pointer. Run `git lfs pull`."
        )


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("MINIMAX_API_KEY") is None,
    reason="live tests require MINIMAX_API_KEY",
)
@pytest.mark.parametrize(
    "fixture_path",
    _LIVE_FIXTURES,
    ids=lambda p: p.name,
)
async def test_extract_profile_on_fixtures(fixture_path: Path) -> None:
    data = fixture_path.read_bytes()
    # Loud guard against an unresolved LFS pointer reaching extract_text.
    if data.startswith(b"version https://git-lfs.github.com/"):
        pytest.fail(
            f"{fixture_path.name} is an unresolved LFS pointer. "
            "Run `git lfs pull` (CI uses `actions/checkout@v4` with `lfs: true`)."
        )
    ingested = extract_text(data, fixture_path.name)
    if isinstance(ingested, StageFailure):
        pytest.fail(f"ingest failed on {fixture_path.name}: {ingested.user_message}")

    redacted = redact(ingested)
    if isinstance(redacted, StageFailure):
        pytest.fail(f"redact failed on {fixture_path.name}: {redacted.user_message}")

    cv_text = redacted.text

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await extract_profile(redacted)

    if isinstance(result, StageFailure):
        pytest.fail(f"L3 failed on {fixture_path.name}: {result.user_message}")

    assert isinstance(result, Profile)
    assert result.detected_role.strip() != "", f"{fixture_path.name}: detected_role is empty"
    assert 0 < result.detected_years_experience < 50, (
        f"{fixture_path.name}: detected_years_experience "
        f"{result.detected_years_experience} outside (0, 50)"
    )

    total_items = (
        len(result.skills)
        + len(result.experience)
        + len(result.education)
        + len(result.soft_signals)
    )
    assert total_items > 0, f"L3 returned an empty profile on {fixture_path.name}"

    verified = 0
    for item_list in (
        result.skills,
        result.experience,
        result.education,
        result.soft_signals,
    ):
        for item in item_list:
            if verify_quote(item.anchor.quote, cv_text, section=item.anchor.section):
                verified += 1
    assert verified == total_items, (
        f"{fixture_path.name}: extract_profile returned {total_items - verified} unverified items"
    )

    verify_events = [e for e in events if e["event"] == "verify" and e["stage"] == "extract"]
    assert len(verify_events) == 1
    ve = verify_events[0]
    returned_total = ve["kept"] + ve["dropped"]
    assert returned_total > 0, f"model returned zero items on {fixture_path.name}"
    survival_rate = ve["kept"] / returned_total
    assert survival_rate >= 0.80, (
        f"{fixture_path.name}: anchor survival rate "
        f"{ve['kept']}/{returned_total} = {survival_rate:.0%} below 80% gate"
    )
