from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import gander.salary as salary_mod
from gander.errors import StageFailure
from gander.llm import LLMClient
from gander.obs import subscribe
from gander.salary import (
    _is_cz_location,
    build_queries,
    country_to_currency,
    currency_to_period,
    estimate_salary,
)
from gander.schemas import Anchor, Profile, ProfileItem, SalaryEstimate, Source

REPO_ROOT = Path(__file__).resolve().parent.parent
SENIOR_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "cvs" / "08_staff_ml_engineer_dvorak.txt"


@pytest.fixture(autouse=True)
def _stub_openrouter_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tests mock `complete_json` but still hit the constructor. Pin the
    # provider so the constructor reads the OpenRouter key (not MINIMAX).
    monkeypatch.setenv("GANDER_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")


def _cz_profile(
    *,
    role: str = "Senior Data Scientist",
    location: str | None = "Prague",
    years: int = 8,
    seniority: str | None = None,
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
        seniority_band=seniority,
    )


def _patch_ddgs(monkeypatch: pytest.MonkeyPatch, text_mock: MagicMock) -> None:
    """Replace ``gander.salary.DDGS`` with a context-manager-shaped mock.

    ``text_mock`` becomes the ``.text(query, ...)`` callable, so tests can
    inspect ``call_count`` / ``side_effect`` directly.
    """
    fake_instance = MagicMock()
    fake_instance.__enter__.return_value.text = text_mock
    fake_instance.__exit__.return_value = False
    monkeypatch.setattr("gander.salary.DDGS", lambda: fake_instance)


@pytest.mark.fast
def test_build_queries_cz_profile_targets_local_boards() -> None:
    profile = _cz_profile()
    queries = build_queries(profile)
    assert len(queries) == 4
    assert all(" OR " not in q for q in queries)
    assert any("site:platy.cz" in q for q in queries)
    assert any("site:profesia.cz" in q for q in queries)


@pytest.mark.fast
def test_build_queries_cz_senior_keeps_eur_cross_check() -> None:
    profile = _cz_profile(years=12)
    queries = build_queries(profile)
    assert len(queries) == 5
    assert any("EUR" in q for q in queries), "senior CZ profile must keep the EUR cross-check query"


@pytest.mark.fast
def test_ddg_text_uses_configured_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    text_mock = MagicMock(return_value=[])
    _patch_ddgs(monkeypatch, text_mock)
    monkeypatch.setenv("GANDER_SALARY_SEARCH_BACKENDS", " brave, yahoo ")

    assert salary_mod._ddg_text("salary query") == []
    text_mock.assert_called_once_with(
        "salary query",
        max_results=20,
        backend="brave,yahoo",
    )


@pytest.mark.fast
def test_ddg_text_uses_default_backends_when_env_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text_mock = MagicMock(return_value=[])
    _patch_ddgs(monkeypatch, text_mock)
    monkeypatch.setenv("GANDER_SALARY_SEARCH_BACKENDS", " , ")

    assert salary_mod._ddg_text("salary query") == []
    text_mock.assert_called_once_with(
        "salary query",
        max_results=20,
        backend="brave,duckduckgo,yahoo,mojeek",
    )


@pytest.mark.fast
def test_ddg_text_falls_back_to_auto_when_configured_backends_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback_results = [{"href": "https://www.platy.cz/en/salaryinfo", "body": "salary row"}]
    text_mock = MagicMock(side_effect=[RuntimeError("backend outage"), fallback_results])
    _patch_ddgs(monkeypatch, text_mock)
    monkeypatch.setenv("GANDER_SALARY_SEARCH_BACKENDS", "brave,duckduckgo")

    assert salary_mod._ddg_text("salary query") == fallback_results
    assert text_mock.call_args_list[0].kwargs == {
        "max_results": 20,
        "backend": "brave,duckduckgo",
    }
    assert text_mock.call_args_list[1].kwargs == {
        "max_results": 20,
        "backend": "auto",
    }


