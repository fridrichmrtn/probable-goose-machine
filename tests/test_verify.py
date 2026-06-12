from __future__ import annotations

import unicodedata
from typing import Any

import pytest
from pydantic import BaseModel

from gander.obs import subscribe
from gander.schemas import Anchor
from gander.verify import claim_supports_quote, drop_unverified, verify_quote

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
    # Section header IS present; quote lives in a DIFFERENT section.
    # After T26: section-restricted on header hit, no whole-CV fallback.
    skills_quote = "python, pytorch, async pipelines, vector databases, distributed"
    assert verify_quote(skills_quote, SOURCE, section="experience") is False


def test_section_match_returns_true() -> None:
    quote = "recommendation system that reduced churn by"
    assert verify_quote(quote, SOURCE, section="experience") is True


def test_verify_quote_section_match_cz() -> None:
    # Bilingual CV: model anchors with the CZ section name. Header is present.
    quote = "vedl tým šesti inženýrů na migraci"
    assert verify_quote(quote, SOURCE_CZ, section="Pracovní zkušenosti") is True


def test_translated_cz_section_alias_matches_without_fallback_event() -> None:
    source = """## Akademická praxe
Vede výzkumnou skupinu pro strojové učení v biomedicíně a koordinuje datovou spolupráci.

## Vzdělání
Docentura v oboru Informatika na Masarykově univerzitě.
"""
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        assert (
            verify_quote(
                "vede výzkumnou skupinu pro strojové učení",
                source,
                section="Academic Experience",
            )
            is True
        )
    assert not any(e["event"] == "verify_section_miss" for e in events)


def test_translated_cz_section_alias_stays_section_local() -> None:
    source = """## Akademická praxe
Vede výzkumnou skupinu pro strojové učení v biomedicíně.

## Vzdělání
Docentura v oboru Informatika na Masarykově univerzitě a Ph.D. v informatice.
"""
    quote = "Docentura v oboru Informatika na Masarykově univerzitě"
    assert verify_quote(quote, source, section="Academic Experience") is False


def test_academic_alias_does_not_match_general_work_section() -> None:
    source = """## Pracovní zkušenosti
Vedl komerční datový tým v bankovnictví a dodal tři produkční modely rizika.

## Akademická praxe
Vede výzkumnou skupinu pro strojové učení v biomedicíně a koordinuje grantovou spolupráci.
"""
    work_quote = "Vedl komerční datový tým v bankovnictví a dodal"
    academic_quote = "Vede výzkumnou skupinu pro strojové učení v biomedicíně"

    assert verify_quote(work_quote, source, section="Academic Experience") is False
    assert verify_quote(academic_quote, source, section="Academic Experience") is True


def test_known_parent_section_includes_employer_subheaders() -> None:
    source = (
        "## Pracovní zkušenosti\n"
        "\n"
        "## TD SYNNEX\n"
        "Founded and led data science & business intelligence teams, was responsible for "
        "co-formulating data strategy, delivery, methodology, architecture, and ROI.\n"
        "\n"
        "## Vzdělání\n"
        "PhD, Economics and Management, Applied Machine Learning.\n"
    )

    quote = (
        "Founded and led data science & business intelligence teams, "
        "was responsible for co-formulating data strategy"
    )
    assert verify_quote(quote, source, section="Pracovní zkušenosti") is True


def test_known_parent_section_stops_at_next_known_section() -> None:
    source = """## Pracovní zkušenosti

## TD SYNNEX
Founded and led data science & business intelligence teams.

## Vzdělání
PhD, Economics and Management, Applied Machine Learning.
"""
    quote = "PhD, Economics and Management, Applied Machine Learning"
    assert verify_quote(quote, source, section="Pracovní zkušenosti") is False


def test_known_parent_section_stops_at_shared_cz_section_vocabulary() -> None:
    source = """## Pracovní zkušenosti

## TD SYNNEX
Founded and led data science & business intelligence teams.

## Certifikace
Certified Kubernetes Administrator issued by Cloud Native Computing Foundation.
"""
    quote = "Certified Kubernetes Administrator issued by Cloud Native Computing Foundation"
    assert verify_quote(quote, source, section="Pracovní zkušenosti") is False


def test_known_parent_section_stops_at_same_level_custom_non_child_header() -> None:
    source = """## Work Experience
Built a recommendation system that reduced churn by 18% over six months.

## Open Source
Maintained a data quality library used by three analytics teams.
"""
    quote = "Maintained a data quality library used by three analytics teams"
    assert verify_quote(quote, source, section="Work Experience") is False


def test_unknown_section_still_stops_at_next_header() -> None:
    source = """## Selected Case Studies
Built a recommendation system that reduced churn by 18% over six months.

## Client Confidential
Led migration from monolith to microservices across three quarters.
"""
    quote = "Led migration from monolith to microservices across"
    assert verify_quote(quote, source, section="Selected Case Studies") is False


def test_verify_quote_section_miss_falls_back() -> None:
    # Source has the quote in body but NO `## SectionName` header for the
    # name the model picked → whole-CV substring fallback rescues the anchor.
    quote = "recommendation system that reduced churn by"
    assert verify_quote(quote, SOURCE, section="references") is True


