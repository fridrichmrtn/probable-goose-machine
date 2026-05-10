from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from jobfit import redact as redact_module
from jobfit.errors import StageFailure
from jobfit.ingest import extract_text
from jobfit.obs import subscribe
from jobfit.redact import redact
from jobfit.schemas import RedactedCV

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cvs"


@pytest.mark.fast
def test_known_cv_redacts_name_email_phone() -> None:
    cv = "Jan Novotný\njan.novotny@example.com\n+420 777 123 456"
    result = redact(cv)
    assert isinstance(result, RedactedCV)

    assert "[NAME]" in result.text
    assert "[EMAIL]" in result.text
    assert "[PHONE]" in result.text
    assert "Jan Novotný" not in result.text
    assert "jan.novotny@example.com" not in result.text
    assert "+420 777 123 456" not in result.text

    kinds = {r.kind for r in result.audit_log}
    assert {"name", "email", "phone"}.issubset(kinds)
    assert len(result.audit_log) == 3
    by_kind = {r.kind: r for r in result.audit_log}
    assert by_kind["name"].replacement == "[NAME]"
    assert by_kind["email"].replacement == "[EMAIL]"
    assert by_kind["phone"].replacement == "[PHONE]"


@pytest.mark.fast
def test_version_tokens_not_redacted_as_year() -> None:
    cv = "Python 3.10\nC++17\nUsing version 2024 of the library."
    result = redact(cv)
    assert isinstance(result, RedactedCV)

    assert "Python 3.10" in result.text
    assert "C++17" in result.text
    assert "version 2024" in result.text
    assert "[YEAR]" not in result.text
    assert not any(r.kind == "year" for r in result.audit_log)


@pytest.mark.fast
@pytest.mark.parametrize(
    "phrase",
    ["January 2018 – Present", "January 2018 - Present"],
)
def test_january_2018_present_redacts_year(phrase: str) -> None:
    result = redact(phrase)
    assert isinstance(result, RedactedCV)
    assert "2018" not in result.text
    assert "[YEAR]" in result.text
    year_entries = [r for r in result.audit_log if r.kind == "year"]
    assert len(year_entries) == 1
    assert year_entries[0].original == "2018"


@pytest.mark.fast
def test_year_range_redacts_both_years() -> None:
    result = redact("2015 – 2020")
    assert isinstance(result, RedactedCV)
    assert "2015" not in result.text
    assert "2020" not in result.text
    assert result.text.count("[YEAR]") == 2
    year_entries = [r for r in result.audit_log if r.kind == "year"]
    assert len(year_entries) == 2
    assert {e.original for e in year_entries} == {"2015", "2020"}


@pytest.mark.fast
def test_idempotency_existing_markers_not_double_redacted() -> None:
    cv = "[NAME]\n[EMAIL]\nReal text with +420 777 111 222."
    result = redact(cv)
    assert isinstance(result, RedactedCV)
    # Existing markers preserved exactly once each.
    assert result.text.count("[NAME]") == 1
    assert result.text.count("[EMAIL]") == 1
    # Phone still gets redacted.
    assert "[PHONE]" in result.text
    assert "+420 777 111 222" not in result.text


@pytest.mark.fast
def test_redact_is_idempotent_over_two_passes() -> None:
    cv = (
        "Jan Novotný\n"
        "jan.novotny@example.com\n"
        "+420 777 123 456\n"
        "Korunní 12, Praha 110 00\n"
        "January 2018 – Present\n"
        "https://example.com/profile\n"
    )
    once = redact(cv)
    assert isinstance(once, RedactedCV)
    twice = redact(once.text)
    assert isinstance(twice, RedactedCV)
    assert twice.text == once.text
    # Second pass produces no new redactions.
    assert twice.audit_log == []


