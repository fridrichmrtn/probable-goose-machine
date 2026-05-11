"""L2 — regex-only PII redaction.

Strips name, email, phone, URL, postcode, and date-context years from CV text
before downstream stages see it (PRD §4.7). Regex-only by design; the LLM pass
is intentionally deferred (PLAN.md cuts).

Limitations (known and accepted for v1):
  * Phone formats like `(420) 777 123 456` or `+1.555.123.4567` do not match.
  * Bare phone numbers are caught only in CZ shape (9 digits, first digit
    non-zero). Other-country bare runs without separators are missed.
  * The 9-10 digit local-separator branch can collide with non-phone digit
    runs like `2024-2026 123` if separated by space/dash; boundary guards
    prevent overlap with adjacent digits but not with adjacent dashes from
    date ranges.
  * Postcode detection requires nearby "comma + city-like word" context; bare
    `110 00` strings are left alone. Street addresses without a postcode
    (PRD §4.7 names "address" as PII) are not covered — backlogged.
  * Year tokens are masked only when in date context (month name or range).
  * The audit-log `span` is recorded against the OUTPUT text (post-substitution),
    not the input — downstream consumers treat it as informational.
"""

from __future__ import annotations

import re
import time
from typing import Final, Literal

from jobfit import obs
from jobfit.errors import StageFailure, stage_boundary
from jobfit.schemas import RedactedCV, Redaction

RedactionKind = Literal["email", "phone", "name", "address", "year", "url"]

_URL: Final = re.compile(r"https?://\S+")

_EMAIL: Final = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Phone — four alternatives, longest-first so CZ explicit wins over generic.
# Boundary guards keep us out of longer digit runs (employee IDs, etc). The
# bare 9-digit branch requires a non-zero leading digit so CZ mobile numbers
# (start in 6/7/9) and CZ landlines (start in 2/3/4/5) match without dragging
# in 0-padded order numbers / sequence IDs.
_PHONE: Final = re.compile(
    r"""
    (?<![\d-])
    (?:
        \+420[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{3}                  # CZ explicit
      | \+\d{1,3}[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{3,4}            # generic international
      | \d{3}[\s-]\d{3}[\s-]\d{3,4}                             # 9-10 digit local with separators
      | [1-9]\d{8}                                              # CZ bare 9-digit
    )
    (?!\d)
    """,
    re.VERBOSE,
)

# CZ postcode — the regex matches a "comma + city" envelope on either side of
# the digit run. The replacer redacts only the digits inside the envelope.
_POSTCODE: Final = re.compile(
    r"""
    (?:
        ,\s*[A-Za-zÀ-ž]{3,}[^,\n]{0,20}?\b\d{3}\ ?\d{2}\b
      | \b\d{3}\ ?\d{2}\b[^,\n]{0,20}?,\s*[A-Za-zÀ-ž]{3,}
    )
    """,
    re.VERBOSE,
)
_POSTCODE_DIGITS: Final = re.compile(r"\b\d{3}\ ?\d{2}\b")

_MARKER_ONLY_LINE: Final = re.compile(r"^\s*\[(EMAIL|PHONE|URL|POSTCODE|YEAR|NAME)\]\s*$")
_MARKER_TOKEN: Final = re.compile(r"\[(?:EMAIL|PHONE|URL|POSTCODE|YEAR|NAME)\]")
# Decorative separators commonly used in single-line CV header rows
# (e.g. "Jan Novotný | +420 …", "Jan Novotný · prague@…").
_HEADER_SEPARATORS: Final = ("|", "·", "•", "—", "–")
# Contact-label words that, when they're the only residue after stripping
# markers/separators, mean the line was already-redacted contact info, not a
# name candidate (e.g. "LinkedIn [URL]" → residue "LinkedIn").
_CONTACT_LABELS: Final = frozenset(
    {
        "email",
        "phone",
        "tel",
        "mobile",
        "linkedin",
        "github",
        "gitlab",
        "website",
        "url",
        "twitter",
        "x",
        "portfolio",
        "address",
        "contact",
    }
)

_MONTH: Final = (
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)"
)
_YEAR_CORE: Final = r"(?:19|20)\d{2}"
_YEAR_WITH_CONTEXT: Final = re.compile(
    rf"""
    (?:
        {_MONTH}\s+{_YEAR_CORE}
      | {_YEAR_CORE}\s+{_MONTH}
      | {_YEAR_CORE}\s*[-–]\s*(?:Present|present|{_YEAR_CORE})
      | (?:Present|present)\s*[-–]\s*{_YEAR_CORE}
    )
    """,
    re.VERBOSE,
)
_YEAR_BARE: Final = re.compile(rf"\b{_YEAR_CORE}\b")

# Labelled "Name: X" form — capped at 4 title-case words, no digits/commas.
# Use `[ \t]+` (not `\s+`) between words so newlines never get eaten by the
# name group under the `(?m)` flag.
_NAME_LABEL: Final = re.compile(
    r"(?im)^[ \t]*Name[ \t]*:[ \t]*"
    r"(?P<name>[A-ZÀ-Ž][\wÀ-ž'’\-]*(?:[ \t]+[A-ZÀ-Ž][\wÀ-ž'’\-]*){0,3})[ \t]*$"
)

