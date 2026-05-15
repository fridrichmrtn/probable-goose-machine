"""L3 — structured profile extraction from a redacted CV.

One MiniMax JSON-mode call against the prompt at `prompts/extract.md`. Every
`ProfileItem` is substring-verified against `redacted.text` and dropped if its
anchor does not survive `verify_quote` (PRD §4.6 hallucination guard).
"""

from __future__ import annotations

import time
from pathlib import Path

from gander import obs
from gander.errors import StageFailure, stage_boundary
from gander.llm import LLMClient
from gander.normalize import normalize_role_with_llm_fallback
from gander.schemas import Profile, ProfileItem, RedactedCV
from gander.verify import drop_unverified

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_LIST_FIELDS: tuple[str, ...] = ("skills", "experience", "education", "soft_signals")


def load_prompt(name: str) -> str:
    """Read a prompt file from src/gander/prompts/."""
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


async def extract_profile(redacted: RedactedCV) -> Profile | StageFailure:
    """Run L3 profile extraction. Returns Profile on success, StageFailure on stage error.

    Verifies every ProfileItem's anchor.quote against `redacted.text` and drops
    unverified items before returning. Emits one `verify` event with aggregate
    kept/dropped counters across all four list fields.
    """
    t0 = time.perf_counter()
    obs.emit("extract", "start", chars=len(redacted.text))

    def _ms() -> int:
        return int((time.perf_counter() - t0) * 1000)

    with stage_boundary("extract") as cm:
        client = LLMClient()
        raw = await client.complete_json(
            system=load_prompt("extract.md"),
            user=redacted.text,
            schema=Profile,
            model="reasoning",
            max_retries=2,
        )
        if not isinstance(raw, Profile):
            raise TypeError(f"complete_json returned {type(raw).__name__}, expected Profile")
        profile = raw

        total_dropped = 0
        total_kept = 0
        kept_lists: dict[str, list[ProfileItem]] = {}
        for field in _LIST_FIELDS:
            items: list[ProfileItem] = getattr(profile, field)
            kept, dropped = drop_unverified(items, redacted.text)
            kept_lists[field] = kept
            total_kept += len(kept)
            total_dropped += dropped

        # Deterministic tenure override (PRD §4.7 + R7 in T28): when L2's
        # date-range parser produced a value, it wins over the LLM's count so
        # salary's years>=10 lift gate cannot be misled by `[YEAR] - [YEAR]`
        # variance. Emit `tenure_override` when |delta| >= 1 — that's the
        # decision-changing threshold for the salary gate.
        update: dict[str, object] = dict(kept_lists)
        if redacted.years_experience_deterministic is not None:
            llm_years = profile.detected_years_experience
            det_years = redacted.years_experience_deterministic
            delta = abs(det_years - llm_years)
            if delta >= 1:
                obs.emit(
                    "extract",
                    "tenure_override",
                    llm=llm_years,
                    deterministic=det_years,
                    delta=delta,
                )
            update["detected_years_experience"] = det_years

        # Role normalization (T27, R4/R5). Runs AFTER the tenure override so the
        # normalizer's seniority signals fire on the trustworthy year count.
        # Pull title candidates from the LLM's experience entries (both summary
        # text and anchor quote — both can carry the role title).
        years_for_normalize = update.get(
            "detected_years_experience", profile.detected_years_experience
        )
        assert isinstance(years_for_normalize, int)
        experience_titles: list[str] = []
        for item in kept_lists["experience"]:
            experience_titles.append(item.text)
            if item.anchor.quote:
                experience_titles.append(item.anchor.quote)
        normalized = await normalize_role_with_llm_fallback(
            profile.detected_role, years_for_normalize, experience_titles
        )
        update["canonical_role"] = normalized.canonical_role
        update["seniority_band"] = normalized.seniority_band
        update["is_management"] = normalized.is_management

        verified = profile.model_copy(update=update)
        obs.emit("extract", "verify", dropped=total_dropped, kept=total_kept)
        obs.emit("extract", "done", duration_ms=_ms(), kept=total_kept)
        return verified

    assert cm.failure is not None  # stage_boundary caught an exception
    return cm.failure
