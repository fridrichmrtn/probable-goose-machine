# T01 — Schemas + StageFailure

Status: done
Owner: software-engineer
Depends on: T00
Unblocks: T02, T14, every stage worker
Estimate: ~30 min

## Goal

Define the Pydantic contracts that every other module depends on, plus the `StageFailure` type and `stage_boundary` decorator. Once this lands, all downstream tasks can compile against a stable interface.

## Deliverables

- [ ] `src/jobfit/schemas.py` with the following models (Pydantic v2):
  - `StageStatus = Literal["pending", "running", "done", "failed"]`
  - `RawCV(filename: str, content_bytes: bytes)` — pre-ingestion.
  - `RedactedCV(text: str, audit_log: list[Redaction])` — post-redaction.
  - `Redaction(kind: Literal["email","phone","name","address","year","url"], original: str, replacement: str, span: tuple[int, int])`
  - `Anchor(quote: str, section: str | None = None)` — every claim points at one.
  - `Component(name: Literal["skills","experience","education","soft_signals"], score_0_100: int, justification: str, anchor: Anchor)`
  - `Profile(skills: list[ProfileItem], experience: list[ProfileItem], education: list[ProfileItem], soft_signals: list[ProfileItem], detected_role: str, detected_location: str | None, detected_years_experience: int)` where `ProfileItem(text: str, anchor: Anchor)`.
  - `Score(total: int, components: list[Component])` — `total` field is a `computed_field` from weighted sum.
  - `Source(url: str, snippet: str, domain: str)`
  - `SalaryEstimate(low: int, high: int, currency: str, period: Literal["month","year"], sources: list[Source], reasoning: str)`
  - `Confidence(tier: Literal["Low","Medium","High"], rationale: str)`
  - `GrowthAction(what: str, time_horizon_months: int, mechanism: str, anchor: Anchor)` with `time_horizon_months: int = Field(ge=1, le=24)`.
  - `Report(profile: Profile | StageFailure, score: Score | StageFailure, salary: SalaryEstimate | StageFailure, confidence: Confidence | StageFailure, growth: list[GrowthAction] | StageFailure, statuses: dict[str, StageStatus], raw_cv_text: str)` — every block plus a status map keyed by stage name.
- [ ] `src/jobfit/errors.py`:
  - `class StageFailure(BaseModel): stage: str; user_message: str; debug_detail: str | None = None`
  - `def stage_boundary(stage_name: str)` — decorator/context-manager that wraps a stage call: catches all `Exception`, emits an `obs.emit("error", stage=...)` event, and returns `StageFailure(stage=stage_name, user_message=...)`. Re-raises only `KeyboardInterrupt` and `SystemExit`.
- [ ] `tests/test_schemas.py` (`@pytest.mark.fast`):
  - `Score.total` recomputes correctly given component scores and weights.
  - `GrowthAction(time_horizon_months=25)` raises `ValidationError`.
  - `Report` accepts a `StageFailure` in any block-shaped field.
  - `stage_boundary` catches exceptions and returns a `StageFailure`.

## Inputs (contract from upstream)

- T00's `pyproject.toml` makes `pydantic`, `pytest`, `pytest-asyncio` available.

## Outputs (contract for downstream)

- All schemas importable from `jobfit.schemas`.
- `StageFailure` and `stage_boundary` importable from `jobfit.errors`.
- Component weights live in a module-level constant `COMPONENT_WEIGHTS = {"skills": 0.35, "experience": 0.30, "education": 0.20, "soft_signals": 0.15}` exported from `jobfit.schemas` so the README and UI can show the same numbers.

## Verification

```bash
uv run pytest -m fast tests/test_schemas.py -v
uv run mypy src/jobfit/schemas.py src/jobfit/errors.py
```

## Reference

- tasks/PLAN.md — § "L0 — Foundation" (schemas list)
- tasks/PLAN.md — § "Cross-cutting"

## Outcome

Schemas + StageFailure landed exactly per `tasks/dev-plan.md`: 8 fast tests pass (parametrized StageFailure-in-each-block expanded the 4 deliverable tests to 8 collected items), `mypy --strict` clean on `schemas.py` + `errors.py`, ruff clean across all three files. No deltas vs. plan. mypy 2.0.0, Pydantic 2.x via `uv run`.
