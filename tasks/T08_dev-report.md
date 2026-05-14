# /dev Report — T08 L2 PII redaction

**Task:** Implement T08 L2 PII redaction (regex-only) per `tasks/T08_redact.md`. New `src/gander/redact.py` with `def redact(text: str) -> RedactedCV | StageFailure`, regex pipeline for email/phone/URL/postcode/name/year, idempotent, wrapped in `stage_boundary("redact")` with obs.emit. New `tests/test_redact.py`. Flip T08 status to done in single commit.
**Branch:** `feat/block-a-early-stages` (shared with T07; T08 stacks on top of `9e8e20e`)
**Worktree:** `/home/mf/GitHub/probable-goose-machine/.worktrees/block-a`
**Stack:** py, gradio, precommit

## Files touched

- `src/gander/redact.py` — new, 322 → ~340 LOC after heal. Pure-function regex pipeline + stage_boundary + obs.emit on done/error.
- `tests/test_redact.py` — new, 208 → ~280 LOC after heal. 17 fast + 3 slow tests.
- `tasks/T08_redact.md` — `Status: todo` → `Status: done`; Outcome paragraph filled in.
- `tasks/T08_dev-plan.md` — 366-line implementation plan written by planner; left untracked (not in scope, consistent with T07).
- `tasks/backlog.md` — appended `## T08-implement-l2-pii-redaction` block with 15 should-fix + 8 nit items. Auto-unions on merge.

## Checks

| Command | Initial (Phase 2) | After heal (Phase 4) |
|---|---|---|
| `uv run ruff format` (redact.py, test_redact.py) | pass | pass |
| `uv run ruff check` (redact.py, test_redact.py) | pass | pass |
| `uv run mypy src/gander` | pass | pass |
| `uv run pytest -m fast tests/test_redact.py -v` | 12 passed | **17 passed** (+5 healed tests) |
| `uv run pytest -m slow tests/test_redact.py -v` | 3 passed | 3 passed (slow fixture assertions tightened) |
| `uv run pytest -m fast` (whole suite) | 69 passed | **74 passed**, no regressions |
| `uv run pre-commit run --all-files` | pass | pass |

## Review findings

### Must-fix (resolved this run)

- **[codex]** `src/gander/redact.py:243` — `_redact_header_name` bailed (returned text unchanged) when the first non-blank line was an already-emitted marker like `[EMAIL]`, leaving the actual name on the next line unredacted. **Fixed:** added `_MARKER_ONLY_LINE` regex and made the scan `continue` past marker-only lines rather than `return`. Test pins the contract: `"[EMAIL]\nJane Smith\n…"` → `Jane Smith` becomes `[NAME]`.
- **[codex]** `src/gander/redact.py:81` — `_NAME_LABEL` used `\s+` between captured-name words; under `(?im)`, `\s` includes `\n`, so `Name: Jane\nExperience` could absorb the next section header into the name group. **Fixed:** replaced every `\s` inside `_NAME_LABEL` with `[ \t]` so the `(?m)` per-line anchor isn't undermined.
- **[qa-engineer]** `tests/test_redact.py` — missing StageFailure return-path test; the `RedactedCV | StageFailure` type union was unenforced and the `assert cm.failure is not None` in `redact.py` would be stripped under `python -O`. **Fixed:** added `test_stage_failure_returned_when_pipeline_raises` using `monkeypatch.setattr(redact_module, "_URL", _BoomPattern())`. (Direct `setattr` on `re.Pattern.finditer` is C-read-only; swapping the module binding works around it.)
- **[qa-engineer]** Missing observability test for failure path. **Fixed:** added `test_failure_path_emits_error_event` — uses `obs.subscribe` to capture events, triggers failure, asserts `error` event with `stage="redact"` and `exc_type="RuntimeError"`. Mirrors `tests/test_ingest.py:187-202`.
- **[qa-engineer]** Slow fixture pass under-asserted — only checked audit_log *kinds*, not that emails/names were actually absent from `result.text`. A regression that records but fails to substitute would have silently passed. **Fixed:** for every `email`/`name` redaction in the slow fixture pass, the test now asserts `r.original not in result.text` AND the corresponding marker is present.
- **[qa-engineer]** No-content fingerprint guarantee on error event (PRD §4.8). **Fixed:** added `test_failure_event_does_not_leak_cv_content` — injects a generic-message exception with a CV containing `jan.novotny@example.com` and asserts the captured `exc_message` does NOT contain the email or the name. Inline docstring records that the guarantee depends on raised exception messages staying generic.

### Must-fix (remaining — exhaustion)

None. Single heal iteration resolved all 6 must-fix items.

### Should-fix (deferred to backlog)

15 items — see `tasks/backlog.md`. Highlights: audit-log span semantics (codex flagged drift, hiring-manager flagged the design choice itself); header-name bail on common `Jan Novotný | +420…` single-line layout (PO + HM); phone regex requires separators (PO); PRD §4.7 names "address" but only postcode is covered (PO); several missing negative tests (QA) to pin documented limitations.

### Nits (deferred to backlog)

8 items — see `tasks/backlog.md`. Includes Czech month names, schema docstrings, `Sept`/`Sep` alternation order, and a slow-marked corpus-guard test that would be more useful as fast.

## Hiring grade

**on-bar.** From hiring-manager: "Pipeline is small but every piece is there, decisions are documented, tests pin the contract beyond happy path; the span-semantics decision and the postcode `original` loss are the two judgment calls a reviewer will push back on, but neither tanks the submission."

## Codex reviewer note

Codex independently flagged the two regex bugs (MF1 + MF2) that no Claude-family reviewer caught — both real failure modes a senior reader would notice. Codex's standalone verdict was **below-bar**; per dev-skill convention, only `hiring-manager` sets the hiring grade. Codex's two must-fix bugs are now fixed and pinned by regression tests, which closes the gap between the two verdicts.

## What this run does NOT prove

- **Realistic header layouts.** The header-name pass still bails on single-line `Name | digit/comma`-style headers (most common real-world CV first line). Backlogged as a should-fix; the slow fixture pass happens to pass because the two chosen fixtures have a bare title-case first line — that's coverage luck, not defense.
- **Address coverage beyond postcode.** PRD §4.7 names "address" as PII; this stage covers only the CZ postcode digits when sandwiched by comma+city. Street lines without postcode survive. Backlogged.
- **Audit-log span consumability.** Spans are OUTPUT-relative and documented as "informational." T15 (downstream PII consumer / UI overlay) needs to read the report before treating spans as actionable offsets into input text.

## Cleanup

This is part of a 3-commit Block A train (T07 + T08 + T09). Do not discard the worktree until the orchestrator has finished T09 and opened the PR. After PR merges:

```bash
git worktree remove .worktrees/block-a
git branch -D feat/block-a-early-stages
```
