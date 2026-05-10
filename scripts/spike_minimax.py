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
import json
import os
import statistics
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, ValidationError

from jobfit import obs
from jobfit.llm import LLMClient
from jobfit.verify import verify_quote

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests/fixtures/cvs"
JUNIOR_TXT = FIXTURES / "01_junior_da_novotny.txt"
SENIOR_TXT = FIXTURES / "08_staff_ml_engineer_dvorak.txt"
CV_SPECS = (("junior", JUNIOR_TXT), ("senior", SENIOR_TXT))
CALLS_PER_CV = 2
TOTAL_CALLS = len(CV_SPECS) * CALLS_PER_CV

ANCHOR_RATE_FLOOR = 0.70
SCORE_SPREAD_FLOOR = 20
JSON_SURVIVAL_FLOOR = 0.90
# MiniMax-M2.7-highspeed measured ~13–18s p50 with reasoning_split=True.
# Reasoning is mandatory on this catalog (no non-reasoning sibling); 8s was unreachable.
# Revisit when we swap providers (e.g. Gemini Flash) per follow-up note in T05_spike.md.
P50_LATENCY_CEILING_S = 20.0

EXTRACT_SYSTEM = (
    "You extract structured skills evidence from a CV.\n\n"
    "Return JSON only matching this schema:\n"
    '  {"skills": [{"text": str, "anchor_quote": str}, ...], '
    '"years_experience": int}\n\n'
    "Rules:\n"
    "- `anchor_quote` MUST be a verbatim substring copied from the CV — at least "
    "6 consecutive words, case-preserved, punctuation-preserved. No paraphrasing. "
    "No ellipses. No edits.\n"
    "- Pick a quote that appears in the CV only once. If you cannot guarantee "
    "uniqueness, copy 8 or more consecutive words.\n"
    "- If you cannot find a 6+ word literal substring that supports a skill, drop "
    "that skill entirely. Do not fabricate.\n"
    "- `years_experience` is the candidate's total professional years across "
    "roles, as an integer.\n"
    "- Return raw JSON only. Do not wrap your response in markdown code fences. "
    "Do not include any prose outside the JSON object."
)

