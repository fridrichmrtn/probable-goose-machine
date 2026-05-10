from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ddgs import DDGS
from pydantic import ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from jobfit.errors import StageFailure, stage_boundary
from jobfit.llm import LLMClient
from jobfit.obs import emit
from jobfit.schemas import Profile, SalaryEstimate, Source

_PROMPT_PATH = Path(__file__).parent / "prompts" / "salary.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

_CZ_MARKERS = ("czech", "cz", "praha", "prague", "brno", "ostrava")

# PRD §4.6 canonical user-facing copy for any salary failure. The four logical
# failure branches differ only in their structured event reason + debug_detail;
# the reviewer-visible string is always this one.
_INSUFFICIENT_DATA_MSG = "Insufficient market data for this profile"


def _is_cz_location(location: str | None) -> bool:
    if not location:
        return True
    lower = location.lower()
    return any(marker in lower for marker in _CZ_MARKERS)


def build_queries(profile: Profile) -> list[str]:
    """Build 2-3 locality-first search queries plus an optional EUR cross-check.

    Pure function. No I/O.
    """
    role = profile.detected_role.strip() or "data scientist"
    location = profile.detected_location
    cz = _is_cz_location(location)

    queries: list[str]
    if cz:
        city = location.strip() if location else "Praha"
        queries = [
            f"{role} salary {city} site:platy.cz OR site:profesia.cz",
            f"{role} mzda CZK 2025",
            f"{role} salary czech republic site:glassdoor.com",
        ]
    else:
        city = location.strip() if location else "Europe"
        queries = [
            f"{role} salary {city} site:glassdoor.com OR site:levels.fyi",
            f"{role} salary EUR 2025 {city}",
        ]

    # Senior EUR cross-check is the senior-specific market signal: lifts the cap
    # to 4 so it survives next to the locality queries.
    if profile.detected_years_experience >= 10:
        queries.append(f"senior {role} salary EUR Europe")
        return queries[:4]

    return queries[:3]


@retry(stop=stop_after_attempt(2), wait=wait_exponential_jitter(initial=1, max=3), reraise=True)
def _ddg_text(query: str) -> list[dict[str, Any]]:
    with DDGS() as ddg:
        return list(ddg.text(query, max_results=8))


def _to_source(raw: dict[str, Any]) -> Source | None:
    url = raw.get("href") or raw.get("url")
    snippet = raw.get("body") or raw.get("snippet") or ""
    if not url:
        return None
    try:
        return Source(url=url, snippet=snippet, domain=urlparse(url).netloc)
    except ValidationError:
        return None


async def search(queries: list[str]) -> list[Source]:
    """Run DDG queries off the event loop, dedupe by URL, return up to 8 sources.

    Raises ``RuntimeError`` if fewer than 2 valid sources come back; the caller's
    ``stage_boundary`` converts that into a ``StageFailure``.
    """
    raw_results: list[dict[str, Any]] = []
    for q in queries:
        results = await asyncio.to_thread(_ddg_text, q)
        raw_results.extend(results)

    seen: set[str] = set()
    sources: list[Source] = []
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
        sources.append(source)
        if len(sources) >= 8:
            break

    emit(
        "salary",
        "salary_search",
        n_queries=len(queries),
        raw_results=len(raw_results),
        dedup_results=len(sources),
        dropped_invalid_url=dropped_invalid,
    )

    if len(sources) < 2:
        raise RuntimeError(_INSUFFICIENT_DATA_MSG)

    return sources


async def estimate_salary(profile: Profile) -> SalaryEstimate | StageFailure:
    async with stage_boundary("salary") as cm:
        queries = build_queries(profile)
        sources = await search(queries)

        client = LLMClient()
        user_payload = json.dumps(
            {
                "context": {
                    "role": profile.detected_role,
                    "location": profile.detected_location,
                    "years": profile.detected_years_experience,
                },
                "results": [s.model_dump(mode="json") for s in sources],
            }
        )
        estimate = await client.complete_json(
            system=_SYSTEM_PROMPT,
            user=user_payload,
            schema=SalaryEstimate,
            model="reasoning",
            temperature=0.0,
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

        input_urls = {str(s.url) for s in sources}
        kept = [s for s in estimate.sources if str(s.url) in input_urls]
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