@pytest.mark.fast
async def test_estimate_salary_returns_stage_failure_when_search_returns_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text_mock = MagicMock(return_value=[])
    _patch_ddgs(monkeypatch, text_mock)

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
    assert search_evt["search_backends"] == "brave,duckduckgo,yahoo,mojeek"
    assert search_evt["query_max_results"] == 20
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
async def test_estimate_salary_retries_each_query_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Per-query resilience contract: when every query fails, tenacity does
    # 2 attempts PER query (not just on the first one). One flaky query no
    # longer aborts the whole loop — each is tried independently, and only
    # the aggregate <2-sources check collapses the stage.
    text_mock = MagicMock(side_effect=RuntimeError("ddg rate limit"))
    _patch_ddgs(monkeypatch, text_mock)

    profile = _cz_profile(years=5)  # <10y so build_queries returns base CZ queries.
    queries = build_queries(profile)
    assert len(queries) == 4

    result = await estimate_salary(profile)

    assert isinstance(result, StageFailure)
    assert result.stage == "salary"
    # Every built query is attempted. Each tenacity attempt tries configured
    # backends, then the `auto` fallback.
    assert text_mock.call_count == 4 * len(queries)


@pytest.mark.fast
async def test_estimate_salary_survives_single_query_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One bad query (e.g. site:a OR site:b shape that DDG sporadically rejects)
    # must NOT nuke the whole search when other queries return sources. The
    # stage proceeds with the survivors.
    good_results = [
        {
            "href": "https://www.platy.cz/platy/it/data-scientist",
            "body": "Median data scientist Praha 95 000 Kc/mes.",
        },
        {
            "href": "https://www.profesia.cz/prace/senior-data-scientist",
            "body": "Senior Data Scientist 110 000 - 150 000 Kc gross monthly.",
        },
    ]
    queries = build_queries(_cz_profile())
    bad_query = queries[0]

    def fake_ddg_text(query: str) -> list[dict[str, Any]]:
        if query == bad_query:
            raise RuntimeError("ddg rejects site: OR site: shape")
        return good_results

    monkeypatch.setattr(salary_mod, "_ddg_text", fake_ddg_text)

    # Mock the LLM step so the test stays hermetic.
    salary = SalaryEstimate(
        low=110000,
        high=150000,
        currency="CZK",
        period="month",
        sources=[
            Source(
                url="https://www.platy.cz/platy/it/data-scientist",  # type: ignore[arg-type]
                snippet="Median data scientist Praha 95 000 Kc/mes.",
                domain="www.platy.cz",
            ),
            Source(
                url="https://www.profesia.cz/prace/senior-data-scientist",  # type: ignore[arg-type]
                snippet="Senior Data Scientist 110 000 - 150 000 Kc gross monthly.",
                domain="www.profesia.cz",
            ),
        ],
        reasoning="based on two cz market snippets",
    )

    captured: dict[str, Any] = {}

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return salary

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await estimate_salary(_cz_profile())

    assert isinstance(result, SalaryEstimate), (
        f"expected SalaryEstimate, got {type(result).__name__}: {result}"
    )
    assert result.currency == "CZK"
    assert captured["max_tokens"] == 768

    # Obs contract: search_event reports the one failed query; the dedicated
    # `query_failures` event carries the type detail.
    search_evt = next(e for e in events if e["event"] == "salary_search")
    assert search_evt["failed_queries"] == 1
    failures_evt = next(e for e in events if e["event"] == "query_failures")
    assert failures_evt["failures"][0]["exc_type"] == "RuntimeError"


@pytest.mark.fast
async def test_search_runs_queries_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_ddg_text(query: str) -> list[dict[str, Any]]:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        slug = query.replace(" ", "-")
        return [{"href": f"https://example.com/{slug}", "body": f"{query} salary"}]

    monkeypatch.setattr(salary_mod, "_ddg_text", fake_ddg_text)

    sources = await salary_mod.search(
        ["data scientist prague", "data engineer prague", "ml engineer prague"],
        country="CZ",
        currency_hint="CZK",
    )

    assert len(sources) == 3
    assert max_active > 1


