"""Tests for gander.timeline.scan_employer_timeline."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from gander.timeline import EmployerEntry, scan_employer_timeline


@pytest.mark.fast
def test_scan_returns_empty_when_no_work_experience_section() -> None:
    text = (
        "## Summary\n"
        "Senior engineer with broad platform experience.\n"
        "## Education\n"
        "MSc Computer Science, 2010 - 2014\n"
    )
    assert scan_employer_timeline(text) == []


@pytest.mark.fast
def test_scan_detects_present_token_current() -> None:
    text = (
        "## Work Experience\nSenior Platform Engineer — Stealth Startup\nJanuary 2024 - Present\n"
    )
    entries = scan_employer_timeline(text)
    assert len(entries) == 1
    assert entries[0].header == "Senior Platform Engineer — Stealth Startup"
    assert entries[0].is_current is True


@pytest.mark.fast
@pytest.mark.parametrize("present_token", ["současnost", "dosud", "nyní"])
def test_scan_detects_czech_present_variants(present_token: str) -> None:
    text = f"## Work Experience\nVedoucí týmu — Alza\nleden 2022 - {present_token}\n"
    entries = scan_employer_timeline(text)
    assert len(entries) == 1
    assert entries[0].is_current is True


@pytest.mark.fast
def test_scan_classifies_closed_when_only_years() -> None:
    text = "## Work Experience\nData Engineer — Past Company\n2018 - 2021\n"
    entries = scan_employer_timeline(text)
    assert len(entries) == 1
    assert entries[0].is_current is False


@pytest.mark.fast
def test_scan_handles_year_marker_post_redaction() -> None:
    text = (
        "## Work Experience\n"
        "Senior Manager — Stealth Startup\n"
        "ledna [YEAR] - Present\n"
        "Engineer — Old Co\n"
        "[YEAR] - [YEAR]\n"
    )
    entries = scan_employer_timeline(text)
    assert len(entries) == 2
    assert entries[0].header == "Senior Manager — Stealth Startup"
    assert entries[0].is_current is True
    assert entries[1].header == "Engineer — Old Co"
    assert entries[1].is_current is False


@pytest.mark.fast
def test_scan_parallel_current_roles() -> None:
    text = (
        "## Work Experience\n"
        "Member of Staff — Stealth Mode Startup\n"
        "ledna [YEAR] - Present\n"
        "Research Engineer — Independent\n"
        "února [YEAR] - Present\n"
    )
    entries = scan_employer_timeline(text)
    assert len(entries) == 2
    assert entries[0].header == "Member of Staff — Stealth Mode Startup"
    assert entries[0].is_current is True
    assert entries[1].header == "Research Engineer — Independent"
    assert entries[1].is_current is True


@pytest.mark.fast
def test_scan_does_not_treat_inline_paragraph_dates_as_entries() -> None:
    # An inline mention inside a long sentence exceeds the 80-char guard and
    # must not surface as its own entry.
    text = (
        "## Work Experience\n"
        "Senior Engineer — Real Co\n"
        "2020 - 2023\n"
        "Built and led platform teams from 2019 - present on many production "
        "systems across regions globally for years.\n"
    )
    entries = scan_employer_timeline(text)
    assert len(entries) == 1
    assert entries[0].header == "Senior Engineer — Real Co"
    assert entries[0].is_current is False


@pytest.mark.fast
def test_scan_header_walks_up_at_most_three_lines() -> None:
    text = "## Work Experience\nLine Five\nLine Four\nLine Three\nLine Two\nLine One\n2018 - 2021\n"
    entries = scan_employer_timeline(text)
    assert len(entries) == 1
    # Walks up at most 3 lines: Three, Two, One — in CV top-down order.
    assert entries[0].header == "Line Three — Line Two — Line One"


@pytest.mark.fast
def test_scan_strips_bullet_glyphs_from_headers() -> None:
    text = "## Work Experience\n• Senior Engineer — Real Co\n2018 - 2021\n"
    entries = scan_employer_timeline(text)
    assert len(entries) == 1
    assert entries[0].header == "Senior Engineer — Real Co"


@pytest.mark.fast
def test_scan_bug_pdf_shape() -> None:
    """Reduced fixture mirroring the failing Profile_new.pdf shape: two parallel
    current entries (Stealth Mode, Research Engineer) followed by three closed
    entries (TD SYNNEX, Alza, DSV). Post-redaction Czech genitive months + [YEAR]."""
    text = (
        "## Pracovní zkušenosti\n"
        "Member of Staff — Stealth Mode Startup\n"
        "ledna [YEAR] - Present\n"
        "Research Engineer — Independent\n"
        "ledna [YEAR] - Present\n"
        "Senior Manager AI & Data Science — TD SYNNEX\n"
        "ledna [YEAR] - prosince [YEAR]\n"
        "Lead Data Scientist — Alza.cz\n"
        "ledna [YEAR] - prosince [YEAR]\n"
        "Data Scientist — DSV\n"
        "ledna [YEAR] - prosince [YEAR]\n"
    )
    entries = scan_employer_timeline(text)
    assert len(entries) == 5
    assert [(e.header, e.is_current) for e in entries] == [
        ("Member of Staff — Stealth Mode Startup", True),
        ("Research Engineer — Independent", True),
        ("Senior Manager AI & Data Science — TD SYNNEX", False),
        ("Lead Data Scientist — Alza.cz", False),
        ("Data Scientist — DSV", False),
    ]


@pytest.mark.fast
def test_scan_does_not_flag_header_with_inline_month_name() -> None:
    # "May Mobility" is a real company name; the header carries the month
    # token "May" plus an em-dash but no year/[YEAR]/present-token, so the
    # detector must not treat it as a date-range line.
    text = "## Work Experience\nMachine Learning Engineer — May Mobility\nJanuary 2020 - Present\n"
    entries = scan_employer_timeline(text)
    assert len(entries) == 1
    assert entries[0].header == "Machine Learning Engineer — May Mobility"
    assert entries[0].is_current is True


@pytest.mark.fast
def test_scan_handles_trailing_segment_after_present() -> None:
    # Splitting on the *last* dash used to misread this as "Remote" on the
    # RHS, dropping the present-token signal. With first-dash splitting the
    # whole "Present - Remote" tail is searched.
    text = (
        "## Work Experience\n"
        "Senior Engineer — Current Co\n"
        "January 2024 - Present - Remote\n"
        "Engineer — Old Co\n"
        "2018 - 2021\n"
    )
    entries = scan_employer_timeline(text)
    assert len(entries) == 2
    assert entries[0].header == "Senior Engineer — Current Co"
    assert entries[0].is_current is True
    assert entries[1].is_current is False


@pytest.mark.fast
def test_employer_entry_is_frozen() -> None:
    entry = EmployerEntry(header="X", dates_raw="2018 - 2021", is_current=False)
    with pytest.raises(FrozenInstanceError):
        entry.header = "Y"  # type: ignore[misc]
