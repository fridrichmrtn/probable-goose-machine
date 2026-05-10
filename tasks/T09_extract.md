# T09 — L3 profile extraction

Status: todo
Owner: ai-ml-engineer
Depends on: T02, T05 (gate)
Unblocks: T15
Estimate: ~45 min

## Goal

Extract a structured `Profile` from the redacted CV via one MiniMax-M1 (or fallback) JSON-mode call. Every item carries an `anchor.quote` that is substring-verified against the redacted source.

## Deliverables

- [ ] `src/jobfit/prompts/extract.md` — system prompt:
  - Instructs model to return JSON matching `Profile` schema.
  - **Hard rule** (verbatim): "For every list item, copy the EXACT supporting substring from the CV into `anchor.quote`. Do not paraphrase. The quote must be at least 6 words long. If you cannot find a 6-word literal substring, omit the item."
  - Detects role title, location (CZ city if present), total years experience.
  - Includes a one-shot example showing a literal-quote anchor.
- [ ] `src/jobfit/extract.py`:
  - `async def extract_profile(redacted: RedactedCV) -> Profile`:
    - Calls `llm.complete_json(system=load_prompt("extract.md"), user=redacted.text, schema=Profile, model="reasoning")`.
    - For each `ProfileItem`, runs `verify_quote(item.anchor.quote, redacted.text, section=item.anchor.section)`. Drops failures via `drop_unverified`. Logs drop counts: `obs.emit("verify", stage="extract", dropped=N, kept=M)`.
    - Wrapped in `stage_boundary("extract")`.
- [ ] `tests/test_extract.py`:
  - `@pytest.mark.live`: run on each acceptance triplet CV (junior/mid/senior); assert ≥80% of returned items survive `verify_quote`. Capture failure if MiniMax struggles — that triggers a prompt revision.
  - `@pytest.mark.live`: assert `Profile.detected_role` is non-empty and `detected_years_experience` is in (0, 50).
  - `@pytest.mark.fast`: a unit test that mocks `llm.complete_json` to return a profile with one paraphrased anchor → assert that item is dropped after verification.

## Verification

```bash
uv run pytest -m fast tests/test_extract.py -v
uv run pytest -m live tests/test_extract.py -v   # needs MINIMAX_API_KEY + fixtures
```

## Reference

- tasks/PLAN.md — § "L3 — Profile Extraction"

## Outcome

(fill in when done — drop-rate per fixture, any prompt iterations)
