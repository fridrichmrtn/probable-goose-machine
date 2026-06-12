# P1 implementation plan — prod-readiness-p1

Branch: `dev/prod-readiness-p1`. Forked from main at c954696.

Implementation order (each is a self-contained commit):
1. P1.3 — Operability (run_id, LLMClient wart, Dockerfile)
2. P1.1 — Honest AI framing (UI banner + seniority_band display)
3. P1.2 — Keep/redo results (download, clear on upload, cancel)
4. P1.5 — Verify semantic gap (claim–quote compatibility check)
5. P1.4 — Eval breadth (synthetic fixtures + slug pinning)

---

## P1.3 — Operability

**Commit: `feat(obs): thread run_id through pipeline; lazy LLMClient key; add Dockerfile`**

### Decision: run_id threading mechanism

Use a `ContextVar[str | None]` named `current_run_id` in `gander/obs.py`, set once at pipeline entry (the same pattern already used for `current_stage`). This adds zero churn to call sites — `emit` reads the contextvar internally and appends `run_id` to every record. The alternative (explicit `run_id` param on every `obs.emit` call) would touch ~20 call sites for zero behavioral gain and conflicts with the no-churn rule on freshly-hardened files.

`current_run_id` is public (exported from `obs`) for the same reason `current_stage` is — tests and pipeline need to set it.

### Decision: LLMClient API key move

`_build_client` currently reads the env var and raises if absent. Move the `OPENROUTER_API_KEY` check out of `_build_client` into an explicit `check_env()` function in `gander/llm.py`. `LLMClient.__init__` still calls `_build_client` (to set up `self._client`), but `_build_client` now passes a placeholder if the key is absent and relies on `check_env()` having been called at boot time. `get_client()` is cached — construction happens once, and `check_env()` is the early-fail gate.

Rationale: tests that stub LLM methods (`monkeypatch.setattr(LLMClient, "complete_json", ...)`) do not call the real API, so they don't need a real key at construction time. Currently 7 test files set `OPENROUTER_API_KEY=test-stub` as boilerplate purely to avoid the constructor raise; these can drop the stub.

Concrete approach:
- Add `def check_env() -> None` to `gander/llm.py`. Raises `RuntimeError("OPENROUTER_API_KEY not set...")` if absent.
- `_build_client` reads the key and uses it (or empty string as placeholder). Does NOT raise.
- `app.py` calls `from gander.llm import check_env; check_env()` before `demo.queue().launch()`. The app fails fast at startup with a clear message.
- `get_client()` does not call `check_env()`; that is the caller's (app.py) responsibility at boot.

Tests that can drop the `OPENROUTER_API_KEY` stub after this change:
- `tests/test_concurrency.py` — `_api_key` autouse fixture
- `tests/test_ingest.py` — 8 `monkeypatch.setenv("OPENROUTER_API_KEY", ...)` calls (those tests patch the method, not the actual HTTP client)

Tests that must KEEP the stub (they test `LLMClient.__init__` and `_build_client` directly):
- `tests/test_llm.py` — `test_openrouter_missing_key_and_removed_providers` — this test specifically asserts the missing-key error; after the refactor it must call `check_env()` instead of testing the constructor. Rewrite the test to assert `check_env()` raises when key absent.
- `tests/test_llm.py` — `test_llm_route_env_override` — constructs `LLMClient()` with a real key stub to verify routing; keep the stub.

### Files to create/modify

