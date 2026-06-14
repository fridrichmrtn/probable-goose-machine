"""Reusable fake stage outputs for tests that need canned pipeline data.

The builder functions mirror `_patch_happy_path` in test_pipeline_fast.py but
with richer fixtures: a multi-sentence evidence quote so e2e tests can assert
the full text is visible (no truncation), a real salary range, and >= 1 growth
action.

`patch_pipeline_stages(monkeypatch)` wires all 7 stage workers on the
`gander.pipeline` namespace in one call, suitable for both function-scoped
monkeypatch fixtures and session-scoped MonkeyPatch contexts.
"""

from __future__ import annotations

from gander.schemas import (
    Anchor,
    Component,
    Confidence,
    GrowthAction,
    Profile,
    ProfileItem,
    RedactedCV,
    SalaryEstimate,
    Score,
    Source,
)

# Multi-sentence quote so e2e tests can assert the FULL text is present in the
# rendered component-quote block (proving no truncation in the HTML renderer).
_LONG_EVIDENCE_QUOTE = (
    "Led end-to-end delivery of a real-time fraud detection pipeline processing "
    "over 50 million events per day, reducing false-positive rate by 34% through "
    "feature engineering on transaction velocity and merchant-category embeddings. "
    "Collaborated cross-functionally with risk, product, and infrastructure teams "
    "to ship three major model iterations on a quarterly cadence."
)


def fake_profile() -> Profile:
    item = ProfileItem(text="python", anchor=Anchor(quote="Python"))
    return Profile(
        skills=[item],
        experience=[item],
        education=[item],
        soft_signals=[item],
        detected_role="Data Engineer",
        detected_location="Prague",
        detected_years_experience=5,
    )


def fake_score() -> Score:
    return Score(
        components=[
            Component(
                name="skills",
                score_0_100=82,
                justification="Strong Python and SQL skills evidenced across multiple projects.",
                anchor=Anchor(quote=_LONG_EVIDENCE_QUOTE, section="Work Experience"),
            ),
            Component(
                name="experience",
                score_0_100=74,
                justification="Five years of data engineering with production ML delivery.",
                anchor=Anchor(quote="5 years of experience", section="Work Experience"),
            ),
            Component(
                name="education",
                score_0_100=65,
                justification="Bachelor's in Computer Science from a respected local university.",
                anchor=Anchor(quote="Bachelor of Science", section="Education"),
            ),
            Component(
                name="soft_signals",
                score_0_100=70,
                justification="Demonstrates cross-functional collaboration and communication.",
                anchor=Anchor(
                    quote="collaborated with risk and product teams",
                    section="Work Experience",
                ),
            ),
        ]
    )


def fake_salary() -> SalaryEstimate:
    return SalaryEstimate(
        low=85_000,
        high=130_000,
        currency="CZK",
        period="month",
        sources=[
            Source(
                url="https://platy.cz/platy/it/data-engineer",  # type: ignore[arg-type]
                snippet="Median salary for Data Engineer in Prague: 97,000 CZK/month",
                domain="platy.cz",
            )
        ],
        reasoning=(
            "Market data from Czech salary surveys suggests mid-level data engineers"
            " in Prague earn between 85k–130k CZK per month."
        ),
    )


def fake_confidence() -> Confidence:
    return Confidence(tier="High", rationale="Three independent sources agree on the range.")


def fake_growth() -> list[GrowthAction]:
    return [
        GrowthAction(
            what="Obtain cloud data platform certification (e.g. dbt or Databricks)",
            time_horizon_months=6,
            mechanism=(
                "Complete the official certification track; build a public portfolio"
                " project demonstrating the skill."
            ),
            setting="capability_artifact",
            anchor=Anchor(quote="experience with dbt and Spark", section="Work Experience"),
        ),
        GrowthAction(
            what="Take ownership of an internal ML pipeline end-to-end",
            time_horizon_months=12,
            mechanism=(
                "Propose and lead one production ML project from data ingestion through monitoring."
            ),
            setting="current_employer",
            anchor=Anchor(quote="Led end-to-end delivery", section="Work Experience"),
        ),
    ]


def fake_redacted(text: str = "redacted cv text") -> RedactedCV:
    return RedactedCV(text=text, audit_log=[])


def patch_pipeline_stages(monkeypatch: object, *, e2e_delays: bool = False) -> None:
    """Stub all 7 pipeline stage workers on the gander.pipeline namespace.

    `monkeypatch` accepts either pytest's function-scoped `MonkeyPatch` or a
    session-scoped `_pytest.monkeypatch.MonkeyPatch` instance — both expose the
    same `.setattr` interface.

    `e2e_delays=True` adds a 50 ms sleep to each stage so that Gradio's SSE
    streaming has time to deliver each intermediate update to the browser before
    the next yield fires. Without delays the pipeline completes in ~35 ms and
    Gradio coalesces the rapid SSE events, leaving the browser stuck on an
    early intermediate state (e.g. "Extracting profile…") even though the
    download button is already visible.

    The final L5 stages (confidence + growth) run concurrently in `pipeline.run`
    and would otherwise complete in the same ~50 ms window, so their two
    completion frames plus the terminal frame arrive as one burst that Gradio
    coalesces — leaving the browser on the pre-final "✓ Confidence ⋯ Plan"
    frame. Giving `plan_growth` a longer delay makes it finish distinctly last,
    so the terminal frame is well-separated and reliably rendered.
    """
    import asyncio

    from gander import pipeline
    from gander.schemas import CVQualitySignals

    _delay = 0.05 if e2e_delays else 0.0
    # plan_growth runs concurrently with judge (L5 fan-out); make it finish last
    # with a clear gap so the final SSE frame is not coalesced. See docstring.
    _final_delay = _delay * 4

    async def _extract_text_ok(file_bytes: bytes, filename: str) -> str:
        if _delay:
            await asyncio.sleep(_delay)
        return "raw cv text"

    def _redact_ok(text: str) -> RedactedCV:
        return fake_redacted(text=text)

    async def _extract_profile_ok(redacted: RedactedCV) -> Profile:
        if _delay:
            await asyncio.sleep(_delay)
        return fake_profile()

    async def _score_profile_ok(redacted: RedactedCV, profile: Profile) -> Score:
        if _delay:
            await asyncio.sleep(_delay)
        return fake_score()

    async def _estimate_salary_ok(profile: Profile) -> SalaryEstimate:
        if _delay:
            await asyncio.sleep(_delay)
        return fake_salary()

    async def _judge_ok(
        sources: list,
        low: int,
        high: int,
        currency: str,
        period: str,
        *,
        cv_quality: CVQualitySignals,
    ) -> Confidence:
        if _delay:
            await asyncio.sleep(_delay)
        return fake_confidence()

    async def _plan_growth_ok(
        redacted: RedactedCV,
        profile: Profile,
        score: Score,
        salary_midpoint: int,
        currency: str,
        market_name: str | None = None,
    ) -> list[GrowthAction]:
        if _final_delay:
            await asyncio.sleep(_final_delay)
        return fake_growth()

    monkeypatch.setattr(pipeline, "extract_text", _extract_text_ok)
    monkeypatch.setattr(pipeline, "redact", _redact_ok)
    monkeypatch.setattr(pipeline, "extract_profile", _extract_profile_ok)
    monkeypatch.setattr(pipeline, "score_profile", _score_profile_ok)
    monkeypatch.setattr(pipeline, "estimate_salary", _estimate_salary_ok)
    monkeypatch.setattr(pipeline, "judge", _judge_ok)
    monkeypatch.setattr(pipeline, "plan_growth", _plan_growth_ok)