@pytest.mark.fast
async def test_estimate_salary_caps_inflated_junior_czk_month_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ddg_results = [
        {
            "href": "https://www.platy.cz/platy/ekonomika-finance-ucetnictvi/analytik-dat",
            "body": "Analytik dat salary survey data for Czech Republic.",
        },
        {
            "href": "https://www.profesia.cz/prace/junior-data-analyst",
            "body": "Junior Data Analyst Prague salary entry-level role.",
        },
    ]
    text_mock = MagicMock(return_value=ddg_results)
    _patch_ddgs(monkeypatch, text_mock)

    inflated = SalaryEstimate(
        low=100000,
        high=130000,
        currency="CZK",
        period="month",
        sources=[
            Source(
                url="https://www.platy.cz/platy/ekonomika-finance-ucetnictvi/analytik-dat",  # type: ignore[arg-type]
                snippet="Analytik dat salary survey data for Czech Republic.",
                domain="www.platy.cz",
            )
        ],
        reasoning="Weak snippets led to an inflated junior range.",
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return inflated

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await estimate_salary(
            _cz_profile(role="Junior Data Analyst", years=1, seniority="junior")
        )

    assert isinstance(result, SalaryEstimate)
    assert result.low == 80000
    assert result.high == 90000
    assert "sanity cap" in result.reasoning
    cap_evt = next(e for e in events if e["event"] == "salary_sanity_cap")
    assert cap_evt["original_high"] == 130000
    assert cap_evt["capped_high"] == 90000


@pytest.mark.fast
async def test_search_prioritizes_known_salary_domains_before_trimming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generic_results = [
        {
            "href": f"https://example{i}.com/result",
            "body": f"Generic salary article {i}",
        }
        for i in range(10)
    ]
    raw_results = [
        *generic_results,
        {
            "href": "https://www.profesia.cz/prace/senior-data-scientist",
            "body": "Senior Data Scientist 110 000 - 150 000 Kc gross monthly.",
        },
        {
            "href": "https://www.platy.cz/platy/it/data-scientist",
            "body": "90. percentil 130 000 Kc/mes.",
        },
    ]

    def fake_ddg_text(_query: str) -> list[dict[str, Any]]:
        return raw_results

    monkeypatch.setattr(salary_mod, "_ddg_text", fake_ddg_text)

    sources = await salary_mod.search(
        ["senior data scientist salary Prague"],
        country="CZ",
        currency_hint="CZK",
    )

    assert len(sources) == 8
    assert [s.domain for s in sources[:2]] == ["www.platy.cz", "www.profesia.cz"]
    assert all(s.domain != "example8.com" for s in sources)
    assert all(s.domain != "example9.com" for s in sources)


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

    async def raising_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        raise RuntimeError("provider 429 throttled")

    monkeypatch.setattr(LLMClient, "complete_json", raising_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await estimate_salary(_cz_profile())

    # PRD §4.6 user copy must survive every transport-error path; stage_boundary
    # must never get to fall back to its `str(exc)` default and leak `provider 429
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


@pytest.mark.fast
async def test_estimate_salary_allows_second_validation_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ddg_results = [
        {
            "href": "https://www.platy.cz/platy/it/data-scientist",
            "body": "Median data scientist Praha 95 000 Kc/mes per platy.cz.",
        },
        {
            "href": "https://www.profesia.cz/prace/senior-data-scientist",
            "body": "Senior Data Scientist 110 000 - 150 000 Kc gross monthly.",
        },
    ]
    text_mock = MagicMock(return_value=ddg_results)
    _patch_ddgs(monkeypatch, text_mock)
    seen_max_retries: int | None = None

    estimate = SalaryEstimate(
        low=110000,
        high=150000,
        currency="CZK",
        period="month",
        sources=[
            Source(
                url="https://www.profesia.cz/prace/senior-data-scientist",  # type: ignore[arg-type]
                snippet="Senior Data Scientist 110 000 - 150 000 Kc gross monthly.",
                domain="www.profesia.cz",
            ),
        ],
        reasoning="based on one cited salary row",
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        nonlocal seen_max_retries
        seen_max_retries = kwargs.get("max_retries")
        return estimate

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    result = await estimate_salary(_cz_profile())

    assert isinstance(result, SalaryEstimate)
    assert seen_max_retries == 2


@pytest.mark.fast
def test_build_queries_drops_non_market_headline() -> None:
    """T27 R4: when normalize rewrites the headline, queries use the canonical role.

    Member-of-Staff style: the verbatim headline must NOT appear; the canonical
    role MUST appear; at least one query carries a management-anchor token.
    """
    item = ProfileItem(text="placeholder", anchor=Anchor(quote="placeholder"))
    profile = Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="Member of Staff",
        detected_location="Prague",
        detected_years_experience=12,
        canonical_role="head of data science",
        seniority_band="head",
        is_management=True,
    )
    queries = build_queries(profile)
    joined = " || ".join(queries).lower()
    assert "member of staff" not in joined
    assert any("head of data science" in q.lower() for q in queries)
    assert any("manager" in q.lower() for q in queries), (
        "management profile must surface a management-anchor query"
    )


@pytest.mark.fast
def test_build_queries_management_non_cz_uses_eur_token() -> None:
    """T27 fix: management anchor must NOT inject CZK for non-CZ locations.

    A Berlin/Vienna management profile should target EUR sources; hardcoding
    CZK biases DDG toward Czech salary boards and contradicts the non-CZ
    locality queries.
    """
    item = ProfileItem(text="placeholder", anchor=Anchor(quote="placeholder"))
    profile = Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="Head of Engineering",
        detected_location="Berlin",
        detected_country="DE",
        detected_years_experience=8,
        canonical_role="head of engineering",
        seniority_band="head",
        is_management=True,
    )
    queries = build_queries(profile)
    # P1: no query may inject CZK on a non-CZ location.
    for q in queries:
        assert "CZK" not in q, f"non-CZ profile must never carry CZK token: {q}"
    # The management anchor is the query containing the literal " manager " token
    # injected by the template (`{canonical} manager salary ...`).
    mgmt_anchor = next(q for q in queries if " manager " in q.lower())
    assert "EUR" in mgmt_anchor, f"management anchor must target EUR on non-CZ: {mgmt_anchor}"


@pytest.mark.fast
def test_build_queries_cz_management_senior_keeps_both_signals() -> None:
    """T27 fix: CZ + management + senior must keep BOTH management and senior EUR.

    Previously the queries[:4] cap dropped the senior EUR cross-check when
    management prepended a query: 3 locality + 1 mgmt = 4, then senior appends
    to index 4 and gets sliced off. The cap is now 5 to fit all attached signals.
    """
    item = ProfileItem(text="placeholder", anchor=Anchor(quote="placeholder"))
    profile = Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="Head of Data",
        detected_location="Prague",
        detected_years_experience=14,
        canonical_role="head of data",
        seniority_band="head",
        is_management=True,
    )
    queries = build_queries(profile)
    assert len(queries) <= 5
    assert any("manager" in q.lower() for q in queries), "management anchor must survive"
    assert any("EUR" in q and "Europe" in q for q in queries), (
        "senior EUR cross-check must survive next to the management anchor"
    )
    assert not any("glassdoor.com" in q.lower() for q in queries), (
        "CZ management+senior should drop lower-priority Glassdoor under the 5-query cap"
    )