**`src/gander/obs.py`**
- Add: `current_run_id: ContextVar[str | None] = ContextVar("current_run_id", default=None)`
- Modify `emit`: append `run_id=current_run_id.get()` to every `record` dict and to the `structlog` call. Keep it last so existing key ordering stays intact.
- Export `current_run_id` (it's module-level already once added).

**`src/gander/llm.py`**
- Add `def check_env() -> None` at module level (before `LLMClient`).
- `_build_client`: read `OPENROUTER_API_KEY` without raising; use `api_key or ""` when constructing `AsyncOpenAI`. The client will fail on first real HTTP call with a clear auth error if the key is absent — acceptable since `check_env()` is expected to have already caught this.
- No other changes to `LLMClient`. Do not touch the retry/timeout logic.

**`src/gander/pipeline.py`**
- Import `uuid` and `obs.current_run_id`.
- At the top of `run()`, generate `run_id = str(uuid.uuid4())` and set `current_run_id.set(run_id)`. Reset via token in a `try/finally` block wrapping the entire async generator body. Include `run_id` in the `pipeline_start` emit.

**`app.py`**
- Add `from gander.llm import check_env` import.
- Call `check_env()` immediately before `demo.queue(...)` at the bottom of the file (the `if __name__ == "__main__"` block is not the right place — the module-level `gr.Blocks` context also needs the env check since HF Spaces imports the module directly). Call it at module level, after all imports, before the `with gr.Blocks() as demo:` block. A module-level `check_env()` call means any import of `app` will validate the key — consistent with HF Space startup behavior.

**`Dockerfile`** (new file, repo root)
```
FROM python:3.11-slim

RUN pip install uv

WORKDIR /app

COPY pyproject.toml uv.lock requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt

COPY src/ src/
COPY prompts/ prompts/
COPY app.py ./

EXPOSE 7860

CMD ["python", "app.py"]
```

Notes:
- Use `requirements.txt` (already maintained by the uv-export pre-commit hook) for the dependency install. This avoids needing `uv sync` inside the image and keeps the image minimal.
- `python:3.11-slim` matches `requires-python = ">=3.11"` and the `tool.mypy.python_version = "3.11"` pin.
- `EXPOSE 7860` — Gradio's default port. HF Spaces also expects 7860.
- `prompts/` must be copied because prompts are loaded from disk at runtime. Verify path by checking `gander/` imports.
- No `OPENROUTER_API_KEY` in the Dockerfile — it must be injected at runtime via env (`-e` flag or HF Space secrets).

### Tests to write

**`tests/test_obs.py`** (existing file — add to it)
- `test_emit_includes_run_id` (`@pytest.mark.fast`): set `current_run_id` to a known uuid via `current_run_id.set(...)`, call `emit`, subscribe and capture the record, assert `record["run_id"] == expected_uuid`.
- `test_emit_run_id_none_when_unset` (`@pytest.mark.fast`): without setting `current_run_id`, subscribe and capture — assert `record["run_id"] is None`.
- `test_run_ids_isolated_across_contextvars` (`@pytest.mark.fast`): use two separate asyncio tasks (or just two synchronous `ContextVar` token pairs) to verify that setting `current_run_id` in one context does not bleed into another (the existing contextvar isolation test pattern in `test_obs.py`; check if one already exists, extend rather than duplicate).

**`tests/test_llm.py`** (existing file)
- Rewrite `test_openrouter_missing_key_and_removed_providers`: after the refactor, `LLMClient()` with no key should NOT raise (construction is cheap). Call `check_env()` instead — assert it raises `RuntimeError` matching "OPENROUTER_API_KEY".
- Add `test_check_env_passes_when_key_set` (`@pytest.mark.fast`): monkeypatch key to a non-empty string, assert `check_env()` returns None without raising.
- `test_get_client_returns_same_instance` and `test_get_client_cache_clear_produces_new_instance` in `test_concurrency.py` — these can drop the `monkeypatch.setenv("OPENROUTER_API_KEY", "test-stub")` autouse fixture after the refactor (remove the fixture entirely from `test_concurrency.py`).

**`tests/test_pipeline_fast.py`** (existing file — add or extend)
- `test_pipeline_run_id_in_obs_events` (`@pytest.mark.fast`): mock all pipeline stages to return stubs, subscribe to obs, run the pipeline, assert every captured record has a `run_id` key and all records share the same non-None uuid string.

### Risks / unknowns
- Verify that `prompts/` is loaded via a path relative to `src/gander/` (not the working directory) — if prompts are loaded as `Path(__file__).parent.parent / "prompts"`, the Dockerfile COPY must adjust. Check the actual `prompts/` load path in `gander/*.py` before finalizing the Dockerfile.
- The `_build_client` silent-key change means an LLM call made without `check_env()` will fail at the first HTTP request (auth error from OpenRouter) rather than at construction. Confirm that every `StageFailure` path catches generic `Exception` and surfaces a user-visible message — it does (stage_boundary), so this is safe, but note it.
- `asyncio.ContextVar` tokens set in an async generator body: the `try/finally` pattern works in async generators for cleanup. The `current_run_id` contextvar token must be reset in `finally` even when the generator is garbage-collected mid-run (e.g., if the Gradio handler cancels). Test that the reset happens via a simple unit test.

---

## P1.1 — Honest AI framing

**Commit: `feat(ui): honest-AI banner + seniority_band in score heading`**

### Decision: banner copy source

Copy adapted directly from PRD §4.7, not invented. The key statements:
- CV evaluation is classified as high-risk AI under the EU AI Act and is well documented to encode demographic bias.
- Structural mitigation: PII (name, photo, contact details, age-implying dates) is redacted before scoring.
- Acknowledged limitation: some bias-encoding signals (school names, language patterns, employer prestige) cannot be fully neutralized. The system is not validated for fairness across protected groups.
- Outputs are framed as candidate hypotheses for the reader to validate, not as authoritative judgments.

Render this as a collapsible `<details>` element (consistent with the existing "How is this scored?" footer) placed immediately ABOVE the score section in the rendered body. Title: "About this report". Do not place it in `app.py` — it belongs in `report.py` where the other body sections live, so it renders only when a real report is present (not during the loading spinner).

### Decision: seniority_band display

`score.total` is already in the `## Score: {score.total}/100` heading in `_score_section`. The `seniority_band` lives on `report.profile` (a `Profile`), not on `score`. The render function `render_body` has access to the full `report` object; `_score_section` only receives `score`. Two options:
1. Pass `profile` to `_score_section` and render the band there.
2. Compose the band into the heading in `render_body` where both are available.

Choose option 2: simpler, no signature change. In `render_body`, after building the score section string, patch the `## Score: {n}/100` heading to `## Score: {n}/100 · {band}` using a string replace (or pass the band as a parameter to a thin wrapper). Actually cleanest: modify `_score_section` signature to accept `seniority_band: str | None = None` and include it in the heading. Call site in `render_body` passes `report.profile.seniority_band` when profile is a `Profile`.

### Files to create/modify

**`src/gander/report.py`**
- Add `_honest_ai_banner() -> str` function. Returns a `<details>` HTML block with the §4.7-sourced copy. Called once from `render_body`, inserted before `_score_section`.
- Modify `_score_section(score, seniority_band: str | None = None)`: add `· {seniority_band}` to the `## Score:` heading when `seniority_band` is not None.
- Modify `render_body`: pass `report.profile.seniority_band` to `_score_section`; prepend `_honest_ai_banner()` to the sections list.

### Tests to write

**`tests/test_render.py`** (existing file — add)
- `test_honest_ai_banner_present_in_body` (`@pytest.mark.fast`): build a minimal `Report` with a real `Profile` and stub other fields, call `render_body`, assert the output contains "About this report" and "bias" (or "EU AI Act" — pick a stable phrase from the actual copy).
- `test_seniority_band_in_score_heading` (`@pytest.mark.fast`): call `_score_section` with a stub `Score` and `seniority_band="senior"`, assert "senior" appears in the returned string near "Score:".
- `test_seniority_band_none_omitted` (`@pytest.mark.fast`): call `_score_section` with `seniority_band=None`, assert no `·` separator appears in the heading (i.e., no "· None" text).
- `test_banner_absent_when_profile_is_failure` (`@pytest.mark.fast`): build a `Report` with `profile=StageFailure(...)`, call `render_body`, assert "About this report" does NOT appear (short-circuit path).

---

## P1.2 — Keep/redo results

**Commit: `feat(ui): markdown download, clear on upload, cancel button`**

### Decision: download format

Use `gr.DownloadButton` (Gradio ≥4.x). The button is hidden initially (`visible=False`) and becomes visible once the report completes. The markdown string is the same content already rendered in `report_md`. Generate the download content from `render_body(report)` — strip HTML tags for a clean markdown file, or pass through as-is (Gradio doesn't care, and `.md` renderers handle inline HTML). Use as-is for simplicity.

Alternative `gr.File` requires writing to a temp file; `gr.DownloadButton` accepts `value=string` directly in newer Gradio versions — verify API before implementing. If `DownloadButton` requires a file path, fall back to writing to a `tempfile.NamedTemporaryFile` and passing the path.

### Decision: clear stale report on new upload

Currently `file_in.change` only enables/disables `run_btn`. Add `report_md`, `tracker_html`, and the new `download_btn` as additional outputs of the `file_in.change` handler. When a new file is selected (or cleared), reset all three to empty/hidden state. This is a one-line lambda change: `lambda f: (gr.Button(...), gr.Markdown("", visible=False), gr.HTML("", visible=False), gr.DownloadButton(visible=False))`.

### Decision: cancel button

Gradio `Button.click` supports `cancels=[run_btn_click_event]` to abort an in-flight generator. Add a `cancel_btn = gr.Button("Cancel", visible=False)` that appears while the pipeline is running and is hidden otherwise. Use the return value of `run_btn.click(...)` as the event to cancel. Toggle visibility via the `handle` generator: yield `cancel_btn` visible at the start, hidden at the end. Add `cancel_btn` to the `outputs` list of `run_btn.click`.

### Files to create/modify

**`app.py`**
- Add `download_btn = gr.DownloadButton("Download report", visible=False)` inside the `gr.Column`.
- Add `cancel_btn = gr.Button("Cancel", visible=False)` inside the `gr.Column`, placed after `run_btn`.
- Modify `file_in.change`: add `download_btn`, `tracker_html`, `report_md`, `cancel_btn` to outputs; reset them all on change.
- Modify `handle` return type and yield tuples to include `download_btn` and `cancel_btn` state.
- `handle` first yield: show `cancel_btn`, hide `download_btn`.
- `handle` final yield: hide `cancel_btn`, show `download_btn` with the report content.
- Use `run_btn.click(...) as run_event` assignment and `cancel_btn.click(fn=None, cancels=[run_event])`.

Note: the `handle` generator already yields 2-tuples `(tracker_html_update, report_md_update)`. Extending to 4-tuple `(tracker, report, cancel_btn, download_btn)` requires updating every `yield` in `handle`. Count the yields before implementing — there are ~5.

### Tests to write

Gradio UI handlers are hard to test without a running server. Write unit-level tests for the behavior that matters:

**`tests/test_pipeline_fast.py`** or a new `tests/test_app_handlers.py`
- `test_handle_clears_on_none_file` (`@pytest.mark.fast`): call the `handle` coroutine with `file_path=None` and collect the first yield; assert `cancel_btn` is not visible (or absent from the update), and `tracker_html` update contains a failure state. (This tests the "Select a CV first" path.)
- This is a thin test — the main risk is the tuple arity mismatch causing a Gradio runtime error. Verify by running the app manually (the `verify` skill should be used post-implementation, not planned as an automated test here).

---

## P1.5 — Verify semantic gap

**Commit: `feat(verify): claim–quote compatibility check via token overlap`**

### Decision: lexical token overlap gate (not LLM)

Add a `claim_supports_quote(claim: str, quote: str) -> bool` function in `gander/verify.py`. This is separate from `verify_quote` (which checks existence). The function answers: "does `quote` provide evidence for `claim`?" using Jaccard token overlap between the normalized claim and the normalized quote.

Threshold: Jaccard ≥ 0.15 (i.e., at least 15% of unique tokens shared). This is deliberately loose because claim and quote legitimately differ in phrasing. The gate is for egregious mismatches ("Led a team" vs. "Joined a team") not paraphrases.

Stopword filtering: strip common English stop words (`a`, `an`, `the`, `in`, `of`, `to`, `with`, `and`, `or`, `for`, `as`, `at`, `by`, `is`, `was`, `on`, `that`) before computing overlap. Without this, high-frequency words dominate and produce false positives.

**Why not LLM?** The LLM approach requires a call on every (claim, quote) pair, which multiplies latency by the number of anchors per CV (typically 10–20), runs into the separation-of-generation-from-grading complexity, and adds $0.00X per run. The substring check already runs in microseconds; a lexical gate runs in microseconds. Save the LLM slot for cases where lexical overlap provably fails (future P2 item if the false-rejection rate turns out to be non-trivial). The `cheap` LLM slot option is noted in the plan but deferred: the current verify_quote + lexical overlap combination addresses the stated problem without it.

**Caller integration**: `drop_unverified` in `verify.py` already filters by `verify_quote`. Extend it: after the substring check passes, apply `claim_supports_quote(item.text, anchor.quote)` and drop items where overlap is below threshold. The `item.text` is the claim text (the justification or plan item text). Emit an `obs.emit` event (`verify_claim_mismatch`) with `stage`, `claim_word_count`, `quote_word_count`, `jaccard_score` (no CV text) when dropping.

**Caller**: `drop_unverified` is called from `score.py` and `growth.py` (check grep results). The change is backward-compatible since `drop_unverified` already returns `(kept, dropped_count)`.

### Files to create/modify

**`src/gander/verify.py`**
- Add `_STOPWORDS: frozenset[str]` constant.
- Add `_content_tokens(text: str) -> frozenset[str]`: normalize → split → filter stopwords → return frozenset of remaining tokens.
- Add `claim_supports_quote(claim: str, quote: str) -> bool`: compute Jaccard of `_content_tokens(claim)` and `_content_tokens(quote)`; return `True` if Jaccard ≥ `_COMPAT_THRESHOLD` (0.15). If either token set is empty after stopword removal, return `True` (avoid false-rejections for very short claims).
- Modify `drop_unverified`: after `verify_quote` passes, call `claim_supports_quote(item.text, anchor.quote)`. If it returns `False`, emit `verify_claim_mismatch` and drop the item (add to dropped count). `item.text` is read from the item using `getattr(item, "text", None)` — items without a `text` attribute skip the compatibility check (backward compat).

The `text` attribute: check that `ProfileItem`, `Component`, and `GrowthAction` all have a `text` or equivalent string field that represents the claim. `Component.justification` is the claim text; `ProfileItem.text` is the item text; `GrowthAction.what` is the action description. The attribute name differs across item types. `drop_unverified` is generic via `anchor_attr`. Add `claim_attr: str = "text"` parameter to `drop_unverified` so callers specify which field is the claim. Default `"text"` preserves backward compat for existing callers; callers for `Component` pass `claim_attr="justification"`.

Check grep for all `drop_unverified` call sites and update them.

### Tests to write

**`tests/test_verify.py`** (existing file — add)

- `test_claim_supports_quote_match` (`@pytest.mark.fast`): claim="Led the migration from monolith to microservices", quote="Led migration from monolith to microservices across three quarters" → True.
- `test_claim_supports_quote_mismatch` (`@pytest.mark.fast`): claim="Led a team of engineers", quote="Joined a team of engineers" → False. This is the canonical mismatched case.
- `test_claim_supports_quote_mismatch_direction_swap` (`@pytest.mark.fast`): claim="Increased revenue by 40%", quote="Built recommendation system that reduced churn by 18% over six months" → False. The numbers and nouns share no overlap after stopwords.
- `test_claim_supports_quote_empty_stopwords_only` (`@pytest.mark.fast`): claim="in the at by", quote="to and or" → True (both token sets empty after stopword removal; function returns True to avoid false-rejections).
- `test_drop_unverified_rejects_mismatched_claim` (`@pytest.mark.fast`): build an item whose substring quote verifies (exists in source) but whose claim does not overlap with the quote. Assert it is dropped. This is the regression test for the current substring-passes-but-semantic-gap behavior.
- `test_drop_unverified_keeps_matching_claim` (`@pytest.mark.fast`): build an item where both substring and claim–quote overlap pass. Assert it is kept.

**`tests/test_obs.py`** (existing or new)
- `test_verify_claim_mismatch_event_emitted` (`@pytest.mark.fast`): subscribe to obs, call `drop_unverified` with a mismatched item, assert a `verify_claim_mismatch` record was emitted with `jaccard_score` key and no CV text.

### Risks / unknowns
- The Jaccard threshold of 0.15 is heuristic. Run the existing acceptance fixtures through the extended `drop_unverified` after implementation to measure false-rejection rate before declaring done. If the threshold causes regressions (legitimate claims dropped), raise it to 0.10 or add a domain-noun exception list. Do not ship if the acceptance suite has new failures attributable to this gate.
- `claim_attr` parameter: verify grep results for all `drop_unverified` call sites (score.py, growth.py, possibly extract.py) and confirm the correct attribute name for each. If attribute names differ significantly, consider making `claim_attr` optional and falling back to `None` when absent rather than erroring.
- `GrowthAction.what` vs `GrowthAction.text`: check the schema. If `GrowthAction` has no `text` field, the default `claim_attr="text"` returns `None` and skips the compat check. That is acceptable as a safe default but should be noted.

---

## P1.4 — Eval breadth

**Commit: `feat(tests): synthetic degradation fixtures; document slug pinning`**

### Decision: synthetic fixtures (not real CVs)

All fixtures must be clearly synthetic — clearly fake names, invented employers, no real PII. Each fixture is a plain `.txt` file in `tests/fixtures/cvs/` (matching the existing `.txt` fixture pattern — note that `.pdf`/`.docx` binaries are LFS-tracked; `.txt` fixtures avoid LFS friction for synthetic content). Check whether the existing pipeline accepts `.txt` input or only `.pdf`/`.docx`. If `.txt` is not an accepted input type for `extract_text`, the fixtures must be in a format the pipeline can ingest.

Looking at `ingest.py` and `pipeline.py`: `extract_text(file_bytes, filename)` branches on filename suffix. If `.txt` is not handled, these fixtures must be `.docx` (simplest to generate programmatically using `python-docx` in a build script). For the test layer, the fixtures can be used as raw text strings passed directly to the relevant sub-stages (redact → extract → score) without going through ingest. This is the correct approach for fast-marked tests: test the degradation behavior at the stage level, not end-to-end.

Three synthetic scenarios:
1. **Non-tech role**: "Marketing coordinator, 3 years in event planning, MS Office, team coordination." Expect: `seniority_band` in {junior, mid}, score < 60 (since the skill/tech signal is weak). Graceful degradation: salary search may return no usable data → Low confidence; growth plan still generates; no crash.
2. **Career changer**: "5 years as a nurse, now transitioning to data analysis. Completed online course in Python and SQL." Expect: `seniority_band` = junior/mid, role normalization likely falls to "unrecognized" or a generic band. Graceful degradation: confidence floor from `default` market provenance; no crash.
3. **Non-CZ market**: "Senior backend engineer, based in Berlin, Germany. 8 years experience in Java, Kubernetes." Expect: market resolves to DE; salary in EUR; growth plan references German market. Graceful degradation: if DDG returns no useful data, salary block shows `Insufficient market data` not a crash.

### Decision: model slug pinning

OpenRouter's Gemini slugs (`google/gemini-2.5-flash`, `google/gemini-2.5-flash-lite`) do not currently expose dated variants in the OpenRouter model catalog format. OpenRouter uses provider-side versioning and doesn't publish `google/gemini-2.5-flash:2025-01-01`-style slugs for Gemini models. Therefore: keep the floating slugs with an inline comment in `llm.py` explaining this. Do NOT guess a date suffix.

Add this comment directly above `_OPENROUTER_ROUTES` in `llm.py`:
```python
# Gemini slugs: OpenRouter does not expose dated variants for Gemini models
# (as of 2026-06-12). Floating slugs are used; re-verify on quarterly infra
# reviews or when behavior regressions appear.
```

This satisfies the "document that and keep the floating slug with an inline note" requirement.

### Files to create/modify

**`tests/fixtures/cvs/14_nontech_marketing_coordinator_synthetic.txt`** (new)
Clearly synthetic CV text for a marketing coordinator. No real names or companies.

**`tests/fixtures/cvs/15_career_changer_nurse_to_data_synthetic.txt`** (new)
Clearly synthetic CV text for a nurse transitioning to data analysis.

**`tests/fixtures/cvs/16_nonCZ_berlin_backend_engineer_synthetic.txt`** (new)
Clearly synthetic CV text for a Berlin-based backend engineer.

**`tests/test_eval_corpus.py`** (existing file — check if the new fixtures auto-load)
The eval corpus runner picks up all files in `tests/fixtures/cvs/*.{pdf,docx}`. Since the new fixtures are `.txt`, they won't be picked up automatically (the corpus runner filters on `SUPPORTED_SUFFIXES = (".pdf", ".docx")`). The fast-marked tests for these fixtures operate at the stage level.

**`tests/test_degradation_synthetic.py`** (new file)
Three test functions, each using a `@pytest.mark.fast` marker. They bypass ingest (no file parsing) and feed the synthetic CV text directly into the pipeline sub-stages.

- `test_nontech_role_graceful_degradation` (`@pytest.mark.fast`):
  - Pass synthetic marketing-coordinator text through `redact()` → `extract_profile(redacted)` (mocked to return a stub `Profile` with `seniority_band="junior"`, `detected_location=None`, realistic skill set).
  - Assert that a `StageFailure` from salary (mocked to return `StageFailure`) does NOT prevent the score from rendering.
  - Assert the report `confidence.tier == "Low"` when salary fails.
  - This is a unit test of the cascade logic, not an integration test.

- `test_career_changer_confidence_floor` (`@pytest.mark.fast`):
  - Construct a `Profile` with `role_normalization_source="unrecognized"`, `detected_location=None`.
  - Verify that `resolve_market(profile).provenance == "default"` (existing `test_market.py` may cover this; add here if not).
  - Verify that confidence capped at Medium for default-provenance market (existing `confidence.py` logic).

- `test_non_cz_market_resolves_de` (`@pytest.mark.fast`):
  - Construct a `Profile` with `detected_location="Berlin, Germany"` (or however the schema stores it).
  - Call `resolve_market(profile)` and assert `market.currency == "EUR"` and `market.country_name` contains "Germany" (existing market resolution logic). This fixture verifies the lookup works for a non-CZ market — it's testing existing behavior against a new profile, not new code. Note: `test_market.py` may already cover DE. If so, skip this test and document why.

**`src/gander/llm.py`**
- Add the Gemini slug pinning comment (see above). No code change.

### Tests to write

Summary already above. Key assertions are **degradation** (salary fails → confidence is Low, report still renders with failure callout in the salary block) rather than scoring accuracy. Do not assert specific scores for synthetic CVs.

### Risks / unknowns
- If the pipeline's `extract_profile` is always async and depends on LLM, fast-marked tests must mock the LLM calls entirely. Verify that `extract_profile` can be called with a mock in the same pattern used by `test_extract.py`.
- The `test_career_changer_confidence_floor` test may be largely redundant with existing `test_confidence_unit.py` tests. Run existing tests first and only add if the scenario is not covered.
- `.txt` fixtures: confirm whether `extract_text` in `ingest.py` handles `.txt` suffix. If it does, the corpus runner could be extended to include them. If not, the note above stands (fast tests bypass ingest).

---

## Commit sequence

```
1. feat(obs): thread run_id through pipeline; lazy LLMClient key; add Dockerfile
2. feat(ui): honest-AI banner + seniority_band in score heading
3. feat(ui): markdown download, clear on upload, cancel button
4. feat(verify): claim–quote compatibility check via token overlap
5. feat(tests): synthetic degradation fixtures; document slug pinning
```

---

## Risks / unknowns (top 3)

1. **Jaccard threshold causes acceptance regressions (P1.5).** The 0.15 Jaccard floor is calibrated on intuition, not measured data. If legitimate claim–quote pairs in the existing 13 CV fixtures fall below this threshold (e.g., paraphrased claims), the acceptance suite will gain new failures. The implementer must run `uv run pytest -m fast` AND spot-check `drop_unverified` output against the existing fixtures before committing. The threshold is easy to adjust, but it must be measured before shipping.

2. **LLMClient silent-key change breaks a test that asserts constructor raises (P1.3).** `test_openrouter_missing_key_and_removed_providers` currently asserts `LLMClient()` raises when the key is absent. After the refactor, this assertion is wrong — construction no longer raises. The test must be rewritten to assert `check_env()` raises instead. If the implementer ships without updating the test, it will silently test nothing meaningful. This is a correctness risk, not a runtime risk.

3. **Gradio `DownloadButton` API compatibility (P1.2).** The `gr.DownloadButton` accepting a `value=string` directly (rather than a file path) depends on the Gradio version pinned in `requirements.txt`. If the installed Gradio version requires a file path, the implementer must write to a `tempfile` instead. Check Gradio release notes for `DownloadButton` before implementing — do not assume the string API is available.
