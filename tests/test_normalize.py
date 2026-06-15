"""Tests for gander.normalize (T27 R4/R5)."""

from __future__ import annotations

from typing import Any

import pytest

from gander.normalize import (
    NormalizedRole,
    _llm_canonicalize_role,
    _LLMCanonicalRole,
    normalize_role,
    normalize_role_with_llm_fallback,
    seniority_rank,
)
from gander.obs import subscribe


@pytest.mark.fast
@pytest.mark.parametrize(
    "detected, years, titles, expected_canonical, expected_band, expected_mgmt, expected_source",
    [
        # Market-token hits — direct path, source="market_token".
        (
            "Senior Data Scientist",
            5,
            [],
            "senior data scientist",
            "senior",
            False,
            "market_token",
        ),
        (
            "Junior Data Analyst",
            1,
            [],
            "junior data analyst",
            "junior",
            False,
            "market_token",
        ),
        (
            "Vedoucí týmu DS",
            8,
            [],
            "vedoucí týmu ds",
            "head",
            True,
            "market_token",
        ),
        (
            "Staff Engineer",
            9,
            [],
            "staff engineer",
            "staff",
            False,
            "market_token",
        ),
        # Named-headline denylist — recovers from experience_titles, picks highest band.
        (
            "Member of Staff",
            12,
            ["Senior Manager AI", "Head of Data Science", "Head of Tender"],
            "head of data science",
            "head",
            True,
            "named_headline",
        ),
        (
            "Data Gardener",
            10,
            ["Head of DS"],
            "head of ds",
            "head",
            True,
            "named_headline",
        ),
        # Tagline-shape — recover from titles even without denylist hit.
        (
            "Data Gardener | AI, Data Science & Engineering @Stealth",
            10,
            ["Senior Manager AI"],
            "senior manager ai",
            "senior",
            True,
            "tagline_shape",
        ),
        (
            "AI Whisperer @ Anywhere",
            5,
            ["Lead DS"],
            "lead ds",
            "senior",
            False,
            "tagline_shape",
        ),
        # Unrecognized fallback — no LLM in sync path.
        (
            "Wizard of Bytes",
            4,
            [],
            "wizard of bytes",
            "mid",
            False,
            "unrecognized",
        ),
    ],
)
def test_normalize_role_deterministic_cases(
    detected: str,
    years: int,
    titles: list[str],
    expected_canonical: str,
    expected_band: str,
    expected_mgmt: bool,
    expected_source: str,
) -> None:
    result = normalize_role(detected, years, titles)
    assert isinstance(result, NormalizedRole)
    assert result.canonical_role == expected_canonical
    assert result.seniority_band == expected_band
    assert result.is_management == expected_mgmt
    assert result.source == expected_source


@pytest.mark.fast
@pytest.mark.parametrize(
    "detected, years, titles, expected_canonical, expected_band, expected_mgmt, expected_source",
    [
        (
            "Junior Data Analyst",
            1,
            [],
            "junior data analyst",
            "junior",
            False,
            "market_token",
        ),
        ("Data Analyst", 3, [], "data analyst", "mid", False, "market_token"),
        (
            "Machine Learning Engineer",
            6,
            [],
            "machine learning engineer",
            "mid",
            False,
            "market_token",
        ),
        (
            "MLOps / Platform Engineer",
            7,
            [],
            "mlops / platform engineer",
            "mid",
            False,
            "market_token",
        ),
        (
            "Senior Data Scientist",
            10,
            [],
            "senior data scientist",
            "senior",
            False,
            "market_token",
        ),
        (
            "Staff Machine Learning Engineer",
            12,
            [],
            "staff machine learning engineer",
            "staff",
            False,
            "market_token",
        ),
        # Tenure floor: 12y IC with no management evidence → at least senior (was mid).
        ("Research Scientist", 12, [], "research scientist", "senior", False, "market_token"),
        ("Head of Data", 15, [], "head of data", "head", True, "market_token"),
        (
            "Data Gardener | AI, Data Science & Engineering @Stealth",
            12,
            [
                "Member of Staff at Stealth AI",
                "Senior Manager, AI & Data at Czech Enterprise",
                "Head of Data Science at Košík",
            ],
            "head of data science",
            "head",
            True,
            "tagline_shape",
        ),
        (
            "Vedoucí výzkumného týmu",
            15,
            [],
            "vedoucí výzkumného týmu",
            "head",
            True,
            "market_token",
        ),
        (
            "Manažer datového oddělení",
            10,
            [],
            "manažer datového oddělení",
            "senior",
            True,
            "market_token",
        ),
    ],
)
def test_bundled_corpus_headlines_normalize_deterministically(
    detected: str,
    years: int,
    titles: list[str],
    expected_canonical: str,
    expected_band: str,
    expected_mgmt: bool,
    expected_source: str,
) -> None:
    """Pin the role strings present in tests/fixtures/cvs/*.txt.

    This catches allowlist drift that generic unit cases can miss: the fixture
    corpus is what acceptance tests actually exercise.
    """
    result = normalize_role(detected, years, titles)
    assert result.canonical_role == expected_canonical
    assert result.seniority_band == expected_band
    assert result.is_management == expected_mgmt
    assert result.source == expected_source


