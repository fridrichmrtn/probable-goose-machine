# T10 — L4a Seniority Scorer: implementation plan

Working directory: `/home/mf/GitHub/probable-goose-machine/.worktrees/block-b` (branch `feat/block-b-late-stages`).

Scope: produce a 0–100 seniority score across four named components (`skills`, `experience`, `education`, `soft_signals`), each carrying a substring-verified anchor, via ONE structured LLM call. Anchors that fail `verify_quote` get dropped. If any of the four required categories is missing after drops, the stage returns a `StageFailure` (the `Score` model requires exactly one component per category — a partial Score is not constructible).

## Files to create

- `src/gander/prompts/score.md` — system prompt (markdown). Loaded at module-import time in `score.py` via a `pathlib.Path(__file__).parent / "prompts" / "score.md"` read.
- `src/gander/score.py` — `score_profile(redacted, profile)` async entry point + an internal `_ComponentList` Pydantic model used solely to validate the LLM JSON envelope.
- `tests/test_score.py` — two `@pytest.mark.fast` tests (deterministic aggregation; drop-then-StageFailure) + two `@pytest.mark.live` tests (junior < 40, senior > 70) + one calibration `pytest.skip` placeholder.

## Files NOT to modify (read-only upstream)

- `src/gander/schemas.py`, `src/gander/llm.py`, `src/gander/verify.py`, `src/gander/obs.py`, `src/gander/errors.py`. Imports only.

## Section 1 — `src/gander/prompts/score.md` (exact prompt text)

The prompt is the entire system message. It is committed as a `.md` file so a reviewer can read it without running code, and so prompt-only tweaks don't churn `score.py`.

Tight outline (write this as flowing prose in the file, not as bullet points the model has to interpret):

```
You score a candidate's absolute seniority on four named components, given a redacted CV.

Return JSON only, exactly matching this schema:
{
  "components": [
    {
      "name": "skills" | "experience" | "education" | "soft_signals",
      "score_0_100": <integer 0..100>,
      "justification": "<one sentence>",
      "anchor": {
        "quote": "<verbatim substring of the CV, >=6 consecutive words>",
        "section": "<CV section header, e.g. 'Work Experience', 'Education'; or null>"
      }
    },
    ... exactly four entries, one per component name ...
  ]
}

Component definitions (score on these, nothing else):

- skills:        breadth and depth of NAMED technologies, tools, and techniques the candidate has demonstrably used. Score on the specificity and modernity of the stack the CV evidences.
- experience:    total years AND role progression AND shipped impact metrics (numbers, scale, latency, revenue, headcount led). Score on the trajectory the CV documents, not on raw years alone.
- education:     formal credentials only — degree level, field, institution attendance dates. Do not score this component on prestige of the school name; treat all accredited institutions equally.
- soft_signals:  evidence of leadership, written/verbal communication, mentorship, cross-team work, and domain depth, drawn from explicit statements in the CV.

Absolute scoring scale (do NOT center on 50):
  0–30   junior / entry (narrow exposure, early career, <2y)
  31–60  mid-level (solid working competence, multiple shipped projects, 2–6y)
  61–85  senior (breadth across stack, mentors others, owns systems, 6–12y)
  86–100 staff / principal (deep platform impact, org-wide leverage, 10y+)

Evidence-based scoring rules — read carefully:
  - Score ONLY on demonstrated skills, role progression, shipped impact metrics, and the literal anchor quotes you select. The anchor IS the evidence.
  - Do NOT score up for prestige signals: school name, employer brand, or fluency/style of the prose. A candidate from a less-known university with shipped impact outscores a candidate from a famous university without it.
  - If the CV has no education section, still emit an education component but pick the lowest-evidence quote you can find from elsewhere and score conservatively. (Downstream verification will drop the component if your quote doesn't match — that's the intended fail-closed behavior.)

Anchor quote rules (anti-paraphrase — these are LITERAL):
  - `anchor.quote` MUST be a verbatim substring copied character-for-character from the CV. Case-preserved. Punctuation-preserved. No ellipses. No edits. No paraphrasing.
  - Pick a quote of at least 6 consecutive words. Prefer a quote that appears in the CV exactly once. If you cannot guarantee uniqueness, copy 8 or more consecutive words instead.
  - `anchor.section` should name the CV header the quote sits under (e.g. "Work Experience", "Education", "Skills"). If you are unsure which header, set section to null — the verifier will fall back to whole-CV match.
  - If you cannot find a 6+ word literal substring of the CV that supports a component, copy your best-effort quote anyway and let downstream verification drop it; do NOT fabricate text that isn't in the CV.

Output format:
  - Return raw JSON only. No prose outside the JSON object. No markdown code fences.
  - Exactly four entries in `components`, one per name. No duplicates. No fifth name.
```

