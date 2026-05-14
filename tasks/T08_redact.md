# T08 — L2 PII redaction (regex-only default)

Status: done
Owner: software-engineer
Depends on: T02, T05 (gate)
Unblocks: T15
Estimate: ~30 min

## Goal

Strip personally-identifying information from the extracted CV before it reaches the scoring stage (PRD §4.7 structural mitigation). Regex-only by default; LLM pass is intentionally deferred (PLAN.md cuts).

## Deliverables

- [ ] `src/gander/redact.py`:
  - `def redact(text: str) -> RedactedCV`:
    - Email regex (RFC-light): `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}` → `[EMAIL]`.
    - Phone regex: international (`\+\d{1,3}[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{3,4}`), CZ format (`\+420 ?\d{3} ?\d{3} ?\d{3}`), generic 9–12 digit groups separated by spaces or hyphens. → `[PHONE]`.
    - URL regex (excluding `[YEAR]` candidates): `https?://\S+` → `[URL]`.
    - Postal code (CZ format `\b\d{3} ?\d{2}\b` only when in proximity to a comma + city-like word) → `[POSTCODE]`.
    - Name detection: heuristic — first non-blank line of CV that's title-case (≤4 words, no commas, no digits) is treated as the candidate name → `[NAME]`. Also detect `Name: X` patterns.
    - Date / age inference: `\b(19|20)\d{2}\b` *only* when adjacent to a month name (`January|February|...|Jan|Feb|...`) or a `–`/`-` range token, replace with `[YEAR]`. Preserves `Python 3.10`, `C++17`, `version 2024`.
    - Each replacement appended to `audit_log: list[Redaction]` with original, replacement, span.
  - Returns `RedactedCV(text=redacted_text, audit_log=...)`.
  - Wrap with `stage_boundary("redact")`.
- [ ] `tests/test_redact.py`:
  - `@pytest.mark.fast`: known CV text with `Jan Novotný\njan.novotny@example.com\n+420 777 123 456` → all three redacted.
  - `@pytest.mark.fast`: `Python 3.10` and `C++17` are NOT redacted.
  - `@pytest.mark.fast`: `January 2018 – Present` → year redacted.
  - `@pytest.mark.fast`: text already containing `[NAME]`/`[EMAIL]` → no double-redaction.
  - `@pytest.mark.slow`: every fixture CV produces an `audit_log` containing at least an email and a name redaction.

## Verification

```bash
uv run pytest -m fast tests/test_redact.py -v
uv run pytest -m slow tests/test_redact.py -v
```

## Reference

- tasks/PLAN.md — § "L2 — PII Redaction (regex-only by default)"
- PRD.md §4.7

## Outcome

Shipped `src/gander/redact.py` (regex-only pipeline: URL → email → phone → CZ
postcode → year-in-date-context → header name → `Name:` label) and
`tests/test_redact.py`. Spans in `Redaction.audit_log` are recorded against the
output text and documented as informational. Helper `_replace_with_audit`
replaces a `name` named-group when present (so `Name: Jan` becomes
`Name: [NAME]` without losing the label) and otherwise replaces the full match.
The header-name pass skips a section-header denylist (`Curriculum Vitae`,
`Summary`, plus Czech equivalents) so a CV that opens with a section heading
still gets the real name redacted from the next non-blank line.

Verification (from `/home/mf/GitHub/probable-goose-machine/.worktrees/block-a`):

- `uv run ruff format` — 2 files left unchanged.
- `uv run ruff check` — all checks passed.
- `uv run mypy src/gander` — Success: no issues found in 8 source files.
- `uv run pytest -m fast tests/test_redact.py -v` — 12 passed, 3 deselected.
- `uv run pytest -m slow tests/test_redact.py -v` — 3 passed (corpus guard +
  both fixtures: `01_junior_da_novotny.docx`, `08_staff_ml_engineer_dvorak.pdf`).
- `uv run pre-commit run --all-files` — all hooks passed.
- Full fast suite (`uv run pytest -m fast`) — 69 passed, no regressions.

Fixture audit-log inspection (no false positives observed):

- `01_junior_da_novotny.docx`: 1 email, 1 phone, 4 year tokens (all in CV date
  ranges), 1 name (`Jan Novotný`).
- `08_staff_ml_engineer_dvorak.pdf`: 1 email, 1 phone, 10 year tokens (date
  ranges in work history + education), 1 name (`Tomáš Dvořák`).

Known limitations (carried from plan §4):

- Phone formats like `(420) 777 123 456`, `+1.555.123.4567`, `00420 …` are not
  matched; the three-branch regex is best-effort per PLAN §L2.
- Postcode requires nearby comma + city-like word context; bare `110 00`
  strings are intentionally left alone.
- Year tokens outside date context (`version 2024`, `C++17`, `Python 3.10`)
  are preserved by design — covered by a dedicated fast test.
