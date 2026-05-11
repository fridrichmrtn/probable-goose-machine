# T09 — L3 profile extraction: implementation plan

Source of truth: `tasks/T09_extract.md`. PLAN reference: §"L3 — Profile Extraction". Builds on T05 outcome (gates passed at 4/4 with anchor-rate 100%, p50 ~16s). The T05 prompt at `scripts/spike_minimax.py:53-69` is the validated baseline; this task adapts it to the full `Profile` schema and ships it as a stage with verify+drop wiring.

## Scope

- Block A scope. New files only: `src/jobfit/prompts/extract.md`, `src/jobfit/extract.py`, `tests/test_extract.py`.
- READ-ONLY (do not modify): `src/jobfit/{schemas,llm,verify,obs,errors,ingest,redact}.py`.
- No new dependencies. Everything already in `pyproject.toml` (`openai`, `pydantic`, `structlog`, `pytest`, `pytest-asyncio`).

## File-by-file change list

### `src/jobfit/prompts/extract.md` (new)

Markdown file consumed verbatim as the LLM `system` prompt. Load via `Path(__file__).parent / 'prompts' / name`. Full text in §"Prompt body" below.

### `src/jobfit/extract.py` (new)

```python
from __future__ import annotations

import time
from pathlib import Path
from typing import cast

from jobfit import obs
from jobfit.errors import StageFailure, stage_boundary
from jobfit.llm import LLMClient
from jobfit.schemas import Profile, ProfileItem, RedactedCV
from jobfit.verify import drop_unverified

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    """Read a prompt file from src/jobfit/prompts/. Synchronous; called once per stage."""
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


async def extract_profile(redacted: RedactedCV) -> Profile | StageFailure:
    """Run L3 profile extraction. Returns Profile on success, StageFailure on stage error.

    Verifies every ProfileItem's anchor.quote against `redacted.text` and drops
    unverified items before returning. Emits one `verify` event with aggregate
    kept/dropped counters across all four list fields.
    """
    t0 = time.perf_counter()
    obs.emit("extract", "start", chars=len(redacted.text))

    def _ms() -> int:
        return int((time.perf_counter() - t0) * 1000)

    with stage_boundary("extract") as cm:
        client = LLMClient()
        raw = await client.complete_json(
            system=load_prompt("extract.md"),
            user=redacted.text,
            schema=Profile,
            model="reasoning",
        )
        profile = cast(Profile, raw)

        total_dropped = 0
        total_kept = 0
        list_fields = ("skills", "experience", "education", "soft_signals")
        kept_lists: dict[str, list[ProfileItem]] = {}
        for field in list_fields:
            items = getattr(profile, field)
            kept, dropped = drop_unverified(items, redacted.text)
            kept_lists[field] = kept
            total_kept += len(kept)
            total_dropped += dropped

        verified = profile.model_copy(update=kept_lists)
        obs.emit(
            "extract",
            "verify",
            dropped=total_dropped,
            kept=total_kept,
        )
        obs.emit("extract", "done", duration_ms=_ms(), kept=total_kept)
        return verified

    assert cm.failure is not None  # stage_boundary caught an exception
    return cm.failure
```

Contract notes:

- Return-type union `Profile | StageFailure` mirrors `ingest.extract_text` and `redact.redact` (T07/T08 pattern). Caller (T15 pipeline) dispatches on isinstance.
- `stage_boundary("extract")` sets `obs.current_stage` so the `llm_call` event emitted from inside `LLMClient.complete_json` is tagged `stage="extract"` (per `llm.py:142-151`). No separate `llm_call` emit here.
- `obs.emit("extract", "verify", dropped=..., kept=...)` fires exactly once per call — aggregate across all four lists per the task spec. The emit happens **inside** the `with` block so it does NOT fire on the failure path.
- `obs.emit("extract", "done", ...)` for symmetry with ingest/redact stages.
- `profile.model_copy(update=...)` returns a new validated Profile preserving `detected_role`, `detected_location`, `detected_years_experience`. Pydantic re-runs validators on copy with update, so `detected_years_experience` range (0–70) is still enforced.
- `cast(Profile, raw)` because `LLMClient.complete_json` is typed `-> BaseModel`; mypy --strict needs the narrowing. (Same pattern as `scripts/spike_minimax.py:184`.)
- Per CLAUDE.md "Trust the boundaries you control" — no input validation on `redacted` (internal caller, type-checked at boundary).

