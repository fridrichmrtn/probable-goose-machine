from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import gander.salary as salary_mod
from gander.errors import StageFailure
from gander.llm import LLMClient
from gander.obs import subscribe
from gander.salary import _is_cz_location, build_queries, estimate_salary
from gander.schemas import Anchor, Profile, ProfileItem, SalaryEstimate, Source

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
async def test_estimate_salary_retries_each_query_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Per-query resilience contract: when every query fails, tenacity does
    # 2 attempts PER query (not just on the first one). One flaky query no
    # longer aborts the whole loop — each is tried independently, and only
    # the aggregate <2-sources check collapses the stage.
    text_mock = MagicMock(side_effect=RuntimeError("ddg rate limit"))
    _patch_ddgs(monkeypatch, text_mock)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-stub")

    profile = _cz_profile(years=5)  # <10y so build_queries returns base CZ queries.
    queries = build_queries(profile)
    assert len(queries) == 4

    result = await estimate_salary(profile)

    assert isinstance(result, StageFailure)
    assert result.stage == "salary"
    # Every built query is attempted; each one runs tenacity's 2 attempts.
    assert text_mock.call_count == 2 * len(queries)


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
    # Side-effect sequence: first query fails on every tenacity attempt (2x),
    # then every remaining query succeeds.
    n_queries = len(build_queries(_cz_profile()))
    text_mock = MagicMock(
        side_effect=[
            RuntimeError("ddg rejects site: OR site: shape"),
            RuntimeError("ddg rejects site: OR site: shape"),
            *([good_results] * (n_queries - 1)),
        ]
    )
    _patch_ddgs(monkeypatch, text_mock)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-stub")

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

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return salary

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = await estimate_salary(_cz_profile())

    assert isinstance(result, SalaryEstimate), (
        f"expected SalaryEstimate, got {type(result).__name__}: {result}"
    )
    assert result.currency == "CZK"

    # Obs contract: search_event reports the one failed query; the dedicated
    # `query_failures` event carries the type detail.
    search_evt = next(e for e in events if e["event"] == "salary_search")
    assert search_evt["failed_queries"] == 1
    failures_evt = next(e for e in events if e["event"] == "query_failures")
    assert failures_evt["failures"][0]["exc_type"] == "RuntimeError"


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

    sources = await salary_mod.search(["senior data scientist salary Prague"])

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
    monkeypatch.setenv("MINIMAX_API_KEY", "test-stub")
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


@pytest.mark.live
@pytest.mark.slow
@pytest.mark.xdist_group("ddg")
@pytest.mark.flaky(reruns=2)
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