def test_verify_quote_section_miss_quote_also_missing() -> None:
    quote = "this exact phrase appears nowhere in the source corpus"
    assert verify_quote(quote, SOURCE, section="references") is False


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
    # Called outside any stage_boundary → current_stage default is None.
    assert miss["stage"] is None


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


# ---------- claim_supports_quote (P1.5 semantic-gap gate) ----------
#
# These pairs were measured (see the jaccard values in comments) and the
# threshold (0.1) was chosen to sit below the lowest legitimate-support pair.
# The gate catches TOPICAL mismatch; it deliberately does NOT catch verb
# substitution on a shared object — that case is asserted as a known limitation.


class _ClaimItem(BaseModel):
    text: str
    anchor: Anchor


@pytest.mark.parametrize(
    "claim,quote",
    [
        # paraphrase, jaccard 0.667
        (
            "Led the migration from monolith to microservices",
            "Led migration from monolith to microservices across three quarters",
        ),
        # skill restate, jaccard 0.222 — the lowest legitimate pair
        (
            "Strong Python and PyTorch background",
            "Built recommendation system in Python and PyTorch over six months",
        ),
        # experience summary, jaccard 0.444
        (
            "Eighteen months owning production on-call",
            "Owned the on-call rotation across two production squads for eighteen months",
        ),
    ],
)
def test_claim_supports_quote_keeps_legitimate_pairs(claim: str, quote: str) -> None:
    assert claim_supports_quote(claim, quote) is True


@pytest.mark.parametrize(
    "claim,quote",
    [
        # different metric/topic, jaccard 0.0
        (
            "Increased revenue by 40 percent",
            "Built recommendation system that reduced churn by 18% over six months",
        ),
        # unrelated domain, jaccard 0.0
        (
            "Designed the company security architecture",
            "Wrote the quarterly marketing newsletter for the European retail team",
        ),
    ],
)
def test_claim_supports_quote_rejects_topical_mismatch(claim: str, quote: str) -> None:
    assert claim_supports_quote(claim, quote) is False


def test_claim_supports_quote_known_limitation_verb_substitution() -> None:
    # KNOWN LIMITATION (intentional): bag-of-words overlap cannot separate
    # "Led" from "Joined" on a shared object — jaccard 0.25, above the 0.222
    # legitimate-support floor. Catching this needs an LLM judge, which the
    # latency/cost budget rejects for a per-anchor check. Asserted so the
    # limitation is visible and a future change to the gate is a conscious one.
    assert (
        claim_supports_quote(
            "Led a team of engineers",
            "Joined a team of engineers in the platform group last year",
        )
        is True
    )


def test_claim_supports_quote_passes_when_too_few_content_tokens() -> None:
    # Both sides reduce to no content tokens after stop-word removal → no signal
    # to reject on, so defer to the existence check (return True).
    assert claim_supports_quote("in the at by", "to and or") is True


def test_drop_unverified_drops_claim_that_quote_does_not_support() -> None:
    # Quote exists in SOURCE under Experience, but the claim is about an
    # unrelated metric — the compatibility gate must drop it even though the
    # substring check passes.
    items = [
        _ClaimItem(
            text="Increased advertising revenue by forty percent",
            anchor=Anchor(
                quote="Built a recommendation system that reduced churn by 18% over six months",
                section="experience",
            ),
        )
    ]
    kept, dropped = drop_unverified(items, SOURCE, claim_attr="text")
    assert kept == []
    assert dropped == 1


def test_drop_unverified_keeps_claim_that_restates_quote() -> None:
    items = [
        _ClaimItem(
            text="Built a recommendation system that reduced churn",
            anchor=Anchor(
                quote="Built a recommendation system that reduced churn by 18% over six months",
                section="experience",
            ),
        )
    ]
    kept, dropped = drop_unverified(items, SOURCE, claim_attr="text")
    assert len(kept) == 1
    assert dropped == 0


def test_drop_unverified_without_claim_attr_skips_compat_gate() -> None:
    # Backward compat: existing callers pass no claim_attr and only get the
    # existence check, even when the (here absent) claim would mismatch.
    items = [
        _ClaimItem(
            text="totally unrelated claim about marketing",
            anchor=Anchor(
                quote="Built a recommendation system that reduced churn by 18% over six months",
                section="experience",
            ),
        )
    ]
    kept, dropped = drop_unverified(items, SOURCE)
    assert len(kept) == 1
    assert dropped == 0


def test_drop_unverified_emits_claim_mismatch_without_cv_text() -> None:
    item = _ClaimItem(
        text="Increased advertising revenue by forty percent",
        anchor=Anchor(
            quote="Built a recommendation system that reduced churn by 18% over six months",
            section="experience",
        ),
    )
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        drop_unverified([item], SOURCE, claim_attr="text")

    mismatch = [e for e in events if e["event"] == "verify_claim_mismatch"]
    assert len(mismatch) == 1
    record = mismatch[0]
    assert record["claim_word_count"] == 6
    assert "jaccard" in record
    # No CV text leaks — only counts and the numeric score.
    serialized = " ".join(str(v) for v in record.values())
    assert "revenue" not in serialized
    assert "recommendation" not in serialized
