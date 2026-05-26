# todo

Project-level work tracker. Each item is a separate task file in this folder. Tick when verified.

## Foundation (sequential)
- [x] **T00** — Project bootstrap (`tasks/T00_bootstrap.md`)
- [x] **T01** — Schemas + StageFailure (`tasks/T01_schemas.md`)
- [x] **T02** — Cross-cutting utils (`tasks/T02_utils.md`)
- [x] **T03** — CI + pre-commit + warm-keeper (`tasks/T03_ci_precommit.md`) — *parallel with T01/T02 after T00*

## Capability gate
- [x] **T04** — CV corpus part 1: junior + senior (`tasks/T04_cvs_part1.md`)
- [x] **T05** — MiniMax capability spike (`tasks/T05_spike.md`) — *gates T07–T13*

## Stage workers (parallel after T05)
- [x] **T07** — L1 ingestion (`tasks/T07_ingest.md`)
- [x] **T08** — L2 PII redaction (`tasks/T08_redact.md`)
- [x] **T09** — L3 profile extraction (`tasks/T09_extract.md`)
- [x] **T10** — L4a scorer (`tasks/T10_score.md`)
- [x] **T11** — L4b salary (CZ-localized) (`tasks/T11_salary.md`)
- [x] **T12** — L4c confidence judge (`tasks/T12_confidence.md`)
- [x] **T13** — L5 growth plan (`tasks/T13_growth.md`)

## Corpus + integration
- [x] **T06** — CV corpus part 2: remaining 8 (`tasks/T06_cvs_part2.md`) — *parallel with stage workers*
- [x] **T14** — Report renderer (`tasks/T14_render.md`) — *parallel after T01*
- [x] **T15** — Pipeline orchestrator (`tasks/T15_pipeline.md`)

