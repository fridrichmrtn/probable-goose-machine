# T08 — L2 PII redaction (regex-only) — dev plan

Branch: `feat/block-a-early-stages`
Worktree: `/home/mf/GitHub/probable-goose-machine/.worktrees/block-a`
Scope: NEW files only — `src/gander/redact.py`, `tests/test_redact.py`.
Read-only: `src/gander/{schemas,llm,verify,obs,errors,ingest}.py`.

## 1. File-by-file change list

### 1.1 `src/gander/redact.py` (new)

Public surface:

```python
def redact(text: str) -> RedactedCV | StageFailure: ...
```

Style mirrors `ingest.extract_text`: structured `obs.emit` at start/done with `duration_ms`; the body runs inside `with stage_boundary("redact") as cm:` and the function returns `cm.failure` if an unexpected exception is caught.

Imports (top-of-file):

```python
from __future__ import annotations

import re
import time
from typing import Final

from gander import obs
from gander.errors import StageFailure, stage_boundary
from gander.schemas import RedactedCV, Redaction
```

Module-level regexes (all compiled at import, all `Final`):

```python
# Markers carved out so we never re-tag our own output.
_MARKER = re.compile(r"\[(?:NAME|EMAIL|PHONE|URL|POSTCODE|YEAR)\]")

# URL — runs first so http://example.com/path doesn't get its digits eaten by phone/year.
_URL = re.compile(r"https?://\S+")

# Email — RFC-light per the task contract.
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Phone — three alternatives, longest-first so CZ wins over generic int'l.
# CZ: "+420 777 123 456" or "+420777123456"
# Int'l generic: "+<1-3>(sep)<3>(sep)<3>(sep)<3-4>"
# Generic local: groups of digits totalling 9-12, with space/hyphen separators only;
#   require a non-digit (or string boundary) on each side to avoid eating IDs like "12345678901234".
_PHONE = re.compile(
    r"""
    (?<![\w\d])                                   # left boundary
    (?:
        \+420[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{3}    # CZ explicit
      | \+\d{1,3}[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{3,4}   # generic international
      | \d{3}[\s-]\d{3}[\s-]\d{3,4}               # 9-10 digit local with separators
    )
    (?!\d)                                        # right boundary
    """,
    re.VERBOSE,
)

# CZ postcode — 5 digits possibly split "123 45" — only when comma + a city-like
# word (letters, optional diacritics, length >=3) is in proximity (±20 chars).
_POSTCODE = re.compile(
    r"""
    (?:
        ,\s*[A-Za-zÀ-ž]{3,}[^,\n]{0,20}?\b(\d{3})\ ?(\d{2})\b      # "..., Praha 110 00"
      | \b(\d{3})\ ?(\d{2})\b[^,\n]{0,20}?,\s*[A-Za-zÀ-ž]{3,}      # "110 00 Praha, CZ"
    )
    """,
    re.VERBOSE,
)
# Note: we capture the whole match and let the replacer find the digit run inside it,
# so the city/comma context survives and only the postcode is masked.
_POSTCODE_DIGITS = re.compile(r"\b\d{3}\ ?\d{2}\b")

# Year inside a date context. Two cases:
#   (a) adjacent to month name (Jan..Dec, full names) within ~12 chars on either side
#   (b) inside a date range token: "<year> – <year>", "<year>-<year>", "<year> – Present"
_MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
_YEAR_CORE = r"(?:19|20)\d{2}"
_YEAR_WITH_CONTEXT = re.compile(
    rf"""
    (?<!\.)                  # don't eat "3.10" → "3.[YEAR]"-style nonsense (no digit boundary needed; the (19|20) prefix already excludes "3.10")
    (?<!\w\.)                # version tokens like "v2024." stay intact
    (?:
        {_MONTH}\s+({_YEAR_CORE})                  # "January 2018"
      | ({_YEAR_CORE})\s+{_MONTH}                  # "2018 January" — rare but accepted
      | ({_YEAR_CORE})\s*[-–]\s*(?:Present|present|{_YEAR_CORE})   # "2018 – Present", "2018-2020"
      | (?:Present|present|{_YEAR_CORE})\s*[-–]\s*({_YEAR_CORE})   # "Present – 2018" reversed range
    )
    """,
    re.VERBOSE,
)
# After matching the full date phrase, the replacer redacts ONLY the year tokens inside it.
_YEAR_BARE = re.compile(rf"\b{_YEAR_CORE}\b")

# Name detection — "Name: X" form (≤4 words, no commas/digits).
_NAME_LABEL = re.compile(
    r"(?im)^\s*Name\s*:\s*(?P<name>[A-ZÀ-Ž][\wÀ-ž'’\-]*(?:\s+[A-ZÀ-Ž][\wÀ-ž'’\-]*){0,3})\s*$"
)
# Title-case first non-blank line, ≤4 words, no commas/digits/markers.
# We match this manually in code, not via regex, because "first non-blank line"
# is a structural property — see _redact_header_name below.
```