Notes on prompt content:
- The bias instruction is explicit and lives in two places: (a) the `education` definition pins the anti-prestige rule for the most likely demographic-correlated bias signal in the CZ corpus (per PRD §4.7 and PLAN `test_bias_smoke.py`), and (b) the "evidence-based scoring rules" block restates it generally for the other three components.
- The output schema is described once, in JSON-shaped pseudocode. We rely on `complete_json`'s native JSON-mode plus the `_ComponentList` Pydantic validator to enforce shape. We do NOT ask the model to emit a `total` — `Score.total` is a `computed_field` derived from the four `score_0_100` integers.
- The "fail-closed via downstream verification" wording is deliberate: it tells the model not to invent quotes when evidence is thin, and acknowledges the drop path so the model isn't tempted to paraphrase into "safer" wording.

## Section 2 — `src/gander/score.py`

```python
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ValidationError

from gander.errors import StageFailure, stage_boundary
from gander.llm import LLMClient
from gander.obs import emit
from gander.schemas import COMPONENT_WEIGHTS, Component, Profile, RedactedCV, Score
from gander.verify import verify_quote

_PROMPT_PATH = Path(__file__).parent / "prompts" / "score.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


class _ComponentList(BaseModel):
    """LLM response envelope: `{"components": [Component, Component, Component, Component]}`.

    Reuses `Component` from schemas (which already enforces name/range/anchor shape).
    Length and per-category uniqueness are NOT enforced here — we surface the model's
    actual output (junk names, dupes, wrong length) to the verify-and-rebuild step,
    where any missing category cleanly becomes a StageFailure.
    """

    components: list[Component]


async def score_profile(
    redacted: RedactedCV, profile: Profile
) -> Score | StageFailure:
    with stage_boundary("score") as cm:
        client = LLMClient()
        user_message = _build_user_message(redacted, profile)

        raw = await client.complete_json(
            system=_SYSTEM_PROMPT,
            user=user_message,
            schema=_ComponentList,
            model="reasoning",
            temperature=0.0,
        )
        assert isinstance(raw, _ComponentList)  # narrows the BaseModel return

        verified: dict[str, Component] = {}
        dropped = 0
        for comp in raw.components:
            if comp.name in verified:
                # Duplicate category from the model — keep the first, count the rest as dropped.
                dropped += 1
                continue
            if verify_quote(
                comp.anchor.quote, redacted.text, section=comp.anchor.section
            ):
                verified[comp.name] = comp
            else:
                dropped += 1

        emit(
            "score",
            "score_components",
            returned=len(raw.components),
            verified=len(verified),
            dropped=dropped,
        )

        required = set(COMPONENT_WEIGHTS.keys())
        missing = required - verified.keys()
        if missing:
            return StageFailure(
                stage="score",
                user_message="Could not verify enough scoring components from CV.",
                debug_detail=f"missing_categories={sorted(missing)} dropped={dropped}",
            )

        score = Score(components=[verified[name] for name in COMPONENT_WEIGHTS])
        emit("score", "score_total", total=score.total)
        return score

    return cm.failure  # type: ignore[return-value]
```

