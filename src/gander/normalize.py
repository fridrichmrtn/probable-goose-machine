"""Deterministic role normalization for the salary stage (R4/R5 in T27).

`salary.build_queries` interpolates `profile.detected_role` verbatim. For
non-market headlines like `Member of Staff`, `Data Gardener`, `Founding
Engineer`, or tagline-shape strings like `Data Gardener | AI @Stealth`, the
DDG queries return junk or drift to generic IC pages — and the salary
estimator produces an IC-band number for what's actually a senior management
profile.

Polarity: **market-token allowlist FIRST**, denylist + tagline-shape SECOND,
LLM fallback LAST. A hardcoded denylist of named non-market headlines will
rot — the next operator's headline won't be on it. Polarity-flipped recognition
makes "doesn't match a market token" the signal, which generalizes to the
next "Data Gardener" without a denylist update.

The sync `normalize_role` covers every deterministic path; the async
`normalize_role_with_llm_fallback` wraps it with an extraction-slot LLM
canonicalize call for the leftover "unrecognized" cases.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Final, Literal

from pydantic import BaseModel, Field

from gander import obs

SeniorityBand = Literal["junior", "mid", "senior", "staff", "head", "director"]
NormalizationSource = Literal[
    "market_token",
    "named_headline",
    "tagline_shape",
    "experience_recovery",
    "llm_fallback",
    "unrecognized",
]


class NormalizedRole(BaseModel):
    canonical_role: str
    seniority_band: SeniorityBand
    is_management: bool
    source: NormalizationSource


# Modifier tokens — first hit (longest-first) sets the band.
_SENIORITY_TOKENS: Final[dict[str, tuple[SeniorityBand, bool]]] = {
    "junior": ("junior", False),
    "jr": ("junior", False),
    "senior": ("senior", False),
    "sr": ("senior", False),
    "staff": ("staff", False),
    "principal": ("staff", False),
    "lead": ("senior", False),
    "head of": ("head", True),
    "head": ("head", True),
    "director of": ("director", True),
    "director": ("director", True),
    "vp": ("director", True),
    "chief": ("director", True),
    "manager": ("senior", True),
    "manazer": ("senior", True),
    "vedouci": ("head", True),
    "reditel": ("director", True),
}

# Bare role nouns — presence alone makes a string look like a market role.
_ROLE_TOKENS: Final[frozenset[str]] = frozenset(
    {"scientist", "engineer", "analyst", "developer", "consultant", "analytik", "vyvojar"}
)

# Named non-market headlines that masquerade as roles. Compared accent-stripped + lowercased.
_NAMED_HEADLINE_DENYLIST: Final[frozenset[str]] = frozenset(
    {"member of staff", "data gardener", "founding engineer", "ai whisperer"}
)

# Separator characters that signal a tagline-shape headline.
_TAGLINE_CHARS: Final[frozenset[str]] = frozenset("|@&")
_TITLE_WORD_RE: Final = re.compile(r"[0-9A-Za-zÀ-ž&]+", re.UNICODE)

_BAND_RANK: Final[dict[SeniorityBand, int]] = {
    "junior": 0,
    "mid": 1,
    "senior": 2,
    "staff": 3,
    "head": 4,
    "director": 5,
}

_SORTED_SENIORITY_TOKENS: Final = sorted(_SENIORITY_TOKENS.items(), key=lambda kv: -len(kv[0]))
_ROLE_TOKEN_RE: Final = re.compile(rf"\b(?:{'|'.join(_ROLE_TOKENS)})\b")
_AT_EMPLOYER_RE: Final = re.compile(r"\s+at\s+", flags=re.IGNORECASE)
_DURATION_SUFFIX_RE: Final = re.compile(
    r"\b\d+\s+(?:years?|months?|tenure|let|měsíc|měsíce|měsíců|mesic|mesice|mesicu)\b.*$",
    flags=re.IGNORECASE,
)


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _norm(s: str) -> str:
    return _strip_accents(s).lower()


def _classify(text: str) -> tuple[SeniorityBand, bool] | None:
    """Map a role string to `(band, is_management)` via market tokens, or `None`."""
    n = _norm(text)
    for token, (band, mgmt) in _SORTED_SENIORITY_TOKENS:
        if re.search(rf"\b{re.escape(token)}\b", n):
            return band, mgmt
    if _ROLE_TOKEN_RE.search(n):
        return "mid", False
    return None


def seniority_rank(title: str) -> int:
    """Comparable seniority rank for title ordering; 0 means unrecognized."""
    classified = _classify(title)
    if classified is None:
        return 0
    band, _ = classified
    return _BAND_RANK[band] + 1


def _is_tagline_shape(text: str) -> bool:
    return any(ch in text for ch in _TAGLINE_CHARS)


def _is_named_denylist(text: str) -> bool:
    return _norm(text).strip() in _NAMED_HEADLINE_DENYLIST


def _is_title_shaped_candidate(text: str) -> bool:
    stripped = " ".join(text.strip().split())
    if not stripped or len(stripped) > 90:
        return False
    if _is_named_denylist(stripped):
        return False
    if any(ch in stripped for ch in ".,;:!?"):
        return False
    if len(_TITLE_WORD_RE.findall(stripped)) > 8:
        return False
    return _classify(stripped) is not None


def _title_prefix_candidates(text: str) -> list[str]:
    """Return title-shaped prefixes from an extracted experience summary.

    L3 returns compact summaries such as "Senior Manager AI at TD SYNNEX, led …"
    or "Research Engineer, 10 years tenure". Salary role recovery needs the
    title prefix, not employer/duration prose.
    """
    stripped = " ".join(text.strip().split())
    if not stripped:
        return []

    candidates: list[str] = []

    def _add(candidate: str) -> None:
        candidate = _DURATION_SUFFIX_RE.sub("", candidate).strip(" -–—,")
        candidate = " ".join(candidate.split())
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    def _add_title_then_full(candidate: str) -> None:
        title_prefix = _AT_EMPLOYER_RE.split(candidate, maxsplit=1)[0]
        _add(title_prefix)
        _add(candidate)

    _add_title_then_full(stripped)
    comma_prefix = stripped.split(",", 1)[0]
    _add_title_then_full(comma_prefix)
    return candidates


def _recover_from_titles(titles: list[str]) -> tuple[str, SeniorityBand, bool] | None:
    """Pick the highest-seniority title that matches a market token; ties → first."""
    best: tuple[int, int, str, SeniorityBand, bool] | None = None
    for i, t in enumerate(titles):
        for candidate in _title_prefix_candidates(t):
            if not _is_title_shaped_candidate(candidate):
                continue
            r = _classify(candidate)
            if r is None:
                continue
            band, mgmt = r
            rank = seniority_rank(candidate)
            if best is None or rank > best[0]:
                best = (rank, i, candidate, band, mgmt)
    if best is None:
        return None
    _, _, title, band, mgmt = best
    return title, band, mgmt


def _recover_current_title(titles: list[str]) -> tuple[str, SeniorityBand, bool] | None:
    """Return the first title-shaped current/top candidate, preserving CV order."""
    for t in titles:
        for candidate in _title_prefix_candidates(t):
            if not _is_title_shaped_candidate(candidate):
                continue
            r = _classify(candidate)
            if r is None:
                continue
            band, mgmt = r
            return candidate, band, mgmt
    return None


def _emit_normalized(detected: str, result: NormalizedRole) -> None:
    if result.canonical_role.strip() != detected.lower().strip():
        obs.emit(
            "extract",
            "role_normalized",
            detected=detected,
            canonical=result.canonical_role,
            seniority=result.seniority_band,
            source=result.source,
        )


def normalize_role(
    detected_role: str,
    years: int,  # noqa: ARG001 — reserved for future band-floor logic
    experience_titles: list[str],
) -> NormalizedRole:
    """Normalize `detected_role` to canonical market vocabulary.

    Synchronous, deterministic-only. Returns `source="unrecognized"` when no
    deterministic path resolves; callers wanting an LLM fallback should use
    `normalize_role_with_llm_fallback`.
    """
    detected = detected_role.strip()
    denylisted = _is_named_denylist(detected)
    tagline = _is_tagline_shape(detected)
    direct = _classify(detected)

    if direct is not None and not denylisted and not tagline:
        band, mgmt = direct
        detected_rank = seniority_rank(detected)
        recovered = _recover_current_title(experience_titles)
        if recovered is not None and detected_rank <= seniority_rank("data scientist"):
            title, recovered_band, recovered_mgmt = recovered
            if seniority_rank(title) > detected_rank:
                result = NormalizedRole(
                    canonical_role=title.lower(),
                    seniority_band=recovered_band,
                    is_management=recovered_mgmt,
                    source="experience_recovery",
                )
                _emit_normalized(detected_role, result)
                return result
        result = NormalizedRole(
            canonical_role=detected.lower(),
            seniority_band=band,
            is_management=mgmt,
            source="market_token",
        )
        _emit_normalized(detected_role, result)
        return result

    if denylisted or tagline:
        recovered = _recover_from_titles(experience_titles)
        if recovered is not None:
            title, band, mgmt = recovered
            source: NormalizationSource = "named_headline" if denylisted else "tagline_shape"
            result = NormalizedRole(
                canonical_role=title.lower(),
                seniority_band=band,
                is_management=mgmt,
                source=source,
            )
            _emit_normalized(detected_role, result)
            return result

    result = NormalizedRole(
        canonical_role=(detected.lower() or "unknown"),
        seniority_band="mid",
        is_management=False,
        source="unrecognized",
    )
    obs.emit("extract", "role_unrecognized", detected=detected_role, fallback="mid_default")
    return result


class _LLMCanonicalRole(BaseModel):
    canonical_role: str
    seniority_band: SeniorityBand
    is_management: bool
    confidence: float = Field(ge=0.0, le=1.0)


_LLM_CANONICALIZE_PROMPT = """\
You normalize a candidate's headline to canonical Czech labor-market vocabulary.

