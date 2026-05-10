from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, computed_field, model_validator

from jobfit.errors import StageFailure

COMPONENT_WEIGHTS: dict[str, float] = {
    "skills": 0.35,
    "experience": 0.30,
    "education": 0.20,
    "soft_signals": 0.15,
}

StageStatus = Literal["pending", "running", "done", "failed", "skipped"]
StageName = Literal["profile", "score", "salary", "confidence", "growth"]
ComponentName = Literal["skills", "experience", "education", "soft_signals"]

REPORT_STAGE_NAMES: tuple[StageName, ...] = (
    "profile",
    "score",
    "salary",
    "confidence",
    "growth",
)


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
    name: ComponentName
    score_0_100: int = Field(ge=0, le=100)
    # Model commentary. The evidence-bearing claim is `anchor`, which must verify
    # against the CV text before rendering.
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
    detected_years_experience: int = Field(ge=0, le=70)


class Source(BaseModel):
    url: HttpUrl
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

    @model_validator(mode="after")
    def _require_ordered_range(self) -> SalaryEstimate:
        if self.low > self.high:
            raise ValueError("SalaryEstimate.low must be <= high")
        return self


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
        if set(names) != set(COMPONENT_WEIGHTS.keys()) or len(names) != len(COMPONENT_WEIGHTS):
            raise ValueError(f"Score requires exactly one component per category; got {names}")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> int:
        weighted = sum(c.score_0_100 * COMPONENT_WEIGHTS[c.name] for c in self.components)
        return int(weighted + 0.5)


class Report(BaseModel):
    profile: Profile | StageFailure
    score: Score | StageFailure
    salary: SalaryEstimate | StageFailure
    confidence: Confidence | StageFailure
    growth: list[GrowthAction] | StageFailure
    statuses: dict[StageName, StageStatus]
    raw_cv_text: str

    @model_validator(mode="after")
    def _require_exact_status_keys(self) -> Report:
        expected = set(REPORT_STAGE_NAMES)
        actual = set(self.statuses)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ValueError(f"Report.statuses mismatch; missing={missing}, extra={extra}")
        return self


Report.model_rebuild()
