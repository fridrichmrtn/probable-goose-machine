from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from jobfit.errors import StageFailure
from jobfit.llm import LLMClient
from jobfit.obs import subscribe
from jobfit.salary import _is_cz_location, build_queries, estimate_salary
from jobfit.schemas import Anchor, Profile, ProfileItem, SalaryEstimate, Source

REPO_ROOT = Path(__file__).resolve().parent.parent
SENIOR_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "cvs" / "08_staff_ml_engineer_dvorak.txt"


def _cz_profile(
    *,
    role: str = "Senior Data Scientist",
    location: str | None = "Prague",
    years: int = 8,
) -> Profile:
    item = ProfileItem(text="placeholder", anchor=Anchor(quote="placeholder"))
    return Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role=role,
        detected_location=location,
        detected_years_experience=years,
    )


def _patch_ddgs(monkeypatch: pytest.MonkeyPatch, text_mock: MagicMock) -> None:
    """Replace ``jobfit.salary.DDGS`` with a context-manager-shaped mock.

    ``text_mock`` becomes the ``.text(query, ...)`` callable, so tests can
    inspect ``call_count`` / ``side_effect`` directly.
    """
    fake_instance = MagicMock()
    fake_instance.__enter__.return_value.text = text_mock
    fake_instance.__exit__.return_value = False
    monkeypatch.setattr("jobfit.salary.DDGS", lambda: fake_instance)


@pytest.mark.fast
def test_build_queries_cz_profile_targets_local_boards() -> None:
    profile = _cz_profile()
    queries = build_queries(profile)
    assert 2 <= len(queries) <= 3
    assert any("platy.cz" in q or "profesia.cz" in q for q in queries)


@pytest.mark.fast
def test_build_queries_cz_senior_keeps_eur_cross_check() -> None:
    profile = _cz_profile(years=12)
    queries = build_queries(profile)
    assert len(queries) == 4
    assert any("EUR" in q for q in queries), "senior CZ profile must keep the EUR cross-check query"


@pytest.mark.fast
async def test_estimate_salary_returns_stage_failure_when_search_returns_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text_mock = MagicMock(return_value=[])
    _patch_ddgs(monkeypatch, text_mock)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-stub")

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await estimate_salary(_cz_profile())

    assert isinstance(result, StageFailure)
    assert result.stage == "salary"
    assert result.user_message == "Insufficient market data for this profile"

    # §4.8: search emits dedup_results=0 and `estimate_salary` catches the
    # RuntimeError raised by `search()` so PRD §4.6 copy is preserved and
    # `stage_boundary` never sees a raw exception. The structured
    # `stage_failure` event carries the reason + exc_type.
    search_evt = next(e for e in events if e["event"] == "salary_search")
    assert search_evt["stage"] == "salary"
    assert search_evt["dedup_results"] == 0
    failure_evt = next(e for e in events if e["event"] == "stage_failure")
    assert failure_evt["stage"] == "salary"
    assert failure_evt["reason"] == "search_error"
    assert failure_evt["exc_type"] == "RuntimeError"


