from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

from jobfit.errors import StageFailure

COMPONENT_WEIGHTS: dict[str, float] = {
    "skills": 0.35,
    "experience": 0.30,
    "education": 0.20,
    "soft_signals": 0.15,
}

StageStatus = Literal["pending", "running", "done", "failed"]


class Redaction(BaseModel):
    kind: Literal["email", "phone", "name", "address", "year", "url"]
    original: str
    replacement: str
    span: tuple[int, int]


class RawCV(BaseModel):
    filename: str
    content_bytes: bytes


class RedactedCV(BaseModel):
    text: str
    audit_log: list[Redaction]


class Anchor(BaseModel):
    """Substring-attribution for a claim.

    `section` names a CV section header (e.g., 'Work Experience', 'Education') — open
    vocabulary, not the closed Component.name set. Section-locality is enforced by
    jobfit.verify.verify_quote (T02).
    """

    quote: str
    section: str | None = None


class Component(BaseModel):
    name: Literal["skills", "experience", "education", "soft_signals"]
    score_0_100: int = Field(ge=0, le=100)
    justification: str
    anchor: Anchor


class ProfileItem(BaseModel):
    text: str
    anchor: Anchor


class Profile(BaseModel):
    skills: list[ProfileItem]
    experience: list[ProfileItem]
    education: list[ProfileItem]
    soft_signals: list[ProfileItem]
    detected_role: str
    detected_location: str | None
    detected_years_experience: int


class Source(BaseModel):
    url: str
    snippet: str
    domain: str


class SalaryEstimate(BaseModel):
    """Salary range with sources and the estimator's reasoning.

    NOTE: when invoking the L4c confidence judge (T12), pass
    `sources`/`low`/`high`/`currency`/`period` individually — `reasoning` must NOT reach
    the judge (PLAN §L4c, recompute-then-compare protocol).
    """

    low: int
    high: int
    currency: str
    period: Literal["month", "year"]
    sources: list[Source]
    reasoning: str


class Confidence(BaseModel):
    tier: Literal["Low", "Medium", "High"]
    rationale: str


class GrowthAction(BaseModel):
    what: str
    time_horizon_months: int = Field(ge=1, le=24)
    mechanism: str
    anchor: Anchor


class Score(BaseModel):
    components: list[Component]

    @model_validator(mode="after")
    def _require_one_component_per_category(self) -> Score:
        names = [c.name for c in self.components]
        if set(names) != set(COMPONENT_WEIGHTS.keys()) or len(names) != len(
            COMPONENT_WEIGHTS
        ):
            raise ValueError(
                "Score requires exactly one component per category; "
                f"got {names}"
            )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> int:
        return round(
            sum(c.score_0_100 * COMPONENT_WEIGHTS[c.name] for c in self.components)
        )


class Report(BaseModel):
    profile: Profile | StageFailure
    score: Score | StageFailure
    salary: SalaryEstimate | StageFailure
    confidence: Confidence | StageFailure
    growth: list[GrowthAction] | StageFailure
    statuses: dict[str, StageStatus]
    raw_cv_text: str


Report.model_rebuild()