Inputs (JSON):
- `detected_role`: the verbatim headline.
- `experience_titles`: prior titles from the CV.
- `years`: total professional years.

Return JSON only:
{
  "canonical_role": "<lowercased canonical market role>",
  "seniority_band": "junior" | "mid" | "senior" | "staff" | "head" | "director",
  "is_management": true | false,
  "confidence": <float 0.0-1.0>
}

Examples of `canonical_role`: "senior data scientist", "head of data science",
"staff machine learning engineer".

Rules:
- Map non-market headlines (e.g. "Data Gardener", "AI Whisperer",
  "Member of Staff") to the closest market role implied by the
  experience_titles and years.
- Seniority must reflect role progression: head/director only when titles or
  years (>=10) support it.
- is_management is true when the canonical role manages people (head,
  director, VP, manager).
- confidence < 0.6 means you can't reliably canonicalize — set it low; the
  pipeline will fall back.

No prose outside the JSON object."""


async def _llm_canonicalize_role(
    detected_role: str,
    experience_titles: list[str],
    years: int,
) -> NormalizedRole | None:
    """Extraction-slot LLM fallback. Returns `None` on low confidence, error, or bad shape."""
    from gander.llm import LLMClient

    payload = json.dumps(
        {"detected_role": detected_role, "experience_titles": experience_titles[:5], "years": years}
    )
    try:
        client = LLMClient()
        raw = await client.complete_json(
            system=_LLM_CANONICALIZE_PROMPT,
            user=payload,
            schema=_LLMCanonicalRole,
            model="extract",
            temperature=0.0,
            max_tokens=256,
        )
    except Exception:
        return None
    if not isinstance(raw, _LLMCanonicalRole) or raw.confidence < 0.6:
        return None
    return NormalizedRole(
        canonical_role=raw.canonical_role.lower().strip(),
        seniority_band=raw.seniority_band,
        is_management=raw.is_management,
        source="llm_fallback",
    )


async def normalize_role_with_llm_fallback(
    detected_role: str,
    years: int,
    experience_titles: list[str],
) -> NormalizedRole:
    """Sync `normalize_role`; on `unrecognized`, retry once via cheap LLM."""
    sync_result = normalize_role(detected_role, years, experience_titles)
    if sync_result.source != "unrecognized":
        return sync_result
    llm_result = await _llm_canonicalize_role(detected_role, experience_titles, years)
    if llm_result is None:
        return sync_result
    obs.emit(
        "extract",
        "role_normalized",
        detected=detected_role,
        canonical=llm_result.canonical_role,
        seniority=llm_result.seniority_band,
        source="llm_fallback",
    )
    return llm_result
