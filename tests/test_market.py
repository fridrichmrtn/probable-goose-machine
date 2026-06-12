"""MarketSpec resolution (P0.1) — one market decision per profile."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gander.market import resolve_market
from gander.schemas import Anchor, Profile, ProfileItem


def _profile(
    *,
    country: str | None = None,
    location: str | None = None,
) -> Profile:
    item = ProfileItem(text="placeholder", anchor=Anchor(quote="placeholder"))
    return Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="Senior Data Scientist",
        detected_location=location,
        detected_country=country,
        detected_years_experience=8,
    )


@pytest.mark.fast
def test_resolve_market_cz_explicit() -> None:
    spec = resolve_market(_profile(country="CZ", location="Prague"))
    assert spec.country == "CZ"
    assert spec.country_name == "Czech Republic"
    assert spec.currency == "CZK"
    assert spec.period == "month"
    assert spec.provenance == "cv_explicit"


@pytest.mark.fast
def test_resolve_market_de_explicit() -> None:
    spec = resolve_market(_profile(country="DE", location="Berlin"))
    assert spec.country == "DE"
    assert spec.country_name == "Germany"
    assert spec.currency == "EUR"
    assert spec.period == "year"
    assert spec.provenance == "cv_explicit"


@pytest.mark.fast
def test_resolve_market_inferred_cz_from_location() -> None:
    spec = resolve_market(_profile(country=None, location="Prague"))
    assert spec.country == "CZ"
    assert spec.currency == "CZK"
    assert spec.provenance == "inferred"


@pytest.mark.fast
def test_resolve_market_default_unknown() -> None:
    spec = resolve_market(_profile(country=None, location=None))
    assert spec.country == "XX"
    assert spec.country_name is None
    assert spec.currency == "USD"
    assert spec.period == "year"
    assert spec.provenance == "default"


@pytest.mark.fast
def test_resolve_market_uk_alias() -> None:
    spec = resolve_market(_profile(country="UK", location="London"))
    assert spec.country == "GB"
    assert spec.currency == "GBP"
    assert spec.provenance == "cv_explicit"


@pytest.mark.fast
def test_resolve_market_unsupported_country_falls_through_to_default() -> None:
    # AQ is ISO-shaped but unsupported; with no CZ-leaning location the
    # resolution must land on the market-blind default, not a silent USD bias
    # labeled as explicit.
    spec = resolve_market(_profile(country="AQ", location="McMurdo Station"))
    assert spec.country == "XX"
    assert spec.provenance == "default"


@pytest.mark.fast
def test_market_spec_is_frozen() -> None:
    spec = resolve_market(_profile(country="DE"))
    with pytest.raises(ValidationError):
        spec.currency = "USD"  # type: ignore[misc]
