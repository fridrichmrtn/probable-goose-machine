# /dev Report — T05 MiniMax capability spike

**Task:** Implement T05 — MiniMax capability spike. Deliverable `scripts/spike_minimax.py` per plan; reuse `jobfit.llm.LLMClient`, `jobfit.verify.verify_quote`, `jobfit.obs.subscribe`, `jobfit.errors.stage_boundary`; read junior + senior CV `.txt` fixtures directly. Sequential calls, inline minimal Pydantic schemas, ≥6-word anchor instruction, fail-loud on gate failure (no auto-swap to Anthropic), preflight key check exits with code 2.
**Branch:** `dev/implement-t05-minimax-capability-spike`
**Worktree:** `/home/mf/GitHub/probable-goose-machine/.worktrees/implement-t05-minimax-capability-spike`
**Stack:** py, gradio, precommit
**Status:** clean (heal addressed all must-fix items)

> ⚠ The spike is a **manual capability gate**. The four gates (anchor-rate, score-spread, JSON-survival, p50 latency) have **not** been measured against live MiniMax in this run — that requires `MINIMAX_API_KEY` in the operator's environment. The script is shipped, formatted, typed, and tested; the operator runs it once to flip T05 `done` (or to record a gate failure and trigger the documented Anthropic swap path).

## Files touched

