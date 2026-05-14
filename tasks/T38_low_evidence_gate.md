# T38 — Low-evidence profile gate (non-CV uploads cascade gracefully)

Status: doing
Owner: software-engineer
Depends on: —
Unblocks: —
Estimate: ~45 min

## Goal

When a non-CV file (or a CV the extractor cannot read) is uploaded, the pipeline currently produces a fabricated salary number. Trace:

- `src/gander/ingest.py:100-157` validates format / corruption / `≥100` chars, not content.
- `src/gander/extract.py::extract_profile` accepts an empty `Profile` (per `prompts/extract.md:23-24`).
- `src/gander/salary.py:161-318` never checks profile sparsity and runs DDG + LLM estimator on whatever `detected_role` the LLM produced.
- `src/gander/confidence.py:68` judges only on web-source agreement, never sees the profile.

PRD §4.5 anchor verification is per-claim, not per-document. The fix is one document-level gate inside `extract_profile` that returns `StageFailure` when too little structural evidence survived anchor verification.

**Framing**: the gate is *not* "this is not a CV". We can't know that. We know we couldn't extract the data we expect. The cause may be a non-CV file, a scanned PDF that slipped past the length check, a CV in an unsupported language, or LLM output that didn't survive verification. The user-facing message must reflect that.

## Deliverables

### Composite-evidence gate

- [x] `src/gander/extract.py`:
  - Add `MIN_CV_SCORE = 3` and `_CV_EVIDENCE_WEIGHTS = {"experience": 3, "education": 2, "skills": 1, "soft_signals": 1}`.
  - Add `_cv_composite_score(kept_lists)` helper.
  - After `drop_unverified()` produces `kept_lists`, return `StageFailure(stage="profile", user_message=LOW_EVIDENCE_MSG, debug_detail=f"composite={...} threshold={MIN_CV_SCORE} kept={...} dropped={...}")` when `composite < MIN_CV_SCORE`.
  - Emit `obs.emit("extract", "low_evidence", composite=..., threshold=MIN_CV_SCORE, **counts)` so monitoring can spot fabricated-salary regressions in production.
- [x] `src/gander/ingest.py`: add `LOW_EVIDENCE_MSG` constant alongside `SCANNED_MSG`/`UNKNOWN_MSG`/`CORRUPT_MSG`/`EMPTY_MSG`. Copy:
  > "We couldn't find the experience, education, or skills we look for in a CV. If this is a CV, check that the text is selectable (not a scanned image) and that sections like Experience or Education are clearly labelled, then try again."

### Tests

- [x] `tests/test_extract.py::test_cv_composite_score_weights` — unit-tests the scoring function against empty, single-skill, single-experience, mixed bags.
- [x] `tests/test_extract.py::test_low_evidence_gate_fires_on_empty_profile` — LLM returns an empty profile → `StageFailure(LOW_EVIDENCE_MSG)`, `low_evidence` obs event emitted with composite=0.
- [x] `tests/test_extract.py::test_low_evidence_gate_fires_when_anchors_all_drop` — LLM returns items but their anchors don't substring-verify against the source text → post-verification composite=0 → gate fires. This is the realistic non-CV path: the LLM hallucinates plausible content that drops on verification.
- [x] `tests/test_extract.py::test_low_evidence_gate_passes_with_one_verified_experience` — single anchor-verified experience entry (weight=3) meets the threshold and `extract_profile` returns a `Profile`.
- [x] `tests/test_failures.py::test_low_evidence_profile_cascades_to_every_downstream_stage` — end-to-end through `pipeline.run()`. Uses a real CV docx for ingest+redact; mocked LLM returns hallucinated content that won't verify. Asserts `profile=StageFailure(LOW_EVIDENCE_MSG)`, every downstream stage cascaded as `StageFailure` with `statuses[stage] == "failed"`, no `running` left.

### Existing-test fix-ups

The three `test_tenure_override_*` cases in `tests/test_extract.py` previously used empty profiles (all four lists `[]`) to isolate the tenure-override logic. With the new gate those profiles would short-circuit before reaching the override. Updated each to include one anchor-verified experience entry (using the existing `_UNIQUE_EXP_QUOTE` 12-word fixture) so the tests still exercise the same override path while clearing the gate.

## Verification

```bash
uv run pytest tests/test_extract.py tests/test_failures.py -v -m fast
uv run pytest tests/test_acceptance.py -v   # ensure real CV fixtures still pass
uv run mypy src/
uv run ruff check src/ tests/
```

Manual end-to-end (post-merge):
- Upload a real CV — full report renders, no `low_evidence` obs event.
- Upload a non-CV PDF (e.g., a 2-page novel excerpt converted to PDF) — UI shows `LOW_EVIDENCE_MSG` in place of fabricated salary; `low_evidence` event in obs stream with `composite=0`.

## Reference

- Plan: `/home/mf/.claude/plans/if-we-upload-something-magical-stroustrup.md`
- PRD §4.5 (anchor verification — per-claim guard this task extends to document-level)

## Outcome

(populated on completion)