Decisions made above and why:

1. **One LLM call.** Honors the latency budget (PLAN §"Latency budget" — L4a is 6s, ~one M2.7-highspeed call). Four sequential calls would blow the round-trip budget. The prompt asks for a four-element list in one envelope.
2. **`_ComponentList` is a thin envelope — not a re-validation layer.** It validates `{"components": [...]}` shape and reuses `Component` (which already enforces `name` Literal, `score_0_100` 0..100 range, and the `Anchor` shape). We deliberately do NOT add length/uniqueness validators to `_ComponentList`; if the model returns three components or two with `name="skills"`, we want to fall through to the missing-categories StageFailure path with a clean log, not raise a `ValidationError` that surfaces as a stage exception with no useful counter.
3. **Drop loop matches T05 spike.** `verify_quote(quote, redacted.text, section=anchor.section)`. If the model emits a section name that doesn't match a CV header, `verify_quote` returns False and the component drops — same as if the quote were paraphrased. This is intentional and is the lever that enforces the ≥70% literal-copy gate from T05.
4. **StageFailure replaces "re-normalization."** The original task brief mentioned re-normalization of weights when a category drops. The current `Score` schema (read-only) requires exactly one component per category — `model_validator` raises if any are missing. So a partial Score is not a representable state. Returning `StageFailure` is the only correct shape; downstream rendering already handles `Score | StageFailure` in `Report.score`.
5. **`stage_boundary` usage.** Standard pattern from T01: `with stage_boundary("score") as cm: ...` — any uncaught exception inside (e.g., MiniMax 5xx, retry exhaustion, JSON-decode failure after `max_retries`) is captured into `cm.failure`. The trailing `return cm.failure` line runs only when an exception was suppressed; mypy needs the `# type: ignore[return-value]` because it can't see that `cm.failure` is non-None on the post-context path.
6. **Telemetry counters per PRD §4.8.** Two events: `score_components` with `returned`, `verified`, `dropped` counters; `score_total` with the final integer score. Stage name is set by `stage_boundary` via `obs.current_stage`. The `llm_call` event with duration is emitted automatically by `complete_json`.
7. **No retries beyond `complete_json`'s default `max_retries=1`.** The retry path inside `complete_json` already re-prompts with the validation error; further retries would compound latency without evidence they help.

### `_build_user_message(redacted, profile)` — content

```python
def _build_user_message(redacted: RedactedCV, profile: Profile) -> str:
    return (
        f"Detected role: {profile.detected_role}\n"
        f"Detected years of experience: {profile.detected_years_experience}\n"
        f"\n"
        f"Redacted CV:\n\n{redacted.text}"
    )
```

What we pass and why:
- `redacted.text` — the full redacted CV text. This is the source the anchors must literal-copy from. Pass it verbatim; do NOT pre-extract sections (the model needs the section headers to label `anchor.section` correctly).
- `profile.detected_role` and `profile.detected_years_experience` — give the model the upstream classification so it doesn't have to re-derive role from scratch. These are weak hints; the prompt's absolute scale doesn't lean on them.
- We deliberately do NOT pass `profile.skills/experience/education/soft_signals` lists. Those are the L3 extraction's view; passing them would tempt the model to score on the upstream paraphrase rather than the raw CV. The anchor literal-copy gate enforces grounding in `redacted.text`.

## Section 3 — `_ComponentList` Pydantic schema (recap)

Defined inline in `score.py`. Single field: `components: list[Component]`. Component is imported from `gander.schemas`. No additional validators. The reason to NOT add `min_length=4` / per-name uniqueness here is that we want missing categories to surface as a clean `StageFailure` with a counter, not as a `ValidationError` raised inside `complete_json`'s retry loop (which would either (a) waste an LLM call retrying a structurally-correct-but-incomplete payload or (b) bubble out as a generic stage exception with no anchor-drop counter).

## Section 4 — Section-locality fallthrough behavior

