# T26 — verify_quote: section-fallback + telemetry (R3)

Status: todo
Owner: software-engineer
Depends on: —
Unblocks: T29
Estimate: ~30 min

## Goal

`verify._section_text` returns `None` when the requested section header isn't present as a `## ...` line in the source. Today, that triggers `verify_quote` to return `False` immediately — so any model-emitted section name that doesn't match an annotated header silently drops the claim, even when the quote itself is a valid 6+ word substring of the CV.

This silent-drop behavior is invisible to operators (no obs event) and combines pathologically with T24's section-vocab gap: bilingual CVs lose every section-tagged anchor before the verifier even checks the quote. The 6/8-word literal floor still defends PRD §4.5.

Add a graceful fallback to whole-CV substring match when the section header isn't found, AND emit an obs event so silent drops become observable per §4.8. **Cap the fallback** so a CV with no annotated headers at all (e.g. T24 partial failure on SK headers) doesn't silently turn off section-restricted verification across the entire scoring stage.

## Deliverables

- [ ] `src/gander/verify.py::verify_quote`:
  - When `section is not None` and `_section_text(source, section)` returns `None`, fall back to whole-source substring match (current behavior when `section is None`).
  - Emit `obs.emit("verify", "verify_section_miss", section=section, fallback="whole_cv")` once per call that hits the fallback.
- [ ] `src/gander/score.py::score_profile` — **per-stage fallback budget**:
  - Subscribe to `verify_section_miss` events for the duration of the stage call (use `obs.subscribe` context manager).
  - If the count of misses within a single `score_profile` call exceeds **2** (i.e. more than half the 4 components hit the fallback), treat the entire scoring stage as section-blind and **fail closed** with `StageFailure("Section anchors unavailable on this CV — could not verify scoring components against named sections.")`. Without this cap, a CV with broken section annotation silently passes via whole-CV fallback for every anchor and PRD §4.5's section-restriction signal is lost.
  - Emit `obs.emit("score", "section_blind_fail", miss_count=N)` when the cap trips, so the operator can see why a stage failed.
- [ ] `src/gander/obs.py`: register `verify_section_miss` and `section_blind_fail` if events are enumerated anywhere; otherwise no change.
- [ ] `tests/test_verify.py`:
  - `test_verify_quote_section_match_cz` — source has `## Pracovní zkušenosti\n...` and the model anchors with `section="Pracovní zkušenosti"` → returns True when the quote is in that section.
  - `test_verify_quote_section_miss_falls_back` — source has the quote but NOT a `## SectionName` header → with fallback returns True; emits `verify_section_miss`.
  - `test_verify_quote_section_miss_quote_also_missing` — section missing AND quote not in source anywhere → returns False; emits `verify_section_miss`.
  - `test_verify_quote_section_match_quote_in_other_section` — quote is in source but NOT inside the named section → today returns False (section-restricted). After fallback: keep section-restricted on hit, fall back only on header miss. Asserts False.
  - `test_verify_section_miss_event_emitted` — uses `gander.obs.subscribe(callback)` to capture events; asserts `verify_section_miss` fires with `section=<name>` and `fallback="whole_cv"` payload. **Required per PRD §4.8** — without this assertion, the event is unprotected by CI.
- [ ] `tests/test_score.py::test_score_section_blind_fail_cap` — construct a synthetic CV with no `## ...` headers; mock 4 verified component candidates (each section-tagged). Assert StageFailure with the section-blind message and that `section_blind_fail` event fires with `miss_count=4`.

## Verification

```bash
uv run pytest tests/test_verify.py -v
```

## Reference

- Plan: `/home/mf/.claude/plans/this-is-a-result-peaceful-blanket.md` § "Confirmed root causes — Score path S2"
- PRD §4.5 (hallucination guard — 6/8-word floor unchanged), §4.8 (observability)

## Outcome

(fill in when done — confirm fallback policy, count of obs events fired during full test suite)
