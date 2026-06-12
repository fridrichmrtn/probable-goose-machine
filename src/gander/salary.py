from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ddgs import DDGS
from ddgs.exceptions import RatelimitException
from pydantic import ValidationError

from gander.config import env_float, env_int
from gander.errors import StageFailure, stage_boundary
from gander.llm import get_client
from gander.market import currency_to_period, resolve_market
from gander.obs import emit
from gander.schemas import Profile, SalaryEstimate, Source

_PROMPT_PATH = Path(__file__).parent / "prompts" / "salary.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

# PRD §4.6 canonical user-facing copy for any salary failure. Every escape
# branch (search transport error, LLM transport error, parse failure, logical
# failure) surfaces this string; differentiation lives in structured
# `stage_failure.reason` events + `debug_detail`.
_INSUFFICIENT_DATA_MSG = "Insufficient market data for this profile"
# Distinct copy for the transient outcome: search transport refused us, the
# market data itself is not missing. §4.6 covers the "no data" path above.
_RATELIMIT_MSG = "Salary search is temporarily rate-limited — please try again in a moment"
_DEFAULT_SALARY_SEARCH_BACKENDS = "brave,duckduckgo,yahoo,mojeek"
_SALARY_SEARCH_MAX_RESULTS = 20
_SALARY_LLM_SOURCE_LIMIT = 8
_DEFAULT_SALARY_SEARCH_TIMEOUT_S = 6
_DEFAULT_SALARY_SEARCH_TOTAL_TIMEOUT_S = 20
_MAX_SALARY_SEARCH_TIMEOUT_S = 15
_MAX_SALARY_SEARCH_TOTAL_TIMEOUT_S = 60.0
_JUNIOR_CZK_MONTH_HIGH_CAP = 90_000
# CZ baseline only: the curated boards we trust for CZ profiles. Outside CZ we
# stop applying this list and let live-search ranking stand — the live-search
# design philosophy is "trust the search engine; don't maintain per-country
# tables." See tasks/T46_salary_multi_market.md.
_SALARY_DOMAIN_PRIORITY: tuple[str, ...] = (
    "platy.cz",
    "profesia.cz",
    "glassdoor",
    "levels.fyi",
)

_ISO_4217_SHAPE = re.compile(r"^[A-Z]{3}$")

# Process-wide search cache: identical queries within the TTL reuse the prior
# results instead of re-hitting DDG (rate-limit pressure on a shared Space IP).
_DDG_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_DDG_CACHE_MAX_ENTRIES = 512
_DEFAULT_DDG_CACHE_TTL_S = 7 * 24 * 3600


def _ddg_cache_ttl_s() -> int:
    return env_int(
        "GANDER_DDG_CACHE_TTL_S",
        _DEFAULT_DDG_CACHE_TTL_S,
        min_value=0,
        max_value=30 * 24 * 3600,
    )


def _salary_search_backends() -> str:
    raw = os.environ.get("GANDER_SALARY_SEARCH_BACKENDS", _DEFAULT_SALARY_SEARCH_BACKENDS)
    backends = [part.strip() for part in raw.split(",") if part.strip()]
    return ",".join(backends) if backends else _DEFAULT_SALARY_SEARCH_BACKENDS


def _salary_search_timeout_s() -> int:
    return env_int(
        "GANDER_SALARY_SEARCH_TIMEOUT_S",
        _DEFAULT_SALARY_SEARCH_TIMEOUT_S,
        max_value=_MAX_SALARY_SEARCH_TIMEOUT_S,
    )


def _salary_search_total_timeout_s() -> float:
    return env_float(
        "GANDER_SALARY_SEARCH_TOTAL_TIMEOUT_S",
        _DEFAULT_SALARY_SEARCH_TOTAL_TIMEOUT_S,
        max_value=_MAX_SALARY_SEARCH_TOTAL_TIMEOUT_S,
    )


def _remaining_search_timeout_s(deadline: float) -> float:
    remaining = deadline - time.perf_counter()
    if remaining <= 0:
        raise TimeoutError("salary search timed out")
    return remaining


def _salary_query_year(today: date | None = None) -> int:
    return (today or date.today()).year


