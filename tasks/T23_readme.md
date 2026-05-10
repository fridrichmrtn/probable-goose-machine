# T23 — L9 README finalize (Decisions section is load-bearing)

Status: todo
Owner: (decided at write time — needs author voice)
Depends on: T17, T20, T21, T22
Unblocks: SUBMIT
Estimate: ~90 min

## Goal

The README is what the reviewer reads first. PRD §9 sets the bar: "This is a senior submission. The README 'Decisions' section should read accordingly — less hand-holding, more visible tradeoff thinking, deliberate cuts noted with brief rationale."

This is the load-bearing artifact. Don't paste the PRD back at them. Write in author voice.

## Deliverables

Replace the bootstrap stub at `README.md` with:

- [ ] **Frontmatter** preserved (HF Space metadata).
- [ ] **Above the fold**:
  - Public Space URL as the first thing visible.
  - One-line note: "First request may take ~20s if the Space is asleep — the warm-keeper cron usually prevents this."
  - Local-run one-liner: `uv sync && MINIMAX_API_KEY=... uv run python app.py`.
- [ ] **How the pipeline works**:
  - Reuse the DAG ASCII from `tasks/PLAN.md`.
  - 1-paragraph stage descriptions.
  - **Highlight three design choices** in dedicated sub-sections (these are the "judgment" signals reviewers look for):
    - "Confidence judged by a *different model* with a recompute-then-compare protocol" — link to `src/jobfit/confidence.py`.
    - "Every claim is a substring-verified anchor with section locality" — link to `src/jobfit/verify.py`.
    - "Per-stage cost + latency surfaced in the UI footer (and CI logs)" — link to `src/jobfit/obs.py`.
- [ ] **Decisions** (written in first person, ~600 words, NOT a paste of PRD):
  - **MiniMax + token plan**: why a non-frontier provider in an AI-first hiring case study. Honest framing — the L0.5 spike validated it (quote the actual numbers from T05's outcome). Less-obvious provider is what the §1.4 "creativity" priority rewards.
  - **DuckDuckGo over paid search**: zero-setup ethos extends from reviewer to build itself; tradeoff (DDG rate-limits) noted with the §4.6 fallback as the safety net.
  - **Gradio + HF Spaces**: AI-community surface; free; single-file deploy.
  - **Regex-only PII redaction**: chosen over LLM-based redaction to remove a failure mode and a model-cost surface; explicit on what's redacted and what's not.
  - **Cuts**: no OCR, no auth/persistence, no batch, no LLM-PII pass, no multi-language. Each with a one-line *why we cut*.
  - **What this cost**: per-run USD figures from T17 (`$0.0X local, $0.0Y CI`) and the corpus-run total from T21.
- [ ] **Bias acknowledgment** (author-voice expansion of PRD §4.7, NOT a paste):
  - What we structurally remove (the regex categories from T08).
  - What we cannot remove (employer prestige, language patterns, CZ school names not in the regex list).
  - Concrete number from T20: "score delta with vs. without MFF UK header on CV #09 was N points".
  - Explicit framing: outputs are *candidate hypotheses for the reviewer to validate*, not authoritative judgments.
- [ ] **Limitations**:
  - English-only.
  - No OCR (loud failure on scanned PDFs).
  - DDG availability dependency.
  - MiniMax not benchmarked against frontier on CV reasoning (or: documented swap to Claude per T05).
  - No fairness validation across protected groups.
- [ ] **Reviewer's quick-eval cheat sheet** (a 30-second skim):
  - 3 bullet-point claims about what makes this submission senior (verifier locality, confidence isolation, observability).
  - Linked code locations for each.

## Verification

- [ ] Read top-to-bottom; trim anything that doesn't serve judgment or reliability (per CLAUDE.md "demand elegance").
- [ ] Anyone unfamiliar with the project should understand what it does and how to run it within 60 seconds.
- [ ] Numbers (cost, latency, bias delta) are real — not placeholders.

## Reference

- tasks/PLAN.md — § "L9 — Deployment + README"
- PRD.md §9

## Outcome

(fill in when done — link to the rendered README on GitHub + HF Space)
