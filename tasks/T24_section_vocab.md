# T24 — Multilingual section vocabulary (R1)

Status: todo
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

(fill in when done — list of new aliases that landed, any deltas to the gate logic)
