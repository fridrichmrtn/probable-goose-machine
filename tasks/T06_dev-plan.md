# T06 Dev Plan — corpus #2–10 + bias-pair anchor + provenance

Worktree: `/home/mf/GitHub/probable-goose-machine/.worktrees/block-c` (branch `feat/block-c-corpus-render`).
Pass that path explicitly to every command. Do NOT cd elsewhere.

## Scope (one commit)

Extend the existing `scripts/build_cv_fixtures.py` (do NOT introduce a new PDF
library) with 8 personas + 1 anonymized variant, regenerate goldens, extend
`SOURCES.md`, flip the task file to `done`. Render templates: a new
`_build_clean_pdf()` for clean PDFs, the existing `_build_messy_pdf()` for the
one messy PDF, and `build_junior_docx`-style python-docx for DOCX outputs.

## Files to touch

- [ ] `scripts/build_cv_fixtures.py` — extend in place.
- [ ] `tests/fixtures/cvs/SOURCES.md` — append 9 sections + bias-pair section + extended calibration table.
- [ ] `tests/fixtures/cvs/02_da_svoboda.pdf` + `.txt` (PDF clean).
- [ ] `tests/fixtures/cvs/03_ds_horak.pdf` + `.txt` (PDF clean).
- [ ] `tests/fixtures/cvs/04_mle_kralova.docx` + `.txt`.
- [ ] `tests/fixtures/cvs/05_mlops_benes.pdf` + `.txt` (PDF messy, two-column + footer cruft).
- [ ] `tests/fixtures/cvs/06_nlp_ds_pokorna.docx` + `.txt`.
- [ ] `tests/fixtures/cvs/07_senior_ds_holub.pdf` + `.txt` (PDF clean).
- [ ] `tests/fixtures/cvs/09_research_phd_marek.pdf` + `.txt` (PDF clean, MFF UK).
- [ ] `tests/fixtures/cvs/09b_research_phd_marek_anon.pdf` + `.txt` (PDF clean, generic school).
- [ ] `tests/fixtures/cvs/10_head_of_data_zemanova.docx` + `.txt`.
- [ ] `tasks/T06_cvs_part2.md` — final step: `Status: todo` → `Status: done` + Outcome paragraph.

Tests to add: **N/A** — verification is fixture rendering + diff-driven; existing
fast-test suite is the regression gate (see Verification).

## Implementation steps

### 1. Refactor `scripts/build_cv_fixtures.py`

- Keep DejaVu font registration block, `CVBlock`, `_build_messy_pdf`,
  `extract_pdf_text`, `extract_docx_text`, `build_junior_docx`, `build_senior_pdf`
  exactly as-is (precedent + working).
- Add `_build_clean_pdf(out_path, blocks, *, name, role, contact)`:
  single-frame `BaseDocTemplate` (one full-width Frame, `showBoundary=0`),
  same DejaVu fonts, header band drawn in `onPage` with name + role + contact,
  serif body / sans heading consistent with the messy PDF so styles look
  cohesive. No footer cruft.
- Add 9 block builder functions (one per persona). Each returns a
  `list[CVBlock]` with sections: Summary, Experience, Education, Skills,
  Selected projects (where natural). Embed 5–15 verifiable anchors per CV
  (named projects, version-pinned tech, quantified outcomes).
  - `_svoboda_blocks()` — Petra Svobodová, 3y, marketing analyst →
    Data Analyst transition. Employer history e.g. Productboard → Rohlik.
    Stack: SQL/dbt/Python/Looker, light scikit-learn. VŠE Prague.
  - `_horak_blocks()` — Lukáš Horák, 5y mid DS at Mall.cz / Seznam.cz.
    Churn-model anchor matching the example in T06_cvs_part2.md. ČVUT FIT.
  - `_kralova_paragraphs()` — Jana Králová, 6y ML eng at Slido / Avast.
    PyTorch 2.3 / FastAPI / K8s stack. ČVUT FEL. (DOCX returns plain
    paragraphs, not CVBlocks — mirror `build_junior_docx` shape.)
  - `_benes_blocks()` — Marek Beneš, 7y MLOps/Platform at Kiwi.com / Pilulka.
    Argo Workflows / Feast / MLflow / Kubernetes anchors. Mention RFC
    authorship. VUT Brno. **Used with `_build_messy_pdf` + footer cruft.**
  - `_pokorna_paragraphs()` — Eva Pokorná, 8y NLP-focused DS at Datamole /
    Seznam.cz. spaCy / HuggingFace transformers / Czech NER fine-tuning
    anchors. MUNI. (DOCX paragraphs.)
  - `_holub_blocks()` — David Holub, 10y Senior DS at Komerční banka /
    Generali Česká. Credit-risk / survival-analysis / SHAP anchors,
    leadership of a 4-person DS team. VŠE.
  - `_marek_blocks(school: str)` — Adam Marek, 12y PhD academia → industry
    at Česká spořitelna research lab. **Takes school as a parameter** so
    09 and 09b are byte-identical except the school line. Anchors:
    NeurIPS workshop paper, T-Mobile CZ collab project, PyTorch Lightning
    research codebase. Brno → Prague.
  - `_zemanova_paragraphs()` — Eliška Zemanová, 15y Head of Data at
    Rohlik / ČSOB. Org-design anchors (built 22-person org from 4),
    data-platform migration, board-level reporting. VŠE. (DOCX paragraphs.)
