# T05 — MiniMax capability spike

Status: todo
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

(fill in when done — actual numbers from each gate; whether swap was needed)