SCORE_SYSTEM = (
    "You score a candidate's absolute skills strength on a seniority scale.\n\n"
    "Return JSON only matching this schema:\n"
    '  {"name": "skills", "score_0_100": int, "anchor_quote": str}\n\n'
    "Rules:\n"
    '- `name` is the literal string "skills".\n'
    "- `score_0_100` is an absolute seniority bucket:\n"
    "    0–30  = junior / entry-level (narrow exposure, early career)\n"
    "    31–60 = mid-level (solid working competence, multiple shipped projects)\n"
    "    61–85 = senior (breadth across stack, mentors others, owns systems)\n"
    "    86–100 = staff / principal (deep platform impact, org-wide leverage)\n"
    "- Place the candidate on this absolute scale based on the CV evidence. Do "
    "not center on 50.\n"
    "- `anchor_quote` MUST be a verbatim substring of at least 6 consecutive "
    "words from the CV that justifies the score. Case- and punctuation-preserved. "
    "No paraphrasing.\n"
    "- Pick a quote that appears in the CV only once. If you cannot guarantee "
    "uniqueness, copy 8 or more consecutive words.\n"
    "- Return raw JSON only. Do not wrap your response in markdown code fences. "
    "Do not include any prose outside the JSON object."
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
            f"Set {required} in the environment before running "
            f"(JOBFIT_LLM_PROVIDER={provider}; .env is not auto-loaded)",
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


def _stage_duration_ms(events: list[dict[str, Any]], stage: str) -> int:
    return sum(
        int(e["duration_ms"])
        for e in events
        if e.get("event") == "llm_call" and e.get("stage") == stage
    )


def _format_row(
    label: str,
    hits: int,
    total: int,
    score: int | None,
    latency_s: float,
) -> str:
    pct = round(100 * hits / total) if total else 0
    score_str = "FAIL" if score is None else str(score)
    return (
        f"{label:7} extract: {hits}/{total} anchors verified ({pct:>3}%)  "
        f"|  score: {score_str}  |  latency avg: {latency_s:.1f}s"
    )


async def main() -> int:
    preflight = _preflight()
    if preflight is not None:
        return preflight

    junior_cv = JUNIOR_TXT.read_text(encoding="utf-8")
    senior_cv = SENIOR_TXT.read_text(encoding="utf-8")

    client = LLMClient()
    events: list[dict[str, Any]] = []

    async def _call_extract(stage: str, cv: str) -> SpikeExtract | None:
        with _stage(stage):
            try:
                parsed = await client.complete_json(
                    system=EXTRACT_SYSTEM,
                    user=f"CV:\n\n{cv}",
                    schema=SpikeExtract,
                    model="reasoning",
                    temperature=0.0,
                    max_retries=0,
                )
            except (ValidationError, json.JSONDecodeError):
                return None
        return cast(SpikeExtract, parsed)

    async def _call_score(stage: str, cv: str) -> SpikeScore | None:
        with _stage(stage):
            try:
                parsed = await client.complete_json(
                    system=SCORE_SYSTEM,
                    user=f"CV:\n\n{cv}",
                    schema=SpikeScore,
                    model="reasoning",
                    temperature=0.0,
                    max_retries=0,
                )
            except (ValidationError, json.JSONDecodeError):
                return None
        return cast(SpikeScore, parsed)

    with obs.subscribe(events.append):
        junior_extract = await _call_extract("spike.junior.extract", junior_cv)
        junior_score = await _call_score("spike.junior.score", junior_cv)
        senior_extract = await _call_extract("spike.senior.extract", senior_cv)
        senior_score = await _call_score("spike.senior.score", senior_cv)

    call_results: list[tuple[str, BaseModel | None]] = [
        ("spike.junior.extract", junior_extract),
        ("spike.junior.score", junior_score),
        ("spike.senior.extract", senior_extract),
        ("spike.senior.score", senior_score),
    ]
    failure_count = sum(1 for _, r in call_results if r is None)
    json_survival = (TOTAL_CALLS - failure_count) / TOTAL_CALLS

    successful_durations_ms = [
        _stage_duration_ms(events, stage) for stage, result in call_results if result is not None
    ]
    p50_s = statistics.median(successful_durations_ms) / 1000 if successful_durations_ms else 0.0

    def _avg_latency_s(stages: list[str]) -> float:
        ms = [_stage_duration_ms(events, s) for s in stages]
        return statistics.mean(ms) / 1000 if ms else 0.0

    junior_latency_s = _avg_latency_s(["spike.junior.extract", "spike.junior.score"])
    senior_latency_s = _avg_latency_s(["spike.senior.extract", "spike.senior.score"])

    if junior_extract is not None:
        junior_hits, junior_total = _count_anchor_hits(junior_extract, junior_cv)
    else:
        junior_hits, junior_total = 0, 0
    if senior_extract is not None:
        senior_hits, senior_total = _count_anchor_hits(senior_extract, senior_cv)
    else:
        senior_hits, senior_total = 0, 0

    total_anchors = junior_total + senior_total
    verified_anchors = junior_hits + senior_hits
    anchor_rate = verified_anchors / total_anchors if total_anchors else 0.0

    if junior_score is not None and senior_score is not None:
        spread: int | None = senior_score.score_0_100 - junior_score.score_0_100
    else:
        spread = None

    print(
        _format_row(
            "junior",
            junior_hits,
            junior_total,
            junior_score.score_0_100 if junior_score is not None else None,
            junior_latency_s,
        )
    )
    print(
        _format_row(
            "senior",
            senior_hits,
            senior_total,
            senior_score.score_0_100 if senior_score is not None else None,
            senior_latency_s,
        )
    )
    print(f"JSON-mode failures: {failure_count}/{TOTAL_CALLS} calls")

    gates: list[tuple[str, bool]] = [
        ("anchor-rate", anchor_rate >= ANCHOR_RATE_FLOOR),
        ("spread", spread is not None and spread >= SCORE_SPREAD_FLOOR),
        ("json-survival", json_survival >= JSON_SURVIVAL_FLOOR),
        ("p50-latency", bool(successful_durations_ms) and p50_s <= P50_LATENCY_CEILING_S),
    ]
    gate_labels = {
        "anchor-rate": f"anchor-rate ≥{int(ANCHOR_RATE_FLOOR * 100)}%?",
        "spread": f"spread ≥{SCORE_SPREAD_FLOOR}?",
        "json-survival": f"json-survival ≥{int(JSON_SURVIVAL_FLOOR * 100)}%?",
        "p50-latency": f"p50 ≤{int(P50_LATENCY_CEILING_S)}s?",
    }
    p50_suffix = f" ({p50_s:.1f}s)" if successful_durations_ms else " (n/a)"
    parts = []
    for name, ok in gates:
        verdict = "YES" if ok else "NO"
        suffix = p50_suffix if name == "p50-latency" else ""
        parts.append(f"{gate_labels[name]} {verdict}{suffix}")
    summary = "  |  ".join(parts)
    print(f"GATES: {summary}")

    for name, ok in gates:
        if not ok:
            print(f"FAILED GATE: {name}")
            return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