Idempotency strategy — chosen approach:

The cleanest mypy-strict-friendly approach is **pattern ordering plus a single "skip-if-already-marker" guard** in the substitution callback, not negative lookbehinds. Reasoning:

- Variable-length negative lookbehinds (`(?<!\[NAME\]...)` flavored guards) are messy and produce false negatives near line boundaries.
- Markers are short, fixed strings. After the URL/email/phone/postcode/year/name passes complete, the text contains literal `[EMAIL]`, `[PHONE]`, etc. tokens. None of the redaction regexes can match a marker token (`[EMAIL]` is not a valid email; `[PHONE]` is not a digit run; the title-case heuristic excludes lines containing `[`).
- The one residual risk is the title-case name heuristic matching a line that already contains `[NAME]`. We explicitly skip lines whose normalized content equals `[NAME]` or whose first non-blank line already starts with `[NAME]`.
- For the `Name: X` form, the regex requires the captured name to be a title-case word run — `Name: [NAME]` won't match because `[` is not in the character class.

Result: running `redact(redact(t).text)` equals `redact(t).text` for the marker tokens. We assert this in tests.

Replacement helper:

```python
def _replace_with_audit(
    text: str,
    pattern: re.Pattern[str],
    kind: Literal["email", "phone", "url", "year", "address", "name"],
    replacement: str,
    audit: list[Redaction],
) -> str:
    """re.sub variant that appends a Redaction per match, with original-text spans
    measured against the post-substitution text the caller will use as its source.
    Spans are recorded relative to the *output* text so they remain stable for the
    audit log consumer; the audit_log is informational, not a re-application key.
    """
    out_parts: list[str] = []
    cursor = 0
    out_pos = 0
    for m in pattern.finditer(text):
        out_parts.append(text[cursor : m.start()])
        out_pos += m.start() - cursor
        out_parts.append(replacement)
        audit.append(
            Redaction(
                kind=kind,
                original=m.group(0),
                replacement=replacement,
                span=(out_pos, out_pos + len(replacement)),
            )
        )
        out_pos += len(replacement)
        cursor = m.end()
    out_parts.append(text[cursor:])
    return "".join(out_parts)
```

Postcode replacer is the only special case — `_POSTCODE` matches the whole "comma + city + digits" envelope but we only redact the digits inside it:

```python
def _replace_postcode(text: str, audit: list[Redaction]) -> str:
    def _sub(m: re.Match[str]) -> str:
        envelope = m.group(0)
        # find the 5-digit postcode inside the envelope
        digits_m = _POSTCODE_DIGITS.search(envelope)
        if digits_m is None:
            return envelope  # defensive; shouldn't happen
        return envelope[: digits_m.start()] + "[POSTCODE]" + envelope[digits_m.end() :]
    # use a callback-based sub but also build the audit via a second pass on the
    # original text against _POSTCODE_DIGITS limited to spans inside _POSTCODE matches.
    ...
```

(Implementation note: simpler to iterate `_POSTCODE.finditer` once, record both audit and rewrite via accumulator.)

Year replacer mirrors postcode: match the full date phrase, then redact the year token(s) inside it:

```python
def _replace_year(text: str, audit: list[Redaction]) -> str:
    # finditer over _YEAR_WITH_CONTEXT, rewrite every (19|20)\d{2} token within
    # the match to [YEAR], record one Redaction per year token.
    ...
```

Header-name detector — non-regex helper because "first non-blank line" is structural:

```python
def _redact_header_name(text: str, audit: list[Redaction]) -> str:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # already redacted or contains markers / commas / digits / [ → bail
        if "[" in stripped or "," in stripped or any(ch.isdigit() for ch in stripped):
            return text
        words = stripped.split()
        if not (1 <= len(words) <= 4):
            return text
        # every word title-case (first char upper, rest letters incl. CZ diacritics)
        if not all(_is_title_word(w) for w in words):
            return text
        # compute span in the (already-rewritten) text and record
        ...
        return updated_text
    return text


def _is_title_word(word: str) -> bool:
    # accept "Novotný", "O'Brien", "Jean-Luc"; reject "MUDr.", "PhD"
    return bool(word) and word[0].isupper() and all(c.isalpha() or c in "'’-" for c in word[1:])
```

Top-level `redact()`:

