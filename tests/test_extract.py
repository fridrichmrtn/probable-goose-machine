from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from gander.errors import StageFailure
from gander.extract import MIN_CV_SCORE, _cv_composite_score, extract_profile, load_prompt
from gander.ingest import LOW_EVIDENCE_MSG, extract_text
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
async def test_extract_profile_allows_second_validation_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    redacted = _redacted_with_anchors()
    seen_max_retries: int | None = None

    synthetic = Profile(
        skills=[ProfileItem(text="dashboards in Looker", anchor=Anchor(quote=_UNIQUE_14W_QUOTE))],
        experience=[
            ProfileItem(text="executive readout owner", anchor=Anchor(quote=_UNIQUE_EXP_QUOTE))
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
        nonlocal seen_max_retries
        seen_max_retries = kwargs.get("max_retries")
        return synthetic

    monkeypatch.setattr(LLMClient, "complete_json", _fake_complete_json)

    result = await extract_profile(redacted)

    assert isinstance(result, Profile)
    assert seen_max_retries == 2


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


@pytest.mark.fast
async def test_tenure_override_event_emitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """T28 R7: when L2 produced a deterministic tenure that differs from the
    LLM's `detected_years_experience` by >=1, the extract stage emits a
    `tenure_override` event with `llm`, `deterministic`, `delta` payload AND
    overrides the value on the returned Profile (so salary's years>=10 gate
    cannot be misled by LLM variance on `[YEAR] - [YEAR]` patterns).

    Required per PRD §4.8 — the override is the load-bearing behaviour, the
    event is the load-bearing observable. Together they close the silent-
    override class identified in lessons.md (2026-05-14)."""
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")

    llm_profile = Profile(
        skills=[],
        # One verified experience entry → composite=3, clears the T38
        # low-evidence gate. Anchor matches the redacted text below.
        experience=[
            ProfileItem(
                text="executive readout owner",
                anchor=Anchor(quote=_UNIQUE_EXP_QUOTE, section=None),
            ),
        ],
        education=[],
        soft_signals=[],
        detected_role="Senior Engineer",
        detected_location="Prague",
        detected_years_experience=7,  # LLM says 7
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
        return llm_profile

    monkeypatch.setattr(LLMClient, "complete_json", _fake_complete_json)

    redacted = RedactedCV(
        text=f"Senior Engineer\n[YEAR] - Present\n{_UNIQUE_EXP_QUOTE}.\n",
        audit_log=[],
        years_experience_deterministic=10,  # L2 says 10
    )

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await extract_profile(redacted)

    assert isinstance(result, Profile)
    # Override applied on the returned Profile.
    assert result.detected_years_experience == 10
    # Override event fired with documented payload.
    override = [e for e in events if e["event"] == "tenure_override" and e["stage"] == "extract"]
    assert override, f"expected tenure_override event, got {events!r}"
    assert override[0]["llm"] == 7
    assert override[0]["deterministic"] == 10
    assert override[0]["delta"] == 3


@pytest.mark.fast
async def test_tenure_override_silent_when_delta_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No event when |delta| < 1 — only decision-changing deltas are surfaced.
    The override still applies (deterministic always wins when present), but
    we don't want noise in the obs stream from rounding-error-class deltas."""
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")

    llm_profile = Profile(
        skills=[],
        experience=[
            ProfileItem(
                text="executive readout owner",
                anchor=Anchor(quote=_UNIQUE_EXP_QUOTE, section=None),
            ),
        ],
        education=[],
        soft_signals=[],
        detected_role="Senior Engineer",
        detected_location="Prague",
        detected_years_experience=10,
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
        return llm_profile

    monkeypatch.setattr(LLMClient, "complete_json", _fake_complete_json)

    redacted = RedactedCV(
        text=f"Senior Engineer\n{_UNIQUE_EXP_QUOTE}.\n",
        audit_log=[],
        years_experience_deterministic=10,
    )

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await extract_profile(redacted)

    assert isinstance(result, Profile)
    assert result.detected_years_experience == 10
    override = [e for e in events if e["event"] == "tenure_override"]
    assert not override, f"unexpected tenure_override event, got {events!r}"


@pytest.mark.fast
async def test_tenure_override_skipped_when_no_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When L2 found no parseable date range (`years_experience_deterministic
    is None`), the LLM's value survives untouched — there's nothing to
    override and we don't synthesise a 0."""
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")

    llm_profile = Profile(
        skills=[],
        experience=[
            ProfileItem(
                text="executive readout owner",
                anchor=Anchor(quote=_UNIQUE_EXP_QUOTE, section=None),
            ),
        ],
        education=[],
        soft_signals=[],
        detected_role="Senior Engineer",
        detected_location="Prague",
        detected_years_experience=7,
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
        return llm_profile

    monkeypatch.setattr(LLMClient, "complete_json", _fake_complete_json)

    redacted = RedactedCV(
        text=f"Senior Engineer\n{_UNIQUE_EXP_QUOTE}.\n",
        audit_log=[],
    )  # default None

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await extract_profile(redacted)

    assert isinstance(result, Profile)
    assert result.detected_years_experience == 7  # LLM value preserved
    override = [e for e in events if e["event"] == "tenure_override"]
    assert not override


@pytest.mark.fast
async def test_extract_normalizes_valid_but_wrong_side_entry_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A market-token-valid personal-project title must not beat the highest
    seniority work-experience title when the extractor returns it first."""
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")

    senior_quote = (
        "Senior Manager AI and Data Science led the enterprise model portfolio "
        "and managed two analytics squads"
    )
    research_quote = (
        "Research Engineer prototype explored embeddings for a personal "
        "recommendation project outside the core role"
    )
    redacted = RedactedCV(
        text=(f"## Work Experience\n{senior_quote}.\n{research_quote}.\n"),
        audit_log=[],
    )
    llm_profile = Profile(
        skills=[],
        experience=[
            ProfileItem(
                text="Research Engineer",
                anchor=Anchor(quote=research_quote, section="Work Experience"),
            ),
            ProfileItem(
                text="Senior Manager AI and Data Science",
                anchor=Anchor(quote=senior_quote, section="Work Experience"),
            ),
        ],
        education=[],
        soft_signals=[],
        detected_role="Research Engineer",
        detected_location="Prague",
        detected_years_experience=10,
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
        return llm_profile

    monkeypatch.setattr(LLMClient, "complete_json", _fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await extract_profile(redacted)

    assert isinstance(result, Profile)
    assert result.canonical_role == "senior manager ai and data science"
    assert result.seniority_band == "senior"
    assert result.is_management is True
    normalized = [e for e in events if e["event"] == "role_normalized"]
    assert normalized[0]["source"] == "experience_recovery"


# ---------- T38 low-evidence gate -------------------------------------------


@pytest.mark.fast
def test_cv_composite_score_weights() -> None:
    """Composite weighs experience>education>skills=soft_signals; empty lists
    score 0 and admit nothing. Threshold of 3 is the document-level guard
    against fabricated salary on a sparse profile."""
    skill = ProfileItem(text="skill", anchor=Anchor(quote="skill evidence quote"))
    experience = ProfileItem(text="experience", anchor=Anchor(quote="experience evidence quote"))
    education = ProfileItem(text="education", anchor=Anchor(quote="education evidence quote"))
    soft_signal = ProfileItem(text="soft", anchor=Anchor(quote="soft evidence quote"))
    empty = {"skills": [], "experience": [], "education": [], "soft_signals": []}
    assert _cv_composite_score(empty) == 0

    one_skill = {**empty, "skills": [skill]}
    assert _cv_composite_score(one_skill) == 1  # below threshold

    one_education = {**empty, "education": [education]}
    assert _cv_composite_score(one_education) == 2  # below threshold

    one_experience = {**empty, "experience": [experience]}
    assert _cv_composite_score(one_experience) == 3  # meets threshold

    mixed = {
        "skills": [skill],
        "experience": [],
        "education": [education],
        "soft_signals": [soft_signal],
    }
    assert _cv_composite_score(mixed) == 4  # 1 + 0 + 2 + 1

    assert MIN_CV_SCORE == 3


@pytest.mark.fast
def test_cv_composite_score_counts_duplicate_evidence_once() -> None:
    duplicate_skill = ProfileItem(text="skill", anchor=Anchor(quote="same evidence quote"))
    duplicate_skill_case = ProfileItem(
        text="skill again",
        anchor=Anchor(quote="Same  evidence quote"),
    )
    duplicate_experience = ProfileItem(
        text="experience",
        anchor=Anchor(quote="same evidence quote"),
    )
    empty = {"skills": [], "experience": [], "education": [], "soft_signals": []}

    repeated_skills = {**empty, "skills": [duplicate_skill, duplicate_skill_case, duplicate_skill]}
    assert _cv_composite_score(repeated_skills) == 1

    repeated_across_fields = {
        **empty,
        "skills": [duplicate_skill],
        "experience": [duplicate_experience],
    }
    assert _cv_composite_score(repeated_across_fields) == 3


@pytest.mark.fast
async def test_low_evidence_gate_fires_on_empty_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the LLM returns an empty profile (all four lists empty), the
    document-level gate returns StageFailure(LOW_EVIDENCE_MSG) and emits a
    `low_evidence` event with the composite score and threshold so the
    cascade in pipeline.py marks score/salary/confidence/growth failed."""
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")

    empty_profile = Profile(
        skills=[],
        experience=[],
        education=[],
        soft_signals=[],
        detected_role="Random Role",
        detected_location=None,
        detected_years_experience=0,
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
        return empty_profile

    monkeypatch.setattr(LLMClient, "complete_json", _fake_complete_json)

    redacted = RedactedCV(text="Once upon a time there was a goose.", audit_log=[])

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await extract_profile(redacted)

    assert isinstance(result, StageFailure)
    assert result.stage == "profile"
    assert result.user_message == LOW_EVIDENCE_MSG
    assert result.debug_detail is not None
    assert "composite=0" in result.debug_detail
    assert "threshold=3" in result.debug_detail

    low_evidence = [e for e in events if e["event"] == "low_evidence" and e["stage"] == "extract"]
    assert len(low_evidence) == 1
    assert low_evidence[0]["composite"] == 0
    assert low_evidence[0]["threshold"] == MIN_CV_SCORE


@pytest.mark.fast
async def test_low_evidence_gate_fires_when_anchors_all_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM returns items but none anchor-verify → post-verification composite
    is 0 → gate fires. This is the common path for a non-CV upload where the
    LLM hallucinates plausible-looking entries that fail substring check."""
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")

    hallucinated = Profile(
        skills=[
            ProfileItem(
                text="Python",
                anchor=Anchor(quote="Built scalable Python pipelines for ETL workloads"),
            ),
        ],
        experience=[
            ProfileItem(
                text="Senior Engineer at Acme",
                anchor=Anchor(quote="Led the team to deliver quarterly product milestones"),
            ),
        ],
        education=[],
        soft_signals=[],
        detected_role="Senior Engineer",
        detected_location=None,
        detected_years_experience=5,
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
        return hallucinated

    monkeypatch.setattr(LLMClient, "complete_json", _fake_complete_json)

    # Source text contains none of the anchor quotes — all items will drop.
    redacted = RedactedCV(text="This is not actually a CV at all, just prose.", audit_log=[])

    result = await extract_profile(redacted)
    assert isinstance(result, StageFailure)
    assert result.user_message == LOW_EVIDENCE_MSG
    assert result.debug_detail is not None
    assert "composite=0" in result.debug_detail


@pytest.mark.fast
async def test_low_evidence_gate_passes_with_one_verified_experience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One anchor-verified experience entry (weight=3) meets the threshold
    exactly and the function returns a Profile, not a StageFailure."""
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")

    profile = Profile(
        skills=[],
        experience=[
            ProfileItem(
                text="experience owner",
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
        return profile

    monkeypatch.setattr(LLMClient, "complete_json", _fake_complete_json)

    redacted = RedactedCV(text=f"Experience\n{_UNIQUE_EXP_QUOTE}.\n", audit_log=[])

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await extract_profile(redacted)

    assert isinstance(result, Profile)
    assert len(result.experience) == 1
    low_evidence = [e for e in events if e["event"] == "low_evidence"]
    assert not low_evidence


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
async def test_extract_profile_on_fixtures(
    fixture_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GANDER_INGEST_MODE", "text")
    data = fixture_path.read_bytes()
    # Loud guard against an unresolved LFS pointer reaching extract_text.
    if data.startswith(b"version https://git-lfs.github.com/"):
        pytest.fail(
            f"{fixture_path.name} is an unresolved LFS pointer. "
            "Run `git lfs pull` (CI uses `actions/checkout@v4` with `lfs: true`)."
        )
    ingested = await extract_text(data, fixture_path.name)
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