@pytest.mark.fast
def test_build_queries_handles_tagline_shape() -> None:
    """T27 R4: tagline-shape headlines (`|`, `@`) are dropped in favor of canonical."""
    item = ProfileItem(text="placeholder", anchor=Anchor(quote="placeholder"))
    profile = Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="Data Gardener | AI @Stealth",
        detected_location="Prague",
        detected_years_experience=8,
        canonical_role="senior data scientist",
        seniority_band="senior",
        is_management=False,
    )
    queries = build_queries(profile)
    assert any("senior data scientist" in q.lower() for q in queries)
    for q in queries:
        assert "|" not in q
        assert "@" not in q


@pytest.mark.fast
def test_salary_prompt_3shot_present() -> None:
    """T27 R5: salary prompt must carry all three example types (junior / senior / mgmt)."""
    prompt_path = (
        Path(__file__).resolve().parent.parent / "src" / "gander" / "prompts" / "salary.md"
    )
    body = prompt_path.read_text(encoding="utf-8")
    lower = body.lower()
    assert "example 1" in lower and "junior" in lower
    assert "example 2" in lower and "senior" in lower
    assert "example 3" in lower
    assert "is_management" in body
    assert "head" in lower
    assert "carve-out" in lower, "Rule 4 carve-out language must be present"
    assert "anchor" in lower, "seniority anchoring instruction must be present"


def _country_profile(
    *,
    country: str,
    location: str,
    role: str = "Senior Data Scientist",
    years: int = 7,
    seniority: str | None = "senior",
) -> Profile:
    item = ProfileItem(text="placeholder", anchor=Anchor(quote="placeholder"))
    return Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role=role,
        detected_location=location,
        detected_country=country,
        detected_years_experience=years,
        seniority_band=seniority,
    )