# Section-header denylist: a first line of these is NOT a name candidate.
_HEADER_DENYLIST: Final = frozenset(
    {
        "summary",
        "profile",
        "resume",
        "cv",
        "curriculum vitae",
        "objective",
        "about me",
        "about",
        "contact",
        "contact information",
        "personal information",
        "experience",
        "work experience",
        "education",
        "skills",
        "projects",
        "pracovní zkušenosti",
        "vzdělání",
        "dovednosti",
        "životopis",
    }
)


def _replace_with_audit(
    text: str,
    pattern: re.Pattern[str],
    kind: RedactionKind,
    replacement: str,
    audit: list[Redaction],
) -> str:
    """Replace each match with `replacement` and record a Redaction per match.

    If the pattern declares a `name` group, only that group is replaced (so
    `Name: Jan` becomes `Name: [NAME]`, keeping the label). Otherwise the
    whole match is replaced. Spans are recorded against the OUTPUT text.
    """
    use_name_group = "name" in pattern.groupindex
    out_parts: list[str] = []
    cursor = 0
    out_pos = 0
    for m in pattern.finditer(text):
        if use_name_group:
            target_start, target_end = m.span("name")
            original = m.group("name")
        else:
            target_start, target_end = m.start(), m.end()
            original = m.group(0)

        prefix = text[cursor:target_start]
        out_parts.append(prefix)
        out_pos += len(prefix)
        out_parts.append(replacement)
        audit.append(
            Redaction(
                kind=kind,
                original=original,
                replacement=replacement,
                span=(out_pos, out_pos + len(replacement)),
            )
        )
        out_pos += len(replacement)
        cursor = target_end
    out_parts.append(text[cursor:])
    return "".join(out_parts)


def _replace_postcode(text: str, audit: list[Redaction]) -> str:
    out_parts: list[str] = []
    cursor = 0
    out_pos = 0
    for m in _POSTCODE.finditer(text):
        envelope = m.group(0)
        digits_m = _POSTCODE_DIGITS.search(envelope)
        if digits_m is None:
            continue
        env_start = m.start()
        digit_abs_start = env_start + digits_m.start()
        digit_abs_end = env_start + digits_m.end()

        # Append the run up to the digit start.
        pre = text[cursor:digit_abs_start]
        out_parts.append(pre)
        out_pos += len(pre)
        out_parts.append("[POSTCODE]")
        audit.append(
            Redaction(
                kind="address",
                original=digits_m.group(0),
                replacement="[POSTCODE]",
                span=(out_pos, out_pos + len("[POSTCODE]")),
            )
        )
        out_pos += len("[POSTCODE]")
        cursor = digit_abs_end
    out_parts.append(text[cursor:])
    return "".join(out_parts)


def _replace_year(text: str, audit: list[Redaction]) -> str:
    out_parts: list[str] = []
    cursor = 0
    out_pos = 0
    for m in _YEAR_WITH_CONTEXT.finditer(text):
        # Emit everything from the previous cursor up to this match unchanged.
        pre = text[cursor : m.start()]
        out_parts.append(pre)
        out_pos += len(pre)

        envelope = m.group(0)
        env_cursor = 0
        for year_m in _YEAR_BARE.finditer(envelope):
            chunk = envelope[env_cursor : year_m.start()]
            out_parts.append(chunk)
            out_pos += len(chunk)
            out_parts.append("[YEAR]")
            audit.append(
                Redaction(
                    kind="year",
                    original=year_m.group(0),
                    replacement="[YEAR]",
                    span=(out_pos, out_pos + len("[YEAR]")),
                )
            )
            out_pos += len("[YEAR]")
            env_cursor = year_m.end()
        tail = envelope[env_cursor:]
        out_parts.append(tail)
        out_pos += len(tail)
        cursor = m.end()
    out_parts.append(text[cursor:])
    return "".join(out_parts)


def _is_title_word(word: str) -> bool:
    """Accept 'Novotný', "O'Brien", 'Jean-Luc'; reject 'PhD', 'MUDr.', 'PROFESSIONAL'."""
    if not word or not word[0].isupper():
        return False
    if len(word) > 1 and word.isupper():
        return False
    return all(c.isalpha() or c in "'’-" for c in word[1:])


def _name_residue_from_mixed_line(stripped: str) -> str | None:
    """Recover a name candidate from a line mixing markers and separators.

    Returns the residue if it looks like a name, else None. Returns None for
    labelled contact lines ("Email: [EMAIL]"), pure label+marker rows
    ("LinkedIn [URL]"), and rows whose residue still carries structural noise
    (digits, commas, stray brackets).
    """
    # Labelled contact lines never carry a name in the value position.
    if ":" in stripped:
        return None
    residue = _MARKER_TOKEN.sub(" ", stripped)
    for sep in _HEADER_SEPARATORS:
        residue = residue.replace(sep, " ")
    residue = " ".join(residue.split())
    if not residue:
        return None
    # Residual structural noise → not a clean name candidate.
    if "[" in residue or "]" in residue or "," in residue:
        return None
    if any(ch.isdigit() for ch in residue):
        return None
    words = residue.split()
    if len(words) == 1 and words[0].lower() in _CONTACT_LABELS:
        return None
    return residue


