# T24 — Multilingual section vocabulary (R1)

Status: done
Owner: software-engineer
Depends on: —
Unblocks: T26, T29
Estimate: ~30 min

## Goal

`ingest._annotate_sections` currently only injects `## ` headers for an English-only set (`{experience, work experience, education, skills, projects, summary, profile}`) plus an all-caps regex. Bilingual CZ/EN CVs and CVs that use title-case English headers like `Languages` / `Certifications` / `Honors-Awards` / `Publications` get **zero** annotated headers, which means every section-tagged anchor downstream fails `verify_quote` and the score stage fails closed.

Extend the section vocabulary to a CZ+EN superset that covers the real CVs the operator runs.

## Deliverables

- [ ] Extend `SECTION_NAMES` in `src/gander/ingest.py:21-31` to cover:
  - **CZ**: `pracovní zkušenosti`, `zkušenosti`, `vzdělání`, `dovednosti`, `nejčastější dovednosti`, `jazyky`, `certifikace`, `ocenění`, `publikace`, `projekty`, `shrnutí`, `profil`, `kontakt`.
  - **EN superset (existing + new)**: `experience`, `work experience`, `professional experience`, `education`, `skills`, `projects`, `summary`, `profile`, `languages`, `certifications`, `honors-awards`, `awards`, `publications`, `contact`.
- [ ] In `_looks_like_section_header`, normalize the line via Unicode NFC + lowercase + collapse whitespace before set-membership check. Strip diacritics for the comparison so `Vzdělání` matches whether the model strips diacritics or not. (The injected `## ` keeps the original casing.)
- [ ] Gate header promotion on `len(stripped) <= 40` AND standalone-short-line so a paragraph mention of "Languages" doesn't get promoted.
- [ ] `tests/test_ingest.py::test_section_vocabulary_cz` — parametrized over the CZ alias set; assert `_annotate_sections` injects `## ` for each.
- [ ] `tests/test_ingest.py::test_section_vocabulary_en_extended` — parametrized over the EN additions.
- [ ] `tests/test_ingest.py::test_inline_languages_not_promoted` — `"He learned several languages including French and German."` is NOT promoted.

## Verification

```bash
uv run pytest tests/test_ingest.py -v
uv run pytest tests/ -v   # nothing else regresses
```

## Reference

- Plan: `/home/mf/.claude/plans/this-is-a-result-peaceful-blanket.md` § "Confirmed root causes — Score path S1"
- PRD §4.5, §4.7

## Outcome

`SECTION_NAMES` expanded from 7 EN entries to 27 entries (14 EN + 13 CZ).

**EN additions** (existing 7 retained): `work experience`, `professional experience`, `languages`, `certifications`, `honors-awards`, `awards`, `publications`, `contact`.

**CZ additions** (13): `pracovní zkušenosti`, `zkušenosti`, `vzdělání`, `dovednosti`, `nejčastější dovednosti`, `jazyky`, `certifikace`, `ocenění`, `publikace`, `projekty`, `shrnutí`, `profil`, `kontakt`.

**Normalization approach**: NFD decompose + strip combining marks (`unicodedata.category(c) != "Mn"`) + lowercase + whitespace collapse. So `Vzdělání`, `vzdelani`, and `  VZDĚLÁNÍ  ` all hash to the same key. Comparison key is precomputed in `_NORMALIZED_SECTION_NAMES` (frozenset) at import time.

**Gate logic**: `_looks_like_section_header` now rejects lines longer than `_MAX_HEADER_CHARS = 40` (covers every alias plus typical decorations like trailing colon / single trailing word, while excluding paragraph sentences that mention a section noun). Existing all-caps regex path retained.

**Tests added** in `tests/test_ingest.py`:
- `test_section_vocabulary_cz` — parametrized over 13 CZ aliases, with both original and NFD-stripped variants.
- `test_section_vocabulary_en_extended` — parametrized over the 7 EN additions.
- `test_inline_languages_not_promoted` — sentence form.
- `test_inline_languages_list_not_promoted` — 54-char inline summary (exercises the length gate).

**Verification**: `uv run pytest -m fast tests/test_ingest.py` → 39 passed. Full fast suite → 218 passed, 47 deselected. No adjacent-suite regressions.
