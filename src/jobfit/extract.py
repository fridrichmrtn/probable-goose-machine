"""L3 — structured profile extraction from a redacted CV.

One MiniMax JSON-mode call against the prompt at `prompts/extract.md`. Every
`ProfileItem` is substring-verified against `redacted.text` and dropped if its
anchor does not survive `verify_quote` (PRD §4.6 hallucination guard).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import cast

from jobfit import obs
from jobfit.errors import StageFailure, stage_boundary
from jobfit.llm import LLMClient
from jobfit.schemas import Profile, ProfileItem, RedactedCV
from jobfit.verify import drop_unverified

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_LIST_FIELDS: tuple[str, ...] = ("skills", "experience", "education", "soft_signals")


def load_prompt(name: str) -> str:
    """Read a prompt file from src/jobfit/prompts/."""
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
        )
        profile = cast(Profile, raw)

        total_dropped = 0
        total_kept = 0
        kept_lists: dict[str, list[ProfileItem]] = {}
        for field in _LIST_FIELDS:
            items: list[ProfileItem] = getattr(profile, field)
            kept, dropped = drop_unverified(items, redacted.text)
            kept_lists[field] = kept
            total_kept += len(kept)
            total_dropped += dropped

        verified = profile.model_copy(update=kept_lists)
        obs.emit("extract", "verify", dropped=total_dropped, kept=total_kept)
        obs.emit("extract", "done", duration_ms=_ms(), kept=total_kept)
        return verified

    assert cm.failure is not None  # stage_boundary caught an exception
    return cm.failure
