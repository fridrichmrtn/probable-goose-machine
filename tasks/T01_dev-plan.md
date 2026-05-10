# T01 — Schemas + StageFailure: implementation plan

Working directory: `/home/mf/GitHub/probable-goose-machine/.worktrees/t01-schemas`.

Scope: the Pydantic contracts every other module compiles against, plus the minimal `StageFailure` type and a `stage_boundary` skeleton. No `verify.py`, no `obs.py`, no `llm.py` — those land in T02. No CI / pre-commit changes — T03. `pyproject.toml` is already complete from T00.

## Files to create

- `src/jobfit/schemas.py` — all Pydantic v2 models the rest of the pipeline imports (RawCV → Report), plus the exported `COMPONENT_WEIGHTS` constant and `StageStatus` Literal alias.
- `src/jobfit/errors.py` — `StageFailure` BaseModel and `stage_boundary(stage_name)` dual sync/async context manager.
- `tests/test_schemas.py` — four `@pytest.mark.fast` tests covering computed-field correctness, range validation, the `Report`-with-`StageFailure` slot pattern, and `stage_boundary` exception capture.

## Implementation order

1. **`src/jobfit/errors.py` first.** `StageFailure` has no dependency on schemas; building it first lets `schemas.py` import it without a forward-reference dance for `StageFailure` itself (the forward-references are in the other direction — `Report` references `StageFailure`).
2. **`src/jobfit/schemas.py`.** Imports `StageFailure` from `jobfit.errors`. Uses `from __future__ import annotations` so all `Profile | StageFailure` unions are strings at class-definition time; then `Report.model_rebuild()` at module bottom resolves them.
3. **`tests/test_schemas.py`.** Imports both modules; exercises behaviour, not implementation.

## `src/jobfit/errors.py` — exact shape

```python
from __future__ import annotations

from types import TracebackType
from typing import Self

from pydantic import BaseModel


class StageFailure(BaseModel):
    stage: str
    user_message: str
    debug_detail: str | None = None


class stage_boundary:
    """Context manager (sync + async) that converts stage exceptions into a StageFailure.

    Usage:
        with stage_boundary("score") as cm:
            ...                       # may raise
        if cm.failure:
            report.score = cm.failure

    KeyboardInterrupt and SystemExit are re-raised. All other Exception subclasses
    are swallowed and recorded as `cm.failure`.
    """

    def __init__(self, stage_name: str) -> None:
        self.stage_name = stage_name
        self.failure: StageFailure | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return self._handle(exc_type, exc)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return self._handle(exc_type, exc)

    def _handle(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
    ) -> bool:
        if exc is None:
            return False
        if isinstance(exc, KeyboardInterrupt | SystemExit):
            return False  # re-raise
        if isinstance(exc, Exception):
            self.failure = StageFailure(
                stage=self.stage_name,
                user_message=str(exc) or type(exc).__name__,
                debug_detail=repr(exc),
            )
            # T02: wire to obs.emit("error", stage=self.stage_name, exc=repr(exc))
            return True  # suppress
        return False
```

Notes:
- Class-name `stage_boundary` (snake_case) is intentional: callers use it as `with stage_boundary("foo") as cm:`, which reads as a function. Mypy strict accepts the lowercase class name; ruff's `N801` is not in the selected lint set (`E,F,I,UP,B,SIM`) so no rename needed.
- Do NOT import `obs` here. The `# T02:` comment is the only reference; T02 will replace it with a real call.
- Do NOT add a `__call__` decorator path. Spec asks for context-manager only; decorator usage isn't required by any T01 caller.

## `src/jobfit/schemas.py` — exact shape

Module skeleton:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field

from jobfit.errors import StageFailure

COMPONENT_WEIGHTS: dict[str, float] = {
    "skills": 0.35,
    "experience": 0.30,
    "education": 0.20,
    "soft_signals": 0.15,
}

