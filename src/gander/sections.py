from __future__ import annotations

import unicodedata

SECTION_NAMES: frozenset[str] = frozenset(
    {
        # English (existing + new for title-case headers seen in CZ/EN CVs)
        "experience",
        "work experience",
        "professional experience",
        "education",
        "skills",
        "projects",
        "summary",
        "profile",
        "languages",
        "certifications",
        "honors-awards",
        "awards",
        "publications",
        "grants",
        "teaching",
        "conferences",
        "references",
        "contact",
        "academic experience",
        "academic practice",
        "research experience",
        # Czech — section labels common on bilingual CZ/EN CVs
        "pracovní zkušenosti",
        "zkušenosti",
        "praxe",
        "akademická praxe",
        "vzdělání",
        "dovednosti",
        "nejčastější dovednosti",
        "jazyky",
        "certifikace",
        "ocenění",
        "publikace",
        "granty",
        "výuka",
        "konference",
        "reference",
        "projekty",
        "shrnutí",
        "profil",
        "kontakt",
    }
)


def normalize_section_name(s: str) -> str:
    """Strip diacritics, lowercase, and collapse internal whitespace."""
    decomposed = unicodedata.normalize("NFD", s)
    no_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return " ".join(no_marks.lower().split())


NORMALIZED_SECTION_NAMES: frozenset[str] = frozenset(
    normalize_section_name(name) for name in SECTION_NAMES
)


_SECTION_ALIAS_GROUPS: tuple[frozenset[str], ...] = tuple(
    frozenset(normalize_section_name(name) for name in group)
    for group in (
        (
            "experience",
            "work experience",
            "professional experience",
            "pracovní zkušenosti",
            "zkušenosti",
            "praxe",
        ),
        (
            "academic experience",
            "academic practice",
            "research experience",
            "akademická praxe",
        ),
        ("education", "vzdělání"),
        ("skills", "dovednosti", "nejčastější dovednosti"),
        ("languages", "jazyky"),
        ("certifications", "certifikace"),
        ("awards", "honors-awards", "ocenění"),
        ("publications", "publikace"),
        ("projects", "projekty"),
        ("summary", "shrnutí"),
        ("profile", "profil"),
        ("contact", "kontakt"),
        ("grants", "granty"),
        ("teaching", "výuka"),
        ("conferences", "konference"),
        ("references", "reference"),
    )
)


def section_name_candidates(s: str) -> frozenset[str]:
    """Return normalized section labels equivalent to ``s``.

    CV authors often keep Czech headers while the LLM reports the English
    translation. The verifier still wants section-local matching, so known
    cross-language aliases resolve to the same header family.
    """
    normalized = normalize_section_name(s)
    for group in _SECTION_ALIAS_GROUPS:
        if normalized in group:
            return group
    return frozenset({normalized})
