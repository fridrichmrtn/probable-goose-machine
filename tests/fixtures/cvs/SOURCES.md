# CV fixture sources

Synthesized CZ data / DS / ML CVs used by the test suite and the user-facing
eval-corpus runner. T04 seeded the two acceptance anchors (#1 junior, #8
senior); T06 fills in #2–7, #9, #10 plus a 09b anonymized variant of #9 for
the T20 bias smoke test.

All names are clearly fictional. Employers are real CZ companies or plausible
CZ-based subsidiaries. Universities are CZ. Salaries (when implied by role)
match the Czech market in CZK monthly gross — bands live in the calibration
table below, never in CV bodies.

## Rendering tools

- DOCX: `python-docx` straight to `.docx` via `_build_docx` (shared by 04, 06,
  10) plus the bespoke `build_junior_docx` for #1.
- PDF (clean): `reportlab` single-frame full-width layout via
  `_build_clean_pdf` (02, 03, 07, 09, 09b). Header band drawn in `onPage`;
  serif body / sans heading consistent with the messy template.
- PDF (messy): `reportlab` two-column layout with deliberate stressors
  (uneven 42/58 column widths, header/footer bands, mixed serif/sans body,
  mid-phrase column breaks) via `_build_messy_pdf` (08 + 05). #05 passes the
  optional `footer_cruft` argument so a "© Marek Beneš 2026 · prepared for
  internal review · do not redistribute" line is drawn into the bottom of the
  body — pdfplumber will see footer chrome interleaved with content.
- Czech diacritics handled via DejaVu Sans / Serif TTF registration; falls
  back to Helvetica/Times-Roman if DejaVu is absent (output then drops
  diacritics — acceptable lossy mode).
- `.txt` golden text is the actual output of `pypdf.PdfReader` (PDF) and
  `python-docx Document.paragraphs` (DOCX), not the source content. Goldens
  reflect what L1 ingestion will see, so verify-against-source tests are
  honest.

Single source script: [`scripts/build_cv_fixtures.py`](../../../scripts/build_cv_fixtures.py).
Re-run with `uv run python scripts/build_cv_fixtures.py` to regenerate.

## #1 — Jan Novotný — Junior Data Analyst (DOCX)

- Files: `01_junior_da_novotny.docx`, `01_junior_da_novotny.txt`.
- Format-stress purpose: clean DOCX baseline; T07 must parse it cleanly via
  `python-docx` with no surprises.
- Role / seniority target: junior, ≤2 years total experience, narrow stack,
  no leadership signals.
- Anchors (verifiable substrings the pipeline can quote):
  1. "Junior Data Analyst" / 1 year at Mall.cz, Prague.
  2. "reducing reporting turnaround from 2 days to 4 hours" — quantified
     outcome.
  3. "18 dbt 1.7 models on PostgreSQL 15" — tech stack with versions.
  4. "column-level tests covering 92% of business-critical fields".
  5. "pandas 2.2" / "Python 3.11" stack signal.
  6. "6.4% drop in repeat purchases among the Home & Garden segment" —
     quantified analytical outcome.
  7. "11 alerts during my first rotation without escalation".
  8. "Bachelor of Economics and Management — VŠE Prague".
  9. "thesis on revenue forecasting using Prophet".
  10. Languages: Czech native + English C1 (FCE 2021).

## #8 — Tomáš Dvořák — Staff ML Engineer (PDF, two-column)

- Files: `08_staff_ml_engineer_dvorak.pdf`, `08_staff_ml_engineer_dvorak.txt`.
- Format-stress purpose: messy two-column reportlab PDF — uneven column
  widths (42% / 58%), header/footer bands, mixed serif body + sans header,
  diacritics requiring TTF embedding. Exercises pdfplumber's column-aware
  fallback when `pypdf` returns interleaved text.
- Role / seniority target: senior anchor — 13 years, 3 roles spanning Avast →
  Kiwi.com → ČSOB, leadership/staff signals (tech lead, guild founder, RFC
  author), broad+deep stack.