- `scripts/spike_minimax.py` — new, 267 → 264 LOC after heal. Sequential 4-call spike, exit 0 on all-pass, exit 1 on gate failure, exit 2 on missing key.
- `src/jobfit/py.typed` — empty marker file added so `mypy --strict scripts/spike_minimax.py` resolves the local `jobfit` package (PEP 561).
- `tasks/T05_dev-plan.md` — implementation checklist written by the planner agent in Phase 1; not committed (per `.gitignore` of plan artifacts is not in effect — left untracked deliberately, the orchestrator's `T05_dev-report.md` is the durable record).
- `tasks/backlog.md` — appended a `## implement-t05-minimax-capability-spike` block with 7 nits (no should-fix items remained after heal). Auto-unions on merge via `merge=union` driver in `.gitattributes`.

## Checks

| Command | Initial (Phase 2) | After heal (Phase 4) |
|---|---|---|
| `uv run ruff format --check scripts/spike_minimax.py` | pass | pass |
| `uv run ruff check scripts/spike_minimax.py` | pass | pass |
| `uv run mypy scripts/spike_minimax.py` | pass | pass |
| `uv run pre-commit run --all-files` | pass | pass |
| `uv run pytest -q -m fast` | pass (32 passed) | pass (32 passed) |
| `unset MINIMAX_API_KEY; uv run python scripts/spike_minimax.py; echo $?` | exit 2 | exit 2 |

The live spike run (with `MINIMAX_API_KEY` set, returns 0 on all-gates-pass) is **deliberately deferred to the operator** — it is the manual gate and re-running it inside `/dev` would burn live MiniMax tokens with no automation benefit.

## Review findings

### Must-fix (resolved this run)

- **[ai-ml-engineer + product-owner + hiring-manager + codex consensus]** `scripts/spike_minimax.py:198-215` — JSON-mode survival gate was decorative. Original code counted `llm_call` events per call and treated `count == 1` as "first-try success", but `LLMClient.complete_json` (`src/jobfit/llm.py:131-142`) emits exactly **one** event per logical call from a `finally` block outside the retry loop, regardless of internal retries. The gate was vacuously always 1.0. **Fixed:** switched to direct exception accounting — `max_retries=0` on each call, wrap in `try/except (ValidationError, JSONDecodeError)`, count caught exceptions as JSON-mode failures. Anchor-rate / spread / latency gates skip `None` results gracefully.
- **[ai-ml-engineer]** `scripts/spike_minimax.py` extract system prompt — instructed "≥6 consecutive words" but didn't warn about `verify_quote`'s uniqueness floor (`src/jobfit/verify.py:31`: 6-7 word quotes must be unique; ≥8 word quotes may repeat). A 6-word non-unique quote silently fails verification. **Fixed:** appended to extract prompt — *"Pick a quote that appears in the CV only once. If you cannot guarantee uniqueness, copy 8 or more consecutive words."*

### Should-fix (resolved this run, bundled in heal commit)

- **[hiring-manager]** Replaced 8 lines of `assert isinstance(parsed, SpikeExtract)` ceremony with `cast(SpikeExtract, parsed)` (and analogous for `SpikeScore`). Adapted to handle the new `None`-on-failure branch from must-fix #1.
- **[product-owner]** Switched `>=`/`<=` ASCII glyphs to Unicode `≥`/`≤` in gate output to match the spec example in `tasks/T05_spike.md`.
- **[product-owner + hiring-manager]** Added the numeric p50 in seconds to the gate output (e.g. `p50 ≤8s? YES (5.4s)`); previously only YES/NO was printed.
- **[ai-ml-engineer]** Renamed per-CV "latency p50" to "latency avg" — "p50 of n=2" was misleading. Global gate stays `p50` (n=4).
- **[ai-ml-engineer]** Rewrote score system prompt to use absolute seniority scale (0-30 entry, 31-60 mid, 61-85 senior, 86-100 staff/principal) instead of "vs mid-level role" anchoring, which encouraged a degenerate `50` for both junior and senior CVs and would tank the spread gate.

### Must-fix (remaining — exhaustion)

None. Single heal iteration resolved all 2 must-fix items.

### Should-fix (deferred to backlog)

None. All 5 should-fix items were bundled into the heal commit.

### Nits (deferred to backlog)

7 items — see `tasks/backlog.md`. Highlights: pin fixture paths to `Path(__file__).resolve()` instead of cwd; replace magic `4` with `len(cvs) * 2`; consider `.env` auto-loading; add few-shot examples to extract/score prompts; promote `_stage` helper into `obs.py` if T07/T08 reuse it; reduce 6-word constant duplication between prompt and `verify.py`; mention the new `src/jobfit/py.typed` marker in the upstream PR description.

## Hiring grade

**below-bar → on-bar after heal.** Initial review burst was unanimous below-bar (3 review agents + codex) on the JSON-survival gate bug — the central reliability claim of the spike was decorative. After the single heal iteration replaced event-counting with direct exception accounting, the gate measures what it claims to. With must-fix #2 (uniqueness warning) also in, the spike is now a faithful capability test. Remaining nits are quality improvements, not correctness blockers.

## Codex reviewer note

Codex independently surfaced the JSON-survival gate bug at the same file:line as the three Claude-family reviewers. Independent confirmation from a different model family is the strongest signal we get — flagging it here so the next operator reading this report knows the issue was not a single-reviewer artifact.

## What this run does NOT prove

- **Live MiniMax behavior.** The spike's four gates have not yet been exercised against `MiniMax-M2.7-highspeed`. The operator runs `uv run python scripts/spike_minimax.py` (with `MINIMAX_API_KEY` set) once to get the verdict.
- **Cost re-verification.** `MODEL_PRICES` in `src/jobfit/llm.py` is currently zeroed pending the spike run; the `obs.subscribe` capture in this script will surface real `prompt_tokens`/`completion_tokens` to recost from. That recost is a follow-up, not part of T05's done condition.
- **Anchor uniqueness on real model output.** The prompt warns the model about uniqueness; whether M2.7 actually copies 8+ words when it cannot guarantee uniqueness is itself a hypothesis the live run tests.

## Cleanup

When you're done with this work:

```bash
git worktree remove .worktrees/implement-t05-minimax-capability-spike
git branch -D dev/implement-t05-minimax-capability-spike
```

Or, to land it:

```bash
git checkout main
git merge --no-ff dev/implement-t05-minimax-capability-spike
```

After landing, run the live gate before flipping `tasks/T05_spike.md` from `Status: todo` → `Status: done`:

```bash
uv run python scripts/spike_minimax.py    # exit 0 = T05 passes; T07–T13 unblocked
                                          # exit 1 = gate failure; follow tasks/T05_spike.md decision logic
```
