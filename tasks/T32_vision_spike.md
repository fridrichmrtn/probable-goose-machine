# T32 — Vision capability spike (MiniMax, with Anthropic mini-spike fallback)

Status: wip
Owner: ai-ml-engineer
Depends on: —
Unblocks: T34 (vision tier implementation)
Estimate: ~1 session

## Goal

Prove the vision-LLM transcription tier is viable before sinking implementation effort into it. Mirror the T05 capability-spike pattern (`scripts/spike_minimax.py`). Output a decision: **adopt MiniMax vision** / **fall back to Claude Sonnet 4.6** / **halt vision tier entirely**.

The decision tree:
1. **MiniMax spike first.** If all 7 hard gates pass → adopt MiniMax, seed `GANDER_VISION_MODEL` default + cost entry. T34 proceeds.
2. **Anthropic mini-spike** (only if MiniMax fails any gate). If all 7 pass → promote `anthropic` to a hard dep, flip provider default. T34 proceeds against Anthropic.
3. **Both fail** → halt; vision tier not viable. Propose a different fix in `tasks/lessons.md` (column-aware text extraction, structured-PDF library, etc.).

Per the user's no-unprompted-deps rule, the Anthropic promotion is a **named decision** — surfaced before the dep is added.

## Deliverables

- [ ] `pyproject.toml`: add `pymupdf` (hard dep). `uv sync`.
- [ ] `tests/fixtures/vision_anchors.json`: 10 verbatim anchor phrases per spike document, hand-curated. Mix of EN + CZ, mix of sidebar / body / headers / dates / typos-or-decorations. Documents: `Profile.pdf` (all 3 pages, dense sidebar+body, CZ/EN bilingual), one EN single-column fixture from `tests/fixtures/cvs/`, one CZ single-column fixture from same.
- [ ] `scripts/spike_minimax_vision.py`:
  - Render each spike PDF page → PNG via `pymupdf` at DPI 200.
  - Call MiniMax via OpenAI-compatible `chat.completions` with `messages[].content` shape carrying base64 PNG. Try `{type: "image_url", image_url: {url: "data:image/png;base64,..."}}` first; fall back to `{type: "input_image", ...}` if needed. Lock the working shape in a module-level constant the spike prints (T34 will reuse it).
  - System prompt = `prompts/ingest_vision.md` (created in T34). For the spike, inline a v0 prompt body covering the 10 rules from the plan's §Transcription prompt.
  - Temperature = 0, `max_tokens = 4096`.
  - Run each PDF 3× and assert byte-identical transcripts (whitespace-normalised). Determinism gate.
  - Compute the 7 gates (below) per PDF. Print a results table mirroring `scripts/spike_minimax.py`'s output. Exit 0 iff all gates pass on all 3 PDFs; exit 1 with `FAILED GATE: <which> on <pdf>`.
- [ ] `tasks/T32_dev-report.md` with the matrix per document, USD cost, p50/p95 latency, drift Jaccard, anchor-survival rate, column-order verdict, determinism verdict, and a single bolded recommendation line.
- [ ] If MiniMax fails: a second invocation in the same script (or sibling `scripts/spike_anthropic_vision.py`) running the Anthropic mini-spike against the same 3 PDFs + 7 gates. Surface in the dev report. Only if Anthropic passes: open a follow-up commit that adds `anthropic` as a hard dep with the user's explicit OK.

## Hard gates (all 3 PDFs must pass all 7)

1. **Anchor survival ≥9/10 per document** via `gander.verify.verify_quote` against the transcript. Mix EN/CZ to catch translation drift.
2. **Column-order detector**: sidebar tokens (`Kontakt`, `Skills`, `Languages`, `Certifications`, `Honors-Awards`) appear before body tokens (`Pracovní zkušenosti`, `Experience`) in the multi-column doc. Auto-reject if flipped.
3. **Translation-drift detector**: every CZ ground-truth anchor appears literally — not as its English translation.
4. **Drift Jaccard floor**: length-≥6 word n-gram Jaccard between vision and text-tier transcripts ≥ 0.6 on the single-column fixtures (where text-tier is known-correct).
5. **Cost ceiling**: per-page USD cost ≤ ~$0.05 (rough budget — recheck against MiniMax pricing console).
6. **Latency**: p95 per-page ≤ 15s.
7. **Determinism**: 3 runs at T=0 → byte-identical (or whitespace-normalised identical) per page.

## Verification

```bash
uv run python scripts/spike_minimax_vision.py --report tasks/T32_dev-report.md
echo $?    # 0 == all gates passed
```

## Out of scope

- Production `complete_vision_text` API surface (lives in T34).
- Anthropic dep promotion as a code change — surfaced as a decision, not executed inside this task.

## Reference

- Plan: `/home/mf/.claude/plans/so-i-have-lowkey-snoopy-dream.md` § "Pre-flight: MiniMax vision capability spike"
- Pattern mirror: `scripts/spike_minimax.py`, `tasks/T05_spike.md`
- Profile.pdf: `/home/mf/Downloads/Profile.pdf` (user-local, gitignored)

## Outcome

(fill in when done — gates table + recommendation)
