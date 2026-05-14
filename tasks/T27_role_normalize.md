# T27 — Role normalization + salary integration (R4 + R5)

Status: todo
Owner: ai-ml-engineer
Depends on: T28
Unblocks: T29
Estimate: ~90 min

## Goal

`salary.build_queries` interpolates `profile.detected_role` verbatim (`f"{role} salary {city} site:platy.cz OR site:profesia.cz"`). For non-market headlines like `Member of Staff`, `Data Gardener`, `Founding Engineer`, `AI Whisperer`, DDG either returns junk or drifts to generic Software Engineer pages — and the salary estimator then produces an IC-band estimate for what is actually a senior management profile (real failure: 70k–130k CZK/mo for a 10y Head-of-DS-equivalent).

The salary prompt (`prompts/salary.md`) compounds this: its only worked example is Senior DS median, with no instruction to estimate at the candidate's actual seniority band when role progression and years say management. The model parrots the IC numbers it sees in the snippets.

Add a deterministic role normalization step + plumb the canonical fields into both query construction and the LLM payload. Update the salary prompt with explicit seniority-anchoring instruction and a Head-of-Data worked example.

## Deliverables

- [ ] New `src/gander/normalize.py` (hard cap: ~150 LOC, single function + module-level tables, no class hierarchy):
  - `def normalize_role(detected_role: str, years: int, experience_titles: list[str]) -> NormalizedRole` where `NormalizedRole` is a Pydantic model with `canonical_role: str`, `seniority_band: Literal["junior","mid","senior","staff","head","director"]`, `is_management: bool`, `source: Literal["market_token","named_headline","tagline_shape","experience_recovery","llm_fallback","unrecognized"]`.
  - **Polarity: market-token allowlist FIRST, denylist + tagline-shape SECOND, LLM fallback LAST.** Rationale: a hardcoded denylist of named non-market headlines (`Member of Staff`, `Data Gardener`, `Founding Engineer`, `AI Whisperer`) will rot — the next operator's headline won't be on it. Polarity-flipped recognition makes "doesn't match a market token" the signal, which generalizes.
    1. **Market-token allowlist hit on `detected_role`** → `canonical_role = detected_role.lower()`, derive `seniority_band` + `is_management` from the matched token. Source: `"market_token"`. Token table examples: `senior`, `staff`, `principal`, `lead`, `manager`, `head of`, `director of`, `vp`, `chief`, `analyst`, `scientist`, `engineer`, `developer`, `consultant`. CZ tokens too: `vedoucí`, `ředitel`, `manažer`, `analytik`, `vývojář`.
    2. **Named-headline denylist hit** (Member of Staff, Data Gardener, Founding Engineer, AI Whisperer) → recover from `experience_titles[0]` that matches a market token. Source: `"named_headline"`.
    3. **Tagline-shape detection** — `detected_role` contains `|`, `@`, or `&` separator characters → treat as tagline, recover from `experience_titles[0]`. Source: `"tagline_shape"`. **This catches the next "Data Gardener | AI, Data Science & Engineering @Stealth" without needing a denylist update.**
    4. **No prior `experience_titles` to recover from + no market token** → call LLM canonicalization fallback (see below). Source: `"llm_fallback"`.
    5. **LLM fallback also fails or returns unparseable** → return `NormalizedRole(canonical_role=detected_role.lower(), seniority_band="mid", is_management=False, source="unrecognized")` and emit `role_unrecognized` event.
  - Token table in module-level constants. Document in module docstring including the rationale for polarity-first design.
- [ ] New `src/gander/normalize.py::_llm_canonicalize_role(detected_role, experience_titles, years)` — fallback when no deterministic path resolves. Single short LLM call to `abab6.5s-chat` (cheapest tier) with a strict JSON schema asking for `{canonical_role, seniority_band, is_management, confidence}`. Discard if `confidence < 0.6`. Per CLAUDE.md "Separate generation from grading": this is a separate cheap judge, not the same model that generated the salary estimate.
- [ ] `src/gander/schemas.py::Profile`: add `canonical_role: str | None = None`, `seniority_band: str | None = None`, `is_management: bool = False`. None-defaulted so existing tests don't break.
- [ ] `src/gander/extract.py::extract_profile`: after the LLM call + verify, before returning, **apply T28's deterministic tenure override FIRST** (so `years` reflects the deterministic value), then call `normalize_role(detected_role, profile.detected_years_experience, experience_titles)` so the normalizer's seniority lift fires on the trustworthy tenure number. Write the canonical fields back. Log `obs.emit("extract", "role_normalized", detected=detected_role, canonical=canonical_role, seniority=seniority_band, source=source)` when normalization changed `detected_role`. Log `obs.emit("extract", "role_unrecognized", detected=detected_role, fallback="mid_default")` when source is `"unrecognized"`.
- [ ] `src/gander/salary.py::build_queries`:
  - Use `profile.canonical_role` when present; fall back to `detected_role`.
  - When `profile.is_management`, prepend a management-specific query: `f"{canonical_role} manager salary {city} CZK 2025"`.
  - Drop the literal headline when `canonical_role != detected_role` (i.e. the headline was non-market).