```python
def redact(text: str) -> RedactedCV | StageFailure:
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
        # name pass goes last: line-structural; running it after year/postcode
        # avoids miscounting a "1995" line as a candidate (the digit guard would
        # have rejected it anyway, but order matters for span stability).
        out = _redact_header_name(out, audit)
        # also do the "Name: X" labelled form (independent of header)
        out = _replace_with_audit(out, _NAME_LABEL, "name", "[NAME]", audit)

        counts = {k: 0 for k in ("email", "phone", "url", "year", "address", "name")}
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
```

Type discipline (mypy --strict):
- `Final` on compiled patterns; no `Any` in signatures.
- `Redaction.kind` is `Literal[...]` per schemas — pass string literals, not `str`.
- Helper signatures use `re.Pattern[str]`, `re.Match[str]`, `list[Redaction]`.

### 1.2 `tests/test_redact.py` (new)

Imports + structure mirror `tests/test_ingest.py`. Use the same `@pytest.mark.fast` / `@pytest.mark.slow` markers, the same `obs.subscribe` fixture pattern, and the same `_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cvs"` constant. No conftest needed.

## 2. Order of regex application (matters)

Sequence inside `redact()`:

1. **URL** — first, so `http://example.com/2020/about` doesn't get the year or digit groups eaten by later passes.
2. **Email** — independent of URL; safe before or after, runs second by convention.
3. **Phone** — must run after URL (URL paths can contain `+420`-shaped strings). Must run before postcode (a CZ postcode `110 00` could be misread by the generic 9-12-digit branch if not bounded; the phone regex's word-boundary guards plus 9+ digit minimum keep `110 00` safe, but ordering preserves the invariant).
4. **Postcode** — needs the "comma + city" envelope intact; runs before the year pass so a "Praha 110 00, 2024" string doesn't get the digits broken up.
5. **Year** — runs before the title-case name heuristic. The heuristic already rejects digit-containing lines, but running year first means audit-log spans for the year are stable regardless of any later name replacement above it.
6. **Header-name** (structural, first non-blank title-case line).
7. **`Name: X`** label form — independent of the header pass; can produce a second `[NAME]` token elsewhere in the doc.

The name passes intentionally run **last** so they cannot eat already-tagged content: by step 6, any line that previously contained an email or phone now contains `[EMAIL]`/`[PHONE]` and is excluded by the `"[" in stripped` guard.

## 3. Test enumeration

Every fast test gets a numbered item below; the slow test runs over every fixture.

1. **`test_known_cv_redacts_name_email_phone`** (`@pytest.mark.fast`)
   - Input: `"Jan Novotný\njan.novotny@example.com\n+420 777 123 456"`.
   - Assertions:
     - `[NAME]`, `[EMAIL]`, `[PHONE]` all present in `result.text`.
     - `"Jan Novotný"` absent, `"jan.novotny@example.com"` absent, `"+420 777 123 456"` absent.
     - `len(result.audit_log) == 3`.
     - Audit kinds collected as a set equal `{"name", "email", "phone"}`.
     - Replacements on the matching entries are exactly `[NAME]` / `[EMAIL]` / `[PHONE]`.

2. **`test_version_tokens_not_redacted_as_year`** (`@pytest.mark.fast`)
   - Input: `"Python 3.10\nC++17\nUsing version 2024 of the library."`.
   - Assertions: `result.text == input` for the substrings — i.e., `"Python 3.10"`, `"C++17"`, `"version 2024"` all still present verbatim. No `[YEAR]` in `result.text`. `audit_log` contains no entry of kind `"year"`.

3. **`test_january_2018_present_redacts_year`** (`@pytest.mark.fast`)
   - Input: `"January 2018 – Present"` (en-dash) and also a hyphen variant `"January 2018 - Present"`.
   - Assertions: `"2018"` absent from `result.text`; `[YEAR]` present; one audit entry of kind `"year"` per call.
   - Sub-case: `"2015 – 2020"` → both years replaced (two entries of kind `"year"`).

4. **`test_idempotency_preserves_existing_markers`** (`@pytest.mark.fast`)
   - Input A: `"[NAME]\n[EMAIL]\nReal text with +420 777 111 222."`. Assert running `redact()` once still redacts the phone, and `result.text.count("[NAME]") == 1` (no `[[NAME]]` etc.).
   - Input B: feed a CV through `redact` twice. Assert `redact(redact(t).text).text == redact(t).text`. Assert marker counts are identical.

5. **`test_observability_emits_redact_event_with_duration`** (`@pytest.mark.fast`)
   - Use `obs.subscribe(events.append)`.
   - Run `redact("Jan Novotný\njan.novotny@example.com")`.
   - Assertions: at least one event with `stage == "redact"`; at least one of those has `event == "done"` AND an integer `duration_ms >= 0`. A `start` event also exists.

Slow tier:

6. **`test_every_fixture_audit_log_has_email_and_name`** (`@pytest.mark.slow`, parametrized over `_FIXTURE_DIR` `*.pdf`/`*.docx`)
   - Round-trip each fixture through `gander.ingest.extract_text` → `gander.redact.redact`. (Necessary because the fixtures are PDFs/DOCX, not raw text.)
   - Assert `extract_text` returned a `str` (skip fixture with a clear pytest.fail if not — failures here are corpus regressions, not redact bugs).
   - Assert `isinstance(result, RedactedCV)`.
   - Assert `{r.kind for r in result.audit_log}` contains both `"email"` and `"name"`.

Edge-case fast tests we should include to make ordering and the postcode rule load-bearing:

7. **`test_url_redaction_does_not_eat_phone_in_path`** (`@pytest.mark.fast`)
   - Input: `"See https://example.com/+420-777-123-456 for context."` → URL replaced, no `[PHONE]` substitution inside the URL match.

8. **`test_postcode_only_redacted_near_city_context`** (`@pytest.mark.fast`)
   - Positive: `"Korunní 12, Praha 110 00"` → `[POSTCODE]` present, `"110 00"` absent.
   - Negative: `"110 00"` standing alone with no comma+city context → unchanged, no `[POSTCODE]` token.
   - Negative: `"Order ID: 110 00"` → unchanged.

(Tests 7 and 8 cost ~10 lines each and prevent silent regressions when later passes reorder. They live in the fast tier.)

## 4. Risks

- **False-positive name detection on first-line section headers.** A CV that opens with a section header instead of a name (e.g., `"Summary"` or `"Curriculum Vitae"` on line 1) is title-case, ≤4 words, no digits/commas — the heuristic would tag it as `[NAME]`. Mitigation: add a small denylist of obvious header phrases to skip (`{"Summary", "Curriculum Vitae", "Profile", "Resume", "CV"}`, case-insensitive). The fixtures lead with real names, so this lives quietly behind the denylist; we don't over-engineer.

- **False-negative phone detection on unusual formats.** Numbers like `(420) 777 123 456`, `+1.555.123.4567`, or `00420 777 123 456` won't match the three branches. Acceptable for v1 (regex-only is explicitly best-effort per PLAN §L2 + PRD §4.7). Documented in the function docstring as a known limitation; reviewers see the audit log so a missed phone is visible, not silent.

- **False-positive postcode on numeric IDs.** Strings like `"Employee ID 110 00, Department"` could match the "digits…comma…city" envelope. The mitigation is the city-like word constraint (`{3,}` letters with optional diacritics) and the proximity window (`{0,20}` chars). Worst case: a 5-digit ID next to a 3-letter word like "ABC" + comma + a long word would slip through. We accept this — the audit log surfaces it and downstream stages don't rely on postcode being absent.

- **Title-case heuristic on Czech diacritics in section headers.** `"Pracovní Zkušenosti"` is title-case, 2 words, no digits — would be tagged as `[NAME]` if it occurred on the first non-blank line. Same mitigation as the section-header denylist; extend with common Czech equivalents (`"Pracovní Zkušenosti"`, `"Vzdělání"`). Cheap.

- **`Name: X` regex stops at 4 words.** Names with `de la`, `van der`, etc. exceed 4 tokens; we'd miss them. Aligned with the task's `≤4 words` constraint, so this is by design, not a defect.

- **Span recording in audit log.** Spans are output-relative, not input-relative — documented in the helper docstring. Downstream consumers (UI debug, T15 reviewer dump) treat the audit log as informational, not as a re-application key, so output-relative spans are fine.

## 5. Verification recipe (exact commands)

Run from the worktree root `/home/mf/GitHub/probable-goose-machine/.worktrees/block-a`:

```bash
# Fast tier — also what pre-commit runs.
uv run pytest -m fast tests/test_redact.py -v

# Slow tier — fixture corpus.
uv run pytest -m slow tests/test_redact.py -v

# Type + style + full pre-commit gate.
uv run ruff format src/gander/redact.py tests/test_redact.py
uv run ruff check src/gander/redact.py tests/test_redact.py
uv run mypy src/gander

# Full pre-commit (matches CI).
uv run pre-commit run --all-files
```

Acceptance criteria for "done":
- All four commands exit 0.
- `uv run pytest -m fast` (whole suite, not just this file) still passes — `redact.py` must not import-time-side-effect anything that breaks other modules.
- `audit_log` length ≥ 3 for the canonical Jan Novotný fixture, with kinds covering name/email/phone.

Plan written to tasks/T08_dev-plan.md, 309 lines.
