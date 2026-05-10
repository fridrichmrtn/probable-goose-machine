# todo

Project-level work tracker. Each item is a separate task file in this folder. Tick when verified.

## Foundation (sequential)
- [x] **T00** — Project bootstrap (`tasks/T00_bootstrap.md`)
- [x] **T01** — Schemas + StageFailure (`tasks/T01_schemas.md`)
- [x] **T02** — Cross-cutting utils (`tasks/T02_utils.md`)
- [x] **T03** — CI + pre-commit + warm-keeper (`tasks/T03_ci_precommit.md`) — *parallel with T01/T02 after T00*

## Capability gate
- [ ] **T04** — CV corpus part 1: junior + senior (`tasks/T04_cvs_part1.md`)
- [ ] **T05** — MiniMax capability spike (`tasks/T05_spike.md`) — *gates T07–T13*

## Stage workers (parallel after T05)
- [ ] **T07** — L1 ingestion (`tasks/T07_ingest.md`)
- [ ] **T08** — L2 PII redaction (`tasks/T08_redact.md`)
- [ ] **T09** — L3 profile extraction (`tasks/T09_extract.md`)
- [ ] **T10** — L4a scorer (`tasks/T10_score.md`)
- [ ] **T11** — L4b salary (CZ-localized) (`tasks/T11_salary.md`)
- [ ] **T12** — L4c confidence judge (`tasks/T12_confidence.md`)
- [ ] **T13** — L5 growth plan (`tasks/T13_growth.md`)

## Corpus + integration
- [ ] **T06** — CV corpus part 2: remaining 8 (`tasks/T06_cvs_part2.md`) — *parallel with stage workers*
- [ ] **T14** — Report renderer (`tasks/T14_render.md`) — *parallel after T01*
- [ ] **T15** — Pipeline orchestrator (`tasks/T15_pipeline.md`)

## UI + tests
- [ ] **T16** — Gradio UI (`tasks/T16_ui.md`)
- [ ] **T17** — Acceptance tests (`tasks/T17_acceptance.md`)
- [ ] **T18** — Failure tests (`tasks/T18_failures.md`)
- [ ] **T19** — Confidence-judge tests (`tasks/T19_judge_tests.md`)
- [ ] **T20** — Bias smoke test (`tasks/T20_bias.md`)
- [ ] **T21** — `scripts/eval_corpus.py` (`tasks/T21_eval_corpus.md`)

## Ship
- [ ] **T22** — HF Space deploy (`tasks/T22_deploy.md`)
- [ ] **T23** — README finalize (`tasks/T23_readme.md`)