@pytest.mark.fast
def test_role_normalized_event_emitted() -> None:
    """When normalization rewrites detected_role, `role_normalized` must fire."""
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        normalize_role(
            "Member of Staff",
            12,
            ["Head of Data Science"],
        )
    role_events = [e for e in events if e["event"] == "role_normalized"]
    assert len(role_events) == 1
    payload = role_events[0]
    assert payload["detected"] == "Member of Staff"
    assert payload["canonical"] == "head of data science"
    assert payload["seniority"] == "head"
    assert payload["source"] == "named_headline"


@pytest.mark.fast
def test_role_unrecognized_event_emitted() -> None:
    """An unrecognizable headline with no recoverable titles must fire
    `role_unrecognized`, and the emitted `fallback` must reflect the actual
    post-floor band, not a hardcoded "mid_default" — the tenure floor can lift it."""
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = normalize_role("Wizard of Bytes", 4, [])
    unrecognized = [e for e in events if e["event"] == "role_unrecognized"]
    assert len(unrecognized) == 1
    payload = unrecognized[0]
    assert payload["detected"] == "Wizard of Bytes"
    assert payload["fallback"] == "mid"
    assert result.source == "unrecognized"
    assert result.seniority_band == "mid"


@pytest.mark.fast
def test_role_unrecognized_event_reports_floored_band() -> None:
    """When tenure floors the unrecognized fallback above mid, the emitted
    `fallback` must match the returned band (regression for the misleading
    hardcoded "mid_default")."""
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = normalize_role("Wizard of Bytes", 12, [])
    payload = next(e for e in events if e["event"] == "role_unrecognized")
    assert payload["fallback"] == "senior"
    assert result.source == "unrecognized"
    assert result.seniority_band == "senior"


@pytest.mark.fast
def test_market_token_match_does_not_emit_role_normalized() -> None:
    """When canonical equals detected.lower(), no `role_normalized` event fires."""
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        normalize_role("Senior Data Scientist", 5, [])
    assert not [e for e in events if e["event"] == "role_normalized"]


@pytest.mark.fast
def test_valid_but_lower_seniority_detected_role_recovers_from_titles() -> None:
    """A market-token-valid side-entry like Research Engineer must not beat
    a clearly senior management title pulled from current work evidence."""
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = normalize_role(
            "Research Engineer",
            10,
            [
                "Senior Manager AI & Data Science",
                "Research Engineer",
                "Manažer datového oddělení",
            ],
        )

    assert result.canonical_role == "senior manager ai & data science"
    assert result.seniority_band == "senior"
    assert result.is_management is True
    assert result.source == "experience_recovery"
    normalized = [e for e in events if e["event"] == "role_normalized"]
    assert normalized[0]["source"] == "experience_recovery"


@pytest.mark.fast
def test_tagline_recovery_uses_title_prefixes_not_duration_summaries() -> None:
    """Profile.pdf-style summaries carry title prefixes plus employer/duration prose.

    The role normalizer must recover the senior/management track from those
    prefixes instead of letting a duration-shaped "Research Engineer" side
    entry drive salary queries.
    """
    result = normalize_role(
        "Data Gardener | AI, Data Science & Engineering @Stealth",
        10,
        [
            "Member of Staff at Stealth Mode Startup, 4 months",
            "Research Engineer, 10 years 7 months tenure",
            "Senior Manager AI at TD SYNNEX, led marketing and commercial data streams",
            "Head of Data Science & Analytics at Alza.cz, founded and led teams",
            "Head of Tender Management & Analytics at DSV Global Transport",
        ],
    )

    assert result.canonical_role == "head of data science & analytics"
    assert result.seniority_band == "head"
    assert result.is_management is True
    assert result.source == "tagline_shape"


