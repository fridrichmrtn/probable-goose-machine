"""Market resolution — one spec per profile, consumed by salary, growth, confidence.

`resolve_market` runs once post-normalize and answers "which labor market is
this CV in?" with explicit provenance. Hoisted out of `salary.py` (P0.1) so
growth no longer assumes CZ while salary resolves 50+ markets, and so the
confidence judge can discount estimates whose geography was never detected.

A field joins `MarketSpec` only if it changes behavior in at least two stages.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from gander.schemas import Profile

# Word-boundary token match — substring "cz" inside "Aczland" or "Czeladz" must
# not flip CZ detection. Tokens are matched case-insensitively against any
# letter-bounded run in the location string.
_CZ_TOKEN_PATTERN = re.compile(
    r"\b(?:czech|cz|praha|prague|brno|ostrava)\b",
    re.IGNORECASE,
)

# Flat country -> ISO-4217 currency map. ~40 markets. Unknown / missing -> USD,
# which is the live-search-friendliest default (most non-CZ snippet text the
# DDG backends surface for English queries already quote USD). Adding a row is
# a one-line PR. Local-payroll period (month vs. year) is a separate concern;
# see `currency_to_period`.
_COUNTRY_CURRENCY: dict[str, str] = {
    "CZ": "CZK",
    "SK": "EUR",
    "PL": "PLN",
    "HU": "HUF",
    "RO": "RON",
    "BG": "BGN",
    "DE": "EUR",
    "AT": "EUR",
    "FR": "EUR",
    "BE": "EUR",
    "NL": "EUR",
    "LU": "EUR",
    "ES": "EUR",
    "PT": "EUR",
    "IT": "EUR",
    "IE": "EUR",
    "FI": "EUR",
    "EE": "EUR",
    "LV": "EUR",
    "LT": "EUR",
    "GR": "EUR",
    "MT": "EUR",
    "CY": "EUR",
    "SI": "EUR",
    "HR": "EUR",
    "CH": "CHF",
    "GB": "GBP",
    "DK": "DKK",
    "NO": "NOK",
    "SE": "SEK",
    "IS": "ISK",
    "US": "USD",
    "CA": "CAD",
    "MX": "MXN",
    "BR": "BRL",
    "AR": "ARS",
    "AU": "AUD",
    "NZ": "NZD",
    "JP": "JPY",
    "KR": "KRW",
    "CN": "CNY",
    "HK": "HKD",
    "SG": "SGD",
    "IN": "INR",
    "ID": "IDR",
    "MY": "MYR",
    "PH": "PHP",
    "TH": "THB",
    "VN": "VND",
    "TR": "TRY",
    "IL": "ILS",
    "AE": "AED",
    "SA": "SAR",
    "ZA": "ZAR",
    "EG": "EGP",
    "UA": "UAH",
}

# Markets where local employment ads quote monthly compensation. Everywhere
# else defaults to annual. The salary prompt uses this only as a hint — the LLM
# may override based on what the snippets actually say.
_MONTHLY_CURRENCIES: frozenset[str] = frozenset({"CZK", "PLN", "HUF", "RON", "BGN"})

# Country display names for query construction. Live search interprets natural
# language better than ISO codes (`DE` matches Germany and a hundred other
# things; "Germany" is unambiguous).
_COUNTRY_NAMES: dict[str, str] = {
    "CZ": "Czech Republic",
    "SK": "Slovakia",
    "PL": "Poland",
    "HU": "Hungary",
    "RO": "Romania",
    "BG": "Bulgaria",
    "DE": "Germany",
    "AT": "Austria",
    "FR": "France",
    "BE": "Belgium",
    "NL": "Netherlands",
    "LU": "Luxembourg",
    "ES": "Spain",
    "PT": "Portugal",
    "IT": "Italy",
    "IE": "Ireland",
    "FI": "Finland",
    "EE": "Estonia",
    "LV": "Latvia",
    "LT": "Lithuania",
    "GR": "Greece",
    "MT": "Malta",
    "CY": "Cyprus",
    "SI": "Slovenia",
    "HR": "Croatia",
    "CH": "Switzerland",
    "GB": "United Kingdom",
    "DK": "Denmark",
    "NO": "Norway",
    "SE": "Sweden",
    "IS": "Iceland",
    "US": "United States",
    "CA": "Canada",
    "MX": "Mexico",
    "BR": "Brazil",
    "AR": "Argentina",
    "AU": "Australia",
    "NZ": "New Zealand",
    "JP": "Japan",
    "KR": "South Korea",
    "CN": "China",
    "HK": "Hong Kong",
    "SG": "Singapore",
    "IN": "India",
    "ID": "Indonesia",
    "MY": "Malaysia",
    "PH": "Philippines",
    "TH": "Thailand",
    "VN": "Vietnam",
    "TR": "Türkiye",
    "IL": "Israel",
    "AE": "United Arab Emirates",
    "SA": "Saudi Arabia",
    "ZA": "South Africa",
    "EG": "Egypt",
    "UA": "Ukraine",
}

_COUNTRY_ALIASES: dict[str, str] = {
    # Common but non-ISO codes the LLM may emit. Anything not aliased and not
    # in `_COUNTRY_CURRENCY` falls back to the location-based path so we don't
    # silently bias an unsupported country into a USD default.
    "UK": "GB",
}

MarketProvenance = Literal["cv_explicit", "inferred", "default"]


class MarketSpec(BaseModel):
    """Resolved labor market for one profile, with resolution provenance.

    `provenance` records how geography was determined: `cv_explicit` (the
    extractor emitted a supported ISO country), `inferred` (legacy CZ-location
    regex matched), or `default` (unknown geography — country "XX", USD/year
    market-blind estimate). Consumers: salary query construction + LLM payload,
    growth prompt market terms, confidence CV-quality floor.
    """

    model_config = ConfigDict(frozen=True)

    country: str  # ISO-3166 alpha-2, or "XX" for unknown
    country_name: str | None
    currency: str  # ISO-4217
    period: Literal["month", "year"]
    provenance: MarketProvenance


def _is_cz_location(location: str | None) -> bool:
    if not location:
        return False
    return bool(_CZ_TOKEN_PATTERN.search(location))


def country_to_currency(country: str | None) -> str:
    """ISO-3166 alpha-2 -> ISO-4217 currency. Unknown / null -> USD."""
    if not country:
        return "USD"
    return _COUNTRY_CURRENCY.get(country.upper(), "USD")


def currency_to_period(currency: str) -> Literal["month", "year"]:
    """ISO-4217 currency -> default period hint ('month' or 'year')."""
    return "month" if currency in _MONTHLY_CURRENCIES else "year"


def _country_display_name(country: str | None) -> str | None:
    if not country:
        return None
    return _COUNTRY_NAMES.get(country.upper())


def _resolve_country(profile: Profile) -> tuple[str, MarketProvenance]:
    """Return (ISO-3166 alpha-2, provenance) for the profile.

    Prefers `detected_country` from extraction (with alias resolution and a
    membership check against the supported currency table); falls back to the
    legacy `_is_cz_location` regex on `detected_location` for backward
    compatibility on CZ-leaning ambiguous CVs and older fixtures. Unknown ->
    `'XX'` (which salary downstream treats as non-CZ, USD-defaulting).
    """
    explicit = (profile.detected_country or "").strip().upper()
    explicit = _COUNTRY_ALIASES.get(explicit, explicit)
    if explicit and explicit in _COUNTRY_CURRENCY:
        return explicit, "cv_explicit"
    if _is_cz_location(profile.detected_location):
        return "CZ", "inferred"
    return "XX", "default"


def resolve_market(profile: Profile) -> MarketSpec:
    """Resolve the profile's labor market once; all stages consume the result."""
    country, provenance = _resolve_country(profile)
    currency = country_to_currency(country)
    return MarketSpec(
        country=country,
        country_name=_country_display_name(country),
        currency=currency,
        period=currency_to_period(currency),
        provenance=provenance,
    )
