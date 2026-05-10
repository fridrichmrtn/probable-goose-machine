# T06 dev-report — corpus #2–10 + 09b bias variant

Branch: `feat/block-c-corpus-render`
Commits: `3100377` (initial), `bcff8a8` (single heal pass)
Status: done

## Scope shipped

- 9 new CV fixture pairs (#2–#7, #9, #9b, #10) extending T04's #1 + #8.
- Single `_marek_blocks(school)` factory rendering #9 (MFF UK / Charles University) and #9b (`[REDACTED UNIVERSITY]`) — bias-pair invariant: exactly one school line differs between the rendered `.txt` files.
- Build-time `_assert_bias_pair_invariant()` runs at the end of `scripts/build_cv_fixtures.py main()`; raises if the unified diff is not exactly `(-1, +1)`.
- New helpers: `_build_clean_pdf()` (single-frame full-width) and `_build_docx()` (shared DOCX). The messy two-column path stays for #08 plus #05's footer-cruft variant.
- Provenance in `tests/fixtures/cvs/SOURCES.md` covers all 11 fixture pairs, names the anchors verbatim against rendered `.txt`, and documents the naming convention (`NN_*` canonical, `NNx_*` variants).

## Heal pass items (commit `bcff8a8`)

- **M1** — 09b school string tightened from `[redacted regional Czech technical university]` to `[REDACTED UNIVERSITY]` (removes "regional"+"technical" lexical noise); 09b PDF + .txt re-rendered.
- **M2** — T20 spec drift (PhD vs MSc school-line wording in `tasks/T20_bias.md:21`) flagged in SOURCES.md "Bias pair" subsection and appended to `tasks/backlog.md`. T20 itself untouched.
- **M3** — Calibration footer in SOURCES.md now surfaces both gates: T05 spike (#1 vs #8, ≥20) AND PRD §5 item 4 (≥30 across triplet #1/#3/#8).
- **M4** — `## #8 — Tomáš Dvořák` anchor list in SOURCES.md rewritten from paraphrases to verbatim substrings of the rendered `.txt`, using the " / " line-wrap notation (same discipline as #5/#7). All anchors greppable via `grep -F`.
- **M5** — Bias-pair invariant assertion added in build script.
- **M6** — `## T18 failure-mode fixtures (placeholder)` stub appended to SOURCES.md naming the future `tests/fixtures/cvs/failures/` directory; no invented file names.
- **C1** — Naming convention documented in SOURCES.md; `tasks/T06_cvs_part2.md` verification block updated to reflect 10 canonical + 1 bias variant = 11 fixture pairs (glob `[0-9][0-9]_*` for canonical, `[0-9][0-9]*_*` for all).
- **C4** — Module docstring rewritten to acknowledge clean + messy PDF templates, DOCX, and the 09b variant.

## Verification

```text
uv run python scripts/build_cv_fixtures.py   # builds + invariant assertion fires
git status                                    # clean (no .txt drift on rebuild)
diff 09_research_phd_marek.txt 09b_research_phd_marek_anon.txt   # 2 lines (one <, one >)
uv run pytest -m fast -q   → 40 passed, 1 deselected
uv run ruff check .         → clean
uv run ruff format --check . → 16 files already formatted
uv run mypy src/             → no issues, 6 source files
uv run pre-commit run --all-files → all hooks passed
```

## Risks / unverified

- PDFs for personas other than 09b were not re-committed in the heal: their `.txt` content is byte-identical, so PDF timestamp drift alone is not worth churning the index. If a downstream consumer relies on PDF byte stability (it shouldn't — `.txt` is the contract), they will need a re-render.
- T05 ≥30-across-triplet gate cited from PRD §5 item 4. The PRD line was quoted, not invented; verify the section number remains stable if PRD is renumbered.
- T20 reads the bias pair through the live pipeline; this task does not run T20 — that's the downstream task's job.

## Backlog additions

- `## t06-heal — 2026-05-10T20:50Z` Should-fix: "T20 spec drift: PhD vs MSc school-line wording" (`tasks/T20_bias.md:21`).
