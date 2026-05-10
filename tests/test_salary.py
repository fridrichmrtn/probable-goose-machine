from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from jobfit.errors import StageFailure
from jobfit.llm import LLMClient
from jobfit.obs import subscribe
from jobfit.salary import build_queries, estimate_salary
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

    # §4.8: search emits dedup_results=0 and the boundary surfaces the
    # RuntimeError raised inside search() as an `error` event.
    search_evt = next(e for e in events if e["event"] == "salary_search")
    assert search_evt["stage"] == "salary"
    assert search_evt["dedup_results"] == 0
    error_evt = next(e for e in events if e["event"] == "error")
    assert error_evt["stage"] == "salary"
    assert error_evt["exc_type"] == "RuntimeError"


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