@pytest.mark.fast
@pytest.mark.parametrize(
    "country, location, currency, country_name",
    [
        ("DE", "Berlin", "EUR", "Germany"),
        ("JP", "Tokyo", "JPY", "Japan"),
        ("US", "San Francisco", "USD", "United States"),
        ("GB", "London", "GBP", "United Kingdom"),
    ],
)
def test_build_queries_non_cz_is_country_aware(
    country: str, location: str, currency: str, country_name: str
) -> None:
    """Non-CZ profiles emit country + local-currency tokens, no `site:` lock."""
    profile = _country_profile(country=country, location=location)
    queries = build_queries(profile)
    joined = " || ".join(queries)

    assert any(currency in q for q in queries), (
        f"{country} queries must carry the local currency token {currency!r}: {queries!r}"
    )
    assert any(country_name in q for q in queries), (
        f"{country} queries must carry the country name {country_name!r}: {queries!r}"
    )
    # No CZ-only domain locks anywhere outside CZ.
    assert "site:platy.cz" not in joined
    assert "site:profesia.cz" not in joined
    # The pre-T46 hardcoded "site:glassdoor.com OR site:levels.fyi" lock is gone.
    assert "site:glassdoor.com OR site:levels.fyi" not in joined
    # No "EUR 2025" cross-check unless the local currency genuinely IS EUR.
    if currency != "EUR":
        assert "EUR 2025" not in joined, (
            f"{country} must not carry a hardcoded EUR token: {queries!r}"
        )
    # No CZK token outside CZ.
    assert "CZK" not in joined


@pytest.mark.fast
def test_build_queries_cz_unchanged_with_explicit_country() -> None:
    """Explicit detected_country='CZ' produces the same queries as the legacy regex path."""
    profile = _cz_profile()
    explicit = profile.model_copy(update={"detected_country": "CZ"})
    assert build_queries(profile) == build_queries(explicit)


@pytest.mark.fast
def test_country_to_currency_table() -> None:
    assert country_to_currency("CZ") == "CZK"
    assert country_to_currency("DE") == "EUR"
    assert country_to_currency("JP") == "JPY"
    assert country_to_currency("US") == "USD"
    assert country_to_currency("GB") == "GBP"
    assert country_to_currency("CH") == "CHF"
    assert country_to_currency("PL") == "PLN"
    # Unknown ISO codes fall back to USD (live-search-friendly default).
    assert country_to_currency("ZZ") == "USD"
    assert country_to_currency(None) == "USD"
    assert country_to_currency("") == "USD"


@pytest.mark.fast
def test_currency_to_period_table() -> None:
    # Monthly markets: CZK, PLN, HUF, RON, BGN.
    assert currency_to_period("CZK") == "month"
    assert currency_to_period("PLN") == "month"
    assert currency_to_period("HUF") == "month"
    assert currency_to_period("RON") == "month"
    assert currency_to_period("BGN") == "month"
    # Everything else defaults to annual.
    assert currency_to_period("EUR") == "year"
    assert currency_to_period("USD") == "year"
    assert currency_to_period("JPY") == "year"
    assert currency_to_period("GBP") == "year"
    assert currency_to_period("CHF") == "year"