### `tests/test_extract.py` (new)

Imports: `pytest`, `pathlib.Path`, `os`, `jobfit.extract`, `jobfit.llm`, `jobfit.schemas`, `jobfit.errors`, `jobfit.verify`, `jobfit.obs`.

Test enumeration in §"Test enumeration" below.

## Prompt body — `src/jobfit/prompts/extract.md`

The verbatim Markdown body the implementer should write to disk. Pattern follows the T05 baseline (`scripts/spike_minimax.py:52-69`) — same hard rule, same uniqueness clause, same anti-fence instruction — adapted from one skill list to the full `Profile` schema, plus the evidence-not-surface clause.

```markdown
You extract a structured profile from a redacted CV.

Return JSON only, matching this schema exactly:

{
  "skills": [{"text": str, "anchor": {"quote": str, "section": str | null}}],
  "experience": [{"text": str, "anchor": {"quote": str, "section": str | null}}],
  "education": [{"text": str, "anchor": {"quote": str, "section": str | null}}],
  "soft_signals": [{"text": str, "anchor": {"quote": str, "section": str | null}}],
  "detected_role": str,
  "detected_location": str | null,
  "detected_years_experience": int
}

## Hard rule on anchors

For every list item, copy the EXACT supporting substring from the CV into `anchor.quote`. Do not paraphrase. The quote must be at least 6 words long. If you cannot find a 6-word literal substring, omit the item.

Pick a quote that appears in the CV only once. If you cannot guarantee uniqueness, copy 8 or more consecutive words.

Preserve case and punctuation exactly. No ellipses. No edits. No reformatting.

If the CV contains a section header like `## Experience` or `## Education`, set `anchor.section` to the header text without the leading `##` (e.g. `"Experience"`). Otherwise set it to `null`.

## Evidence, not surface

Extract on concrete technical and professional evidence: skills used, systems built, scope owned, measurable impact, role progression, education completed.

Do NOT extract or rate on candidate identity, demographic signals, language style, school prestige, or employer prestige as a proxy for ability. The Education list is for the qualification itself, not its perceived ranking. If a school name is the only signal supporting an item, omit the item.

If a redaction marker (`[NAME]`, `[EMAIL]`, `[PHONE]`, `[YEAR]`, `[POSTCODE]`, `[URL]`) appears inside an otherwise-valid 6+ word quote, keep the marker in the quote as-is.

## Detected fields

- `detected_role`: the candidate's most recent or headline role title as it appears on the CV. Non-empty string.
- `detected_location`: a CZ city (Prague, Brno, Ostrava, Plzeň, …) if the CV names one; otherwise the country or `null`.
- `detected_years_experience`: total professional years across roles, as an integer between 0 and 50. Use the CV's stated tenures; do not round up.

## One-shot example

CV excerpt:

```
## Experience
Senior Data Scientist — Rohlik, Prague
March 2021 – present
Built the demand forecasting pipeline serving 14 fulfilment centres on PySpark 3.5 and MLflow, replacing a static rule-based model and lifting forecast accuracy by 22 percentage points over the prior baseline.
```

Valid item:

```json
{
  "text": "Owns demand forecasting at Rohlik, lifted accuracy 22 percentage points",
  "anchor": {
    "quote": "Built the demand forecasting pipeline serving 14 fulfilment centres on PySpark 3.5 and MLflow",
    "section": "Experience"
  }
}
```

The `quote` is 14 consecutive words copied verbatim from the CV. The `text` is the extractor's own summary; the `quote` is the evidence.

## Output format

