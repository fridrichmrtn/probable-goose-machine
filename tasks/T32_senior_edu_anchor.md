# T32 — Senior fixture education-anchor verify miss

Status: open
Owner: ai-ml-engineer (follow-up from T30 phase 1)
Depends on: T24 (merged), T25 (merged), T26 (merged), T30 phase 1 (PR #10)
Unblocks: removing the `@pytest.mark.xfail(strict=True)` on
`tests/test_acceptance.py::test_score_spread_at_least_30`
Estimate: ~60 min investigation + fix

## Symptom

On `08_staff_ml_engineer_dvorak.pdf` the L5 report's `score` arrives via the
T25 partial-Score path with `dropped == ["education"]`. CI run
`25858085344` (PR #10 head `c44f8d8`) emitted:

```
01_junior_da_novotny.docx        → score_total=43   (full 4-of-4, no dropped)
03_ds_horak.pdf                  → score_partial dropped=["soft_signals"], total=54
08_staff_ml_engineer_dvorak.pdf  → score_partial dropped=["education"],   total=72
```

With `education` weight = 0.20 contributing 0 (T25 "drop = 0, don't
re-normalize", PRD §4.5), senior's total compresses ~10–15 points below the
full-Score baseline. PRD §5.4 differentiation gate (`senior.total -
junior.total >= 30`) lands at 29 — off by one.

The test `test_score_spread_at_least_30` is currently `xfail(strict=True)` on
PR #10 so the rest of the acceptance suite can land. When this task fixes
the anchor miss, the test will unexpectedly pass and strict-xfail will
flag it for removal.

## Root-cause hypotheses (in order of likelihood)

1. **Extract-stage LLM produced an anchor quote that doesn't substring-match
   the redacted CV text.** `verify_quote` runs against the redacted source.
   If the LLM paraphrased even one character (curly quote, hyphen variant,
   non-breaking space), `verify_quote` returns False and the component
   drops. T26's section-fallback path already absorbed the section-header
   mismatch case; this would be a different miss (body-quote substring).
2. **Post-redaction artifact in the anchor span.** If the education line
   contains a token redact() rewrites (e.g. a date → `[YEAR]`, a school
   URL → `[URL]`), and the LLM's quote was taken from pre-redaction text,
   the quote will fail to match. Extract reads the redacted text, so this
   would be a bug in either the LLM (ignoring instructions) or redact (over-
   rewriting a span the prompt expected raw).
3. **Phantom anchor — LLM invented a line that isn't in the CV.** Less
   likely given T26's section-fallback verifier already accepts loose
   section matching, but possible if the LLM hallucinated a degree the CV
   doesn't list.

## Investigation steps

```bash
# 1. Reproduce locally with one CV (deterministic seed if possible).
uv run python -c "
import asyncio
from pathlib import Path
from gander import pipeline, obs
fname = '08_staff_ml_engineer_dvorak.pdf'
path = Path('tests/fixtures/cvs') / fname
events = []
async def run():
    with obs.subscribe(events.append):
        async for snap in pipeline.run(path.read_bytes(), fname):
            pass
    return snap
snap = asyncio.run(run())
print('dropped:', snap.score.dropped)
print('redacted preview:', snap.redacted_cv_text[:500])
# Find the extract-stage education anchor candidate
for e in events:
    if e.get('event') == 'verify_quote_failed' and e.get('section') == 'education':
        print('FAILED:', e)
"

# 2. Compare the LLM's anchor quote to the redacted CV text byte-by-byte to
#    classify the miss (hypothesis 1 vs 2 vs 3).
```

## Fix paths (decide after investigation)

- **If hypothesis 1**: tighten the extract prompt to demand exact substring
  quotes, or relax `verify_quote` whitespace/punctuation normalization
  carefully (T26's fallback path is the natural extension point).
- **If hypothesis 2**: align the prompt's anchor instructions with what the
  redacted text actually contains (i.e. point the model at `[YEAR]`-aware
  quoting). Already required for `[URL]` markers per T28.
- **If hypothesis 3**: this is a fabrication and `verify_quote`'s rejection
  is the correct behaviour. Then the question shifts to: should this CV
  actually drop the education component, or should the prompt be tightened
  to stop the LLM from inventing education lines? Discuss with
  ai-ml-engineer.

## Verification

- `test_score_spread_at_least_30` un-xfails automatically (strict=True).
- Senior 08 emits full 4-of-4 Score (no `dropped`).
- Local fast suite stays green.
- One live acceptance run confirms the spread climbs back above 30 on the
  EN triplet.

## Reference

- PRD §4.5 ("drop, don't fabricate"), §5.4 (differentiation gate)
- T25: `src/gander/schemas.py::Score`, `src/gander/score.py:100-119`
- T26: `src/gander/verify.py::verify_quote` section-fallback
- T28: redact tagline + tenure handling
- PR #10 CI failure: run 25858085344