- [ ] `src/gander/salary.py::estimate_salary`: include the canonical fields in the LLM payload context: `{"role": canonical_role, "seniority": seniority_band, "is_management": is_management, "location": ..., "years": ...}`.
- [ ] `src/gander/prompts/salary.md` — **3-shot block, not single example** (one example flips the anchor; doesn't teach the seniority decision):
  - Add a hard rule: "Estimate at the candidate's stated seniority band, not the median of the surfaced sources. If the snippets are dominated by IC pay but the candidate is `is_management=True` and `years >= 8`, anchor on the upper-third of the IC band or on any management/lead row in the snippets — not the median."
  - **Carve-out for HARD RULE 4** (currently: "if fewer than 2 results corroborate, emit tightest defensible range"): "Rule 4 does not apply when `is_management=True` and snippets are IC-only — extrapolate above the IC band and name the extrapolation in `reasoning`." Without this carve-out, Rule 4 actively fights the senior lift.
  - Replace the single Senior DS example with a **3-shot block** demonstrating the seniority decision:
    1. **Junior IC** — anchors at snippet median.
    2. **Senior IC** — anchors at upper third of snippets.
    3. **Management with IC-only snippets** — anchors above the snippets, names the gap in `reasoning` (e.g. "Snippets reflect IC pay (~150k); candidate is Head-level with 10y → estimating 220–280k based on management premium typical for CZ market").
  - Without all three, the model can't generalize the seniority lift; you'll hit the same regression on the next non-market headline.
- [ ] `tests/test_normalize.py`:
  - Parametrize over named-headline cases: `[("Member of Staff", 12, ["Senior Manager AI", "Head of Data Science", "Head of Tender"]) → ("head of data science", "head", True, "named_headline")]`, `[("Data Gardener", 10, ["Head of DS"]) → "head"]`.
  - Tagline-shape cases (no denylist update needed): `[("Data Gardener | AI, Data Science & Engineering @Stealth", 10, ["Senior Manager AI"]) → ("senior manager ai", "senior", True, "tagline_shape")]`, `[("AI Whisperer @ Anywhere", 5, ["Lead DS"]) → ("lead ds", "senior", False, "tagline_shape")]`.
  - Market-token hits: `[("Senior Data Scientist", 5, [...]) → ("senior data scientist", "senior", False, "market_token")]`, `[("Junior Data Analyst", 1, []) → ("junior data analyst", "junior", False, "market_token")]`, `[("Vedoucí týmu DS", 8, []) → ("vedoucí týmu ds", "head", True, "market_token")]`.
  - Unrecognized fallback: `[("Wizard of Bytes", 4, []) → seniority_band="mid", source="unrecognized"]`.
- [ ] `tests/test_normalize.py::test_role_normalized_event_emitted` — uses `gander.obs.subscribe(callback)` to capture events. Asserts `role_normalized` fires with `detected/canonical/seniority/source` payload when normalization changes the role. **Required per PRD §4.8.**
- [ ] `tests/test_normalize.py::test_role_unrecognized_event_emitted` — for unrecognized headline with no recoverable experience_titles → asserts `role_unrecognized` fires with `detected` and `fallback="mid_default"` payload. Catches silent denylist rot.
- [ ] `tests/test_salary.py`:
  - `test_build_queries_drops_non_market_headline` — `Profile(detected_role="Member of Staff", canonical_role="head of data science", is_management=True, years=12)` → ≥1 query DOES NOT contain `"member of staff"`; ≥1 contains `"head of data science"`; ≥1 contains a management token.
  - `test_build_queries_handles_tagline_shape` — `Profile(detected_role="Data Gardener | AI @Stealth", canonical_role="senior data scientist", is_management=False)` → ≥1 query contains `"senior data scientist"`; no query contains `|` or `@`.
- [ ] `tests/test_salary.py::test_salary_prompt_3shot_present` — read `prompts/salary.md`; assert it contains markers for all three example types (`junior`, `senior`, `management with IC-only snippets`). Catches accidental prompt-revert.

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