Return raw JSON only. Do not wrap your response in markdown code fences. Do not include any prose outside the JSON object.
```

Notes on the prompt body:

- The hard-rule paragraph is the exact wording from `tasks/T09_extract.md:17-18` (T09 source-of-truth).
- The uniqueness clause is copied from T05's validated prompt (`scripts/spike_minimax.py:61-62`), now durable because T05 passed 4/4 gates with it.
- The "no markdown fences" closer is also from T05 (`spike_minimax.py:67-68`) — `llm.py:_strip_think` has a fence fallback, but the prompt should still discourage fences so we save tokens and avoid edge cases.
- The one-shot example uses a 14-word literal quote (well above the 8-word safety margin) and shows `section` populated from a `## Experience` header — exercising the `Anchor.section` field that `verify_quote` honours via `_section_text`. The fictional employer/numbers in the example are obviously synthetic; the implementer can keep them as-is.
- Schema is shown as a single JSON literal (not Pydantic). MiniMax structured-output gets confused by Python type annotations; the T05 prompt deliberately uses JSON-literal syntax with `str | null`.

## Test enumeration

Module header:

```python
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest

from jobfit import extract as extract_module
from jobfit.errors import StageFailure
from jobfit.extract import extract_profile, load_prompt
from jobfit.llm import LLMClient
from jobfit.obs import subscribe
from jobfit.schemas import Anchor, Profile, ProfileItem, RedactedCV
from jobfit.verify import verify_quote

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cvs"
```

### 1. `@pytest.mark.fast` — `test_paraphrased_anchor_is_dropped`

Goal: end-to-end verify+drop wiring + verify-event emission.

- Build a `RedactedCV` whose `.text` contains a unique 14-word literal phrase:
  `"Built dashboards in Looker covering four product categories on PostgreSQL 15 across the analytics team"`.
- Monkeypatch `LLMClient.complete_json` (async) to return a synthetic `Profile` with:
  - one `skills` item whose anchor quote IS that 14-word literal (will verify),
  - one `skills` item whose anchor quote is a paraphrase that doesn't substring-match (will be dropped),
  - one `experience` item whose anchor matches (will verify),
  - empty `education` and `soft_signals`,
  - `detected_role="Junior Data Analyst"`, `detected_location="Prague"`, `detected_years_experience=1`.
- Subscribe with `obs.subscribe` to capture events.
- Run `await extract_profile(redacted)`.
- Assertions:
  - result is `Profile` (not `StageFailure`).
  - `len(result.skills) == 1` (paraphrase dropped).
  - `len(result.experience) == 1`.
  - `result.detected_role == "Junior Data Analyst"`.
  - Exactly one `verify` event with `stage == "extract"`, `dropped == 1`, `kept == 2`.

Monkeypatch shape — patch the class method (matches `tests/test_ingest.py:94-111` style):

```python
async def _fake_complete_json(self, *, system, user, schema, model="reasoning", **kwargs):
    return Profile(
        skills=[
            ProfileItem(
                text="dashboards in Looker",
                anchor=Anchor(
                    quote="Built dashboards in Looker covering four product categories on PostgreSQL 15 across the analytics team",
                    section=None,
                ),
            ),
            ProfileItem(
                text="paraphrased item",
                anchor=Anchor(
                    quote="Wrote some Python scripts for various ad-hoc analyses on retail data",
                    section=None,
                ),
            ),
        ],
        experience=[...verifies...],
        education=[],
        soft_signals=[],
        detected_role="Junior Data Analyst",
        detected_location="Prague",
        detected_years_experience=1,
    )

monkeypatch.setattr(LLMClient, "complete_json", _fake_complete_json)
```

`LLMClient.__init__` requires `MINIMAX_API_KEY` to be set; the monkeypatch happens after construction inside `extract_profile`, so we also need `monkeypatch.setenv("MINIMAX_API_KEY", "test-key")` at the top of the test. The fake never makes a real call.

### 2. `@pytest.mark.fast` — `test_stage_failure_returned_when_llm_raises`

Goal: stage_boundary failure path; error event tagged with stage='extract'; PII not leaked to `exc_message`.

Mirrors `tests/test_redact.py:228-277` (`test_failure_path_emits_error_event` + `test_failure_event_does_not_leak_cv_content`). One test that asserts both — keeps the fast-suite test count tight.

