from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ddgs import DDGS
from pydantic import ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from gander.errors import StageFailure, stage_boundary
from gander.llm import LLMClient
from gander.obs import emit
from gander.schemas import Profile, SalaryEstimate, Source

_PROMPT_PATH = Path(__file__).parent / "prompts" / "salary.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

# Word-boundary token match — substring "cz" inside "Aczland" or "Czeladz" must
# not flip CZ detection. Tokens are matched case-insensitively against any
# letter-bounded run in the location string.
_CZ_TOKEN_PATTERN = re.compile(
    r"\b(?:czech|cz|praha|prague|brno|ostrava)\b",
    re.IGNORECASE,
)

# PRD §4.6 canonical user-facing copy for any salary failure. Every escape
# branch (search transport error, LLM transport error, parse failure, logical
# failure) surfaces this string; differentiation lives in structured
# `stage_failure.reason` events + `debug_detail`.
_INSUFFICIENT_DATA_MSG = "Insufficient market data for this profile"
_DEFAULT_SALARY_SEARCH_BACKENDS = "brave,duckduckgo,yahoo,mojeek"
_SALARY_SEARCH_MAX_RESULTS = 20
_SALARY_LLM_SOURCE_LIMIT = 8
_JUNIOR_CZK_MONTH_HIGH_CAP = 90_000
_SALARY_DOMAIN_PRIORITY: tuple[str, ...] = (
    "platy.cz",
    "profesia.cz",
    "glassdoor",
    "levels.fyi",
)


def _salary_search_backends() -> str:
    raw = os.environ.get("GANDER_SALARY_SEARCH_BACKENDS", _DEFAULT_SALARY_SEARCH_BACKENDS)
    backends = [part.strip() for part in raw.split(",") if part.strip()]
    return ",".join(backends) if backends else _DEFAULT_SALARY_SEARCH_BACKENDS


def _is_cz_location(location: str | None) -> bool:
    if not location:
        return True
    return bool(_CZ_TOKEN_PATTERN.search(location))


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


def build_queries(profile: Profile) -> list[str]:
    """Build 2-3 locality-first search queries plus an optional EUR cross-check.

    Pure function. No I/O.

    Uses `profile.canonical_role` when set (T27, R4). When the canonical role
    differs from the verbatim headline (i.e. T27 normalized away a non-market
    or tagline-shape headline), the verbatim headline is dropped from the
    queries so DDG doesn't drift to junk pages. Management profiles get an
    extra management-specific query.
    """
    canonical = (profile.canonical_role or "").strip()
    detected = profile.detected_role.strip()
    role = canonical or detected or "data scientist"
    location = profile.detected_location
    cz = _is_cz_location(location)

    queries: list[str]
    if cz:
        city = location.strip() if location else "Praha"
        queries = [
            f"{role} salary {city} site:platy.cz",
            f"{role} salary {city} site:profesia.cz",
            f"{role} mzda CZK 2025",
        ]
        if not (profile.is_management and canonical and profile.detected_years_experience >= 10):
            queries.append(f"{role} salary czech republic site:glassdoor.com")
        mgmt_currency_token = "CZK 2025"
    else:
        city = location.strip() if location else "Europe"
        queries = [
            f"{role} salary {city} site:glassdoor.com OR site:levels.fyi",
            f"{role} salary EUR 2025 {city}",
        ]
        mgmt_currency_token = "EUR 2025"

    if profile.is_management and canonical:
        queries.insert(0, f"{canonical} manager salary {city} {mgmt_currency_token}")

    if profile.detected_years_experience >= 10:
        queries.append(f"senior {role} salary EUR Europe")

    # Cap covers all attached signals: 2-3 locality + optional management + optional senior.
    return queries[:5]


@retry(stop=stop_after_attempt(2), wait=wait_exponential_jitter(initial=1, max=3), reraise=True)
def _ddg_text(query: str) -> list[dict[str, Any]]:
    backends = _salary_search_backends()
    with DDGS() as ddg:
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


def _prioritize_sources(sources: list[Source]) -> list[Source]:
    return [
        source
        for _, source in sorted(
            enumerate(sources),
            key=lambda indexed: (_salary_domain_rank(indexed[1]), indexed[0]),
        )
    ]


