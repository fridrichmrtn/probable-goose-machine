# T27 — Role normalization + salary integration (R4 + R5)

Status: todo
Owner: ai-ml-engineer
Depends on: —
Unblocks: T29
Estimate: ~75 min

## Goal

`salary.build_queries` interpolates `profile.detected_role` verbatim (`f"{role} salary {city} site:platy.cz OR site:profesia.cz"`). For non-market headlines like `Member of Staff`, `Data Gardener`, `Founding Engineer`, `AI Whisperer`, DDG either returns junk or drifts to generic Software Engineer pages — and the salary estimator then produces an IC-band estimate for what is actually a senior management profile (real failure: 70k–130k CZK/mo for a 10y Head-of-DS-equivalent).

The salary prompt (`prompts/salary.md`) compounds this: its only worked example is Senior DS median, with no instruction to estimate at the candidate's actual seniority band when role progression and years say management. The model parrots the IC numbers it sees in the snippets.

Add a deterministic role normalization step + plumb the canonical fields into both query construction and the LLM payload. Update the salary prompt with explicit seniority-anchoring instruction and a Head-of-Data worked example.

## Deliverables

- [ ] New `src/gander/normalize.py`:
  - `def normalize_role(detected_role: str, years: int, experience_titles: list[str]) -> NormalizedRole` where `NormalizedRole` is a Pydantic model with `canonical_role: str`, `seniority_band: Literal["junior","mid","senior","staff","head","director"]`, `is_management: bool`.
  - Regex/keyword based; pure function; no LLM. Recognize the named non-market headlines (`Member of Staff`, `Data Gardener`, `Founding Engineer`, `AI Whisperer`, `Tech Lead`, `Builder`, `Engineer`) — when matched, recover the canonical role from the most-recent prior `experience_titles` entry that DOES match a market token (e.g. `Senior Manager`, `Head of`, `Director of`, `Principal`, `Staff`).
  - Token table in module-level constants. Document in module docstring.
- [ ] `src/gander/schemas.py::Profile`: add `canonical_role: str | None = None`, `seniority_band: str | None = None`, `is_management: bool = False`. None-defaulted so existing tests don't break.
- [ ] `src/gander/extract.py::extract_profile`: after the LLM call + verify, before returning, call `normalize_role(...)` and write the canonical fields back. Log `obs.emit("extract", "role_normalized", detected=detected_role, canonical=canonical_role, seniority=seniority_band)` when normalization changed something.
- [ ] `src/gander/salary.py::build_queries`:
  - Use `profile.canonical_role` when present; fall back to `detected_role`.
  - When `profile.is_management`, prepend a management-specific query: `f"{canonical_role} manager salary {city} CZK 2025"`.
  - Drop the literal headline when `canonical_role != detected_role` (i.e. the headline was non-market).
- [ ] `src/gander/salary.py::estimate_salary`: include the canonical fields in the LLM payload context: `{"role": canonical_role, "seniority": seniority_band, "is_management": is_management, "location": ..., "years": ...}`.
- [ ] `src/gander/prompts/salary.md`:
  - Add a hard rule: "Estimate at the candidate's stated seniority band, not the median of the surfaced sources. If the snippets are dominated by IC pay but the candidate is `is_management=True` and `years >= 8`, anchor on the upper-third of the IC band or on any management/lead row in the snippets — not the median."
  - Add a second worked example for a `Head of Data Science` profile with mixed IC-and-management snippets.
- [ ] `tests/test_normalize.py`:
  - Parametrize over `[("Member of Staff", 12, ["Senior Manager AI", "Head of Data Science", "Head of Tender"]) → ("head of data science", "head", True)]`, `[("Data Gardener", 10, ["Head of DS"]) → "head"]`, `[("Senior Data Scientist", 5, [...]) → "senior"]`, `[("Junior Data Analyst", 1, []) → "junior"]`.
- [ ] `tests/test_salary.py`:
  - `test_build_queries_drops_non_market_headline` — `Profile(detected_role="Member of Staff", canonical_role="head of data science", is_management=True, years=12)` → ≥1 query DOES NOT contain `"member of staff"`; ≥1 contains `"head of data science"`; ≥1 contains a management token.

## Verification

```bash
uv run pytest tests/test_normalize.py tests/test_salary.py tests/test_extract.py -v
uv run mypy src/
```

Live verification deferred to T29 (which exercises the full senior-CV path through the pipeline).

## Reference

- Plan: `/home/mf/.claude/plans/this-is-a-result-peaceful-blanket.md` § "Confirmed root causes — Salary path Sa1, Sa2, Sa3"
- PRD §4.3, §4.4

## Outcome

(fill in when done — list of normalized headlines that landed; salary prompt diff summary; before/after on Profile.pdf if rerun)
