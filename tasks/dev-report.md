# /dev Report — T45 vision parallelization + per-stage `max_tokens` caps

**Task:** Implement improvements A (parallelize vision page loop) and B (cap `max_tokens` per stage) from `/home/mf/.claude/plans/as-it-is-after-nested-shell.md`. Also create a pickup-able `tasks/T45_*.md` and mark it in `tasks/todo.md`.
**Branch:** `dev/parallelize-vision-cap-max-tokens`
**Worktree:** `/home/mf/GitHub/probable-goose-machine/.worktrees/parallelize-vision-cap-max-tokens`
**Stack:** py, precommit, gradio

## Files touched

T45 implementation (commit `0e4c4c3`):

- `src/gander/ingest.py` — vision page loop wrapped with `asyncio.gather` + `asyncio.Semaphore(4)`; per-page `max_tokens=1500`; emits `ingest_vlm_page_done` per page.
- `src/gander/llm.py` — added `max_tokens: int | None = None` to `complete_json`, `complete_text`, `complete_vision_text`, and the three underlying OpenRouter chat helpers. Conditional forwarding when not None preserves baseline tests.
- `src/gander/extract.py:241` — `max_tokens=3000` on extract slot.
- `src/gander/score.py:112` — `max_tokens=1024` on reasoning slot.
- `src/gander/salary.py:296` — `max_tokens=768` on reasoning slot.
- `src/gander/confidence.py:150,214,236` — step A `max_tokens=128`, step B initial + regenerate `max_tokens=256`.
- `src/gander/growth.py:229` — `max_tokens=1536` on reasoning slot.
- `tests/test_ingest.py` — new `test_pdf_vlm_parallel_preserves_page_order_and_bounds_concurrency`.
- `tests/test_llm.py` — three forwarding tests for the new parameter (one per entry point).
- `tests/test_{extract,score,salary,growth_unit,confidence_unit}.py` — captured-kwargs assertions for the per-stage cap.
- `tasks/T45_vision_parallel_and_token_caps.md` — new pickup-able task spec.
- `tasks/todo.md` — T45 line under "Post-merge follow-ups".
- `tasks/dev-plan.md` — overwritten with T45 plan (flagged in residue: use `--prefix T45` next time).

Heal pass (commit `3904d80`):

- `src/gander/llm.py` — added `_emit_truncation` helper; wired into `_chat_json`, `_chat_text`, `_chat_vision_text` to emit a structured `llm_truncated` obs event when `finish_reason == "length"` and `max_tokens` was set by the caller. Does not raise — visibility-only, per the plan's §B Risk contract.
- `tests/test_llm.py` — added `test_chat_json_emits_llm_truncated_when_finish_reason_length`; asserts the event carries `stage`, `model`, `max_tokens`, `prompt_tokens`, `completion_tokens`.

## Checks

| Command | Initial (after T45) | After heal |
|---|---|---|
| `uv run pre-commit run --all-files` | pass | pass |
| `uv run pytest -m fast --strict-markers -q` | pass (384) | pass (385, +1 regression test) |
| `uv run mypy src` | pass | pass |

No failing checks at either stage. Heal was triggered by `must_fix` non-empty, not by red checks.

## Review findings

### Must-fix (resolved this run)

- `[ai-ml-engineer] src/gander/llm.py` — `finish_reason == "length"` was captured but never surfaced; truncated responses flowed downstream silently. **Resolved**: added `_emit_truncation` helper that fires an `llm_truncated` obs event (with stage, model, cap, and token usage) on every chat call where the cap was set and the provider returned `length`.
- `[qa-engineer] tests/` — no regression test for the cap-truncation path. **Resolved**: added `test_chat_json_emits_llm_truncated_when_finish_reason_length` in the fast suite; stubs OpenRouter chat to return `finish_reason="length"` + still-parseable JSON (the silent-success failure mode) and asserts the new event fires.
- `[qa-engineer] obs` — no per-stage cap-truncation counter (PRD §4.8). **Resolved**: the `llm_truncated` event carries `stage` (from `obs.current_stage`) so existing event aggregation groups by stage without code changes.

### Must-fix (remaining — exhaustion)

None.

### Should-fix (deferred → `tasks/backlog.md`)

15 items captured under `## parallelize-vision-cap-max-tokens — 2026-05-15T11:00Z`. Convergent themes:

- `[ai-ml + ux + hiring + qa]` MiniMax silently drops `max_tokens` — foot-gun when the provider toggle flips back; MiniMax currently inactive.
- `[ai-ml + hiring]` three repeated OpenRouter kwargs blocks — extract a `_build_openrouter_kwargs` helper.
- `[qa + hiring]` `peak["max"] >= 2` concurrency assertion is timing-coupled; tighten with `asyncio.Event` gating.
- `[qa]` no 2-page failure-isolation test for `asyncio.gather(..., return_exceptions=False)` partial-failure semantics.
- `[hiring]` five stage-cap literals lack a central registry (`STAGE_TOKEN_CAPS`).
- `[hiring + ai-ml]` `_STEP_B_MAX_TOKENS` literal `256` repeated across initial + regenerate paths.
- `[hiring]` `assert captured["max_tokens"] == N` per-stage cap tests are tautological.
- `[po + hiring]` T45 marked `Done` without `openrouter-live` run.

### Nits

5 items (semaphore magic literal, `dev-plan.md` overwrite without `--prefix`, `png_to_index` round-trip dict, three near-identical `test_llm.py` forwarding tests not parametrized, single-letter loop variable `i`). Listed in the backlog block.

## Hiring grade

**on-bar** — consensus across all five Agent reviewers. One-line rationale: implementation is correct, scoped, and ships with the right test for the parallelism property — but ships without a regression test for the cap-truncation failure mode that §B itself introduces. The heal closed that gap; remaining residue is convention/refactor, not bar-changing. Codex's independent verdict on the diff was `on-bar` as well; convergence between provider families is a useful corroboration that the design reads cleanly.

## Verification posture

Verified:

- Pre-commit, fast pytest (385 tests), mypy strict all green at HEAD `3904d80`.
- `asyncio.gather` preserves page order (`tests/test_ingest.py::test_pdf_vlm_parallel_preserves_page_order_and_bounds_concurrency`).
- `max_tokens` forwarding into the OpenRouter `chat.completions.create` call (three tests in `test_llm.py`).
- New `llm_truncated` obs event fires with expected fields when the cap clips a response (`test_chat_json_emits_llm_truncated_when_finish_reason_length`).

Not verified (deferred):

- **End-to-end measurement** of the predicted wallclock win on Profile.pdf (~61 s → ~53 s). Plan §"Verification path" step 2 calls for re-running `scripts/measure_pipeline.py` post-implementation. Deferred to next manual run with `OPENROUTER_API_KEY` set.
- **`openrouter-live` CI workflow** on this branch — the binding live gate runs after merge.
- **MiniMax path** is unchanged by this work and is currently inactive (provider toggle is on OpenRouter); no live MiniMax verification attempted.

## Cleanup

When you're done with this work:

```
git worktree remove .worktrees/parallelize-vision-cap-max-tokens
git branch -D dev/parallelize-vision-cap-max-tokens
```

Or, to land it:

```
git checkout main
git merge --no-ff dev/parallelize-vision-cap-max-tokens
```

Note: parent branch is `t42-pipeline-wallclock-wins`, which is ahead of `main`. For a clean PR diff against `main`, rebase or merge `t42-pipeline-wallclock-wins` first (or open the PR against `t42-pipeline-wallclock-wins` directly).