StageStatus = Literal["pending", "running", "done", "failed"]
```

Then declare, in this order (later models reference earlier ones):

1. `Redaction(BaseModel)` — `kind: Literal["email","phone","name","address","year","url"]`, `original: str`, `replacement: str`, `span: tuple[int, int]`.
2. `RawCV(BaseModel)` — `filename: str`, `content_bytes: bytes`.
3. `RedactedCV(BaseModel)` — `text: str`, `audit_log: list[Redaction]`.
4. `Anchor(BaseModel)` — `quote: str`, `section: str | None = None`. Single canonical attribution shape; downstream models embed `anchor: Anchor` rather than duplicating `anchor_quote: str`.
5. `Component(BaseModel)` — `name: Literal["skills","experience","education","soft_signals"]`, `score_0_100: int = Field(ge=0, le=100)`, `justification: str`, `anchor: Anchor`.
6. `ProfileItem(BaseModel)` — `text: str`, `anchor: Anchor`.
7. `Profile(BaseModel)` — `skills: list[ProfileItem]`, `experience: list[ProfileItem]`, `education: list[ProfileItem]`, `soft_signals: list[ProfileItem]`, `detected_role: str`, `detected_location: str | None`, `detected_years_experience: int`.
8. `Source(BaseModel)` — `url: str`, `snippet: str`, `domain: str`. (Plain `str` for `url`; Pydantic `HttpUrl` would force serialization gymnastics downstream and the spec doesn't require it.)
9. `SalaryEstimate(BaseModel)` — `low: int`, `high: int`, `currency: str`, `period: Literal["month","year"]`, `sources: list[Source]`, `reasoning: str`.
10. `Confidence(BaseModel)` — `tier: Literal["Low","Medium","High"]`, `rationale: str`.
11. `GrowthAction(BaseModel)` — `what: str`, `time_horizon_months: int = Field(ge=1, le=24)`, `mechanism: str`, `anchor: Anchor`.
12. `Score(BaseModel)` — declares only `components: list[Component]`. Then a `@computed_field` named `total` returning `int`:

    ```python
    class Score(BaseModel):
        components: list[Component]

        @computed_field  # type: ignore[prop-decorator]
        @property
        def total(self) -> int:
            return round(
                sum(c.score_0_100 * COMPONENT_WEIGHTS[c.name] for c in self.components)
            )
    ```

    Formula: weighted sum of `component.score_0_100 * COMPONENT_WEIGHTS[component.name]` over all components, then `round()` to int (Python banker's rounding is fine — the test uses values that don't land on .5 boundaries). The `# type: ignore[prop-decorator]` is a known mypy-strict-plus-Pydantic interaction documented in Pydantic's `computed_field` docs; do not try to work around it with a `@cached_property` or factory.

13. `Report(BaseModel)`:

    ```python
    class Report(BaseModel):
        profile: Profile | StageFailure
        score: Score | StageFailure
        salary: SalaryEstimate | StageFailure
        confidence: Confidence | StageFailure
        growth: list[GrowthAction] | StageFailure
        statuses: dict[str, StageStatus]
        raw_cv_text: str
    ```

14. **At module bottom:** `Report.model_rebuild()` to resolve the `StageFailure` forward references introduced by `from __future__ import annotations`. Without this, `Report` instantiation raises `PydanticUserError: 'Report' is not fully defined`.

Notes:
- Do NOT add `model_config = ConfigDict(...)` overrides. Defaults (validate-on-init, strict=False at the model level, allow extra=ignore) are right for T01.
- Do NOT add `field_validator`s. Range constraints use `Field(ge=..., le=...)`; that's the entire validation surface needed.
- Do NOT export anything beyond what's declared. No `__all__`. Other modules import by name.

## Tests to write — `tests/test_schemas.py`

All four marked `@pytest.mark.fast`. File header:

```python
import pytest
from pydantic import ValidationError

from jobfit.errors import StageFailure, stage_boundary
from jobfit.schemas import (
    Anchor,
    Component,
    Confidence,
    GrowthAction,
    Profile,
    Report,
    SalaryEstimate,
    Score,
    Source,
)
```

1. **`test_score_total_recomputes_from_components_and_weights`**
   - Build four `Component`s with `score_0_100` of `80, 60, 40, 100` for `skills, experience, education, soft_signals` respectively, each with a stub `Anchor(quote="x")` and `justification="."`.
   - Construct `Score(components=[...])`.
   - Expected: `80*0.35 + 60*0.30 + 40*0.20 + 100*0.15 = 28 + 18 + 8 + 15 = 69`.
   - Assert `score.total == 69`.

