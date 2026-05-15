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
        "contact",
        # Czech — section labels common on bilingual CZ/EN CVs
        "pracovní zkušenosti",
        "zkušenosti",
        "vzdělání",
        "dovednosti",
        "nejčastější dovednosti",
        "jazyky",
        "certifikace",
        "ocenění",
        "publikace",
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
