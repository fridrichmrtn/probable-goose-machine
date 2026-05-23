from __future__ import annotations

import re
import statistics
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from gander.schemas import Source

ConfidenceTier = Literal["Low", "Medium", "High"]
PeriodHint = Literal["month", "year"]

_RANGE_K_RE = re.compile(
    r"(?<![\w.])(?P<low>\d+(?:[.,]\d+)?)\s*[kK]?\s*(?:-|to)\s*"
    r"(?P<high>\d+(?:[.,]\d+)?)\s*[kK](?![\w.])",
    re.IGNORECASE,
)
_SALARY_NUMBER_RE = re.compile(
    r"(?<![\w.])(?:\d+(?:[.,]\d+)?\s*[kK]|\d{1,3}(?:[ .,\u00a0]\d{3})+|\d{5,7})(?![\w.])"
)
_MONTH_RE = re.compile(
    r"\b(?:monthly|per\s+month|a\s+month|/mo|/month|mesicne|mesic|month)\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(
    r"\b(?:annual|annually|yearly|per\s+year|a\s+year|/yr|/year|p\.?a\.?|rocne)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourceRubricResult:
    tier: ConfidenceTier | None
    reason: str
    distinct_domains: int
    comparable_values: int
    spread: float | None = None


@dataclass
class _DomainEvidence:
    values: list[float] = field(default_factory=list)
    periods: set[PeriodHint] = field(default_factory=set)
    ambiguous_period: bool = False


def _normalize_domain(domain: str) -> str:
    normalized = domain.strip().casefold()
    if normalized.startswith("www."):
        return normalized[4:]
    return normalized


def _parse_number_token(token: str) -> float | None:
    compact = token.strip().replace(" ", "").replace("\u00a0", "").lower()
    try:
        if compact.endswith("k"):
            return float(compact[:-1].replace(",", ".")) * 1000
        digits = re.sub(r"\D", "", compact)
        return float(digits) if digits else None
    except ValueError:
        return None


def _overlaps(span: tuple[int, int], ranges: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(start < range_end and end > range_start for range_start, range_end in ranges)


def _salary_numbers(snippet: str) -> list[float]:
    values: list[float] = []
    range_spans: list[tuple[int, int]] = []

    for match in _RANGE_K_RE.finditer(snippet):
        range_spans.append(match.span())
        for group_name in ("low", "high"):
            value = _parse_number_token(match.group(group_name) + "k")
            if value is not None and value >= 10_000:
                values.append(value)

    for match in _SALARY_NUMBER_RE.finditer(snippet):
        if _overlaps(match.span(), range_spans):
            continue
        value = _parse_number_token(match.group(0))
        if value is not None and value >= 10_000:
            values.append(value)

    return values


def _period_hint(snippet: str) -> PeriodHint | Literal["ambiguous"] | None:
    ascii_snippet = (
        unicodedata.normalize("NFKD", snippet.casefold()).encode("ascii", "ignore").decode("ascii")
    )
    has_month = bool(_MONTH_RE.search(ascii_snippet))
    has_year = bool(_YEAR_RE.search(ascii_snippet))
    if has_month and has_year:
        return "ambiguous"
    if has_month:
        return "month"
    if has_year:
        return "year"
    return None


def evaluate_source_rubric(sources: Sequence[Source]) -> SourceRubricResult:
    by_domain: dict[str, _DomainEvidence] = {}

    for source in sources:
        domain = _normalize_domain(source.domain)
        if not domain:
            continue
        evidence = by_domain.setdefault(domain, _DomainEvidence())
        values = _salary_numbers(source.snippet)
        if not values:
            continue
        evidence.values.extend(values)
        hint = _period_hint(source.snippet)
        if hint == "ambiguous":
            evidence.ambiguous_period = True
        elif hint is not None:
            evidence.periods.add(hint)

    distinct_domains = len(by_domain)
    if distinct_domains < 2:
        return SourceRubricResult(
            tier="Low",
            reason="fewer_than_two_domains",
            distinct_domains=distinct_domains,
            comparable_values=sum(1 for evidence in by_domain.values() if evidence.values),
        )

    domain_values: list[float] = []
    domain_periods: list[PeriodHint | None] = []
    for evidence in by_domain.values():
        if not evidence.values:
            continue
        if evidence.ambiguous_period or len(evidence.periods) > 1:
            return SourceRubricResult(
                tier=None,
                reason="ambiguous_period",
                distinct_domains=distinct_domains,
                comparable_values=len(domain_values),
            )
        domain_values.append(statistics.median(evidence.values))
        domain_periods.append(next(iter(evidence.periods)) if evidence.periods else None)

    comparable_values = len(domain_values)
    if comparable_values < distinct_domains:
        return SourceRubricResult(
            tier=None,
            reason="insufficient_numeric_evidence",
            distinct_domains=distinct_domains,
            comparable_values=comparable_values,
        )

    known_periods = {period for period in domain_periods if period is not None}
    if len(known_periods) > 1:
        return SourceRubricResult(
            tier=None,
            reason="mixed_period",
            distinct_domains=distinct_domains,
            comparable_values=comparable_values,
        )
    if known_periods and any(period is None for period in domain_periods):
        return SourceRubricResult(
            tier=None,
            reason="ambiguous_period",
            distinct_domains=distinct_domains,
            comparable_values=comparable_values,
        )

    median = statistics.median(domain_values)
    if median <= 0:
        return SourceRubricResult(
            tier=None,
            reason="invalid_median",
            distinct_domains=distinct_domains,
            comparable_values=comparable_values,
        )
    spread = max(abs(value - median) / median for value in domain_values)

    if spread > 0.50:
        return SourceRubricResult(
            tier="Low",
            reason="source_disagreement",
            distinct_domains=distinct_domains,
            comparable_values=comparable_values,
            spread=spread,
        )
    if distinct_domains == 2:
        return SourceRubricResult(
            tier="Medium",
            reason="two_domains",
            distinct_domains=distinct_domains,
            comparable_values=comparable_values,
            spread=spread,
        )
    if spread >= 0.25:
        return SourceRubricResult(
            tier="Medium",
            reason="moderate_spread",
            distinct_domains=distinct_domains,
            comparable_values=comparable_values,
            spread=spread,
        )
    return SourceRubricResult(
        tier="High",
        reason="three_plus_domains_agree",
        distinct_domains=distinct_domains,
        comparable_values=comparable_values,
        spread=spread,
    )