2. **`test_growth_action_rejects_out_of_range_months`**
   - `with pytest.raises(ValidationError): GrowthAction(what="x", time_horizon_months=0, mechanism="y", anchor=Anchor(quote="z"))`.
   - `with pytest.raises(ValidationError): GrowthAction(what="x", time_horizon_months=25, mechanism="y", anchor=Anchor(quote="z"))`.
   - (Optional sanity: a single positive case at `time_horizon_months=12` to confirm the bounds aren't inverted — keep it inline, not a separate test.)

3. **`test_report_accepts_stage_failure_in_each_block`**
   - Construct one valid instance of each block payload (a real `Profile`, `Score`, `SalaryEstimate`, `Confidence`, `[GrowthAction(...)]`) plus a single `StageFailure(stage="x", user_message="boom")`.
   - Five assertions / sub-cases (a parametrize is fine, or five inline `Report(...)` constructions): for each block field in turn, build a `Report` where that field is the `StageFailure` and the other four are valid. Assert `isinstance(report.<field>, StageFailure)` for the failed slot, and the other slots are their normal types.
   - Use `statuses={"profile": "done", "score": "done", "salary": "done", "confidence": "done", "growth": "done"}` and `raw_cv_text="..."` to satisfy the remaining required fields.

4. **`test_stage_boundary_catches_exception_and_yields_failure`**
   - ```python
     with stage_boundary("test_stage") as cm:
         raise RuntimeError("boom")
     assert cm.failure is not None
     assert cm.failure.stage == "test_stage"
     assert cm.failure.user_message == "boom"
     assert cm.failure.debug_detail and "RuntimeError" in cm.failure.debug_detail
     ```
   - Verifies the `with` block does not propagate the exception (line after `with` is reached) AND that the captured `StageFailure` has the right `stage` plus a non-empty `user_message`.

No async test for `stage_boundary` in T01 — the dual sync/async shape is implemented but the async path has no caller until T15. T15's pipeline tests will exercise `__aenter__`/`__aexit__`. (`asyncio_mode = "auto"` is already configured in `pyproject.toml`, so adding one later is one decorator-free `async def`.)

## Verification commands (run inside worktree)

```bash
uv run pytest -m fast tests/test_schemas.py -v
uv run mypy src/jobfit/schemas.py src/jobfit/errors.py
uv run ruff check src/jobfit/schemas.py src/jobfit/errors.py tests/test_schemas.py
```

All three must exit 0. Also expected clean (sanity, but not gating):

```bash
uv run ruff format --check src/jobfit/schemas.py src/jobfit/errors.py tests/test_schemas.py
```

If `mypy` complains about `computed_field` decoration order, confirm the `# type: ignore[prop-decorator]` comment is on the `@computed_field` line and that `@property` is the inner decorator. Do not change Pydantic version or strip mypy strict mode to chase this.

## Definition of done

- Three files created at the paths above; no other source files touched.
- All three verification commands pass on a fresh `uv sync`.
- `Report` instantiates with both real-payload and `StageFailure`-payload variants in every block-shaped slot.
- `tasks/T01_schemas.md` Outcome section filled in (one paragraph: any deltas vs. this plan, mypy version actually used, surprises if any).

## Out of scope (deferred to other tasks)

- `src/jobfit/verify.py` (`verify_quote`, `drop_unverified`) — **T02**.
- `src/jobfit/obs.py` (`emit`) — **T02**. The `# T02:` comment in `errors.py` is the wire-up marker; do not import `obs` here.
- `src/jobfit/llm.py` (MiniMax-via-OpenAI-SDK async client) — **T02**.
- `tests/conftest.py`, sample-CV fixtures, marker registration helpers — **T02** / fixtures land alongside their consumers.
- `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `.github/workflows/warm-keeper.yml` — **T03**.
- `pyproject.toml` modifications — already complete in T00 (`pydantic>=2`, pytest markers, `asyncio_mode = "auto"`, mypy strict, ruff config all present).
- Decorator-form `stage_boundary` (`@stage_boundary("foo") def f(): ...`) — not requested by any T01 caller; revisit only if T15 wants it.
- Async test for `stage_boundary.__aenter__` — covered by T15 pipeline tests.
- Any `__all__`, re-exports from `jobfit/__init__.py`, or convenience constructors. Callers import models by name from `jobfit.schemas`.
