from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, computed_field, field_validator, model_validator

from gander.errors import StageFailure

_ISO_3166_ALPHA2 = re.compile(r"^[A-Z]{2}$")

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
    # Computed deterministically from raw date ranges in the CV (CZ+EN month
    # parsing, interval-union, gap-skip). When non-None, extract overrides the
    # LLM's `detected_years_experience` so salary's years>=10 lift gate cannot
    # be misled by LLM variance on `[YEAR] - [YEAR]` patterns (PRD §4.7 + R7).
    years_experience_deterministic: int | None = None


class Anchor(BaseModel):
    """Substring-attribution for a claim.

    `section` names a CV section header (e.g., 'Work Experience', 'Education') — open
    vocabulary, not the closed Component.name set. Section-locality is enforced by
    gander.verify.verify_quote (T02).
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
    # ISO-3166 alpha-2 (CZ, DE, JP, US, GB, …). When null, salary.py falls back
    # to the `_is_cz_location` regex on `detected_location` and defaults to "CZ"
    # — preserving legacy behavior for ambiguous or CZ-leaning CVs.
    detected_country: str | None = None
    detected_years_experience: int = Field(ge=0, le=70)

    @field_validator("detected_country", mode="before")
    @classmethod
    def _validate_country_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper() if isinstance(value, str) else value
        if not normalized:
            return None
        if not _ISO_3166_ALPHA2.fullmatch(normalized):
            raise ValueError(
                f"detected_country must be ISO-3166 alpha-2 (e.g. 'CZ'); got {value!r}"
            )
        return normalized

    # Populated post-LLM by gander.normalize.normalize_role (R4/R5 in T27).
    # When set, salary.build_queries + estimate_salary use these in place of
    # the raw `detected_role`, so non-market headlines (Member of Staff,
    # Data Gardener, …) don't drive DDG and the LLM salary estimator anchors
    # at the candidate's actual seniority band.
    canonical_role: str | None = None
    seniority_band: str | None = None
    is_management: bool = False
    role_normalization_source: str | None = None


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
    # Non-empty: salary.py rejects any estimate whose sources don't intersect the
    # DDG inputs, so an empty `sources` is already a stage failure downstream.
    # Enforcing here lets `LLMClient.complete_json`'s ValidationError-retry loop
    # recover the rare model sample that drops the field instead of bubbling
    # all the way to `StageFailure(debug_detail='model_urls=[]')`.
    sources: list[Source] = Field(min_length=1)
    reasoning: str

    @model_validator(mode="after")
    def _require_ordered_range(self) -> SalaryEstimate:
        if self.low > self.high:
            raise ValueError("SalaryEstimate.low must be <= high")
        return self


class Confidence(BaseModel):
    tier: Literal["Low", "Medium", "High"]
    rationale: str


class CVQualitySignals(BaseModel):
    """CV-extraction quality signals fed into the confidence judge.

    Built by pipeline.py from the verified Profile + Score so confidence can
    reflect thin CV understanding, not only market-source agreement.
    """

    dropped_score_components: int = Field(ge=0, le=3)
    canonical_role_resolved: bool
    location_detected: bool


class GrowthAction(BaseModel):
    what: str
    time_horizon_months: int = Field(ge=1, le=24)
    mechanism: str
    anchor: Anchor


class Score(BaseModel):
    components: list[Component]
    # Components the model returned but verify_quote could not anchor to the CV.
    # Renderer surfaces these in the footer so the reviewer can see which
    # categories were silently zero-weighted (PRD §4.5 "drop, don't fabricate").
    dropped: list[ComponentName] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_experience_component(self) -> Score:
        # T25: experience is mandatory; {skills, education, soft_signals} may be
        # dropped. Each surviving category may appear at most once. Dropped
        # components contribute 0 to `total` (the weighted formula is unchanged —
        # missing weights simply don't sum). Re-normalizing was rejected: it lets
        # a senior who drops 3 components report total = experience.score_0_100,
        # which can land above a junior with all 4 verified and break PRD §5.4
        # differentiation. Drop-as-zero preserves cross-CV calibration.
        names = [c.name for c in self.components]
        if len(names) != len(set(names)):
            raise ValueError(f"Score components must be unique per category; got {names}")
        unknown = set(names) - set(COMPONENT_WEIGHTS.keys())
        if unknown:
            raise ValueError(f"Score has unknown component names: {sorted(unknown)}")
        if "experience" not in names:
            raise ValueError("Score requires an `experience` component (T25: mandatory)")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> int:
        weighted = sum(c.score_0_100 * COMPONENT_WEIGHTS[c.name] for c in self.components)
        return int(weighted + 0.5)


class Report(BaseModel):
    # Block fields permit `None` so the L6 pipeline (T15) can yield intermediate
    # streaming states where downstream stages have not produced output yet.
    # Renderer treats `None` as "not yet rendered, skip the section"; StageFailure
    # remains the "stage attempted and failed" representation.
    profile: Profile | StageFailure | None = None
    score: Score | StageFailure | None = None
    salary: SalaryEstimate | StageFailure | None = None
    confidence: Confidence | StageFailure | None = None
    growth: list[GrowthAction] | StageFailure | None = None
    statuses: dict[StageName, StageStatus]
    raw_cv_text: str
    # Post-redaction text — the source every stage's `verify_quote` ran against.
    # Anchor consumers (acceptance tests, debug tooling) must check quotes
    # against this string, not `raw_cv_text`: a quote containing a redaction
    # marker like `[YEAR]` or `[URL]` is valid against the redacted text but
    # would spuriously fail against the raw text. Defaults to `""` so the L1
    # ingest-failed snapshot (which never reaches `redact()`) still validates.
    redacted_cv_text: str = ""
    # Populated by the L6 pipeline subscriber on every yield; aggregates the
    # `usd_cost` and `duration_ms` fields emitted by gander.llm `llm_call`
    # events. Footer in gander.report interpolates these.
    total_cost_usd: float = 0.0
    total_latency_ms: int = 0

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
