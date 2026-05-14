from __future__ import annotations

import unicodedata
from typing import Any

import pytest
from pydantic import BaseModel

from gander.obs import subscribe
from gander.schemas import Anchor
from gander.verify import drop_unverified, verify_quote

pytestmark = pytest.mark.fast


SOURCE = """## Skills
Python, PyTorch, async pipelines, vector databases, distributed systems.

## Experience
Built a recommendation system that reduced churn by 18% over six months.
Led migration from monolith to microservices across three quarters.

## Education
Charles University, MFF UK, MSc in Computer Science, 2018.
"""

# CZ source for bilingual-CV regression coverage (T26 — § Pracovní zkušenosti).
SOURCE_CZ = """## Pracovní zkušenosti
Vedl tým šesti inženýrů na migraci platformy z monolitu na mikroslužby.

## Dovednosti
Python, PyTorch, asynchronní pipeliny, vektorové databáze.
"""

# Same 6-word phrase appears twice → fails uniqueness rule for 6-word quotes.
SOURCE_DUP = """## Experience
Reduced churn by eighteen percent last quarter for the recommendation system team.
Reduced churn by eighteen percent last quarter for the marketplace team.
"""


def test_six_word_unique_quote_verifies() -> None:
    assert verify_quote("recommendation system that reduced churn by", SOURCE) is True


def test_six_word_duplicated_quote_rejected() -> None:
    assert verify_quote("reduced churn by eighteen percent last", SOURCE_DUP) is False


def test_eight_word_duplicated_quote_verifies() -> None:
    quote = "reduced churn by eighteen percent last quarter for"
    assert verify_quote(quote, SOURCE_DUP) is True


def test_five_word_quote_rejected() -> None:
    assert verify_quote("recommendation system that reduced churn", SOURCE) is False


def test_section_mismatch_returns_false() -> None:
    skills_quote = "python, pytorch, async pipelines, vector databases, distributed"
    assert verify_quote(skills_quote, SOURCE, section="experience") is False


def test_section_match_returns_true() -> None:
    quote = "recommendation system that reduced churn by"
    assert verify_quote(quote, SOURCE, section="experience") is True


def test_verify_quote_section_match_cz() -> None:
    # Bilingual CV: model anchors with the CZ section name. Header is present.
    quote = "vedl tým šesti inženýrů na migraci"
    assert verify_quote(quote, SOURCE_CZ, section="Pracovní zkušenosti") is True


def test_verify_quote_section_miss_falls_back() -> None:
    # Source has the quote in body but NO `## SectionName` header for the
    # name the model picked → whole-CV substring fallback rescues the anchor.
    quote = "recommendation system that reduced churn by"
    assert verify_quote(quote, SOURCE, section="references") is True


def test_verify_quote_section_miss_quote_also_missing() -> None:
    quote = "this exact phrase appears nowhere in the source corpus"
    assert verify_quote(quote, SOURCE, section="references") is False


def test_verify_quote_section_match_quote_in_other_section() -> None:
    # Section header IS present; quote lives in a DIFFERENT section. Today and
    # after T26: section-restricted on header hit, no fallback. Returns False.
    skills_quote = "python, pytorch, async pipelines, vector databases, distributed"
    assert verify_quote(skills_quote, SOURCE, section="experience") is False


def test_verify_section_miss_event_emitted() -> None:
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        assert (
            verify_quote(
                "recommendation system that reduced churn by", SOURCE, section="references"
            )
            is True
        )
    miss = next(e for e in events if e["event"] == "verify_section_miss")
    assert miss["section"] == "references"
    assert miss["fallback"] == "whole_cv"
    assert miss["stage"] == "verify"


def test_verify_section_miss_event_not_emitted_on_header_hit() -> None:
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        verify_quote("recommendation system that reduced churn by", SOURCE, section="experience")
    assert not any(e["event"] == "verify_section_miss" for e in events)


def test_punctuation_preserved_in_normalization() -> None:
    quote = "we reduced churn by 18% last year"
    source = "## Experience\nWe reduced churn by 18% last year and grew ARR.\n"
    assert verify_quote(quote, source) is True


def test_unicode_nfc_normalization_handles_pdf_diacritic_forms() -> None:
    quote = "Tomáš Dvořák vedl tým šesti inženýrů"
    source = unicodedata.normalize("NFD", f"## Experience\n{quote} v Praze.\n")
    assert verify_quote(quote, source, section="Experience") is True


class _Item(BaseModel):
    anchor: Anchor


def test_section_resolves_under_h1_header() -> None:
    src = "# Experience\nLed migration from monolith to microservices across three quarters.\n"
    quote = "led migration from monolith to microservices"
    assert verify_quote(quote, src, section="experience") is True


def test_section_resolves_under_h3_header() -> None:
    src = "### Experience\nLed migration from monolith to microservices across three quarters.\n"
    quote = "led migration from monolith to microservices"
    assert verify_quote(quote, src, section="experience") is True


def test_drop_unverified_filters_correctly() -> None:
    items = [
        _Item(
            anchor=Anchor(
                quote="recommendation system that reduced churn by",
                section="experience",
            )
        ),
        # In wrong section — verifiable elsewhere but not under "experience".
        _Item(
            anchor=Anchor(
                quote="python, pytorch, async pipelines, vector databases, distributed",
                section="experience",
            )
        ),
        # Too short.
        _Item(anchor=Anchor(quote="reduced churn by 18%", section="experience")),
    ]
    kept, dropped = drop_unverified(items, SOURCE)
    assert len(kept) == 1
    assert dropped == 2