@pytest.mark.fast
async def test_estimate_salary_rejects_malformed_iso_currency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ISO-4217 shape gate: 'EURO' (4 letters) rejected, fail-closed to PRD copy."""
    ddg_results = [
        {"href": "https://example.de/a", "body": "DE DS salary"},
        {"href": "https://example.de/b", "body": "DE DS salary"},
    ]
    _patch_ddgs(monkeypatch, MagicMock(return_value=ddg_results))

    malformed = SalaryEstimate(
        low=60000,
        high=90000,
        currency="EURO",  # 4 letters — fails ISO-4217 shape check
        period="year",
        sources=[
            Source(
                url="https://example.de/a",  # type: ignore[arg-type]
                snippet="DE DS salary",
                domain="example.de",
            )
        ],
        reasoning="malformed currency code",
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return malformed

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await estimate_salary(_country_profile(country="DE", location="Berlin"))

    assert isinstance(result, StageFailure)
    failure_evt = next(e for e in events if e["event"] == "stage_failure")
    assert failure_evt["reason"] == "invalid_currency_shape"
    assert failure_evt["currency"] == "EURO"


@pytest.mark.fast
async def test_estimate_salary_accepts_jpy_for_japan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JPY round-trip — the pre-T46 `{CZK,EUR,USD}` whitelist would have rejected this."""
    ddg_results = [
        {"href": "https://doda.jp/career/ds", "body": "Tokyo DS 8M-12M JPY annual"},
        {"href": "https://en.indeed.jp/data-scientist", "body": "Senior DS Tokyo annual"},
    ]
    _patch_ddgs(monkeypatch, MagicMock(return_value=ddg_results))

    estimate = SalaryEstimate(
        low=8_000_000,
        high=12_000_000,
        currency="JPY",
        period="year",
        sources=[
            Source(
                url="https://doda.jp/career/ds",  # type: ignore[arg-type]
                snippet="Tokyo DS 8M-12M JPY annual",
                domain="doda.jp",
            ),
        ],
        reasoning="based on jp board",
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return estimate

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    result = await estimate_salary(_country_profile(country="JP", location="Tokyo"))

    assert isinstance(result, SalaryEstimate), result
    assert result.currency == "JPY"
    assert result.period == "year"


@pytest.mark.fast
async def test_estimate_salary_emits_period_mismatch_warning_without_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Period hint disagreement is a soft signal, not a stage failure (T46)."""
    ddg_results = [
        {"href": "https://levels.fyi/x", "body": "SF DS comp"},
        {"href": "https://glassdoor.com/y", "body": "SF DS comp"},
    ]
    _patch_ddgs(monkeypatch, MagicMock(return_value=ddg_results))

    # US hint = USD / year. LLM returns USD / month — warn but accept.
    estimate = SalaryEstimate(
        low=15000,
        high=25000,
        currency="USD",
        period="month",
        sources=[
            Source(
                url="https://levels.fyi/x",  # type: ignore[arg-type]
                snippet="SF DS comp",
                domain="levels.fyi",
            ),
        ],
        reasoning="snippets quoted monthly",
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return estimate

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await estimate_salary(_country_profile(country="US", location="San Francisco"))

    assert isinstance(result, SalaryEstimate), result
    mismatch = next(e for e in events if e["event"] == "period_mismatch")
    assert mismatch["currency"] == "USD"
    assert mismatch["period"] == "month"
    assert mismatch["expected_period"] == "year"
    assert mismatch["country"] == "US"


@pytest.mark.fast
async def test_search_preserves_live_order_outside_cz(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-CZ profiles must NOT apply the CZ-curated _SALARY_DOMAIN_PRIORITY (T46)."""
    raw_results = [
        {"href": "https://example.com/result-1", "body": "Generic salary article 1"},
        {"href": "https://example.com/result-2", "body": "Generic salary article 2"},
        # Pre-T46 these would have been re-ranked to the top by _SALARY_DOMAIN_PRIORITY.
        {"href": "https://www.glassdoor.com/Salaries/data-scientist", "body": "Glassdoor DS"},
        {"href": "https://www.levels.fyi/data-scientist", "body": "levels.fyi DS"},
    ]

    def fake_ddg_text(_query: str) -> list[dict[str, Any]]:
        return raw_results

    monkeypatch.setattr(salary_mod, "_ddg_text", fake_ddg_text)

    sources = await salary_mod.search(
        ["senior data scientist salary Berlin Germany EUR"],
        country="DE",
        currency_hint="EUR",
    )

    # Live-search order preserved: generic results first as DDG returned them.
    assert sources[0].domain == "example.com"
    # Glassdoor / levels.fyi are NOT promoted to the front for a DE profile.
    assert [s.domain for s in sources[:2]] != ["www.glassdoor.com", "www.levels.fyi"]


@pytest.mark.fast
async def test_salary_search_event_includes_country_and_tld_histogram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T46 telemetry contract: salary_search must carry country / currency_hint /
    sources_per_tld so we can observe live-search behavior per market without
    curating per-country tables."""
    raw_results = [
        {"href": "https://doda.jp/career/ds", "body": "Tokyo DS"},
        {"href": "https://en.indeed.jp/x", "body": "Tokyo DS"},
        {"href": "https://www.glassdoor.com/x", "body": "Tokyo DS"},
    ]

    def fake_ddg_text(_query: str) -> list[dict[str, Any]]:
        return raw_results

    monkeypatch.setattr(salary_mod, "_ddg_text", fake_ddg_text)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        await salary_mod.search(
            ["senior data scientist Tokyo Japan JPY 2025"],
            country="JP",
            currency_hint="JPY",
        )

    search_evt = next(e for e in events if e["event"] == "salary_search")
    assert search_evt["country"] == "JP"
    assert search_evt["currency_hint"] == "JPY"
    assert search_evt["sources_per_tld"] == {".jp": 2, ".com": 1}


@pytest.mark.live
@pytest.mark.slow
@pytest.mark.xdist_group("ddg")
@pytest.mark.flaky(reruns=2)
@pytest.mark.skipif(not os.environ.get("OPENROUTER_API_KEY"), reason="needs OPENROUTER_API_KEY")
async def test_senior_fixture_estimate_returns_czk_range() -> None:
    # Ensures the live path actually calls DDG + OpenRouter. Skips elsewhere.
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