@pytest.mark.fast
def test_observability_emits_redact_event_with_duration() -> None:
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = redact("Jan Novotný\njan.novotny@example.com")
    assert isinstance(result, RedactedCV)

    redact_events = [e for e in events if e["stage"] == "redact"]
    assert redact_events, f"expected redact events, got {events!r}"

    starts = [e for e in redact_events if e["event"] == "start"]
    dones = [e for e in redact_events if e["event"] == "done"]
    assert starts, f"expected start event, got {events!r}"
    assert dones, f"expected done event, got {events!r}"

    done = dones[0]
    assert "duration_ms" in done
    assert isinstance(done["duration_ms"], int)
    assert done["duration_ms"] >= 0
    assert "duration_ms" not in starts[0]
    assert "redactions" in done
    assert done["redactions"] == len(result.audit_log)


@pytest.mark.fast
def test_url_redaction_does_not_eat_phone_in_path() -> None:
    cv = "See https://example.com/+420-777-123-456 for context."
    result = redact(cv)
    assert isinstance(result, RedactedCV)
    assert "[URL]" in result.text
    # Phone substring was inside the URL; the URL pass owned it.
    assert "[PHONE]" not in result.text
    assert not any(r.kind == "phone" for r in result.audit_log)


@pytest.mark.fast
def test_postcode_only_redacted_near_city_context() -> None:
    pos = redact("Korunní 12, Praha 110 00")
    assert isinstance(pos, RedactedCV)
    assert "[POSTCODE]" in pos.text
    assert "110 00" not in pos.text

    bare = redact("110 00")
    assert isinstance(bare, RedactedCV)
    assert "[POSTCODE]" not in bare.text
    assert "110 00" in bare.text

    id_like = redact("Order ID: 110 00")
    assert isinstance(id_like, RedactedCV)
    assert "[POSTCODE]" not in id_like.text
    assert "110 00" in id_like.text


@pytest.mark.fast
def test_name_label_form_redacted() -> None:
    result = redact("Name: Jane Smith")
    assert isinstance(result, RedactedCV)
    assert "Jane Smith" not in result.text
    assert "[NAME]" in result.text
    # The label itself survives — only the value is masked.
    assert "Name:" in result.text


@pytest.mark.fast
def test_section_header_not_misread_as_name() -> None:
    cv = "Curriculum Vitae\n\nJan Novotný\njan@example.com"
    result = redact(cv)
    assert isinstance(result, RedactedCV)
    # The header line stays intact; the actual name on a later line gets redacted.
    assert "Curriculum Vitae" in result.text
    assert "Jan Novotný" not in result.text
    assert "[NAME]" in result.text


@pytest.mark.fast
def test_marker_only_first_line_does_not_block_name_redaction() -> None:
    """MF1: when an earlier pass (URL/email/phone) leaves a marker-only line at
    the top, the header-name pass must skip it instead of bailing — otherwise a
    real name on the next line survives."""
    result = redact("[EMAIL]\nJane Smith\nSome content")
    assert isinstance(result, RedactedCV)
    assert "Jane Smith" not in result.text
    assert "[NAME]" in result.text
    # Pre-existing marker is preserved (idempotency) and content remains.
    assert result.text.count("[EMAIL]") == 1
    assert "Some content" in result.text


@pytest.mark.fast
def test_name_label_does_not_consume_newline_into_name_group() -> None:
    """MF2: `\\s+` between name words must not match `\\n`, or the next line
    gets eaten by the name group."""
    result = redact("Name: Jane\nExperience")
    assert isinstance(result, RedactedCV)
    assert "[NAME]" in result.text
    assert "Experience" in result.text
    # Label survives intact; only the value got masked.
    assert "Name:" in result.text


class _BoomPattern:
    """Drop-in for `re.Pattern` whose `finditer` raises with a fixed message.

    Used to exercise the redact stage_boundary path. The message is fixed
    (no PII echo) so MF6 verifies the boundary's exc_message wiring, not the
    caller's hygiene about what it puts into raised exceptions.
    """

    groupindex: dict[str, int] = {}

    def finditer(self, _text: str) -> object:
        raise RuntimeError("synthetic redact failure")


