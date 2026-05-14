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

# Post-ship hardening (bilingual-senior regression on Profile.pdf)

T24 (section vocab) ─┐
T25 (score partial) ─┤
T26 (verify fallback)┤
T27 (role normalize) ┴── T29 (CZ senior fixture) ── T30 (§5.4 CI gate, closes T17)
T28 (redact + tenure)
T31 (multimodal spike) — parallel, no merge
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
| T24 | Multilingual section vocabulary (R1) | — | software-engineer | 45 min |
| T25 | Score: experience-mandatory + re-normalized total (R2) | — | ai-ml-engineer | 45 min |
| T26 | verify_quote: section-fallback + telemetry (R3) | — | software-engineer | 30 min |
| T27 | Role normalization + salary integration (R4+R5) | — | ai-ml-engineer | 75 min |
| T28 | Redact: tagline-headline name fix + deterministic tenure (R6+R7) | — | software-engineer | 45 min |
| T29 | Acceptance eval: bilingual CZ senior fixture #11 | T24, T25, T26, T27 | ai-ml-engineer | 2h |
| T30 | §5.4 differentiation eval wired into CI (closes T17) | T29 | ai-ml-engineer | 60 min |
| T31 | SPIKE: multimodal vision ingest as L1+L2 alternative | — | ai-ml-engineer | 1–2 sessions |

**Total estimate**: ~14h for T00–T23; +~6h for T24–T30 hardening; T31 is a parallel spike. T24–T28 are independent and parallelizable; T29 fans them in; T30 closes T17.
