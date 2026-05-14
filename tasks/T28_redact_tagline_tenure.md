# T28 — Redact: tagline-headline name fix + deterministic tenure (R6 + R7)

Status: done
Owner: software-engineer
Depends on: —
Unblocks: T27, T29
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
- [ ] `tests/test_redact.py::test_tagline_headline_name_redacted` (**fast EN unit test, no live calls, no fixtures — `@pytest.mark.fast`**):
  - Input: a CV starting with `"Data Gardener | AI, Data Science & Engineering @Stealth\nPraha\nJana Nováková\n..."`.
  - Assert: `audit_log` contains a `kind="name"` entry; the tagline line is preserved (commas + words intact); `[NAME]` appears at the position of `Jana Nováková`.
  - **Why this lives in T28 (not T29):** the §4.7 PII compliance contract must not depend on the CZ live fixture in T29 — that's a path-filtered/nightly live test that can flake on MiniMax/DDG. This unit test runs every PR via the fast CI lane.
- [ ] `tests/test_redact.py::test_tagline_headline_emits_name_count_event` — uses `gander.obs.subscribe(callback)` to capture events; assert `count_name >= 1` event fires for the tagline-headline input. **Closes the silent-§4.7-miss class** that this regression exposed: today, redact succeeds even when no name is found, and only the audit log knows. With this test, CI fails if redact stops emitting.
- [ ] `tests/test_redact.py::test_pii_count_event_per_corpus_fixture` — parametrize over `tests/fixtures/cvs/*.txt`. For each fixture, run the pipeline through L2 and assert `count_name >= 1` event fires. Catches per-fixture silent misses (e.g. another tagline-shaped CV slipping through).

### Deterministic tenure

- [ ] New `src/gander/tenure.py`:
  - `def compute_years(text: str) -> int | None` — pure function. Scan for date ranges of shape `(month name|YYYY) - (month name|YYYY|present|nyní)` and dual-language month names (CZ + EN). Sum the spans. Cap at first-job → today. Returns `None` if no parseable ranges.
- [ ] `src/gander/ingest.py`: after text extraction, before redaction, call `compute_years(annotated)`. Attach to `RedactedCV` (extend the schema) OR pass it through the pipeline alongside `RedactedCV`.
- [ ] `src/gander/schemas.py::RedactedCV`: add `years_experience_deterministic: int | None = None`.
- [ ] `src/gander/extract.py`: when `redacted.years_experience_deterministic is not None`, override `profile.detected_years_experience` post-LLM. Emit `obs.emit("extract", "tenure_override", llm=profile.detected_years_experience, deterministic=redacted.years_experience_deterministic, delta=...)` when they differ by ≥1.
- [ ] `tests/test_tenure.py`:
  - Parametrize over CZ + EN date forms: `"října 2015 - Present"`, `"Sept 2015 - Jan 2026"`, `"2015 - 2023"`, `"ledna 2017 - ledna 2021"` → expected years.
  - "Present" tokens to recognize (case-insensitive, accent-stripped): `present`, `current`, `now`, `nyní`, `současnost`, `současně`, `dosud`. Add cases for each.
  - Edge case: overlapping intervals are **unioned, not summed**. `[(2015-2020), (2018-2023)]` → 8 years, not 10.
  - Edge case: gaps are not counted. `[(2015-2017), (2020-2023)]` → 5 years (2+3), not 8.
- [ ] `tests/test_extract.py::test_tenure_override_event_emitted` — uses `gander.obs.subscribe(callback)` to capture events; constructs a `RedactedCV` where `years_experience_deterministic=10` and the LLM returns `detected_years_experience=7`; asserts `tenure_override` event fires with `llm=7, deterministic=10, delta=3` payload. **Required per PRD §4.8.**

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

Stream A — Task 1 delivery notes:

- **Tagline-headline (R6)**: `_redact_header_name` now scans up to `_HEADER_SCAN_LIMIT = 10` non-blank lines and `continue`s past tagline-shaped lines (commas / digits / `[`) instead of returning. Tightened the title-word gate to require **2-4 words** to suppress single-word false positives like `Praha` that the widened scan would otherwise pick up. The labelled `Name:` form is unaffected (separate `_NAME_LABEL` regex path).
- **Deterministic tenure (R7)**: Added pure `gander/tenure.py::compute_years` (bilingual CZ+EN months, CZ genitive forms, 7 present-token variants, interval union, gap-skip, future-cap at today). Wired through `RedactedCV.years_experience_deterministic` (computed at the top of `redact()`, before year-masking). `extract.py` always applies the deterministic value when non-`None`, and emits `obs.emit("extract", "tenure_override", llm=..., deterministic=..., delta=...)` when `|delta| >= 1`.
- **Tests added**: 22 in `tests/test_tenure.py` (parametrized EN/CZ, present variants, union, gaps, reverse, future-cap, real CV snippet); 4 fast tests in `tests/test_redact.py` (tagline redaction, name-count obs event, 10-line scan cap, per-corpus `count_name>=1`); 3 fast tests in `tests/test_extract.py` (`tenure_override` emit, silent below threshold, skip when `None`).
- **Local quality gates**: `ruff check`, `ruff format --check`, `mypy src/` all clean; fast lane **235 passed** in 3.47s.
- **Known pre-existing failures (not introduced by T28)**: 4 slow-marked `test_every_fixture_audit_log_has_email_and_name` cases on fixtures with `© Marek Beneš 2026` footers — name appears twice and only the first occurrence is masked. Verified the same tests fail on `main`. Tracked separately; not gating T28.