def _apply_sanity_caps(profile: Profile, estimate: SalaryEstimate) -> SalaryEstimate:
    if (
        profile.seniority_band == "junior"
        and profile.detected_years_experience <= 2
        and estimate.currency == "CZK"
        and estimate.period == "month"
        and estimate.high > _JUNIOR_CZK_MONTH_HIGH_CAP
    ):
        original_low = estimate.low
        original_high = estimate.high
        high = _JUNIOR_CZK_MONTH_HIGH_CAP
        low = min(estimate.low, high - 10_000)
        emit(
            "salary",
            "salary_sanity_cap",
            cap="junior_czk_month",
            original_low=original_low,
            original_high=original_high,
            capped_low=low,
            capped_high=high,
        )
        reasoning = (
            estimate.reasoning.rstrip()
            + " Junior CZK/month sanity cap applied for a <=2-year junior profile."
        )
        return estimate.model_copy(update={"low": low, "high": high, "reasoning": reasoning})
    return estimate


def build_queries(profile: Profile, *, today: date | None = None) -> list[str]:
    """Build 2-3 locality-first search queries with country/currency hints.

    Pure function. No I/O.

    CZ profiles keep the curated `site:platy.cz` / `site:profesia.cz` baseline.
    All other countries delegate to live search: queries include the country
    name and the local ISO-4217 currency token, but no `site:` lock-in — the
    design avoids per-country curated domain tables on purpose
    (tasks/T46_salary_multi_market.md).

    Uses `profile.canonical_role` when set (T27, R4). When the canonical role
    differs from the verbatim headline, the verbatim headline is dropped so
    DDG doesn't drift to junk pages. Management profiles get an extra
    management-specific query.
    """
    canonical = (profile.canonical_role or "").strip()
    detected = profile.detected_role.strip()
    role = canonical or detected or "data scientist"
    location = profile.detected_location
    spec = resolve_market(profile)
    country = spec.country
    country_name = spec.country_name
    currency = spec.currency
    year = _salary_query_year(today)

    queries: list[str]
    if country == "CZ":
        city = location.strip() if location else "Praha"
        queries = [
            f"{role} salary {city} site:platy.cz",
            f"{role} salary {city} site:profesia.cz",
            f"{role} mzda CZK {year}",
        ]
        if not (profile.is_management and canonical and profile.detected_years_experience >= 10):
            queries.append(f"{role} salary czech republic site:glassdoor.com")
        mgmt_currency_token = f"CZK {year}"
        mgmt_city = city
    elif country == "XX":
        queries = [
            f"{role} salary USD {year}",
            f"{role} compensation USD {year}",
        ]
        mgmt_currency_token = f"USD {year}"
        mgmt_city = ""
    else:
        # Non-CZ: live-search-first. No site: lock-in. Country name disambiguates;
        # the local currency token primes the search engine toward local boards.
        location_hint = location.strip() if location else (country_name or "")
        city_or_country = location_hint or (country_name or "")
        queries = [f"{role} salary {city_or_country} {currency} {year}".strip()]
        if country_name:
            queries.append(f"{role} {country_name} compensation {year}")
        else:
            queries.append(f"{role} salary {currency} {year}")
        mgmt_currency_token = f"{currency} {year}"
        mgmt_city = city_or_country

    if profile.is_management and canonical:
        query_parts = [canonical, "manager salary", mgmt_city, mgmt_currency_token]
        queries.insert(0, " ".join(part for part in query_parts if part).strip())

    if profile.detected_years_experience >= 10:
        if country == "CZ":
            queries.append(f"senior {role} salary EUR Europe {year}")
        elif country_name:
            queries.append(f"senior {role} salary {country_name} {currency} {year}")
        else:
            queries.append(f"senior {role} salary {currency} {year}")

    # Cap covers all attached signals: 2-3 locality + optional management + optional senior.
    return queries[:5]


def _ddg_text(query: str, timeout_s: float | None = None) -> list[dict[str, Any]]:
    backends = _salary_search_backends()
    timeout = _salary_search_timeout_s() if timeout_s is None else timeout_s
    with DDGS(timeout=timeout) as ddg:  # type: ignore[arg-type]
        try:
            return list(
                ddg.text(
                    query,
                    max_results=_SALARY_SEARCH_MAX_RESULTS,
                    backend=backends,
                )
            )
        except Exception:
            if backends == "auto":
                raise
            return list(
                ddg.text(
                    query,
                    max_results=_SALARY_SEARCH_MAX_RESULTS,
                    backend="auto",
                )
            )