async def search(queries: list[str]) -> list[Source]:
    """Run DDG queries off the event loop, dedupe by URL, return up to 8 sources.

    Raises ``RuntimeError`` if fewer than 2 valid sources come back; the caller's
    ``stage_boundary`` converts that into a ``StageFailure``.
    """
    search_backends = _salary_search_backends()
    raw_results: list[dict[str, Any]] = []
    failed_queries: list[dict[str, str]] = []

    async def _run_query(query: str) -> tuple[list[dict[str, Any]], dict[str, str] | None]:
        try:
            return await asyncio.to_thread(_ddg_text, query), None
        except Exception as exc:
            # DDG occasionally rejects one query shape (e.g. site:a OR site:b)
            # while the others succeed. Treat single-query failures as expected
            # and continue; only collapse to StageFailure if <2 sources survive
            # in aggregate.
            return [], {"query": query, "exc_type": type(exc).__name__}

    # build_queries caps fan-out at five today. If that grows, add a small
    # semaphore here before DDG starts rate-limiting one runner IP.
    for results, failure in await asyncio.gather(*(_run_query(q) for q in queries)):
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

    sources = _prioritize_sources(candidates)[:_SALARY_LLM_SOURCE_LIMIT]

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
    )
    if failed_queries:
        emit("salary", "query_failures", failures=failed_queries)

    if len(sources) < 2:
        if failed_queries:
            types = sorted({fq["exc_type"] for fq in failed_queries})
            raise RuntimeError(f"{_INSUFFICIENT_DATA_MSG} (query failures: {','.join(types)})")
        raise RuntimeError(_INSUFFICIENT_DATA_MSG)

    return sources


async def estimate_salary(profile: Profile) -> SalaryEstimate | StageFailure:
    async with stage_boundary("salary") as cm:
        queries = build_queries(profile)

        try:
            sources = await search(queries)
        except Exception as exc:
            # Catches every search escape path (tenacity-exhausted transport errors,
            # the deliberate `<2 sources` RuntimeError, anything else) so the
            # user-facing string never falls back to `stage_boundary`'s `str(exc)`
            # default, which would leak ddgs/tenacity internals.
            emit(
                "salary",
                "stage_failure",
                reason="search_error",
                exc_type=type(exc).__name__,
            )
            return StageFailure(
                stage="salary",
                user_message=_INSUFFICIENT_DATA_MSG,
                debug_detail=f"{type(exc).__name__}: {exc}",
            )

        client = LLMClient()
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
                    "years": profile.detected_years_experience,
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
            )
        except Exception as exc:
            emit(
                "salary",
                "stage_failure",
                reason="llm_error",
                exc_type=type(exc).__name__,
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
            )
            return StageFailure(
                stage="salary",
                user_message=_INSUFFICIENT_DATA_MSG,
                debug_detail=f"complete_json returned {type(estimate).__name__}",
            )

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
            )
            return StageFailure(
                stage="salary",
                user_message=_INSUFFICIENT_DATA_MSG,
                debug_detail=f"model_urls={[str(s.url) for s in estimate.sources]}",
            )
        if estimate.currency not in {"CZK", "EUR", "USD"}:
            emit(
                "salary",
                "stage_failure",
                reason="unsupported_currency",
                currency=estimate.currency,
            )
            return StageFailure(
                stage="salary",
                user_message=_INSUFFICIENT_DATA_MSG,
                debug_detail=f"currency={estimate.currency!r}",
            )
        if (estimate.currency == "CZK" and estimate.period != "month") or (
            estimate.currency in {"EUR", "USD"} and estimate.period != "year"
        ):
            emit(
                "salary",
                "stage_failure",
                reason="currency_period_mismatch",
                currency=estimate.currency,
                period=estimate.period,
            )
            return StageFailure(
                stage="salary",
                user_message=_INSUFFICIENT_DATA_MSG,
                debug_detail=f"currency={estimate.currency!r} period={estimate.period!r}",
            )
        if estimate.low >= estimate.high:
            emit(
                "salary",
                "stage_failure",
                reason="invalid_range",
                low=estimate.low,
                high=estimate.high,
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
        )
        return verified

    return cm.failure  # type: ignore[return-value]