@pytest.mark.fast
def test_stage_failure_returned_when_pipeline_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MF3: exercise the StageFailure return path so the post-block assert
    cannot be silently elided under `python -O`."""
    monkeypatch.setattr(redact_module, "_URL", _BoomPattern())

    result = redact("Jan Novotný\njan.novotny@example.com")
    assert isinstance(result, StageFailure)
    assert result.stage == "redact"
    assert result.user_message


@pytest.mark.fast
def test_failure_path_emits_error_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """MF4: the failure branch must surface a structured `error` event tagged
    with stage='redact' (PRD §4.8)."""
    monkeypatch.setattr(redact_module, "_URL", _BoomPattern())

    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = redact("Jan Novotný\njan.novotny@example.com")
    assert isinstance(result, StageFailure)

    errors = [e for e in events if e["event"] == "error" and e["stage"] == "redact"]
    assert errors, f"expected error event for redact stage, got {events!r}"
    assert errors[0]["exc_type"] == "RuntimeError"


@pytest.mark.fast
def test_failure_event_does_not_leak_cv_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MF6: the error event's `exc_message` must not echo PII tokens from the
    input CV (PRD §4.8 — fingerprint-only, no content). The injected exception
    carries a fixed generic message, so any PII appearing in exc_message would
    indicate the boundary is mixing input content into the error context.
    """
    monkeypatch.setattr(redact_module, "_URL", _BoomPattern())

    pii_email = "jan.novotny@example.com"
    pii_name = "Jan Novotný"
    events: list[dict[str, Any]] = []
    with subscribe(events.append):
        result = redact(f"{pii_name}\n{pii_email}")
    assert isinstance(result, StageFailure)

    errors = [e for e in events if e["event"] == "error" and e["stage"] == "redact"]
    assert errors, f"expected error event, got {events!r}"
    assert pii_email not in errors[0]["exc_message"]
    assert pii_name not in errors[0]["exc_message"]


@pytest.mark.slow
def test_fixture_corpus_present() -> None:
    pdfs = list(_FIXTURE_DIR.glob("*.pdf"))
    docxs = list(_FIXTURE_DIR.glob("*.docx"))
    if not pdfs and not docxs:
        pytest.fail("no CV fixtures found in tests/fixtures/cvs/ — corpus regression")


@pytest.mark.slow
@pytest.mark.parametrize(
    "fixture_path",
    sorted(list(_FIXTURE_DIR.glob("*.pdf")) + list(_FIXTURE_DIR.glob("*.docx"))),
    ids=lambda p: p.name,
)
def test_every_fixture_audit_log_has_email_and_name(fixture_path: Path) -> None:
    extracted = extract_text(fixture_path.read_bytes(), fixture_path.name)
    if isinstance(extracted, StageFailure):
        pytest.fail(f"ingest failed on fixture {fixture_path.name}: {extracted.user_message}")

    result = redact(extracted)
    assert isinstance(result, RedactedCV)
    kinds = {r.kind for r in result.audit_log}
    assert "email" in kinds, f"no email redacted in {fixture_path.name}; kinds={kinds!r}"
    assert "name" in kinds, f"no name redacted in {fixture_path.name}; kinds={kinds!r}"

    # MF5: the audit log records what *was* redacted — confirm the substitution
    # actually happened (original gone, marker present), not just the recording.
    marker_for_kind = {"email": "[EMAIL]", "name": "[NAME]"}
    for r in result.audit_log:
        if r.kind not in marker_for_kind:
            continue
        assert r.original not in result.text, (
            f"{r.kind} value {r.original!r} survives in redacted text of {fixture_path.name}"
        )
        assert marker_for_kind[r.kind] in result.text, (
            f"missing {marker_for_kind[r.kind]} in redacted text of {fixture_path.name}"
        )