def _cached_ddg_text(query: str, timeout_s: float | None = None) -> list[dict[str, Any]]:
    key = query.strip()
    now = time.monotonic()
    cached = _DDG_CACHE.get(key)
    if cached is not None and now - cached[0] < _ddg_cache_ttl_s():
        emit("salary", "ddg_cache_hit", query_len=len(key))
        # Copies, so callers can't mutate rows served to later requests.
        return [dict(row) for row in cached[1]]
    results = _ddg_text(query, timeout_s)
    if len(_DDG_CACHE) >= _DDG_CACHE_MAX_ENTRIES:
        _DDG_CACHE.pop(next(iter(_DDG_CACHE)))
    _DDG_CACHE[key] = (now, results)
    return results


def _to_source(raw: dict[str, Any]) -> Source | None:
    url = raw.get("href") or raw.get("url")
    snippet = raw.get("body") or raw.get("snippet") or ""
    if not url:
        return None
    try:
        return Source(url=url, snippet=snippet, domain=urlparse(url).netloc)
    except ValidationError:
        return None


def _salary_domain_rank(source: Source) -> int:
    domain = source.domain.casefold()
    for rank, token in enumerate(_SALARY_DOMAIN_PRIORITY):
        if token in domain:
            return rank
    return len(_SALARY_DOMAIN_PRIORITY)


def _prioritize_sources(sources: list[Source], *, apply_priority: bool) -> list[Source]:
    """Rank sources for the LLM. CZ -> curated priority list; everywhere else
    preserves search-engine order (the live-search-first design philosophy).
    """
    if not apply_priority:
        return list(sources)
    return [
        source
        for _, source in sorted(
            enumerate(sources),
            key=lambda indexed: (_salary_domain_rank(indexed[1]), indexed[0]),
        )
    ]


def _tld_histogram(sources: list[Source]) -> dict[str, int]:
    """Count sources by their TLD suffix (`.cz`, `.de`, `.com`, …).

    Used in telemetry so we can observe — without curating — whether live
    search consistently surfaces local boards for a given country.
    """
    counts: dict[str, int] = {}
    for source in sources:
        domain = source.domain.lower()
        tld = "." + domain.rsplit(".", 1)[-1] if "." in domain else domain or "(empty)"
        counts[tld] = counts.get(tld, 0) + 1
    return counts


