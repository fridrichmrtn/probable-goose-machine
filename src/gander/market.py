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

# Single source of truth: country -> (ISO-4217 currency, display name).
# ~55 markets; unknown / missing country -> USD, which is the
# live-search-friendliest default (most non-CZ snippet text the DDG backends
# surface for English queries already quotes USD). Display names feed query
# construction — live search interprets natural language better than ISO codes
# (`DE` matches Germany and a hundred other things; "Germany" is unambiguous).
# Adding a market is a one-line PR. Local-payroll period (month vs. year) is a
# separate concern; see `currency_to_period`.
_COUNTRY_INFO: dict[str, tuple[str, str]] = {
    "CZ": ("CZK", "Czech Republic"),
    "SK": ("EUR", "Slovakia"),
    "PL": ("PLN", "Poland"),
    "HU": ("HUF", "Hungary"),
    "RO": ("RON", "Romania"),
    "BG": ("BGN", "Bulgaria"),
    "DE": ("EUR", "Germany"),
    "AT": ("EUR", "Austria"),
    "FR": ("EUR", "France"),
    "BE": ("EUR", "Belgium"),
    "NL": ("EUR", "Netherlands"),
    "LU": ("EUR", "Luxembourg"),
    "ES": ("EUR", "Spain"),
    "PT": ("EUR", "Portugal"),
    "IT": ("EUR", "Italy"),
    "IE": ("EUR", "Ireland"),
    "FI": ("EUR", "Finland"),
    "EE": ("EUR", "Estonia"),
    "LV": ("EUR", "Latvia"),
    "LT": ("EUR", "Lithuania"),
    "GR": ("EUR", "Greece"),
    "MT": ("EUR", "Malta"),
    "CY": ("EUR", "Cyprus"),
    "SI": ("EUR", "Slovenia"),
    "HR": ("EUR", "Croatia"),
    "CH": ("CHF", "Switzerland"),
    "GB": ("GBP", "United Kingdom"),
    "DK": ("DKK", "Denmark"),
    "NO": ("NOK", "Norway"),
    "SE": ("SEK", "Sweden"),
    "IS": ("ISK", "Iceland"),
    "US": ("USD", "United States"),
    "CA": ("CAD", "Canada"),
    "MX": ("MXN", "Mexico"),
    "BR": ("BRL", "Brazil"),
    "AR": ("ARS", "Argentina"),
    "AU": ("AUD", "Australia"),
    "NZ": ("NZD", "New Zealand"),
    "JP": ("JPY", "Japan"),
    "KR": ("KRW", "South Korea"),
    "CN": ("CNY", "China"),
    "HK": ("HKD", "Hong Kong"),
    "SG": ("SGD", "Singapore"),
    "IN": ("INR", "India"),
    "ID": ("IDR", "Indonesia"),
    "MY": ("MYR", "Malaysia"),
    "PH": ("PHP", "Philippines"),
    "TH": ("THB", "Thailand"),
    "VN": ("VND", "Vietnam"),
    "TR": ("TRY", "Türkiye"),
    "IL": ("ILS", "Israel"),
    "AE": ("AED", "United Arab Emirates"),
    "SA": ("SAR", "Saudi Arabia"),
    "ZA": ("ZAR", "South Africa"),
    "EG": ("EGP", "Egypt"),
    "UA": ("UAH", "Ukraine"),
}

# Markets where local employment ads quote monthly compensation. Everywhere
# else defaults to annual. The salary prompt uses this only as a hint — the LLM
# may override based on what the snippets actually say.
_MONTHLY_CURRENCIES: frozenset[str] = frozenset({"CZK", "PLN", "HUF", "RON", "BGN"})

_COUNTRY_ALIASES: dict[str, str] = {
    # Common but non-ISO codes the LLM may emit. Anything not aliased and not
    # in `_COUNTRY_INFO` falls back to the location-based path so we don't
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
    info = _COUNTRY_INFO.get(country.upper())
    return info[0] if info else "USD"


def currency_to_period(currency: str) -> Literal["month", "year"]:
    """ISO-4217 currency -> default period hint ('month' or 'year')."""
    return "month" if currency in _MONTHLY_CURRENCIES else "year"


def _country_display_name(country: str | None) -> str | None:
    if not country:
        return None
    info = _COUNTRY_INFO.get(country.upper())
    return info[1] if info else None


def _resolve_country(profile: Profile) -> tuple[str, MarketProvenance]:
    """Return (ISO-3166 alpha-2, provenance) for the profile.

    Prefers `detected_country` from extraction (with alias resolution and a
    membership check against the supported market table); falls back to the
    legacy `_is_cz_location` regex on `detected_location` for backward
    compatibility on CZ-leaning ambiguous CVs and older fixtures. Unknown ->
    `'XX'` (which salary downstream treats as non-CZ, USD-defaulting).
    """
    explicit = (profile.detected_country or "").strip().upper()
    explicit = _COUNTRY_ALIASES.get(explicit, explicit)
    if explicit and explicit in _COUNTRY_INFO:
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