- Add 9 `build_*` functions wiring each persona to its template:
  - `build_svoboda_pdf`, `build_horak_pdf`, `build_holub_pdf`,
    `build_marek_pdf(out_path, *, school)` — call `_build_clean_pdf`.
  - `build_benes_pdf` — call `_build_messy_pdf` with a footer-cruft variant
    (parameterise `_build_messy_pdf` to accept an optional `footer_cruft: str`
    drawn in `_draw_chrome` below the existing footer band; default `None`
    preserves senior PDF byte-for-byte).
  - `build_kralova_docx`, `build_pokorna_docx`, `build_zemanova_docx` —
    new DOCX builders each taking a `(out_path, paragraphs, name, role,
    contact)` shape OR mirroring `build_junior_docx` per-CV. Pick whichever
    is shorter; the script already biases inline so per-CV is fine.
- Extend `main()` to render all 11 fixture pairs (the original 2 from T04 +
  9 new). Use a single list-driven loop where natural so the rendering loop
  reads as data, not 11 stamped-out blocks.

### 2. Bias-pair invariant (CRITICAL — T20 dependency)

- `_marek_blocks("MFF UK / Charles University, Prague")` and
  `_marek_blocks("[redacted regional Czech technical university]")` must
  produce structures identical except in the one school string.
- Verification step: after rendering, run
  `diff tests/fixtures/cvs/09_research_phd_marek.txt tests/fixtures/cvs/09b_research_phd_marek_anon.txt`
  and confirm a single hunk that touches only the school line.
- If the diff shows more than the school line: STOP and re-plan; do not
  paper over with tweaks.

### 3. Calibration discipline

- No literal salary numbers in CV bodies (CVs convey level via title,
  scope, team size, seniority signals — not by stating CZK figures).
- Calibration band lives in `SOURCES.md` table only:
  - 02 ~55–70k, 03 ~75–95k (mid acceptance anchor), 04 ~85–110k,
    05 ~110–140k, 06 ~110–140k, 07 ~140–180k, 09/09b ~140–180k
    research-pay, 10 ~180–250k.
  - Junior #1 (45–55k) and Staff #8 (160–220k) entries already exist.
- Confirm monotonicity by visual scan of the table.

### 4. Extend `tests/fixtures/cvs/SOURCES.md`