async def search(
    queries: list[str],
    *,
    country: str,
    currency_hint: str,
) -> list[Source]:
    """Run DDG queries off the event loop, dedupe by URL, return up to 8 sources.

    Raises ``RuntimeError`` if fewer than 2 valid sources come back; the caller's
    ``stage_boundary`` converts that into a ``StageFailure``.
    """
    search_backends = _salary_search_backends()
    raw_results: list[dict[str, Any]] = []
    failed_queries: list[dict[str, str]] = []
    total_timeout_s = _salary_search_total_timeout_s()
    deadline = time.perf_counter() + total_timeout_s

    async def _run_query(query: str) -> tuple[list[dict[str, Any]], dict[str, str] | None]:
        try:
            timeout_s = min(
                float(_salary_search_timeout_s()), _remaining_search_timeout_s(deadline)
            )
            return await asyncio.to_thread(_cached_ddg_text, query, timeout_s), None
        except Exception as exc:
            # DDG occasionally rejects one query shape (e.g. site:a OR site:b)
            # while the others succeed. Treat single-query failures as expected
            # and continue; only collapse to StageFailure if <2 sources survive
            # in aggregate.
            return [], {"query": query, "exc_type": type(exc).__name__}

    # build_queries caps fan-out at five today. If that grows, add a small
    # semaphore here before DDG starts rate-limiting one runner IP.
    try:
        gathered = await asyncio.wait_for(
            asyncio.gather(*(_run_query(q) for q in queries)),
            timeout=total_timeout_s,
        )
    except TimeoutError as exc:
        emit(
            "salary",
            "salary_search",
            n_queries=len(queries),
            raw_results=0,
            candidate_sources=0,
            dedup_results=0,
            dropped_invalid_url=0,
            failed_queries=len(queries),
            search_backends=search_backends,
            query_max_results=_SALARY_SEARCH_MAX_RESULTS,
            country=country,
            currency_hint=currency_hint,
            sources_per_tld={},
            timeout_s=total_timeout_s,
            reason="total_timeout",
        )
        raise RuntimeError(f"{_INSUFFICIENT_DATA_MSG} (search timeout)") from exc

    for results, failure in gathered:
        raw_results.extend(results)
        if failure is not None:
            failed_queries.append(failure)

    seen: set[str] = set()
    candidates: list[Source] = []
    dropped_invalid = 0
    for raw in raw_results:
        url = raw.get("href") or raw.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        source = _to_source(raw)
        if source is None:
            dropped_invalid += 1
            continue
        candidates.append(source)

    sources = _prioritize_sources(candidates, apply_priority=(country == "CZ"))[
        :_SALARY_LLM_SOURCE_LIMIT
    ]

    emit(
        "salary",
        "salary_search",
        n_queries=len(queries),
        raw_results=len(raw_results),
        candidate_sources=len(candidates),
        dedup_results=len(sources),
        dropped_invalid_url=dropped_invalid,
        failed_queries=len(failed_queries),
        search_backends=search_backends,
        query_max_results=_SALARY_SEARCH_MAX_RESULTS,
        country=country,
        currency_hint=currency_hint,
        sources_per_tld=_tld_histogram(sources),
    )
    if failed_queries:
        emit("salary", "query_failures", failures=failed_queries)

    if len(sources) < 2:
        if failed_queries:
            types = sorted({fq["exc_type"] for fq in failed_queries})
            # RatelimitException has no subclasses and ddgs raises it directly,
            # so the recorded class name identifies it exactly.
            if types == [RatelimitException.__name__]:
                raise RuntimeError(_RATELIMIT_MSG)
            raise RuntimeError(f"{_INSUFFICIENT_DATA_MSG} (query failures: {','.join(types)})")
        raise RuntimeError(_INSUFFICIENT_DATA_MSG)

    return sources


