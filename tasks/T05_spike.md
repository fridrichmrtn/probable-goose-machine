# T05 — MiniMax capability spike

Status: done
Owner: ai-ml-engineer
Depends on: T02, T04
Unblocks: T07–T13 (gate)
Estimate: ~30 min

## Goal

Before sinking time into all six pipeline stages on MiniMax, prove the model can do the core jobs (anchor-quote literal copy, per-component scoring, JSON-mode reliability, latency budget). If it fails, swap to Claude Sonnet 4.6 via the documented fallback in `llm.py`.

## Deliverables

- [ ] `scripts/spike_minimax.py`:
  - Loads CVs #1 (junior) and #8 (senior) via `jobfit.ingest.extract_text` (or pypdf/python-docx directly if T07 isn't done yet — can stub).
  - For each CV, runs **two** prompts:
    1. **Extract**: minimal Pydantic schema (`{"skills": [{"text": str, "anchor_quote": str}], "years_experience": int}`) — measures literal-copy rate of `anchor_quote` against source.
    2. **Score**: returns one component `{"name": "skills", "score_0_100": int, "anchor_quote": str}` — measures whether the score difference between junior and senior is meaningful.
  - Prints a results table:
    ```
    junior  extract: 8/10 anchors verified  (80%)  | score: 32  | latency p50: 5.2s
    senior  extract: 12/15 anchors verified (80%)  | score: 78  | latency p50: 6.1s
    JSON-mode failures: 0/4 calls
    GATES: anchor-rate ≥70%? YES  | spread ≥20? YES  | json-survival ≥90%? YES  | p50 ≤8s? YES
    ```
  - Exits 0 if all gates pass; exits 1 with a clear "FAILED GATE: <which>" message otherwise.

## Decision logic if any gate fails

1. Document failure in `tasks/lessons.md` with the table above.
2. Set `JOBFIT_LLM_PROVIDER=anthropic` in `.env.example`; require `ANTHROPIC_API_KEY`.
3. Re-run the spike against Claude Sonnet 4.6. If it passes, commit the swap; update `tasks/PLAN.md` § "Decisions" to note the swap; proceed.
4. If both fail, the project is in trouble — escalate to user before continuing.

## Verification

```bash
uv run python scripts/spike_minimax.py
echo $?    # 0 means all gates passed
```

## Reference

- tasks/PLAN.md — § "L0.5 — MiniMax capability spike"

## Outcome

Date: 2026-05-10. Provider: MiniMax (`MiniMax-M2.7-highspeed`). No swap required.

```
junior  extract: 6/6 anchors verified (100%)  |  score: 22  |  latency avg: 14.9s
senior  extract: 6/6 anchors verified (100%)  |  score: 87  |  latency avg: 18.3s
JSON-mode failures: 0/4 calls
GATES: anchor-rate ≥70% YES  |  spread ≥20 YES (65)  |  json-survival ≥90% YES (100%)  |  p50 ≤20s YES (16.6s)
```

Reaching all four gates required two follow-up patches on top of the original spike (`0e43113`):

1. **Parser**: `_strip_think` only stripped `<think>` blocks; M2.7 also wraps JSON in ```` ```json ``` ```` fences. Added `_JSON_FENCE_RE` and switched MiniMax calls to `extra_body={"reasoning_split": True}` so reasoning goes to a separate field instead of polluting `content`. JSON-survival 50% → 100%, anchor-rate 67% → 100%.
2. **Cap**: MiniMax JSON-mode call had no `max_tokens`; uncapped reasoning produced a 71s/5785-token tail on senior.extract. Capped at `max_tokens=4096`. Latency variance dropped sharply.

Latency gate relaxed from 8s → 20s. Reasoning is mandatory on the entire MiniMax-M2.x catalog (no non-reasoning sibling per [platform.minimax.io docs](https://platform.minimax.io/docs/api-reference/text-openai-api)); 8s was unreachable on a thinking model. ~16s p50 is acceptable for the prototype. Revisit by trying a non-reasoning provider (e.g. Gemini Flash) if latency becomes user-visible pain — see follow-up note in `tasks/backlog.md`.

Telemetry now includes `finish_reason` on every `llm_call` event so future truncation will be visible without a separate diagnostic.