For each new CV, append a section in the same shape T04 used (#1 / #8):

- `## ## NN — Name — Role (FORMAT)`
- Files line.
- Format-stress purpose.
- Role / seniority target.
- Anchors (5–15 verifiable substrings copied from the rendered .txt — copy
  AFTER rendering so substrings actually survive extraction).

Then add:

- `## Bias pair: 09 vs 09b` — explain the controlled-variable choice (school
  line only), why this pair exists (T20 CZ-school-prestige bias smoke test),
  and the byte-level invariant the diff check enforces.
- Append the 9 new rows (02, 03, 04, 05, 06, 07, 09, 09b, 10) to the
  calibration table immediately after the existing #1 / #8 rows. Order rows
  by persona number for readability.

### 5. Flip task file

Final step before commit. Edit `tasks/T06_cvs_part2.md`:

- `Status: todo` → `Status: done`.
- Tick the deliverable checkboxes that match what shipped.
- Fill in the `## Outcome` paragraph with: rendering tool notes
  (`_build_clean_pdf` added, footer-cruft variant of `_build_messy_pdf`,
  DOCX path unchanged), any deltas from the spec, and verification evidence
  bullets (file counts, diff result, fast-test status).

## Verification (run from worktree root, in this order)

```bash
# 1. Regenerate all 11 fixture pairs.
uv run --project /home/mf/GitHub/probable-goose-machine/.worktrees/block-c \
  python /home/mf/GitHub/probable-goose-machine/.worktrees/block-c/scripts/build_cv_fixtures.py

# 2. File counts.
ls /home/mf/GitHub/probable-goose-machine/.worktrees/block-c/tests/fixtures/cvs/*.pdf \
   /home/mf/GitHub/probable-goose-machine/.worktrees/block-c/tests/fixtures/cvs/*.docx | wc -l   # expect 11
ls /home/mf/GitHub/probable-goose-machine/.worktrees/block-c/tests/fixtures/cvs/*.txt | wc -l    # expect 11

# 3. Per-fixture extraction sanity (>200 chars, mirroring T06 contract).
for f in /home/mf/GitHub/probable-goose-machine/.worktrees/block-c/tests/fixtures/cvs/*.pdf \
         /home/mf/GitHub/probable-goose-machine/.worktrees/block-c/tests/fixtures/cvs/*.docx; do
  uv run --project /home/mf/GitHub/probable-goose-machine/.worktrees/block-c python -c "
from pathlib import Path
from gander.ingest import extract_text
p = Path('$f')
t = extract_text(p.read_bytes(), p.name)
assert len(t) > 200, f'{p.name}: {len(t)} chars'
print(f'{p.name}: {len(t)} chars OK')
"
done

# 4. Bias-pair invariant: diff must touch ONLY the school line.
diff /home/mf/GitHub/probable-goose-machine/.worktrees/block-c/tests/fixtures/cvs/09_research_phd_marek.txt \
     /home/mf/GitHub/probable-goose-machine/.worktrees/block-c/tests/fixtures/cvs/09b_research_phd_marek_anon.txt

# 5. Existing fast-test suite is green.
uv run --project /home/mf/GitHub/probable-goose-machine/.worktrees/block-c pytest -m fast -q

# 6. Lint + format clean.
uv run --project /home/mf/GitHub/probable-goose-machine/.worktrees/block-c \
  ruff format --check scripts/ src/ tests/
uv run --project /home/mf/GitHub/probable-goose-machine/.worktrees/block-c \
  ruff check scripts/ src/ tests/

# 7. Pre-commit dry run before commit.
uv run --project /home/mf/GitHub/probable-goose-machine/.worktrees/block-c \
  pre-commit run --files \
    scripts/build_cv_fixtures.py \
    tests/fixtures/cvs/SOURCES.md \
    tasks/T06_cvs_part2.md
```

If any step fails, fix root cause; do not paper over.

## Risks and mitigations

- **Bias-pair drift.** Easy to accidentally vary punctuation, spacing, or a
  date when hand-authoring 09 vs 09b. Mitigation: single
  `_marek_blocks(school)` function — call site is the ONLY place the two
  diverge. Diff check (verification step 4) is the gate.
- **DejaVu fonts absent on the build host.** Script already falls back to
  Helvetica/Times-Roman with lossy diacritics. Acceptable but: if the bias
  pair is rendered on a host without DejaVu, anchors with diacritics may
  drop. Mitigation: confirm `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`
  exists before rendering; if absent, install (or run on a host where it is)
  rather than ship lossy goldens.
- **Anchor strings that don't survive PDF extraction.** Quantified anchors
  (e.g., `"reduced churn by 11%"`) may be split across columns/lines in the
  messy PDF. Mitigation: copy SOURCES.md anchor substrings from the
  rendered `.txt`, not from the source code. For the messy PDF (05), bias
  anchors toward short phrases that survive `pypdf` extraction even when
  interleaved.
- **Calibration realism.** Czech ML/DS market salaries shift; the rough
  bands are CZK gross monthly. State as "rough" in the table; do not
  pretend they are sourced.
- **Demographic correlated signals.** The bias pair intentionally varies
  school prestige; the rest of the corpus must NOT introduce other
  demographic signals (age cues beyond years of experience, gender-coded
  hobbies, ethnicity markers). Names are a controlled choice (Czech
  fictional); keep employer/skill profiles plausible across persona genders
  rather than gender-typed.
- **Time budget.** ~2h estimate. If `_build_clean_pdf` discovery balloons
  past 30 min, fall back to one-frame `BaseDocTemplate` copied from the
  messy PDF with the gutter removed — do not invent a new layout system.

## Commit

One commit at the end. No co-author trailers. No `--no-verify`. No force push.

```text
T06: corpus #2–10 + bias-pair anchor + provenance

Adds 8 personas + 09b anonymized variant, extends SOURCES.md provenance,
factors _marek_blocks(school) so 09/09b differ only in the school line
(byte-level diff verified). Reuses existing reportlab + python-docx scaffold
via new _build_clean_pdf helper; messy PDF path adds optional footer cruft
for 05_mlops_benes.

Verification: 11 fixture pairs render; every PDF/DOCX > 200 chars extracted;
diff 09 vs 09b touches only the school line; fast-test suite green;
ruff format + check clean.
```

Stage explicit paths only — no `git add -A`.
