"""Tests for gander.tenure.compute_years (T28 R7)."""

from __future__ import annotations

import pytest

from gander import tenure
from gander.tenure import compute_years


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin "today" so `Present`-bearing test cases produce stable values.

    The 2026-05 date matches the project's current working date; tests that
    care about "to Present" use this as the upper bound.
    """
    monkeypatch.setattr(tenure, "_today_ym", lambda: (2026, 5))


@pytest.mark.fast
@pytest.mark.parametrize(
    "text, expected",
    [
        # Single ranges, EN + CZ.
        ("Sept 2015 - Jan 2026", 10),
        ("September 2015 - January 2026", 10),
        ("ledna 2017 - ledna 2021", 4),
        ("2015 - 2023", 8),
        ("října 2015 - Present", 10),  # Oct 2015 - May 2026 = 10y7m -> 10
        ("January 2018 – Present", 8),  # Jan 2018 - May 2026 = 8y4m -> 8
        # Bare year to present.
        ("2018 - present", 8),
    ],
)
def test_simple_ranges(text: str, expected: int) -> None:
    assert compute_years(text) == expected


@pytest.mark.fast
@pytest.mark.parametrize(
    "present_token",
    ["present", "Current", "now", "nyní", "současnost", "současně", "dosud"],
)
def test_present_variants(present_token: str) -> None:
    """Every documented "present"-equivalent token must parse to today."""
    text = f"January 2020 - {present_token}"
    # 2020-01 → 2026-05 = 6y4m → 6.
    assert compute_years(text) == 6


@pytest.mark.fast
def test_overlapping_intervals_are_unioned() -> None:
    """Overlap counts once: [2015-2020) ∪ [2018-2023) = [2015-2023) = 8 years."""
    text = "Role A: 2015 - 2020\nRole B: 2018 - 2023"
    assert compute_years(text) == 8


@pytest.mark.fast
def test_gaps_are_not_counted() -> None:
    """Disjoint intervals sum: [2015-2017) + [2020-2023) = 2 + 3 = 5 years."""
    text = "Role A: 2015 - 2017\nRole B: 2020 - 2023"
    assert compute_years(text) == 5


@pytest.mark.fast
def test_returns_none_when_no_parseable_range() -> None:
    assert compute_years("No dates here, just prose about projects.") is None


@pytest.mark.fast
def test_handles_em_and_en_dashes() -> None:
    assert compute_years("January 2018 — May 2026") == 8
    assert compute_years("January 2018 – May 2026") == 8
    assert compute_years("January 2018 - May 2026") == 8


@pytest.mark.fast
def test_reverse_range_is_ignored() -> None:
    """A range whose end precedes its start is dropped, not silently treated."""
    assert compute_years("January 2020 - January 2018") is None


@pytest.mark.fast
def test_future_present_capped_at_today() -> None:
    """A `Present` endpoint never advances past today's frozen date."""
    # If the model later swapped `_today_ym`, the answer would shift; pinned
    # here at 2026-05, January 2026 → Present is 5 months → 0 years.
    assert compute_years("January 2026 - Present") == 0


@pytest.mark.fast
def test_cz_genitive_forms_parsed() -> None:
    """CZ date ranges use the genitive form ('ledna', 'prosince')."""
    assert compute_years("ledna 2020 - prosince 2024") == 5  # Jan 2020 - Dec 2024 = 5y
    assert compute_years("října 2015 - prosince 2020") == 5  # Oct 2015 - Dec 2020 = 5y2m


@pytest.mark.fast
def test_real_cv_snippet_with_prose() -> None:
    """End-to-end style: a chunk of CV text with prose between ranges."""
    text = (
        "Work Experience\n"
        "Senior Engineer @ Acme. October 2015 - Present. Led a team of 5.\n"
        "Engineer @ BetaCorp. January 2012 - September 2015. Backend.\n"
    )
    # 2012-01 - 2015-09 (44 months) + 2015-10 - 2026-05 (128 months) = 172 months -> 14
    assert compute_years(text) == 14


@pytest.mark.fast
def test_education_section_excluded_from_tenure() -> None:
    """Codex P1: tenure must scope to the work-experience section. An education
    range (`2010 - 2014`) outside the work section MUST NOT contribute to the
    override — otherwise senior-tier estimates get inflated by school years."""
    text = (
        "Work Experience\n"
        "Engineer @ Acme. January 2020 - January 2023. Backend.\n"
        "\n"
        "Education\n"
        "B.Sc. Computer Science, Charles University. 2010 - 2014.\n"
        "M.Sc. Computer Science, Charles University. 2014 - 2016.\n"
    )
    # Work section alone: 2020-01 → 2023-01 = 3y. Education adds 6y if leaked.
    assert compute_years(text) == 3


@pytest.mark.fast
def test_future_range_dropped_after_clamp() -> None:
    """Copilot P2: a range entirely in the future (`Jan 2027 - Dec 2028`)
    must NOT contribute negative months once `end_months` is clamped to today.
    With today pinned at 2026-05, the clamp pulls end back to 2026-05 while
    start stays at 2027-01 → start > end → drop the interval."""
    text = (
        "Work Experience\n"
        "Engineer @ Acme. January 2020 - January 2023. Backend.\n"
        "Future role. January 2027 - December 2028. Not started.\n"
    )
    # Only the 2020-2023 range counts; the future range is dropped, not subtracted.
    assert compute_years(text) == 3
