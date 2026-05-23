from __future__ import annotations

import pytest

from gander.schemas import Source
from gander.source_rubric import evaluate_source_rubric


def _source(domain: str, snippet: str, path: str = "salary") -> Source:
    return Source(url=f"https://{domain}/{path}", snippet=snippet, domain=domain)  # type: ignore[arg-type]


@pytest.mark.fast
def test_source_rubric_one_domain_is_low() -> None:
    result = evaluate_source_rubric(
        [_source("platy.cz", "Analysts earn around 100000 CZK per month.")]
    )

    assert result.tier == "Low"
    assert result.reason == "fewer_than_two_domains"
    assert result.distinct_domains == 1


@pytest.mark.fast
def test_source_rubric_two_domains_caps_at_medium() -> None:
    result = evaluate_source_rubric(
        [
            _source("platy.cz", "Analysts earn around 100000 CZK per month."),
            _source("profesia.cz", "Analyst compensation is about 105000 CZK per month."),
        ]
    )

    assert result.tier == "Medium"
    assert result.reason == "two_domains"
    assert result.comparable_values == 2


@pytest.mark.fast
def test_source_rubric_three_domains_tight_spread_is_high() -> None:
    result = evaluate_source_rubric(
        [
            _source("platy.cz", "Analysts earn around 100000 CZK per month."),
            _source("profesia.cz", "Analyst compensation is about 105000 CZK per month."),
            _source("glassdoor.com", "Prague analysts average 110000 CZK per month."),
        ]
    )

    assert result.tier == "High"
    assert result.reason == "three_plus_domains_agree"
    assert result.spread is not None
    assert result.spread <= 0.25


@pytest.mark.fast
def test_source_rubric_three_domains_disagreement_is_low() -> None:
    result = evaluate_source_rubric(
        [
            _source("platy.cz", "Junior analysts earn around 50000 CZK per month."),
            _source("profesia.cz", "Mid-level analysts earn 100000 CZK per month."),
            _source("glassdoor.com", "Lead analyst compensation reaches 200000 CZK per month."),
        ]
    )

    assert result.tier == "Low"
    assert result.reason == "source_disagreement"
    assert result.spread is not None
    assert result.spread > 0.50


@pytest.mark.fast
def test_source_rubric_duplicate_domains_use_one_domain_median() -> None:
    result = evaluate_source_rubric(
        [
            _source("platy.cz", "Analysts earn around 90000 CZK per month.", "a"),
            _source("www.platy.cz", "Analysts earn around 110000 CZK per month.", "b"),
            _source("profesia.cz", "Analyst compensation is about 100000 CZK per month."),
        ]
    )

    assert result.tier == "Medium"
    assert result.distinct_domains == 2
    assert result.comparable_values == 2
    assert result.spread == 0.0


@pytest.mark.fast
def test_source_rubric_range_snippets_use_per_domain_medians() -> None:
    result = evaluate_source_rubric(
        [
            _source("platy.cz", "Analysts usually land in the 90-110k CZK monthly range."),
            _source("profesia.cz", "Analyst roles pay 100k to 120k CZK per month."),
            _source("glassdoor.com", "Analyst compensation averages 105000 CZK per month."),
        ]
    )

    assert result.tier == "High"
    assert result.comparable_values == 3
    assert result.spread is not None
    assert result.spread < 0.25


@pytest.mark.fast
def test_source_rubric_mixed_periods_are_ambiguous() -> None:
    result = evaluate_source_rubric(
        [
            _source("platy.cz", "Analysts earn around 100000 CZK per month."),
            _source("levels.fyi", "Analyst compensation is about 1200000 CZK per year."),
            _source("glassdoor.com", "Prague analysts average 105000 CZK per month."),
        ]
    )

    assert result.tier is None
    assert result.reason == "mixed_period"


@pytest.mark.fast
def test_source_rubric_nonnumeric_multi_domain_sources_do_not_cap() -> None:
    result = evaluate_source_rubric(
        [
            _source("platy.cz", "Analyst pay in Prague is competitive."),
            _source("profesia.cz", "Analyst compensation in the Czech market is solid."),
        ]
    )

    assert result.tier is None
    assert result.reason == "insufficient_numeric_evidence"
    assert result.comparable_values == 0
