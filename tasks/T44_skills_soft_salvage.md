# T44 — Skills and soft-signal evidence salvage

Status: done
Owner: software-engineer
Depends on: T38, T40
Unblocks: cleaner Profile.pdf rerun before T39/T40 closure
Estimate: ~45 min

## Goal

Live review showed that skills or soft-signal evidence can disappear even when
the CV clearly contains it. The common shape is a compact section such as
`Python, SQL, Kubernetes` that is too short for the 6-word quote floor, while
longer Experience/Profile lines prove the same tools or professional signals.

Preserve the grounding rule: do not lower the quote floor and do not fabricate
components. Rescue only evidence that can still be verified as a literal CV
substring.

## Implementation

- `src/gander/prompts/extract.md`: instruct extraction to use longer
  Experience/Projects/Profile/Summary lines for `skills` and `soft_signals`
  when compact dedicated sections are too short.
- `src/gander/extract.py`: after LLM output verification, salvage missing
  `skills`/`soft_signals` items from long, verifier-passing lines containing
  named tools or leadership/mentorship/stakeholder signals. Existing evidence
  quotes are not reused.
- `src/gander/prompts/score.md`: give the scorer the same compact-section
  guidance for skills/soft anchors.
- `src/gander/score.py`: run the existing single logical retry when
  `skills` or `soft_signals` drop, with retry copy that points the model at
  longer literal evidence lines.

## Verification

- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -p no:rerunfailures tests/test_extract.py tests/test_score.py -m fast --strict-markers -v`
- `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/gander/extract.py src/gander/score.py tests/test_extract.py tests/test_score.py`
- `UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check src/gander/extract.py src/gander/score.py tests/test_extract.py tests/test_score.py`
- `UV_CACHE_DIR=/tmp/uv-cache uv run mypy src/gander/extract.py src/gander/score.py`
- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -m fast --strict-markers -q`

## Outcome

Implemented on 2026-05-15. Focused fast tests passed: 29 passed, 15
deselected. Ruff check/format and mypy passed on touched source/tests. Full
fast suite passed: 378 passed, 58 deselected.