## UI + tests
- [x] **T16** — Gradio UI (`tasks/T16_ui.md`)
- [x] **T17** — Acceptance tests (`tasks/T17_acceptance.md`) — *closed via T30 phase 1 (PR #10, dea3dcf)*
- [x] **T18** — Failure tests (`tasks/T18_failures.md`) — *PR #12, 4641765*
- [x] **T19** — Confidence-judge tests (`tasks/T19_judge_tests.md`)
- [x] **T20** — Bias smoke test (`tasks/T20_bias.md`) — *PR #14, 56310bc*
- [x] **T21** — `scripts/eval_corpus.py` (`tasks/T21_eval_corpus.md`) — *PR #15, a76561d*
- [x] **QA01** — QA audit (`tasks/qa_audit.md`) — *PR #13, 7fec4e5*

## Ship
- [x] **T22** — HF Space deploy (`tasks/T22_deploy.md`)
- [ ] **T23** — README finalize (`tasks/T23_readme.md`) — *README replaced; reproducibility and deploy recovery documented; live corpus/bias numbers still pending*

## Post-ship hardening (Profile.pdf bilingual-senior regression — see plan; revised after multi-agent review 2026-05-14)
- [x] **T24** — Multilingual section vocabulary, R1 (`tasks/T24_section_vocab.md`) — *PR #16, 1897bd8*
- [x] **T25** — Score: experience-mandatory, drop-as-zero, R2 (`tasks/T25_score_partial.md`) — *PR #18, e1df8f0*
- [x] **T26** — verify_quote: section-fallback + per-stage cap, R3 (`tasks/T26_verify_fallback.md`) — *PR #9, 212aff5*
- [x] **T27** — Role normalization (polarity-flipped + LLM fallback) + salary 3-shot, R4+R5 (`tasks/T27_role_normalize.md`) — *PR #17, 3cc0092*
- [x] **T28** — Redact: tagline-headline name fix + deterministic tenure, R6+R7 (`tasks/T28_redact_tagline_tenure.md`) — *PR #11, 3602324*
- [x] **T29** — Acceptance eval: 3 CZ fixtures (#11 bilingual, #12 academic, #13 corporate) (`tasks/T29_cz_senior_fixture.md`) — *PR #35 `openrouter-live` passed on run 25932192588*
- [x] **T30 phase 1** — Wire §5.4 differentiation eval into CI (closes T17) (`tasks/T30_acceptance_ci.md`) — *PR #10, dea3dcf*
- [x] **T30 phase 2** — CZ-triplet extension — *CZ cross-fixture invariants implemented in `test_acceptance_cz.py`; PR #35 `openrouter-live` passed*
- [x] ~~**T31** — SPIKE: multimodal vision ingest~~ — *superseded by T32–T35 Token Plan VLM chain; no longer an active pickup* (`tasks/T31_multimodal_spike.md`)

## MiniMax Token Plan LLM ingest
- [x] **T32** — Synthetic Token Plan VLM spike passed (`tasks/minimax_token_plan_vlm_report.md`) — *MiniMax `API-vlm`, 100% synthetic anchor survival, usable*
- [x] **T33** — Async ingest refactor (`tasks/T33_async_extract_text.md`)
- [x] **T34** — PDF VLM + DOCX text-LLM ingest implementation (`tasks/T34_vision_ingest_tier.md`)
- [ ] **T35** — Regression, live gating, and docs (`tasks/T35_corpus_regression_and_gating.md`) — *opt-in synthetic MiniMax API-vlm smoke + spend docs added; live run still pending*

## Post-merge follow-ups (T30 phase 1 self-heal residue)
- [x] **T36** — Senior fixture education-anchor verify miss (`tasks/T36_senior_edu_anchor.md`) — *strict EN score-spread gate restored; PR #35 `openrouter-live` passed*
- [x] **T37** — Cassette/mock DDG for live tests (`tasks/T37_ddg_cassette.md`) — *DDG replay fixture added; `_optional_growth` and salary flaky rerun removed*
- [x] **T38** — Low-evidence profile gate (`tasks/T38_low_evidence_gate.md`) — *PR #22; non-CV uploads now fail closed before downstream salary/score/growth*
- [ ] **T39** — Growth backward-bias + salary role-mismatch (Profile.pdf rerun) (`tasks/T39_growth_backward_bias.md`) — *verifier + role recovery fixes fast-verified; final private Profile.pdf rerun pending explicit approval*
- [ ] **T40** — CV-quality signals into confidence judge (`tasks/T40_confidence_cv_signals.md`) — *live cap path observed; final post-T39 private Profile.pdf rerun pending explicit approval*
- [x] **T42** — Pipeline wallclock wins (parallel DDG, L4c ∥ L5, OpenRouter Flash defaults) (`tasks/T42_pipeline_wallclock_wins.md`) — *implemented + fast/live/UI-smoke verified; OpenRouter vision path now covered by live CI*
- [ ] **T43** — Report readability: visual breaks, Plan typography, Score component grid (`tasks/T43_report_readability.md`) — *renderer/CSS + render tests implemented; synthetic light/dark desktop+mobile browser smoke passed; Profile.pdf/PR screenshot attachment pending*
- [x] **T44** — Skills/soft-signal evidence salvage (`tasks/T44_skills_soft_salvage.md`) — *keeps 6-word quote floor; rescues verifier-passing evidence from longer CV lines*
- [x] **T45** — Vision parallelization + per-stage max_tokens caps (`tasks/T45_vision_parallel_and_token_caps.md`) — *implemented on branch `dev/parallelize-vision-cap-max-tokens`; fast suite green*
- [x] **T46** — Salary stage: country-agnostic, live-search-first (`tasks/T46_salary_multi_market.md`) — *implemented on branch `t46-salary-multi-market`; fast salary/country coverage and PR #35 live CI green*
- [x] **T47** — Education scoring rubric: degree-band calibration (`tasks/T47_education_calibration.md`) — *PhD and bias live regressions passed in PR #35 `openrouter-live`*
- [x] **T48** — Confidence source rubric + OpenRouter route-table refactor (`tasks/T48_confidence_routing_refactor.md`) — *focused checks pass; full fast blocked by unresolved DOCX LFS pointers*
- [x] **T49** — Architecture hardening from code-review audit (`tasks/T49_architecture_hardening.md`) — *salary geography/year freshness, PDF/provider budgets, privacy copy, timeouts, latency semantics, LFS hygiene; fast suite green*

## Provider plumbing
- [x] **T41** — Wire OpenRouter; drop direct Anthropic provider (`tasks/T41_openrouter_provider.md`) — *PR #25, required `openrouter-live` CI pass*
- [x] **T45** — Gemini extraction routing + prompt stability (`tasks/T45_gemini_extract_stabilization.md`) — *LLM-first extraction-only provider routing plus prompt stability fixes; private PDF rerun pending explicit approval*