- Anchors (verbatim substrings of the rendered `.txt`; two-column wrap
  breaks long phrases mid-line, so anchors are short or split with " / "
  to indicate a line break — same discipline as #5 / #7):
  1. "Staff Machine Learning Engineer" — header + summary opener.
  2. "13 years of experience across" — quantified tenure.
  3. "leading a team of 6 engineers" — leadership.
  4. "12M+ daily scoring" — scale at ČSOB.
  5. "cutting median" / "inference latency from 240 ms to 38" —
     quantified latency win (wraps across two lines).
  6. "reducing infra cost by 41%" — quantified cost win.
  7. "Founded the ML platform guild (8" / "engineers across 3 squads)" —
     guild-founder signal (wraps).
  8. "two-tower" / "retrieval-then-ranking architecture" — tech depth
     broken across the column wrap.
  9. "lifting click-through on the top-3" — quantified A/B opener.
  10. "billion file scans per month at peak" — Avast scale.
  11. "false-positive rate from 0.32% to 0.11%" — quantified quality.
  12. "calibrated LightGBM 2.1" — version-pinned model.
  13. "Ing. (M.Sc.) in Computer Science — ČVUT FIT," — graduate degree.
  14. "Bc. (B.Sc.) in Computer Science — VUT Brno" — undergrad.
  15. "presented at MLPrague 2022" — community / external visibility.

## #2 — Petra Svobodová — Data Analyst (PDF clean)

- Files: `02_da_svoboda.pdf`, `02_da_svoboda.txt`.
- Format-stress purpose: clean single-frame PDF — baseline for the
  layout-trivial PDF path (no columns, no footer cruft); proves the clean
  template extracts cleanly through `pypdf`.
- Role / seniority target: 3 years, marketing-analytics → data-analyst
  transition, narrow stack, no leadership.
- Anchors (verifiable substrings copied from the rendered `.txt`):
  1. "Data Analyst with 3 years of experience transitioning from marketing
     analytics".
  2. "Data Analyst — Rohlik.cz, Prague".
  3. "42 models on PostgreSQL 15" — dbt model count + version.
  4. "Reduced the daily ops-dashboard refresh from 18" / "minutes to 4
     minutes" — quantified outcome.
  5. "9.2% drop in picks-per-hour" — quantified analytical outcome.
  6. "Marketing Analyst — Productboard, Prague".
  7. "scikit-learn 1.4" / "Python 3.11" / "pandas 2.2" stack signals.
  8. "14% activation gap for EU SMB accounts" — quantified analytical
     outcome from prior role.
  9. "Ing. (M.Sc.) in Quantitative Methods — VŠE Prague".
  10. "thesis on uplift modelling for direct-mail campaigns".

## #3 — Lukáš Horák — Data Scientist (PDF clean)

- Files: `03_ds_horak.pdf`, `03_ds_horak.txt`.
- Format-stress purpose: clean single-frame PDF; acts as the **mid
  acceptance anchor** for T17 (40–70 score band, 70–110k CZK).
- Role / seniority target: 5 years, mid Data Scientist across Czech
  e-commerce/search, mentorship signal but no team-lead title.
- Anchors:
  1. "Data Scientist with 5 years of mid-level experience".
  2. "Led the customer churn model retraining for Mall.cz, reducing 30-day
     churn by 11%" — quantified outcome.
  3. "scikit-learn 1.4, MLflow 2.7, PostgreSQL 15" — version-pinned stack.
  4. "LightGBM 3.3" / "Airflow 2.9" — version pins.
  5. "cutting forecast MAPE on top-200 SKUs from 24% to 17%" — quantified.
  6. "Data Scientist — Seznam.cz, Prague" / "Zboží.cz product feed".
  7. "XGBoost 1.7, 220M rows daily" — scale + version.
  8. "Lifted top-3 CTR by 6.8% in a 30-day A/B" — quantified A/B.
  9. "Ing. (M.Sc.) in Computer Science — ČVUT FIT, Prague".
  10. "Churn 2024 (Mall.cz)" — named project anchor.

## #4 — Jana Králová — Machine Learning Engineer (DOCX)

- Files: `04_mle_kralova.docx`, `04_mle_kralova.txt`.
- Format-stress purpose: clean DOCX; `python-docx` round-trip baseline for a
  mid-senior CV body.
- Role / seniority target: 6 years, ML Engineer focused on training→serving
  handoff at Slido and Avast.
- Anchors:
  1. "Machine Learning Engineer with 6 years of experience".
  2. "Machine Learning Engineer — Slido (Cisco), Brno".
  3. "PyTorch 2.3, FastAPI, Kubernetes 1.29" — version-pinned stack.
  4. "Argo Rollouts with automatic canary on online accuracy".
  5. "Kubeflow Pipelines 2.1 setup, cutting retrain wall-clock from 9 hours
     to 70 minutes" — quantified outcome + version pin.
  6. "model-to-staging lead time from 6 days to 11 hours" — quantified.
  7. "Junior ML Engineer — Avast, Prague" — role progression signal.
  8. "Ing. (M.Sc.) in Computer Science — ČVUT FEL, Prague".
  9. "ONNX, Docker, PostgreSQL, Prometheus, Grafana" — platform stack.
  10. "Languages: Czech (native), English (C1), Slovak (fluent)".

## #5 — Marek Beneš — MLOps / Platform Engineer (PDF messy + footer cruft)

- Files: `05_mlops_benes.pdf`, `05_mlops_benes.txt`.
- Format-stress purpose: messy two-column PDF **plus footer cruft** drawn
  into the bottom of the body — the chrome line overlaps content so
  pdfplumber needs to recognise and strip a footer band that does not sit
  cleanly below the body. This is the worst-case extraction CV in the
  corpus.
- Role / seniority target: 7 years, MLOps/platform-engineer track, RFC
  authorship signal but no people-management title.
- Anchors (copied from rendered `.txt`, biased toward short phrases that
  survive interleaved column breaks):
  1. "MLOps / Platform Engineer with 7" / "years building the ML
     infrastructure".
  2. "MLOps Engineer — Kiwi.com," — role line.
  3. "Argo Workflows 3.5" — version pin.
  4. "180+ scheduled training jobs per" / "week" — quantified scale.
  5. "cutting orchestration" / "infra cost by 38%" — quantified outcome.
  6. "Authored the internal RFC on" / "feature-store contracts" —
     RFC-authorship signal.
  7. "Feast 0.40" / "Redis 7" / "MLflow 2.10" — version-pinned stack.
  8. "Reduced the data-scientist setup time" / "from 2 days to under 30
     minutes" — quantified.
  9. "Ing. (M.Sc.) in Information Systems — VUT" / "Brno".
  10. Footer cruft anchor: "© Marek Beneš 2026 · prepared for internal
      review · do not redistribute" — used by T07 tests as a *negative*
      anchor (extraction layer must drop or quarantine it).

## #6 — Eva Pokorná — Senior NLP Data Scientist (DOCX)

- Files: `06_nlp_ds_pokorna.docx`, `06_nlp_ds_pokorna.txt`.
- Format-stress purpose: clean DOCX; NLP-specific anchors stress the
  vocabulary side of T11's claim-extraction.
- Role / seniority target: 8 years, senior NLP-focused DS; incomplete PhD
  signal in education history (intentional non-linear path).
- Anchors:
  1. "NLP-focused Data Scientist with 8 years of experience".
  2. "Senior NLP Data Scientist — Datamole, Prague".
  3. "Small-E-Czech BERT" — Czech-specific NLP signal.
  4. "F1 on the agritech holdout: 0.918 (baseline 0.74)" — quantified.
  5. "Label Studio 1.13" — version-pinned tooling.
  6. "labelling-to-training-set lead time from 11 days to 3 days" —
     quantified.
  7. "XLM-R model, lifting suggest-acceptance rate by 8.4%" — quantified.
  8. "Reduced false-positive rate from 1.8% to 0.9%" — quantified.
  9. "Ph.D. (incomplete, 2 years) in Computational Linguistics — MUNI Brno"
     — non-linear education path.
  10. "RobeCzech" + "Czech-language NER and POS tagging" — domain depth.

## #7 — David Holub — Senior Data Scientist (PDF clean)

- Files: `07_senior_ds_holub.pdf`, `07_senior_ds_holub.txt`.
- Format-stress purpose: clean single-frame PDF that flows to a second
  page; tests multi-page header repetition in the clean template.
- Role / seniority target: 10 years, senior DS in CZ banking/insurance,
  leads a 4-person team.
- Anchors:
  1. "Senior Data Scientist with 10 years of experience in Czech banking
     and insurance".
  2. "Senior Data Scientist — Komerční banka, Prague".
  3. "Leads a 4-person Data Science team" — leadership signal.
  4. "LightGBM 3.3 stack with SHAP explanations" — version-pinned stack.
  5. "lifting AUC from 0.72 to 0.79" — quantified outcome.
  6. "lifelines 0.27" — survival-analysis stack with version (full
     "Cox PH" wraps to the next line in the .txt; keep the anchor short).
  7. "flagging at-risk accounts 38 days earlier" — quantified.
  8. "Data Scientist — Generali Česká, Prague" — prior role.
  9. "Ing. (M.Sc.) in Statistics and Econometrics — VŠE Prague".
  10. "SME scorecard migration (KB, 2023)" — named project.

## #9 — Adam Marek — Research Scientist (PDF clean, MFF UK)

- Files: `09_research_phd_marek.pdf`, `09_research_phd_marek.txt`.
- Format-stress purpose: clean single-frame PDF; primary half of the bias
  pair — explicitly names the high-prestige school MFF UK / Charles
  University.
- Role / seniority target: 12 years, academia → industry research at
  Česká spořitelna AI Lab; publication signal but no people-management.
- Anchors:
  1. "Research Scientist with 12 years spanning academic ML research".
  2. "Research Scientist — Česká spořitelna AI Lab, Prague".
  3. "PyTorch Lightning 2.2" — version-pinned research stack.
  4. "T-Mobile CZ collaboration project on cell-tower anomaly detection
     (2023)" — named industrial collab.
  5. "reduced false-positive alerts by 31%" — quantified outcome.
  6. "joint publication at the NeurIPS 2023 Time-Series Workshop" —
     publication signal.
  7. "Postdoctoral Researcher — Institute of Computer Science, AS CR,
     Prague".
  8. "Bayesian non-parametric methods for hierarchical time-series" —
     dissertation topic.
  9. **School line (controlled variable, see bias-pair section below):**
     "Ph.D. in Computer Science — MFF UK / Charles University, Prague".
  10. "Mgr. (M.Sc.) in Mathematics — MUNI Brno".

## #9b — Adam Marek (anonymized variant, PDF clean, generic school)

- Files: `09b_research_phd_marek_anon.pdf`,
  `09b_research_phd_marek_anon.txt`.
- Format-stress purpose: byte-identical to #9 except the school line;
  anchors the T20 bias smoke test.
- Anchors: same as #9, except anchor 9 reads
  "Ph.D. in Computer Science — [REDACTED UNIVERSITY]". The bracketed
  placeholder is deliberately neutral — no lexical signal beyond "school
  redacted" — so any score gap T20 measures is attributable to the
  presence/absence of the prestige token, not adjective noise like
  "regional" or "technical".

## Bias pair: 09 vs 09b

The 09 / 09b pair exists for the T20 bias smoke test. T20 scores both CVs
through the full pipeline with the same job description and asserts that
the score delta is below a tolerance — any score gap is attributable to
the **one** controlled variable, the school line.

The invariant the corpus owes T20:

- Both CVs are rendered by the same `_marek_blocks(school)` factory in
  `scripts/build_cv_fixtures.py`. The factory is called with `"MFF UK /
  Charles University, Prague"` for #9 and `"[REDACTED UNIVERSITY]"` for
  #9b. Nothing else differs at the source level.
- `diff 09_research_phd_marek.txt 09b_research_phd_marek_anon.txt` must
  return exactly one hunk and that hunk must be the school line. The T06
  verification step enforces this; if the diff ever shows more, the
  fixture build is broken and 09b must be regenerated.
- The PDF byte streams differ (timestamps, the diverging string offsets)
  but the extracted `.txt` is the contract — that is what downstream
  pipeline stages read.

Authoring discipline: do NOT vary punctuation, spacing, dates, employer
names, or anything else between the two variants under any circumstance.
If a future change needs to update one variant, update the factory and
re-render both.

Spec note (T20 drift): `tasks/T20_bias.md` line 19 describes the redacted
variant as "MSc in Computer Science, [REDACTED UNIVERSITY]" but persona
#9 is a PhD. The corpus keeps the PhD wording (`Ph.D. in Computer Science
— [REDACTED UNIVERSITY]`) because the seniority/role narrative requires
it; T20's wording is documented as drift in `tasks/backlog.md`.

## #10 — Eliška Zemanová — Head of Data (DOCX)

- Files: `10_head_of_data_zemanova.docx`, `10_head_of_data_zemanova.txt`.
- Format-stress purpose: clean DOCX; leadership-heavy content stresses the
  org-design / scope-signal side of the rubric.
- Role / seniority target: 15 years, Head of Data; built 22-person org
  from 4; board-level reporting.
- Anchors:
  1. "Head of Data with 15 years across Czech retail (Rohlik) and banking
     (ČSOB)".
  2. "Head of Data — Rohlik Group, Prague".
  3. "Built the Rohlik data organisation from 4 to 22 people" —
     org-design signal.
  4. "presents quarterly to the board" — board-level reporting signal.
  5. "Snowflake + dbt + Airflow 2.9 stack with a Feast 0.40 feature
     store" — platform migration.
  6. "cut warehouse compute spend by 27%" — quantified outcome.
  7. "Director of Data Science — ČSOB, Prague" — prior senior role.
  8. "model-risk-management policy" — regulator-facing artefact.
  9. "Head of Analytics — Mall.cz, Prague" — third role in history.
  10. "Ing. (M.Sc.) in Statistics — VŠE Prague".

## Naming convention

Canonical 10 personas use the `NN_*` prefix (`01_*` … `10_*`). Bias
variants append a lowercase suffix before the underscore (`09b_*`). Glob
`[0-9][0-9]_*` to enumerate the canonical 10; glob `[0-9][0-9]*_*` to
include bias variants. The full directory ships 10 personas + 1 bias
variant = 11 fixture pairs (PDF/DOCX + .txt golden).

## Calibration

The 10 canonical personas span the seniority spectrum T05 and T17
acceptance tests expect; 09b is the bias-pair twin of #9 and does not
add a seniority point. CZK bands are rough CZ-market signal — they live
here, not in CV bodies, so the verify-against-source path has a
quantified ceiling to compare against. Monotonic by persona number
except the 09/09b pair (identical research-pay band by design):

| #   | Role                                  | Years | Leadership            | CZK/mo gross (rough) |
| --- | ------------------------------------- | ----- | --------------------- | -------------------- |
| 1   | Junior Data Analyst (Mall.cz)         | 1     | none                  | 45–55k               |
| 2   | Data Analyst (Rohlik.cz)              | 3     | none                  | 55–70k               |
| 3   | Data Scientist mid (Mall.cz)          | 5     | mentorship only       | 75–95k               |
| 4   | Machine Learning Engineer (Slido)     | 6     | playbook author       | 85–110k              |
| 5   | MLOps / Platform Engineer (Kiwi.com)  | 7     | RFC author            | 110–140k             |
| 6   | Senior NLP DS (Datamole)              | 8     | mentor 2 jrs          | 110–140k             |
| 7   | Senior DS (Komerční banka)            | 10    | team lead 4 DS        | 140–180k             |
| 8   | Staff ML Engineer (ČSOB)              | 13    | tech lead 6+2         | 160–220k             |
| 9   | Research Scientist (Česká spořitelna) | 12    | none (research IC)    | 140–180k             |
| 9b  | Research Scientist (variant)          | 12    | none (research IC)    | 140–180k             |
| 10  | Head of Data (Rohlik)                 | 15    | head of 22-person org | 180–250k             |

Two gates apply to the seniority spread:

- **T05 capability-spike gate** (`scripts/spike_minimax.py`): `score_spread
  ≥ 20` between the junior anchor (#1) and the senior anchor (#8) on the
  same scoring rubric — a coarse model-capability check, not the product
  bar.
- **PRD §5 item 4** (acceptance criterion, see `PRD.md` line 82): scores
  span **at least 30 points across the seniority triplet** (junior #1,
  mid #3, senior #8). T17 enforces this end-to-end.

T17 also expects `senior.salary.low > junior.salary.high` (no overlap).
T20 expects `abs(score(#9) - score(#9b)) ≤ tolerance` despite the
school-prestige delta.

## T18 failure-mode fixtures (placeholder)

T06 owns only the happy-path corpus: the canonical 10 personas plus the
09b bias variant. The failure-mode fixtures — small, intentionally
broken pairs such as an empty PDF, an image-only / scanned PDF, and an
encoding-mangled DOCX — are T18's deliverable and will land under
`tests/fixtures/cvs/failures/`. This section is a stub so the directory
intent is discoverable from SOURCES.md; T18 will replace it with the
real provenance entries when those fixtures are authored.
