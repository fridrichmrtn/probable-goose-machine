"""MiniMax capability spike for T05.

Runs four sequential LLM calls against the junior and senior CV fixtures
(extract + score per CV) and applies four go/no-go gates: anchor verification
rate, junior-vs-senior score spread, first-try JSON-mode survival, and p50
latency. Prints a results table and a single decision line.

Run: ``uv run python scripts/spike_minimax.py``

Exit codes:
  0 — all gates passed.
  1 — at least one gate failed (preceded by ``FAILED GATE: <name>`` to stdout).
  2 — preflight env-var check failed (message on stderr).

Provider exceptions (auth, network, rate-limit, 5xx) bubble as tracebacks.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from jobfit import obs
from jobfit.llm import LLMClient
from jobfit.verify import verify_quote

FIXTURES = Path("tests/fixtures/cvs")
JUNIOR_TXT = FIXTURES / "01_junior_da_novotny.txt"
SENIOR_TXT = FIXTURES / "08_staff_ml_engineer_dvorak.txt"

ANCHOR_RATE_FLOOR = 0.70
SCORE_SPREAD_FLOOR = 20
JSON_SURVIVAL_FLOOR = 0.90
P50_LATENCY_CEILING_S = 8.0

EXTRACT_SYSTEM = (
    "You extract structured skills evidence from a CV.\n\n"
    "Return JSON only matching this schema:\n"
    '  {"skills": [{"text": str, "anchor_quote": str}, ...], '
    '"years_experience": int}\n\n'
    "Rules:\n"
    "- `anchor_quote` MUST be a verbatim substring copied from the CV — at least "
    "6 consecutive words, case-preserved, punctuation-preserved. No paraphrasing. "
    "No ellipses. No edits.\n"
    "- If you cannot find a 6+ word literal substring that supports a skill, drop "
    "that skill entirely. Do not fabricate.\n"
    "- `years_experience` is the candidate's total professional years across "
    "roles, as an integer."
)

SCORE_SYSTEM = (
    "You score a candidate's skills strength for a generic mid-level data/ML "
    "role.\n\n"
    "Return JSON only matching this schema:\n"
    '  {"name": "skills", "score_0_100": int, "anchor_quote": str}\n\n'
    "Rules:\n"
    '- `name` is the literal string "skills".\n'
    "- `score_0_100` reflects skills strength: 0–30 = junior with narrow "
    "exposure, 31–60 = solid mid-level, 61–85 = senior with breadth, "
    "86–100 = staff/principal with deep platform impact.\n"
    "- `anchor_quote` MUST be a verbatim substring of at least 6 consecutive "
    "words from the CV that justifies the score. Case- and punctuation-preserved. "
    "No paraphrasing."
)


class SpikeSkill(BaseModel):
    text: str = Field(min_length=1)
    anchor_quote: str = Field(min_length=1)


class SpikeExtract(BaseModel):
    skills: list[SpikeSkill] = Field(min_length=1)
    years_experience: int = Field(ge=0, le=80)


class SpikeScore(BaseModel):
    name: Literal["skills"]
    score_0_100: int = Field(ge=0, le=100)
    anchor_quote: str = Field(min_length=1)


def _preflight() -> int | None:
    provider = os.environ.get("JOBFIT_LLM_PROVIDER", "minimax")
    required = "ANTHROPIC_API_KEY" if provider == "anthropic" else "MINIMAX_API_KEY"
    if not os.environ.get(required):
        print(
            f"Set {required} in .env (JOBFIT_LLM_PROVIDER={provider})",
            file=sys.stderr,
        )
        return 2
    return None


@contextmanager
def _stage(name: str) -> Iterator[None]:
    token = obs.current_stage.set(name)
    try:
        yield
    finally:
        obs.current_stage.reset(token)


def _count_anchor_hits(extract: SpikeExtract, cv_text: str) -> tuple[int, int]:
    verified = sum(1 for skill in extract.skills if verify_quote(skill.anchor_quote, cv_text))
    return verified, len(extract.skills)


def _stage_events(events: list[dict[str, Any]], stage: str) -> list[dict[str, Any]]:
    return [e for e in events if e.get("event") == "llm_call" and e.get("stage") == stage]


def _format_row(label: str, hits: int, total: int, score: int, latency_s: float) -> str:
    pct = round(100 * hits / total) if total else 0
    return (
        f"{label:7} extract: {hits}/{total} anchors verified ({pct:>3}%)  "
        f"|  score: {score}  |  latency p50: {latency_s:.1f}s"
    )


async def main() -> int:
    preflight = _preflight()
    if preflight is not None:
        return preflight

    junior_cv = JUNIOR_TXT.read_text(encoding="utf-8")
    senior_cv = SENIOR_TXT.read_text(encoding="utf-8")

    client = LLMClient()
    events: list[dict[str, Any]] = []

    with obs.subscribe(events.append):
        with _stage("spike.junior.extract"):
            junior_extract_raw = await client.complete_json(
                system=EXTRACT_SYSTEM,
                user=f"CV:\n\n{junior_cv}",
                schema=SpikeExtract,
                model="reasoning",
                temperature=0.0,
                max_retries=1,
            )
        with _stage("spike.junior.score"):
            junior_score_raw = await client.complete_json(
                system=SCORE_SYSTEM,
                user=f"CV:\n\n{junior_cv}",
                schema=SpikeScore,
                model="reasoning",
                temperature=0.0,
                max_retries=1,
            )
        with _stage("spike.senior.extract"):
            senior_extract_raw = await client.complete_json(
                system=EXTRACT_SYSTEM,
                user=f"CV:\n\n{senior_cv}",
                schema=SpikeExtract,
                model="reasoning",
                temperature=0.0,
                max_retries=1,
            )
        with _stage("spike.senior.score"):
            senior_score_raw = await client.complete_json(
                system=SCORE_SYSTEM,
                user=f"CV:\n\n{senior_cv}",
                schema=SpikeScore,
                model="reasoning",
                temperature=0.0,
                max_retries=1,
            )

    assert isinstance(junior_extract_raw, SpikeExtract)
    assert isinstance(junior_score_raw, SpikeScore)
    assert isinstance(senior_extract_raw, SpikeExtract)
    assert isinstance(senior_score_raw, SpikeScore)
    junior_extract = junior_extract_raw
    junior_score = junior_score_raw
    senior_extract = senior_extract_raw
    senior_score = senior_score_raw

    j_extract_events = _stage_events(events, "spike.junior.extract")
    j_score_events = _stage_events(events, "spike.junior.score")
    s_extract_events = _stage_events(events, "spike.senior.extract")
    s_score_events = _stage_events(events, "spike.senior.score")

    per_call_durations_ms = [
        sum(int(e["duration_ms"]) for e in j_extract_events),
        sum(int(e["duration_ms"]) for e in j_score_events),
        sum(int(e["duration_ms"]) for e in s_extract_events),
        sum(int(e["duration_ms"]) for e in s_score_events),
    ]
    per_call_event_counts = [
        len(j_extract_events),
        len(j_score_events),
        len(s_extract_events),
        len(s_score_events),
    ]

    junior_hits, junior_total = _count_anchor_hits(junior_extract, junior_cv)
    senior_hits, senior_total = _count_anchor_hits(senior_extract, senior_cv)

    total_anchors = junior_total + senior_total
    verified_anchors = junior_hits + senior_hits
    anchor_rate = verified_anchors / total_anchors if total_anchors else 0.0

    spread = senior_score.score_0_100 - junior_score.score_0_100

    first_try_count = sum(1 for c in per_call_event_counts if c == 1)
    json_survival = first_try_count / 4

    p50_s = statistics.median(per_call_durations_ms) / 1000

    junior_latency_s = statistics.median(per_call_durations_ms[:2]) / 1000
    senior_latency_s = statistics.median(per_call_durations_ms[2:]) / 1000

    print(
        _format_row(
            "junior",
            junior_hits,
            junior_total,
            junior_score.score_0_100,
            junior_latency_s,
        )
    )
    print(
        _format_row(
            "senior",
            senior_hits,
            senior_total,
            senior_score.score_0_100,
            senior_latency_s,
        )
    )
    print(f"JSON-mode failures: {4 - first_try_count}/4 calls")

    gates: list[tuple[str, bool]] = [
        ("anchor-rate", anchor_rate >= ANCHOR_RATE_FLOOR),
        ("spread", spread >= SCORE_SPREAD_FLOOR),
        ("json-survival", json_survival >= JSON_SURVIVAL_FLOOR),
        ("p50-latency", p50_s <= P50_LATENCY_CEILING_S),
    ]
    gate_labels = {
        "anchor-rate": "anchor-rate >=70%?",
        "spread": "spread >=20?",
        "json-survival": "json-survival >=90%?",
        "p50-latency": "p50 <=8s?",
    }
    summary = "  |  ".join(f"{gate_labels[name]} {'YES' if ok else 'NO'}" for name, ok in gates)
    print(f"GATES: {summary}")

    for name, ok in gates:
        if not ok:
            print(f"FAILED GATE: {name}")
            return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
