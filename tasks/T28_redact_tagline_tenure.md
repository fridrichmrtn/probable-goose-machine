# T28 — Redact: tagline-headline name fix + deterministic tenure (R6 + R7)

Status: todo
Owner: software-engineer
Depends on: —
Unblocks: —
Estimate: ~45 min

## Goal

Two related defects surfaced by the bilingual senior CV run:

1. **§4.7 PII regression (R6).** `_redact_header_name` (`src/gander/redact.py:349-350`) bails (`return text`) on the first non-blank line if it contains `,`, `[`, or any digit. The Profile.pdf headline `"Data Gardener | AI, Data Science & Engineering @Stealth"` contains a comma → name never redacted, scan terminates. This is a silent compliance bug — it does not show up in the user-facing report.

2. **Tenure non-determinism (R7).** `redact._replace_year` masks year tokens BEFORE `extract.md` is asked to count tenure. `Profile.detected_years_experience` is therefore inferred by the LLM from `[YEAR] - [YEAR]` patterns rather than computed from real dates. This is brittle (LLM variance) and can mislead salary's `years≥10` lift gate.

## Deliverables

### Tagline-headline name fix

- [ ] `src/gander/redact.py::_redact_header_name`:
  - When the first non-blank line contains `,`/`[`/digits AND has no markers, `continue` past it instead of `return text`. The intent is "this isn't a name candidate, look at the next line", not "abort".
  - Bound the scan to the first 10 non-blank lines so we don't scan the whole CV.
- [ ] `tests/test_redact.py::test_tagline_headline_name_redacted`:
  - Input: a CV starting with `"Data Gardener | AI, Data Science & Engineering @Stealth\nPraha\nJana Nováková\n..."`.
  - Assert: `audit_log` contains a `kind="name"` entry; the tagline line is preserved (commas + words intact); `[NAME]` appears at the position of `Jana Nováková`.

### Deterministic tenure

- [ ] New `src/gander/tenure.py`:
  - `def compute_years(text: str) -> int | None` — pure function. Scan for date ranges of shape `(month name|YYYY) - (month name|YYYY|present|nyní)` and dual-language month names (CZ + EN). Sum the spans. Cap at first-job → today. Returns `None` if no parseable ranges.
- [ ] `src/gander/ingest.py`: after text extraction, before redaction, call `compute_years(annotated)`. Attach to `RedactedCV` (extend the schema) OR pass it through the pipeline alongside `RedactedCV`.
- [ ] `src/gander/schemas.py::RedactedCV`: add `years_experience_deterministic: int | None = None`.
- [ ] `src/gander/extract.py`: when `redacted.years_experience_deterministic is not None`, override `profile.detected_years_experience` post-LLM. Emit `obs.emit("extract", "tenure_override", llm=profile.detected_years_experience, deterministic=redacted.years_experience_deterministic, delta=...)` when they differ by ≥1.
- [ ] `tests/test_tenure.py`:
  - Parametrize over CZ + EN date forms: `"října 2015 - Present"`, `"Sept 2015 - Jan 2026"`, `"2015 - 2023"`, `"ledna 2017 - ledna 2021"` → expected years.
  - Edge case: overlapping ranges shouldn't double-count.

## Verification

```bash
uv run pytest tests/test_redact.py tests/test_tenure.py tests/test_extract.py -v
uv run mypy src/
```

Re-run on Profile.pdf at the deployed Space (manual): check `count_name >= 1` in obs and `detected_years_experience` matches the deterministic value.

## Reference

- Plan: `/home/mf/.claude/plans/this-is-a-result-peaceful-blanket.md` § "Additional failure modes F2, F3"
- PRD §4.7

## Outcome

(fill in when done — confirm name redaction count, observed deterministic years on Profile.pdf, any LLM-vs-deterministic deltas in the test corpus)