`verify_quote(quote, redacted.text, section=anchor.section)`:

- If `anchor.section is None` → `verify_quote` runs whole-CV match (≥6 words unique, OR ≥8 words). Component verifies if the literal substring is present anywhere.
- If `anchor.section` is a string but no `## <section>` header (any H1–H6) matches in the CV → `_section_text` returns None → `verify_quote` returns False → component drops. This is the desired fail-closed behavior: we don't silently fall back to whole-CV match when the model named a non-existent section, because that lets the model skip section discipline.
- If `anchor.section` matches a CV header → search is restricted to that section's body.

This means the prompt is explicit: "If you are unsure which header, set section to null." That phrasing keeps the model conservative — it can opt out of section-locality by emitting `null`, but if it commits to a section name, it pays the verification cost. This is the right trade for a one-shot call.

## Section 5 — Tests in `tests/test_score.py`

File header:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from gander.errors import StageFailure
from gander.llm import LLMClient
from gander.schemas import (
    Anchor,
    Component,
    Profile,
    ProfileItem,
    RedactedCV,
    Score,
)
from gander.score import _ComponentList, score_profile

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "cvs"
JUNIOR_FIXTURE = FIXTURE_DIR / "01_junior_da_novotny.txt"
SENIOR_FIXTURE = FIXTURE_DIR / "08_staff_ml_engineer_dvorak.txt"
```

### Test 1 — `@pytest.mark.fast` deterministic aggregation

```python
@pytest.mark.fast
def test_score_total_is_deterministic_weighted_sum() -> None:
    score = Score(
        components=[
            Component(name="skills", score_0_100=80,
                      justification=".", anchor=Anchor(quote="x")),
            Component(name="experience", score_0_100=60,
                      justification=".", anchor=Anchor(quote="x")),
            Component(name="education", score_0_100=40,
                      justification=".", anchor=Anchor(quote="x")),
            Component(name="soft_signals", score_0_100=100,
                      justification=".", anchor=Anchor(quote="x")),
        ]
    )
    # 80*0.35 + 60*0.30 + 40*0.20 + 100*0.15 = 28 + 18 + 8 + 15 = 69
    assert score.total == 69