- `monkeypatch.setenv("MINIMAX_API_KEY", "test-key")`.
- Patch `LLMClient.complete_json` to raise `RuntimeError("synthetic extract failure")` (fixed message, no PII echo — so any PII appearing in `exc_message` would be the boundary mixing input content).
- Build `RedactedCV` containing PII tokens `pii_email = "jan.novotny@example.com"` and `pii_name = "Jan Novotný"` (these would normally have been redacted by L2; using raw PII here is the simplest way to assert the boundary is content-free).
- Subscribe events, call `await extract_profile(redacted)`.
- Assertions:
  - result is `StageFailure`, `result.stage == "extract"`, `result.user_message` non-empty.
  - Events include one `error` event with `stage == "extract"`, `exc_type == "RuntimeError"`.
  - `pii_email not in error_event["exc_message"]` and `pii_name not in error_event["exc_message"]`.
  - No `verify` event was emitted (because the failure short-circuits before the verify block).

### 3. `@pytest.mark.fast` — `test_load_prompt_reads_extract_md`

Tiny smoke: `load_prompt("extract.md")` returns a non-empty string containing the hard-rule sentence (`"copy the EXACT supporting substring"`). Guards against the prompt file being silently moved or emptied.

Three fast tests total. Two cover the load-bearing branches; the third is a 3-line file-presence check.

### 4. `@pytest.mark.live` — `test_extract_profile_on_fixtures`

Goal: end-to-end behavioural gate against real MiniMax. Gated on `MINIMAX_API_KEY`. Parametrized over every `.txt` fixture in `tests/fixtures/cvs/`.

- Skip-marker on the module (collection-time guard so missing key skips cleanly):

  ```python
  pytestmark = pytest.mark.skipif(
      os.environ.get("MINIMAX_API_KEY") is None,
      reason="live tests require MINIMAX_API_KEY",
  )
  ```

  Applied as a function-level `skipif` on each live test, not module-level, so the fast tests above stay collectable when the key is absent.

- Discover fixtures: `sorted((_FIXTURE_DIR).glob("*.txt"))`. Today that's two files (junior + senior); T06 adds more.