@pytest.mark.fast
async def test_estimate_salary_rejects_llm_urls_not_in_search_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # DDG returns two real-looking results.
    ddg_results = [
        {
            "href": "https://www.platy.cz/platy/it/data-scientist",
            "body": "Median data scientist Praha 95 000 Kc/mes.",
        },
        {
            "href": "https://www.profesia.cz/prace/senior-data-scientist",
            "body": "Senior Data Scientist 110 000 - 150 000 Kc gross monthly.",
        },
    ]
    text_mock = MagicMock(return_value=ddg_results)
    _patch_ddgs(monkeypatch, text_mock)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-stub")

    # Build a valid SalaryEstimate whose sources are ALL outside the DDG set.
    hallucinated = SalaryEstimate(
        low=110000,
        high=150000,
        currency="CZK",
        period="month",
        sources=[
            Source(
                url="https://example.com/made-up-1",  # type: ignore[arg-type]
                snippet="fabricated",
                domain="example.com",
            ),
            Source(
                url="https://example.org/made-up-2",  # type: ignore[arg-type]
                snippet="also fabricated",
                domain="example.org",
            ),
        ],
        reasoning="model invented these urls",
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return hallucinated

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await estimate_salary(_cz_profile())

    assert isinstance(result, StageFailure)
    assert result.stage == "salary"
    assert result.user_message == "Insufficient market data for this profile"

    failure_evt = next(e for e in events if e["event"] == "stage_failure")
    assert failure_evt["stage"] == "salary"
    assert failure_evt["reason"] == "no_verifiable_sources"
    assert failure_evt["returned"] == 2


@pytest.mark.fast
async def test_estimate_salary_caps_retries_per_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # tenacity does exactly 2 attempts on the first query; reraise=True
    # propagates the RuntimeError up into the stage boundary, so no later
    # query is ever attempted. The exact count is the contract.
    text_mock = MagicMock(side_effect=RuntimeError("ddg rate limit"))
    _patch_ddgs(monkeypatch, text_mock)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-stub")

    profile = _cz_profile(years=5)  # <10y so build_queries returns 2-3
    queries = build_queries(profile)
    assert len(queries) <= 3

    result = await estimate_salary(profile)

    assert isinstance(result, StageFailure)
    assert result.stage == "salary"
    assert text_mock.call_count == 2


@pytest.mark.fast
@pytest.mark.parametrize(
    "location, expected_cz",
    [
        ("Prague", True),
        ("Praha 5", True),
        ("Brno", True),
        ("Czech Republic", True),
        ("CZ", True),
        ("Berlin", False),
        ("Aczland", False),  # substring "cz" inside an unrelated city — must NOT match
        ("Czeladz", False),  # Polish city; "cz" is a substring of "czeladz" — must NOT match
        ("Krakow, Poland", False),
        ("New Prague, Minnesota", True),  # "prague" as a standalone word, accepted
    ],
)
def test_is_cz_location_uses_word_boundaries(location: str, expected_cz: bool) -> None:
    assert _is_cz_location(location) is expected_cz


@pytest.mark.fast
def test_is_cz_location_treats_missing_location_as_cz() -> None:
    # Empty/None locations default to CZ to keep CZK-default behavior stable for
    # CVs with no detected location — documented invariant of `build_queries`.
    assert _is_cz_location(None) is True
    assert _is_cz_location("") is True


@pytest.mark.fast
async def test_estimate_salary_maps_llm_transport_error_to_prd_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Sufficient DDG results so we reach the `complete_json` call.
    ddg_results = [
        {
            "href": "https://www.platy.cz/platy/it/data-scientist",
            "body": "Median data scientist Praha 95 000 Kc/mes.",
        },
        {
            "href": "https://www.profesia.cz/prace/senior-data-scientist",
            "body": "Senior Data Scientist 110 000 - 150 000 Kc gross monthly.",
        },
    ]
    text_mock = MagicMock(return_value=ddg_results)
    _patch_ddgs(monkeypatch, text_mock)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-stub")

    async def raising_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        raise RuntimeError("minimax 429 throttled")

    monkeypatch.setattr(LLMClient, "complete_json", raising_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await estimate_salary(_cz_profile())

    # PRD §4.6 user copy must survive every transport-error path; stage_boundary
    # must never get to fall back to its `str(exc)` default and leak `minimax 429
    # throttled` to the UI.
    assert isinstance(result, StageFailure)
    assert result.stage == "salary"
    assert result.user_message == "Insufficient market data for this profile"

    failure_evt = next(e for e in events if e["event"] == "stage_failure")
    assert failure_evt["reason"] == "llm_error"
    assert failure_evt["exc_type"] == "RuntimeError"


@pytest.mark.fast
async def test_estimate_salary_replaces_llm_snippets_with_input_snippets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Real-looking DDG results — the test asserts that ONLY the input snippet text
    # survives to the final SalaryEstimate, even if the LLM emits a different
    # snippet body alongside the matching URL. This closes the fabrication channel
    # codex P1 flagged: model keeps a real URL but invents the snippet text.
    real_snippet_a = "Median data scientist Praha 95 000 Kc/mes per platy.cz."
    real_snippet_b = "Senior Data Scientist 110 000 - 150 000 Kc gross monthly."
    ddg_results = [
        {"href": "https://www.platy.cz/platy/it/data-scientist", "body": real_snippet_a},
        {"href": "https://www.profesia.cz/prace/senior-data-scientist", "body": real_snippet_b},
    ]
    text_mock = MagicMock(return_value=ddg_results)
    _patch_ddgs(monkeypatch, text_mock)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-stub")

    estimate = SalaryEstimate(
        low=110000,
        high=150000,
        currency="CZK",
        period="month",
        sources=[
            Source(
                url="https://www.platy.cz/platy/it/data-scientist",  # type: ignore[arg-type]
                snippet="FAKE SNIPPET — model invented this text",
                domain="malicious-impostor.example",
            ),
            Source(
                url="https://www.profesia.cz/prace/senior-data-scientist",  # type: ignore[arg-type]
                snippet="ANOTHER FAKE SNIPPET",
                domain="another-impostor.example",
            ),
        ],
        reasoning="midpoint 130000",
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return estimate

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    result = await estimate_salary(_cz_profile())
    assert isinstance(result, SalaryEstimate)

    # URL is the join key; snippet + domain must come from the inputs, not the LLM.
    surviving_snippets = {s.snippet for s in result.sources}
    surviving_domains = {s.domain for s in result.sources}
    assert surviving_snippets == {real_snippet_a, real_snippet_b}
    assert surviving_domains == {"www.platy.cz", "www.profesia.cz"}
    assert "FAKE SNIPPET — model invented this text" not in surviving_snippets
    assert "malicious-impostor.example" not in surviving_domains


@pytest.mark.live
@pytest.mark.slow
@pytest.mark.skipif(not os.environ.get("MINIMAX_API_KEY"), reason="needs MINIMAX_API_KEY")
async def test_senior_fixture_estimate_returns_czk_range() -> None:
    # Ensures the live path actually calls DDG + MiniMax. Skips elsewhere.
    cv_text = SENIOR_FIXTURE.read_text(encoding="utf-8")
    assert cv_text  # fixture present
    profile = _cz_profile(
        role="Staff Machine Learning Engineer",
        location="Prague",
        years=13,
    )

    result = await estimate_salary(profile)

    assert isinstance(result, SalaryEstimate), (
        f"expected SalaryEstimate, got {type(result).__name__}: {result}"
    )
    assert result.low < result.high
    assert result.currency == "CZK"
    assert len(result.sources) >= 1
    for s in result.sources:
        assert str(s.url).startswith("http")