@pytest.mark.fast
def test_valid_mid_detected_role_not_overridden_by_prior_head_title() -> None:
    """Canonical role and management flag stay the conservative current role; the
    band still reflects demonstrated leadership + tenure. The prior Head title
    does not rewrite "data scientist" to management, but the 8y IC with a Head in
    the history is floored to staff (top IC band), not left at mid."""
    result = normalize_role(
        "Data Scientist",
        8,
        ["Data Scientist", "Head of Data Science"],
    )

    assert result.canonical_role == "data scientist"
    assert result.source == "market_token"
    assert result.seniority_band == "staff"
    assert result.is_management is False


@pytest.mark.fast
def test_role_recovery_ignores_sentence_shaped_experience_summaries() -> None:
    """Sentence-shaped experience summaries count for neither canonical recovery
    nor the band floor. The 16-word "Senior Manager AI ... managed two squads"
    prose is not a title-shaped candidate, so it does NOT become the canonical
    role (stays "research engineer") and does NOT supply management evidence — the
    band reflects the tenure floor only (10y → senior), not the staff lift. This
    guards the false-positive fix: only the candidate's own title-shaped roles
    lift the band, not arbitrary prose that may name someone else's title."""
    result = normalize_role(
        "Research Engineer",
        10,
        [
            "Senior Manager AI and Data Science led the enterprise model portfolio "
            "and managed two analytics squads",
            "Research Engineer",
        ],
    )

    assert result.canonical_role == "research engineer"
    assert result.source == "market_token"
    assert result.seniority_band == "senior"
    assert result.is_management is False


@pytest.mark.fast
def test_research_engineer_with_management_history_floors_to_staff() -> None:
    """Regression for the reported defect: a long-tenured research engineer whose
    CV shows a management history was anchored at IC/mid, poisoning the salary
    search. The canonical title stays "research engineer" (accepted as correct),
    but the band must floor to staff so the salary anchor reflects ~10y tenure +
    demonstrated leadership. Mirrors the Profile.pdf shape without sending the CV:
    the extractor's prose summaries carry a title-shaped prefix ("Head of Data
    Science & Analytics", "Senior Manager AI & Data Science") that supplies the
    management evidence, while the current IC role appears first so canonical
    recovery keeps "research engineer"."""
    result = normalize_role(
        "Research Engineer",
        10,
        [
            "Research Engineer, 10 years 7 months tenure",
            "Head of Data Science & Analytics at Alza.cz, founded and led the analytics team",
            "Senior Manager AI & Data Science at TD SYNNEX, led commercial data streams",
        ],
    )

    assert result.canonical_role == "research engineer"
    assert result.seniority_band == "staff"
    assert result.is_management is False
    assert result.source == "market_token"


@pytest.mark.fast
def test_unrelated_stakeholder_mention_is_not_management_evidence() -> None:
    """False-positive guard: an experience summary that merely *mentions* another
    person's management title ("Partnered with the Head of Sales ...") must NOT
    lift an IC to staff. The 9-word prose is not title-shaped, so it supplies no
    management evidence — the band reflects the tenure floor only (8y → senior)."""
    result = normalize_role(
        "Data Scientist",
        8,
        ["Partnered with the Head of Sales on forecasting dashboards"],
    )

    assert result.canonical_role == "data scientist"
    assert result.seniority_band == "senior"
    assert result.is_management is False


@pytest.mark.fast
def test_compound_ic_manager_title_floors_to_staff() -> None:
    """False-negative guard: a compound title whose management token trails a
    longer non-management token ("Principal Engineer / Engineering Manager")
    classifies as (staff, False) under `_classify`'s first-match rule, hiding the
    manager history. The band-floor scan checks all management tokens, so the 10y
    IC with explicit manager history is correctly floored to staff."""
    result = normalize_role(
        "Research Engineer",
        10,
        [
            "Research Engineer, 10 years tenure",
            "Principal Engineer / Engineering Manager",
        ],
    )

    assert result.canonical_role == "research engineer"
    assert result.seniority_band == "staff"
    assert result.is_management is False


@pytest.mark.fast
def test_valid_senior_detected_role_is_not_overridden_by_prior_head_title() -> None:
    """The recovery path is intentionally narrow: it fixes low/mid side-entry
    picks without converting every senior IC with a past head title into management.
    The canonical role and management flag stay IC; the band floor lifts the 10y
    senior IC with a Head in the history to staff (top IC band)."""
    result = normalize_role(
        "Senior Data Scientist",
        10,
        ["Head of Data Science", "Senior Data Scientist"],
    )

    assert result.canonical_role == "senior data scientist"
    assert result.source == "market_token"
    assert result.seniority_band == "staff"
    assert result.is_management is False


