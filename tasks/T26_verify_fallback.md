# T26 — verify_quote: section-fallback + telemetry (R3)

Status: todo
Owner: software-engineer
Depends on: —
Unblocks: T29
Estimate: ~30 min

## Goal

`verify._section_text` returns `None` when the requested section header isn't present as a `## ...` line in the source. Today, that triggers `verify_quote` to return `False` immediately — so any model-emitted section name that doesn't match an annotated header silently drops the claim, even when the quote itself is a valid 6+ word substring of the CV.

This silent-drop behavior is invisible to operators (no obs event) and combines pathologically with T24's section-vocab gap: bilingual CVs lose every section-tagged anchor before the verifier even checks the quote. The 6/8-word literal floor still defends PRD §4.5.

Add a graceful fallback to whole-CV substring match when the section header isn't found, AND emit an obs event so silent drops become observable per §4.8.

## Deliverables

- [ ] `src/gander/verify.py::verify_quote`:
  - When `section is not None` and `_section_text(source, section)` returns `None`, fall back to whole-source substring match (current behavior when `section is None`).
  - Emit `obs.emit("verify", "verify_section_miss", section=section, fallback="whole_cv")` once per call that hits the fallback.
- [ ] `src/gander/obs.py`: register `verify_section_miss` if events are enumerated anywhere; otherwise no change.
- [ ] `tests/test_verify.py`:
  - `test_verify_quote_section_match_cz` — source has `## Pracovní zkušenosti\n...` and the model anchors with `section="Pracovní zkušenosti"` → returns True when the quote is in that section.
  - `test_verify_quote_section_miss_falls_back` — source has the quote but NOT a `## SectionName` header → with fallback returns True; emits `verify_section_miss`.
  - `test_verify_quote_section_miss_quote_also_missing` — section missing AND quote not in source anywhere → returns False; emits `verify_section_miss`.
  - `test_verify_quote_section_match_quote_in_other_section` — quote is in source but NOT inside the named section → behavior: today returns False (section-restricted). After fallback, what should happen? **Decision in this task**: keep section-restricted on hit, fall back only on header miss. So this test asserts False (the section was found; the quote just isn't in it).

## Verification

```bash
uv run pytest tests/test_verify.py -v
```

## Reference

- Plan: `/home/mf/.claude/plans/this-is-a-result-peaceful-blanket.md` § "Confirmed root causes — Score path S2"
- PRD §4.5 (hallucination guard — 6/8-word floor unchanged), §4.8 (observability)

## Outcome

(fill in when done — confirm fallback policy, count of obs events fired during full test suite)