- Per fixture:
  1. Read `fixture_path.read_text(encoding="utf-8")` as the `RedactedCV.text` (skip the L1+L2 stages — this test isolates L3).
  2. `result = await extract_profile(RedactedCV(text=..., audit_log=[]))`.
  3. Skip the fixture (don't fail the run) if `result` is `StageFailure` — record via `pytest.skip(f"L3 failed on {name}: {result.user_message}")`. The task is "L3 returns something usable on the fixtures" — a single MiniMax transport hiccup shouldn't fail CI; persistent failure across multiple fixtures will fail the drop-rate gate below in aggregate when we add a follow-up.
  4. Assert `isinstance(result, Profile)`.
  5. Assert `result.detected_role` is non-empty (`result.detected_role.strip() != ""`).
  6. Assert `0 < result.detected_years_experience < 50` (strict bounds per task spec; `Profile.detected_years_experience` schema is `0..70` so we add the runtime check).
  7. Compute drop-rate arithmetic (see below).

#### Drop-rate gate arithmetic (test 4)

Per task spec: ≥70% of returned profile items survive `verify_quote` across all four lists combined.

```python
total_items = (
    len(result.skills)
    + len(result.experience)
    + len(result.education)
    + len(result.soft_signals)
)
# kept = items already in result; extract_profile has already dropped failures.
# Total returned BEFORE dropping is not exposed; the only thing we can measure
# from outside is "of the items the stage returned, how many still verify against
# the CV text" — which should be 100% by construction. The acceptance gate the
# task names is the model's own pre-drop rate; we have to measure it from the
# raw model output, not the stage return.

# Decision: re-verify the kept items as a smoke (must be 100%, else extract_profile
# is buggy), AND separately count how many made it through. Per the task's
# acceptance criterion phrasing ("≥70% of returned profile items survive"),
# returned == surviving, so the gate that meaningfully bites is on the COUNT
# of survivors relative to a floor.

# Empty-denominator handling: a CV that produces zero items in any single list
# is normal; a CV that produces zero items across ALL FOUR lists indicates the
# stage is broken or the model returned an empty Profile. Treat total_items == 0
# as a hard fail, not a divide-by-zero skip.
assert total_items > 0, f"L3 returned an empty profile on {fixture_path.name}"

# Per-item re-verification — guards against extract_profile leaving unverified
# items in the result by mistake.
verified = 0
for item_list in (result.skills, result.experience, result.education, result.soft_signals):
    for item in item_list:
        if verify_quote(item.anchor.quote, redacted.text, section=item.anchor.section):
            verified += 1

assert verified == total_items, (
    f"{fixture_path.name}: extract_profile returned {total_items - verified} "
    "unverified items — drop_unverified wiring is broken"
)

# The "≥70% survive" gate the task names is measured at the model layer, not the
# stage-return layer. To assert it without exposing the pre-drop count, we
# subscribe to obs events and read the `verify` event's dropped/kept counters:
events: list[dict[str, Any]] = []
with subscribe(events.append):
    result2 = await extract_profile(RedactedCV(text=..., audit_log=[]))
verify_events = [e for e in events if e["event"] == "verify" and e["stage"] == "extract"]
assert len(verify_events) == 1
ve = verify_events[0]
returned_total = ve["kept"] + ve["dropped"]
assert returned_total > 0, f"model returned zero items on {fixture_path.name}"
assert ve["kept"] / returned_total >= 0.70, (
    f"{fixture_path.name}: anchor verification rate "
    f"{ve['kept']}/{returned_total} below 70% gate"
)
```

Per-fixture wall time on MiniMax-M2.7-highspeed is ~16s p50 (T05 outcome). Two fixtures present today → ~32s for the live suite; well under any reasonable CI ceiling. Marked `@pytest.mark.live` so it never runs under `-m fast`.

#### Single combined live test vs two

The task spec lists test 3 (drop-rate + detected fields) and test 4 (skipif gate) as separate items. They share the same call cost and the same fixture loop; one parametrized live test that does both assertions inside the loop is the elegant version. The `skipif` is applied to that single function. So in practice this is **one** live test with parametrize, not two — listed as separate bullets in the task to make the gates explicit.

Final live test count: **1 parametrized test** covering both task bullets (3 and 4). Total tests in the file: **3 fast + 1 live (parametrized)**.

## Risks

### R1: paraphrased anchors slip past `verify_quote`

`verify_quote` requires ≥6 words with uniqueness OR ≥8 words. A model paraphrase that happens to share 6 consecutive content words with the CV (e.g. "Built daily revenue and margin dashboards in Looker" vs "Built revenue and margin dashboards in Looker daily") could pass. Mitigation: T05 already validated this combo (verbatim-rule + uniqueness clause) at 100% anchor rate on the two fixtures. We're not adding a new defense here; the prompt is the same shape. If the live test 4 shows <70% survival rate on any added fixture (T06), iterate the prompt — that's the explicit escape valve the task spec already builds in ("Capture failure if MiniMax struggles — that triggers a prompt revision").

### R2: Profile fields with empty lists → zero denominator

A model that returns `skills=[]`, `experience=[]`, `education=[]`, `soft_signals=[]` (all four empty) gives `total_items == 0` and breaks the percentage math. **Handling**: assert `total_items > 0` as a hard failure in the live test (an empty profile across all four lists means the extractor is unusable). For the `verify` event check, assert `returned_total = kept + dropped > 0` similarly. We do NOT skip the fixture — zero items across four lists on a real CV is a regression, not a tolerated edge case. The Pydantic schema does not enforce non-empty list fields, so this is the right place for the runtime check.

### R3: `Anchor.section` field — populate or skip?

The schema supports `section: str | None`. `verify_quote` honours it via `_section_text` (text-restricted matching). Trade-off:

- Populate: stricter matching (an "Education" claim can't anchor on a quote that lives under "Experience"). But the model has to correctly identify section headers, and `redacted.text` includes `## <header>` annotations from `ingest._annotate_sections` so the model has the signal.
- Skip (always `null`): looser matching against the entire CV. Lower bar for the model, slightly higher hallucination risk.

**Decision**: instruct the model to populate `section` when a header is visible, otherwise `null`. The prompt body's "Hard rule on anchors" paragraph already says this. The cost is ~1 token per item; the win is section-locality on the verifier. Note `Anchor.section` is open-vocabulary (per `schemas.py:46-55`) — author-driven header text, not the closed `Component.name` set. The `_annotate_sections` pass inserts `## Experience`, `## Education`, `## Skills`, etc. against a fixed list (`ingest.py:21-31`), so the model has consistent headers to copy from.

### R4: prompt path resolution

`load_prompt` builds `Path(__file__).parent / "prompts" / name`. In editable installs (`uv sync` package mode = true per pyproject.toml), `__file__` resolves under `src/jobfit/`, and `prompts/` sits next to `extract.py`. The `prompts/` directory exists (currently `.gitkeep`-only). Verified by `ls src/jobfit/prompts/`. No risk; flagging for completeness.

### R5: model_copy validator re-run

`profile.model_copy(update={"skills": [...], ...})` runs validators in Pydantic v2 (`extra="allow"` by default; we're updating existing fields). The `Profile` model has no whole-model validator beyond field constraints, and field constraints (`ge`/`le` on `detected_years_experience`) only run on construction, not copy. Safer alternative: construct a new `Profile(**profile.model_dump() | kept_lists)` — but that's equivalent and more verbose. `model_copy(update=...)` is the idiomatic v2 path. Acceptable.

### R6: live test latency under CI concurrency=1

Two fixtures × ~16s ≈ 32s; T06 may bring it to ~80s with 5 fixtures. Live suite is not on the pre-commit critical path (CLAUDE.md / pyproject markers: `fast` runs in pre-commit, `live` is opt-in). The CI workflow (`.github/workflows/ci.yml`) runs full suite per user directive; concurrency=1 keeps token-plan cost bounded. Acceptable for now; revisit if fixture count grows past ~10.

## Verification recipe

Exact commands the implementer runs before declaring T09 done (mirrors T07/T08 acceptance gates):

```bash
# format + lint
uv run ruff format --check src/jobfit/extract.py tests/test_extract.py
uv run ruff check src/jobfit/extract.py tests/test_extract.py

# strict types over the package
uv run mypy src/jobfit

# pre-commit (covers ruff + mypy + fast pytest)
uv run pre-commit run --all-files

# fast unit suite for this module
uv run pytest -m fast tests/test_extract.py -v

# live suite (requires MINIMAX_API_KEY; not part of fast pre-commit)
uv run pytest -m live tests/test_extract.py -v
```

All must pass before T09 is marked done. Plus:

- Three fast tests green.
- One parametrized live test green over the two current fixtures; if any single fixture hits a transport/auth hiccup, retry once before failing.
- No new entries in `pyproject.toml` `dependencies` or `dependency-groups.dev`.
- `tasks/T09_extract.md` "Outcome" section filled in with: per-fixture drop-rate from the `verify` event counters, total live wall time, anything iterated in the prompt.

## Out of scope (deferred, explicit)

- Multi-call retry beyond `LLMClient.complete_json`'s built-in 1-retry on schema-validation failure. T05 saw 100% JSON survival with the current `max_tokens=4096` + `reasoning_split=True` settings; no extra retry layer needed.
- Per-list verify-event breakdown (one event per field). The task spec explicitly asks for one aggregate event; finer granularity is decoration.
- Section-locality dropped-item diagnostics in the event payload (e.g. `dropped_skills=N`). Deferred — kept/dropped totals are the load-bearing signal.
- Telemetry on `detected_role` / `detected_years_experience` (e.g. counter for empty role). Not in task spec; add only if T15 acceptance tests demand it.
- Sad-path live test for a CV that should produce sparse extraction. Out of scope for L3 — the partial-failure-streaming test (`test_partial_failure_streaming.py`, T18) covers the pipeline-level handling of `StageFailure` from L3.