@pytest.mark.fast
def test_seniority_rank_orders_management_and_cz_titles() -> None:
    assert seniority_rank("Wizard of Bytes") == 0
    assert seniority_rank("Research Engineer") < seniority_rank("Senior Manager AI")
    assert seniority_rank("Senior Manager AI") == seniority_rank("Manažer datového oddělení")
    assert seniority_rank("Senior Manager AI") < seniority_rank("Vedoucí výzkumného týmu")


@pytest.mark.fast
def test_tagline_with_no_recoverable_titles_falls_through_to_unrecognized() -> None:
    """Tagline shape + empty titles → unrecognized (deterministic path exhausted)."""
    result = normalize_role("Data Gardener | AI @Stealth", 5, [])
    assert result.source == "unrecognized"
    assert result.seniority_band == "mid"


@pytest.mark.fast
async def test_async_wrapper_returns_sync_result_when_deterministic() -> None:
    """Deterministic hits short-circuit before the LLM fallback runs."""
    result = await normalize_role_with_llm_fallback("Senior Data Scientist", 5, [])
    assert result.source == "market_token"
    assert result.canonical_role == "senior data scientist"


@pytest.mark.fast
async def test_async_wrapper_skips_llm_when_recovery_succeeds() -> None:
    """A denylisted headline with recoverable titles never hits the LLM."""
    result = await normalize_role_with_llm_fallback("Member of Staff", 12, ["Head of Data Science"])
    assert result.source == "named_headline"
    assert result.is_management is True


@pytest.mark.fast
async def test_async_wrapper_calls_llm_for_unrecognized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unrecognized headline with no recovery → LLM fallback fires."""
    fake_calls: list[dict[str, Any]] = []

    async def fake_canonicalize(detected: str, titles: list[str], years: int) -> Any:
        fake_calls.append({"detected": detected, "titles": titles, "years": years})
        return NormalizedRole(
            canonical_role="head of data science",
            seniority_band="head",
            is_management=True,
            source="llm_fallback",
        )

    monkeypatch.setattr("gander.normalize._llm_canonicalize_role", fake_canonicalize)

    result = await normalize_role_with_llm_fallback("Wizard of Bytes", 12, [])
    assert result.source == "llm_fallback"
    assert result.canonical_role == "head of data science"
    assert len(fake_calls) == 1
    # Sanity-check the LLM schema is callable (the test patches it out, but the
    # real one must exist to keep the import path live).
    _ = _LLMCanonicalRole.model_fields


@pytest.mark.fast
async def test_llm_canonicalize_role_uses_extract_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Role fallback belongs to L3 extraction, so it uses the extract model slot."""
    seen: dict[str, Any] = {}

    async def fake_complete_json(self: object, **kwargs: Any) -> _LLMCanonicalRole:
        seen.update(kwargs)
        return _LLMCanonicalRole(
            canonical_role="head of data science",
            seniority_band="head",
            is_management=True,
            confidence=0.9,
        )

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr("gander.llm.LLMClient.complete_json", fake_complete_json)

    result = await _llm_canonicalize_role("Wizard of Bytes", ["Head of Data Science"], 12)

    assert isinstance(result, NormalizedRole)
    assert seen["model"] == "extract"
    assert result.canonical_role == "head of data science"
    assert result.source == "llm_fallback"


@pytest.mark.fast
async def test_async_wrapper_keeps_unrecognized_when_llm_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM fallback returning None must not change the sync result."""

    async def fake_canonicalize(detected: str, titles: list[str], years: int) -> None:
        return None

    monkeypatch.setattr("gander.normalize._llm_canonicalize_role", fake_canonicalize)
    result = await normalize_role_with_llm_fallback("Wizard of Bytes", 4, [])
    assert result.source == "unrecognized"
    assert result.seniority_band == "mid"


@pytest.mark.fast
async def test_llm_canonicalize_forwards_max_tokens_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`normalize_role_with_llm_fallback` caps the cheap-tier `complete_json` call
    at 256 tokens. Regression guard: this was the one previously-uncapped
    OpenRouter call site missed in T45."""
    from gander.llm import LLMClient
    from gander.normalize import _LLMCanonicalRole

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")

    captured: dict[str, Any] = {}

    async def _fake_complete_json(self: LLMClient, **kwargs: Any) -> _LLMCanonicalRole:
        captured.update(kwargs)
        return _LLMCanonicalRole(
            canonical_role="head of data science",
            seniority_band="head",
            is_management=True,
            confidence=0.9,
        )

    monkeypatch.setattr(LLMClient, "complete_json", _fake_complete_json)

    result = await normalize_role_with_llm_fallback("Wizard of Bytes", 12, [])

    assert result.source == "llm_fallback"
    assert captured["max_tokens"] == 256