def _redact_header_name(text: str, audit: list[Redaction]) -> str:
    """Mask the first non-blank line that looks like a name.

    Skips obvious section headers (denylist) so a CV starting with "Curriculum
    Vitae" still gets its real name redacted from a later line. Skips lines
    that are entirely a redaction marker, and continues past mixed lines made
    of label+marker decoration (e.g. "Email: [EMAIL]", "LinkedIn [URL]").
    For lines that mix a name with markers/separators (e.g.
    "Jan Novotný | [PHONE]"), extracts the name residue and masks only that
    span.
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if _MARKER_ONLY_LINE.match(stripped):
            continue

        has_marker = bool(_MARKER_TOKEN.search(stripped))
        if has_marker:
            residue = _name_residue_from_mixed_line(stripped)
            if residue is None:
                # Labelled / decoration-only contact line — keep scanning.
                continue
            if residue.lower() in _HEADER_DENYLIST:
                continue
            words = residue.split()
            if not (1 <= len(words) <= 4) or not all(_is_title_word(w) for w in words):
                continue
            # Mask only the residue span inside the line; leave markers intact.
            idx = line.find(residue)
            if idx < 0:
                continue
            new_line = line[:idx] + "[NAME]" + line[idx + len(residue) :]
            prefix_lines = lines[:i]
            prefix_text = "\n".join(prefix_lines)
            prefix_len = len(prefix_text) + (1 if prefix_lines else 0)
            name_span_start = prefix_len + idx
            audit.append(
                Redaction(
                    kind="name",
                    original=residue,
                    replacement="[NAME]",
                    span=(name_span_start, name_span_start + len("[NAME]")),
                )
            )
            lines[i] = new_line
            return "\n".join(lines)

        # No markers on this line — original strict gate.
        if "[" in stripped or "," in stripped or any(ch.isdigit() for ch in stripped):
            return text
        if stripped.lower() in _HEADER_DENYLIST:
            continue
        # All-uppercase lines (e.g. "PROFESSIONAL SUMMARY") are section
        # headings, not names; skip past them rather than bailing the scan.
        if stripped.isupper():
            continue
        words = stripped.split()
        if not (1 <= len(words) <= 4):
            return text
        if not all(_is_title_word(w) for w in words):
            return text

        leading_ws_len = len(line) - len(line.lstrip())
        name_start_in_line = leading_ws_len
        name_end_in_line = name_start_in_line + len(stripped)
        new_line = line[:name_start_in_line] + "[NAME]" + line[name_end_in_line:]

        prefix_lines = lines[:i]
        prefix_text = "\n".join(prefix_lines)
        prefix_len = len(prefix_text) + (1 if prefix_lines else 0)
        name_span_start = prefix_len + name_start_in_line
        audit.append(
            Redaction(
                kind="name",
                original=stripped,
                replacement="[NAME]",
                span=(name_span_start, name_span_start + len("[NAME]")),
            )
        )
        lines[i] = new_line
        return "\n".join(lines)
    return text


def redact(text: str) -> RedactedCV | StageFailure:
    """Redact PII from CV text and return the result alongside an audit log.

    Returns a `RedactedCV` on success, or a `StageFailure` if an unexpected
    error escapes the regex pipeline (the boundary catches everything).
    """
    t0 = time.perf_counter()
    obs.emit("redact", "start", chars=len(text))

    def _ms() -> int:
        return int((time.perf_counter() - t0) * 1000)

    with stage_boundary("redact") as cm:
        audit: list[Redaction] = []
        out = text
        out = _replace_with_audit(out, _URL, "url", "[URL]", audit)
        out = _replace_with_audit(out, _EMAIL, "email", "[EMAIL]", audit)
        out = _replace_with_audit(out, _PHONE, "phone", "[PHONE]", audit)
        out = _replace_postcode(out, audit)
        out = _replace_year(out, audit)
        out = _redact_header_name(out, audit)
        out = _replace_with_audit(out, _NAME_LABEL, "name", "[NAME]", audit)

        counts: dict[str, int] = {
            "email": 0,
            "phone": 0,
            "url": 0,
            "year": 0,
            "address": 0,
            "name": 0,
        }
        for r in audit:
            counts[r.kind] += 1
        obs.emit(
            "redact",
            "done",
            redactions=len(audit),
            duration_ms=_ms(),
            **{f"count_{k}": v for k, v in counts.items()},
        )
        return RedactedCV(text=out, audit_log=audit)

    assert cm.failure is not None
    return cm.failure
