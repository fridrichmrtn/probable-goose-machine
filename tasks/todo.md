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
- [ ] **T23** — README finalize (`tasks/T23_readme.md`)

## Post-ship hardening (Profile.pdf bilingual-senior regression — see plan; revised after multi-agent review 2026-05-14)
- [x] **T24** — Multilingual section vocabulary, R1 (`tasks/T24_section_vocab.md`) — *PR #16, 1897bd8*
- [x] **T25** — Score: experience-mandatory, drop-as-zero, R2 (`tasks/T25_score_partial.md`) — *PR #18, e1df8f0*
- [x] **T26** — verify_quote: section-fallback + per-stage cap, R3 (`tasks/T26_verify_fallback.md`) — *PR #9, 212aff5*
- [x] **T27** — Role normalization (polarity-flipped + LLM fallback) + salary 3-shot, R4+R5 (`tasks/T27_role_normalize.md`) — *PR #17, 3cc0092*
- [x] **T28** — Redact: tagline-headline name fix + deterministic tenure, R6+R7 (`tasks/T28_redact_tagline_tenure.md`) — *PR #11, 3602324*
- [ ] **T29** — Acceptance eval: 3 CZ fixtures (#11 bilingual, #12 academic, #13 corporate) (`tasks/T29_cz_senior_fixture.md`) — *deps T24, T25, T26, T27, T28*
- [x] **T30 phase 1** — Wire §5.4 differentiation eval into CI (closes T17) (`tasks/T30_acceptance_ci.md`) — *PR #10, dea3dcf*
- [ ] **T30 phase 2** — CZ-triplet extension — *deps T29*
- [ ] ~~**T31** — SPIKE: multimodal vision ingest~~ — *superseded by T32–T35 vision chain* (`tasks/T31_multimodal_spike.md`)

## MiniMax Token Plan LLM ingest
- [x] **T32** — Synthetic Token Plan VLM spike passed (`tasks/minimax_token_plan_vlm_report.md`) — *MiniMax `API-vlm`, 100% synthetic anchor survival, usable*
- [x] **T33** — Async ingest refactor (`tasks/T33_async_extract_text.md`)
- [x] **T34** — PDF VLM + DOCX text-LLM ingest implementation (`tasks/T34_vision_ingest_tier.md`)
- [ ] **T35** — Regression, live gating, and docs (`tasks/T35_corpus_regression_and_gating.md`)

## Post-merge follow-ups (T30 phase 1 self-heal residue)
- [ ] **T36** — Senior fixture education-anchor verify miss (`tasks/T36_senior_edu_anchor.md`) — *unblocks reverting the partial-Score branch in `test_score_spread_at_least_30`*
- [ ] **T37** — Cassette/mock DDG for live tests (`tasks/T37_ddg_cassette.md`) — *unblocks removing `_optional_growth` + `@flaky(reruns=2)`*
