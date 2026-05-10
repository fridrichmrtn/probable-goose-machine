# Task index

This folder is the source of truth for build execution. Every task is a pickup-able unit with explicit dependencies and a verification criterion. Architecture lives in [PLAN.md](PLAN.md); lessons learned live in [lessons.md](lessons.md).

## How to pick up a task

1. Open [todo.md](todo.md) for a quick status view across all tasks.
2. Open the task file (`T<NN>_*.md`); confirm `Depends on:` are all `done`.
3. Set `Status: wip` and your name/agent in `Owner:` before starting.
4. Implement; satisfy the `Verification` block.
5. Set `Status: done` when verified; tick the box in `todo.md`; append a one-line note to the task's "Outcome" section.
6. If you discover the contract is wrong, do **not** silently change it — open an issue in `tasks/lessons.md` so downstream tasks can adapt.

## DAG (compact)

```
T00 ──┬── T01 ── T02 ──┬── T05 (spike, gates stage tasks) ──┬── T07 (ingest)
      │                │                                    ├── T08 (redact)
      ├── T03 (CI)     ├── T14 (report renderer)            ├── T09 (extract)
      ├── T04 (CVs 1+8)│                                    ├── T10 (score)
      │                │                                    ├── T11 (salary)
      │                │                                    ├── T12 (confidence)
      │                │                                    └── T13 (growth)
      └── T06 (other 8 CVs)                                                │
                                                                          ▼
                                                                       T15 (pipeline)
                                                                          │
                                                  ┌───────────────────────┼────────────┐
                                                  ▼                       ▼            ▼
                                              T16 (UI)              T17 (accept)   T18 (fail)
                                                  │                       │            │
                                                  ▼                       ▼            ▼
                                              T22 (deploy)            T19 (judge)  T20 (bias)
                                                  │                                    │
                                                  └────────────────┬───────────────────┤
                                                                   ▼                   ▼
                                                                T21 (eval_corpus)  T23 (README)
```

## Task list

| ID | Title | Depends on | Owner suggestion | Estimate |
|---|---|---|---|---|
| T00 | Project bootstrap | — | software-engineer | 30 min |
| T01 | Schemas + StageFailure | T00 | software-engineer | 30 min |
| T02 | Cross-cutting utils (verify, obs, llm, errors) | T01 | software-engineer | 60 min |
| T03 | CI + pre-commit + warm-keeper workflows | T00 | software-engineer | 30 min |
| T04 | CV corpus part 1 — junior + senior fixtures | T00 | software-engineer | 30 min |
| T05 | MiniMax capability spike | T02, T04 | ai-ml-engineer | 30 min |
| T06 | CV corpus part 2 — remaining 8 CVs + SOURCES.md | T04 | software-engineer | 2h |
| T07 | L1 ingestion (PDF/DOCX → text) | T02, T05 | software-engineer | 30 min |
| T08 | L2 PII redaction (regex-only default) | T02, T05 | software-engineer | 30 min |
| T09 | L3 profile extraction | T02, T05 | ai-ml-engineer | 45 min |
| T10 | L4a seniority scorer | T02, T05 | ai-ml-engineer | 45 min |
| T11 | L4b salary search + estimator (CZ-localized) | T02, T05 | ai-ml-engineer | 75 min |
| T12 | L4c confidence judge (recompute-then-compare) | T02, T05 | ai-ml-engineer | 45 min |
| T13 | L5 growth plan | T02, T05 | ai-ml-engineer | 60 min |
| T14 | L6 report renderer (`report.py`) | T01 | ux-engineer | 45 min |
| T15 | L6 pipeline orchestrator (`pipeline.py`) | T07–T13 | software-engineer | 45 min |
| T16 | L7 Gradio UI + stage tracker | T14 (T15 for live) | ux-engineer | 2h |
| T17 | L8 acceptance tests (Jaccard, calibration, anchor uniqueness, cost) | T15, T06 | ai-ml-engineer | 90 min |
| T18 | L8 failure-path + partial-failure-streaming tests | T15 | software-engineer | 45 min |
| T19 | L8 confidence-judge tests (structural + recompute golden) | T12 | ai-ml-engineer | 30 min |
| T20 | L8 bias smoke test (CZ school prestige) | T15, T06 | ai-ml-engineer | 30 min |
| T21 | scripts/eval_corpus.py — 10-CV live runner | T15, T06 | software-engineer | 45 min |
| T22 | L9 HF Space + secrets wiring | T16 | software-engineer | 45 min |
| T23 | L9 README incl. Decisions section | T17–T22 | (owner) | 90 min |

**Total estimate**: ~14h across all tasks. Parallelizable phases (T07–T13, T17–T20) can compress wall time substantially.
