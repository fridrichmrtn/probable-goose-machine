# T08 — L2 PII redaction (regex-only default)

Status: todo
Owner: software-engineer
Depends on: T02, T05 (gate)
Unblocks: T15
Estimate: ~30 min

## Goal

Strip personally-identifying information from the extracted CV before it reaches the scoring stage (PRD §4.7 structural mitigation). Regex-only by default; LLM pass is intentionally deferred (PLAN.md cuts).

## Deliverables

- [ ] `src/jobfit/redact.py`:
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

(fill in when done — esp. any false-positive redactions on real fixtures)