```

Why this duplicates one already-existing case in `test_schemas.py`: T10's contract includes "deterministic aggregation given fixed components." Owning the test here makes T10's verification self-contained and lets future schema reorganization keep the contract test attached to the consumer. It's two assertions of overhead.

### Test 2 — `@pytest.mark.fast` drop → StageFailure

Build a fake `_ComponentList` payload where ONE anchor is unverifiable; assert `score_profile` returns `StageFailure`, not a partial Score.

```python
@pytest.mark.fast
@pytest.mark.asyncio
async def test_score_returns_stage_failure_when_anchor_unverifiable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cv_text = (
        "## Work Experience\n"
        "Built a recommendation system that reduced churn by eighteen percent.\n"
        "Mentored four junior engineers across two squads in the platform team.\n"
        "## Education\n"
        "MSc in Computer Science, accredited university, two thousand eighteen.\n"
        "## Skills\n"
        "Python, PyTorch, async pipelines, vector databases, distributed systems work.\n"
    )
    redacted = RedactedCV(text=cv_text, audit_log=[])
    item = ProfileItem(text="x", anchor=Anchor(quote="recommendation system that reduced churn by"))
    profile = Profile(
        skills=[item], experience=[item], education=[item], soft_signals=[item],
        detected_role="engineer",
        detected_location=None,
        detected_years_experience=5,
    )

    payload = _ComponentList(
        components=[
            Component(name="skills", score_0_100=70, justification=".",
                      anchor=Anchor(quote="python, pytorch, async pipelines, vector databases",
                                    section="Skills")),
            Component(name="experience", score_0_100=65, justification=".",
                      anchor=Anchor(quote="recommendation system that reduced churn by",
                                    section="Work Experience")),
            # This one is unverifiable: the quote is paraphrased — not present in cv_text.
            Component(name="education", score_0_100=55, justification=".",
                      anchor=Anchor(quote="masters degree in computer science earned in twenty eighteen",
                                    section="Education")),
            Component(name="soft_signals", score_0_100=60, justification=".",
                      anchor=Anchor(quote="mentored four junior engineers across two squads",
                                    section="Work Experience")),
        ]
    )

    async def fake_complete_json(self: LLMClient, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(LLMClient, "complete_json", fake_complete_json)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-stub")  # LLMClient.__init__ requires it

    result = await score_profile(redacted, profile)
    assert isinstance(result, StageFailure)
    assert result.stage == "score"
    assert "scoring components" in result.user_message.lower()
```

Notes on test 2:
- The "skills" anchor is a 5-word unique substring? Count: `python, pytorch, async pipelines, vector databases` — 5 words after comma-stripping. **Verify count before committing**: actually `python` `pytorch` `async` `pipelines` `vector` `databases` = 6 tokens. Whitespace-collapsed normalization in `verify.py` treats commas as part of the word. The verify rule is `len(needle.split())`, so "python," counts as one token. Pick a 6-token substring deliberately: `"python, pytorch, async pipelines, vector databases"` splits to 6 tokens. If uniqueness fails in the local fixture, expand to 8 tokens by adding `, distributed systems work`. **Action for implementation: when writing the test, paste the substring into a small REPL check (`len(s.split()) >= 6`) before committing.**
- The unverifiable "education" quote (`"masters degree in computer science earned in twenty eighteen"`) is intentionally a paraphrase of the CV line, with no 6-word literal overlap with `"MSc in Computer Science, accredited university, two thousand eighteen."`. That's the dropped category.
- `monkeypatch.setattr(LLMClient, "complete_json", ...)` patches the bound method on the class so any `LLMClient()` constructed inside `score_profile` uses the fake. We also `setenv("MINIMAX_API_KEY", "test-stub")` to satisfy the constructor.
- `pytestmark` is not used at module level — we mix `fast` and `live` in this file. Each test carries its own marker.

### Test 3 — `@pytest.mark.live` junior < 40

```python
@pytest.mark.live
@pytest.mark.asyncio
async def test_junior_fixture_scores_below_40() -> None:
    cv_text = JUNIOR_FIXTURE.read_text(encoding="utf-8")
    redacted = RedactedCV(text=cv_text, audit_log=[])
    item = ProfileItem(text="placeholder", anchor=Anchor(quote="placeholder"))
    profile = Profile(
        skills=[item], experience=[item], education=[item], soft_signals=[item],
        detected_role="Junior Data Analyst",
        detected_location="Prague",
        detected_years_experience=1,
    )
    result = await score_profile(redacted, profile)
    assert isinstance(result, Score), f"expected Score, got {type(result).__name__}: {result}"
    assert result.total < 40, f"junior fixture scored {result.total}, expected <40"
```

### Test 4 — `@pytest.mark.live` senior > 70

```python
@pytest.mark.live
@pytest.mark.asyncio
async def test_senior_fixture_scores_above_70() -> None:
    cv_text = SENIOR_FIXTURE.read_text(encoding="utf-8")
    redacted = RedactedCV(text=cv_text, audit_log=[])
    item = ProfileItem(text="placeholder", anchor=Anchor(quote="placeholder"))
    profile = Profile(
        skills=[item], experience=[item], education=[item], soft_signals=[item],
        detected_role="Staff Machine Learning Engineer",
        detected_location="Prague",
        detected_years_experience=13,
    )
    result = await score_profile(redacted, profile)
    assert isinstance(result, Score), f"expected Score, got {type(result).__name__}: {result}"
    assert result.total > 70, f"senior fixture scored {result.total}, expected >70"
```

Notes on tests 3+4:
- We bypass T08 redaction and feed the raw fixture text directly as `RedactedCV.text`. The fixtures are already plaintext; T08's redaction is orthogonal to scoring behavior (the model still sees section headers, role progression, metrics).
- We bypass T09 profile extraction and hand-build a minimal `Profile` from fields visible in the fixture header. This isolates T10's behavior from T09's correctness — the live test answers "given a perfect upstream, does scoring land in band?".
- `ProfileItem.anchor` requires a `quote` string but the field is unused by `score_profile` (we only consume `detected_role` and `detected_years_experience`). A placeholder quote is fine; we're not testing Profile validity here.

### Test 5 — calibration placeholder

```python
@pytest.mark.live
@pytest.mark.slow
@pytest.mark.asyncio
async def test_score_calibration_variance_on_mid_fixture() -> None:
    pytest.skip("no mid fixture authored yet — covered by T17 acceptance once T06 lands")
```

The skip is unconditional and the body doesn't reference any not-yet-existing module, so it lints clean and runs (as skipped) under both `-m fast` and `-m live` selections. T17 wires this up once T06 ships fixtures `02..07`.

## Verification commands

```bash
# Lint + type-check (will run via pre-commit too):
uv run pre-commit run --all-files

# Fast tests (no API key required):
uv run pytest -q -m fast tests/test_score.py

# Live tests (requires MINIMAX_API_KEY in env):
uv run pytest -q -m live tests/test_score.py
```

All three must pass. Pre-commit covers ruff + mypy on the new files. The fast suite must run under 1s per test (it should — the only real work is one Pydantic instantiation and a string match per test).

## Definition of done

- `src/gander/prompts/score.md`, `src/gander/score.py`, `tests/test_score.py` exist at the paths above.
- `pre-commit run --all-files` is green.
- `uv run pytest -q -m fast tests/test_score.py` is green (2 tests pass, 1 skipped under `-m live`).
- `uv run pytest -q -m live tests/test_score.py` is green when MINIMAX_API_KEY is set: junior < 40, senior > 70, calibration skipped with the documented message.
- `tasks/T10_score.md` Outcome section filled in with the actual junior/senior scores observed and any deltas vs. this plan.

## Out of scope (deferred)

- Calibration variance test body (depends on T06 mid fixtures).
- `test_bias_smoke.py` school-prestige pair test — separate test file, owned by T17 acceptance suite.
- L4a/L4b concurrent execution (`asyncio.gather`) — orchestrator wiring lives in T15.
- Schema changes to `Score` (e.g., re-normalization with missing categories) — read-only upstream, and the StageFailure path is the correct surface.
- Anthropic-fallback prompt-caching tweaks — `complete_json` already handles provider routing; nothing T10-specific.

## Risks / unknowns

- **Live junior score landing ≥40.** The T05 spike showed junior=`skills` score in the 30–55 band on this fixture. The aggregate (skills 0.35 + experience 0.30 + education 0.20 + soft 0.15) usually drags below 40 because junior CVs typically score low on `experience` (1y) and `soft_signals` (no leadership), but it's a real risk. If the live test fails high, the first lever is tightening the prompt's "absolute scale, do not center on 50" sentence; the second is widening the band to <45 in the T10 test contract (requires acceptance criteria sign-off, not a unilateral change).
- **Senior score landing ≤70.** Less likely given the spike showed senior `skills` consistently 75–90, but possible if `education` scores low (the senior fixture has education but it's terse — 2 lines).
- **Section-name vocabulary mismatch.** The model may emit `"Experience"` while the CV header is `"## Experience"` (which `_section_text` treats as `"experience"` after lowercasing) — these match. But `"Work Experience"` vs `"Experience"` won't. The fail-closed drop behavior is the safety net; if it triggers too often we'll see the StageFailure path firing on real CVs and need to tighten the prompt to enumerate the actual fixture-header vocabulary. Acceptable risk for round 1.
- **MiniMax JSON-mode reliability.** T05 measured 100% JSON survival on these two fixtures; the `complete_json` retry path covers transient failures. No mitigation needed unless live tests flake.