async def estimate_salary(profile: Profile) -> SalaryEstimate | StageFailure:
    async with stage_boundary("salary") as cm:
        t0 = time.perf_counter()

        def _ms() -> int:
            return int((time.perf_counter() - t0) * 1000)

        queries = build_queries(profile)
        spec = resolve_market(profile)
        country = spec.country
        country_name = spec.country_name
        currency_hint = spec.currency
        period_hint = spec.period

        try:
            sources = await search(queries, country=country, currency_hint=currency_hint)
        except Exception as exc:
            # Catches every search escape path (tenacity-exhausted transport errors,
            # the deliberate `<2 sources` RuntimeError, anything else) so the
            # user-facing string never falls back to `stage_boundary`'s `str(exc)`
            # default, which would leak ddgs/tenacity internals.
            user_msg = _RATELIMIT_MSG if _RATELIMIT_MSG in str(exc) else _INSUFFICIENT_DATA_MSG
            emit(
                "salary",
                "stage_failure",
                reason="search_error",
                exc_type=type(exc).__name__,
                duration_ms=_ms(),
            )
            return StageFailure(
                stage="salary",
                user_message=user_msg,
                debug_detail=f"{type(exc).__name__}: {exc}",
            )

        client = get_client()
        # Canonical fields feed the LLM the seniority signal it needs to anchor
        # correctly on management profiles even when the snippets are IC-only
        # (T27, R5). Fall back to the verbatim headline when normalization
        # didn't run / didn't resolve.
        user_payload = json.dumps(
            {
                "context": {
                    "role": profile.canonical_role or profile.detected_role,
                    "seniority": profile.seniority_band,
                    "is_management": profile.is_management,
                    "location": profile.detected_location,
                    "country": country if country != "XX" else None,
                    "country_name": country_name,
                    "currency_hint": currency_hint,
                    "period_hint": period_hint,
                    "market_provenance": spec.provenance,
                    "years": profile.detected_years_experience,
                    "geography_note": (
                        "geography unknown; broad USD/year search is a market-blind "
                        "reference, not a localized personal estimate"
                        if country == "XX"
                        else None
                    ),
                },
                "results": [s.model_dump(mode="json") for s in sources],
            }
        )
        try:
            estimate = await client.complete_json(
                system=_SYSTEM_PROMPT,
                user=user_payload,
                schema=SalaryEstimate,
                model="reasoning",
                temperature=0.0,
                max_retries=2,
                max_tokens=768,
            )
        except Exception as exc:
            emit(
                "salary",
                "stage_failure",
                reason="llm_error",
                exc_type=type(exc).__name__,
                duration_ms=_ms(),
            )
            return StageFailure(
                stage="salary",
                user_message=_INSUFFICIENT_DATA_MSG,
                debug_detail=f"{type(exc).__name__}: {exc}",
            )
        if not isinstance(estimate, SalaryEstimate):
            emit(
                "salary",
                "stage_failure",
                reason="invalid_llm_output",
                got_type=type(estimate).__name__,
                duration_ms=_ms(),
            )
            return StageFailure(
                stage="salary",
                user_message=_INSUFFICIENT_DATA_MSG,
                debug_detail=f"complete_json returned {type(estimate).__name__}",
            )

        normalized_currency = (estimate.currency or "").strip().upper()
        if normalized_currency != estimate.currency:
            estimate = estimate.model_copy(update={"currency": normalized_currency})

        estimate = _apply_sanity_caps(profile, estimate)

        # Verify every emitted source against the inputs by URL AND replace the
        # snippet/domain with the actual DDG-returned values. The LLM is allowed
        # to surface a subset of the input URLs, but it can never invent the
        # snippet text or domain field — those flow back from `sources` so that
        # `confidence.judge` downstream consumes only data the search actually
        # produced. Closes the fabrication channel flagged by codex P1.
        input_sources_by_url = {str(s.url): s for s in sources}
        kept: list[Source] = []
        for est_src in estimate.sources:
            matched = input_sources_by_url.get(str(est_src.url))
            if matched is None:
                continue
            kept.append(matched)
        dropped = len(estimate.sources) - len(kept)
        if dropped:
            emit(
                "salary",
                "salary_sources_dropped",
                dropped=dropped,
                reason="url_not_in_inputs",
            )
        if not kept:
            emit(
                "salary",
                "stage_failure",
                reason="no_verifiable_sources",
                returned=len(estimate.sources),
                duration_ms=_ms(),
            )
            return StageFailure(
                stage="salary",
                user_message=_INSUFFICIENT_DATA_MSG,
                debug_detail=f"model_urls={[str(s.url) for s in estimate.sources]}",
            )
        # ISO-4217 shape only. The pre-T46 `{CZK, EUR, USD}` whitelist
        # actively rejected legitimate non-CZ-leaning outputs (JPY, GBP, CHF,
        # PLN, …); the shape check still catches LLM garbage like `"EURO"` or
        # `"$"`.
        if not _ISO_4217_SHAPE.fullmatch(estimate.currency):
            emit(
                "salary",
                "stage_failure",
                reason="invalid_currency_shape",
                currency=estimate.currency,
                duration_ms=_ms(),
            )
            return StageFailure(
                stage="salary",
                user_message=_INSUFFICIENT_DATA_MSG,
                debug_detail=f"currency={estimate.currency!r}",
            )
        # Per-currency period hint: warn but accept. The snippets win — per-
        # currency caps and stricter invariants wait for empirical telemetry.
        expected_period = currency_to_period(estimate.currency)
        if estimate.period != expected_period:
            emit(
                "salary",
                "period_mismatch",
                currency=estimate.currency,
                period=estimate.period,
                expected_period=expected_period,
                country=country,
            )
        if estimate.low >= estimate.high:
            emit(
                "salary",
                "stage_failure",
                reason="invalid_range",
                low=estimate.low,
                high=estimate.high,
                duration_ms=_ms(),
            )
            return StageFailure(
                stage="salary",
                user_message=_INSUFFICIENT_DATA_MSG,
                debug_detail=f"low={estimate.low} high={estimate.high}",
            )

        verified = estimate.model_copy(update={"sources": kept})
        emit(
            "salary",
            "salary_estimate",
            low=verified.low,
            high=verified.high,
            currency=verified.currency,
            period=verified.period,
            n_sources=len(verified.sources),
            country=country,
            currency_hint=currency_hint,
        )
        emit(
            "salary",
            "done",
            duration_ms=_ms(),
            n_sources=len(verified.sources),
            country=country,
            currency=verified.currency,
            period=verified.period,
        )
        return verified

    return cm.failure  # type: ignore[return-value]
