# T31 — SPIKE: multimodal vision ingest as L1+L2 alternative

Status: deferred-post-submission
Owner: ai-ml-engineer
Depends on: —
Unblocks: —
Estimate: ~1–2 sessions (spike, no production code)

> **Deferred** (2026-05-14): submission deadline is today; this spike's outcome cannot influence T24/T28 in time. Pick up post-submission as round-2 architectural prep. Does not block T24–T30 hardening work.

## Goal

The bilingual-senior regression was caused by deterministic L1 (`ingest._extract_pdf`, `_annotate_sections`) and L2 (`redact._redact_header_name`) failing on inputs they were never tested on:
- F1 — multi-column PDFs survive pypdf's column-bleed and never reach the cleaner pdfplumber pass
- S1 — `SECTION_NAMES` is English-only; CZ headers (`Pracovní zkušenosti`, `Vzdělání`, …) bypass annotation entirely
- F3 — `_redact_header_name` regex bails on tagline-shaped first lines containing commas
- F4 — the 6-word literal substring floor in `verify_quote` drops most CZ short bullets

T24 / T26 / T28 patch each of these symptomatically. **A single multimodal vision pass over the rendered PDF could collapse all four classes into one stage.** The candidate model would consume the PDF/DOCX as an image and emit annotated structured text directly (sections labeled, multi-column resolved, language-agnostic, semantic PII candidates flagged).

This is a **spike**, not a migration. Output is a `tasks/T31_dev-report.md` with cost/latency/fidelity numbers and a binary recommendation: **do nothing / migrate L1 only / migrate L1+L2**. No production code lands from this task.

## Hypothesis to test

A multimodal vision pass would:
1. Side-step F1 entirely (vision sees the layout, not the text-extractor's serialization).
2. Side-step S1 (model identifies sections by visual structure, not vocabulary lookup).
3. Side-step F4 indirectly (cleaner extracted text → more bullets survive the literal floor).
4. Enable holistic semantic PII redaction for F3, replacing regex with a model that understands "this header line is a personal name, this one is a tagline."

Cost: a single vision call replaces L1+L2's deterministic stages. Risk: vendor lock-in to a specific VL model, higher per-CV cost, slower latency, less explainable redaction (no audit log unless the model emits one), and PRD §4.7 auditability becomes prompt-defined rather than code-defined.

## Deliverables

- [ ] **Precondition gate (do this first, ~10 min):** verify MiniMax exposes a vision modality on the OpenAI-compatible endpoint via a single API smoke call. If it does not, the spike concludes "do nothing" without writing the prototype script — provider singleness (CLAUDE.md / `gander.llm`) closes the option, and the rest of the deliverables are skipped. Document the API check result + endpoint version in `tasks/T31_dev-report.md` regardless of outcome.
- [ ] Spike branch (`spike/multimodal-ingest`) — not merged.
- [ ] Vendor scan: which VL models can consume PDF-as-image and return structured text?
  - **MiniMax**: does the OpenAI-compatible endpoint (`abab*`, `MiniMax-M*`) expose a `vision` modality? If not, this option is closed by the `gander.llm` provider-singleness constraint (CLAUDE.md).
  - **Anthropic Claude** (vision): allowed only as the existing fallback per CLAUDE.md.
  - Other providers: explicitly out of scope unless MiniMax cannot deliver — adds a second provider, breaks `gander.llm` singleness.
- [ ] Prototype script `scripts/spike_multimodal_ingest.py`:
  - Iterate over the 10-CV corpus + Profile.pdf (+ fixture #11 once T29 lands).
  - For each: render PDF page-by-page → image → call VL model with a prompt asking for `{annotated_markdown_text, detected_sections: [...], pii_candidates: [{kind, text, line}...]}`.
  - Log USD cost (token counts × current pricing), wall-clock latency, raw response.
- [ ] Ground-truth comparison:
  - For each fixture, compare against the current pipeline's `RedactedCV.text` and `Profile.detected_*` fields.
  - Score: how many CZ section headers correctly identified vs T24's regex; how many PII spans correctly identified vs L2 regex; how many bullets survive on Profile.pdf-style multi-column layouts.
- [ ] Decision matrix in the spike report:
  | Criterion | L1+L2 today (post-T24/26/28) | Vision-L1 only | Vision-L1+L2 |
  |---|---|---|---|
  | Section recall on bilingual CV | … | … | … |
  | PII recall on tagline CVs | … | … | … |
  | Multi-column extraction fidelity | … | … | … |
  | USD per CV | … | … | … |
  | p50/p95 latency seconds | … | … | … |
  | Auditable Redaction log per §4.7? | yes (regex spans) | partial (vision emits hints, regex still anchors) | only if model emits structured spans |
  | Provider singleness preserved? | yes | depends on MiniMax | depends |
- [ ] `tasks/T31_dev-report.md` with the matrix + a recommendation:
  - **Do nothing** — T24+T26+T28 are sufficient; spike concludes vision adds cost without proportional fidelity gain.
  - **Migrate L1 only** — vision replaces text extraction + section annotation; L2 stays regex-based to keep the auditable Redaction log.
  - **Migrate L1+L2** — vision replaces both; L2 audit log gets emitted by the model as structured output (spec the response schema in the report).

## Verification

```bash
uv run python scripts/spike_multimodal_ingest.py --corpus tests/fixtures/cvs/ --report tasks/T31_dev-report.md
```

Spike is "verified" when the report contains all matrix cells with concrete numbers (not "TBD") and a single bolded recommendation line.

## Decision criteria (must be answered in the report)

1. **Fidelity** vs ground-truth section/header recovery on the 10-CV corpus + Profile.pdf + fixture #11.
2. **Cost-per-CV delta** vs current pipeline (current ~$0.02–0.05/run per T17).
3. **Latency delta** (PRD §7 says ~60s end-to-end; vision adds page-rendering + image-input tokens).
4. Whether semantic redaction can produce the auditable `Redaction` log §4.7/§4.8 demand, or whether L2 stays regex-based even if L1 goes multimodal.
5. Whether MiniMax exposes a vision endpoint at the right cost/quality, or whether this implies a second provider (rejected by `gander.llm` provider-singleness).

## Out of scope

- **Migrating production code.** The spike outputs a recommendation only.
- Switching providers away from MiniMax even if the spike says vision is better elsewhere — that's a separate decision requiring product/owner sign-off.
- OCR for scanned PDFs — PRD §6 explicitly excludes scanned inputs.

## Reference

- Plan: `/home/mf/.claude/plans/this-is-a-result-peaceful-blanket.md` § "T31 — SPIKE: Multimodal vision ingest"
- CLAUDE.md — provider singleness via `gander.llm`
- PRD §4.7, §4.8, §6, §7

## Outcome

(fill in when done — recommendation + matrix link + decision rationale; if recommendation is "migrate", spawn follow-up T<NN> tasks)
