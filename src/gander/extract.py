"""L3 — structured profile extraction from a redacted CV.

One OpenRouter JSON-mode call against the prompt at `prompts/extract.md`. Every
`ProfileItem` is substring-verified against `redacted.text` and dropped if its
anchor does not survive `verify_quote` (PRD §4.6 hallucination guard).
"""

from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path

from gander import obs
from gander.errors import StageFailure, stage_boundary
from gander.ingest import LOW_EVIDENCE_MSG
from gander.llm import LLMClient
from gander.normalize import normalize_role_with_llm_fallback
from gander.schemas import Anchor, Profile, ProfileItem, RedactedCV
from gander.verify import drop_unverified, verify_quote

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_LIST_FIELDS: tuple[str, ...] = ("skills", "experience", "education", "soft_signals")

# Composite-evidence weights, post-anchor-verification (T38). Experience is the
# strongest single CV signal; education is the structured second; skills and
# soft_signals are easier to extract incidentally from non-CV text and weight
# accordingly. Threshold of 3 admits 1 experience entry, 1 education + 1 skill,
# 3 skills, etc. — and rejects empty / single-skill profiles that today silently
# produce a fabricated salary.
_CV_EVIDENCE_WEIGHTS: dict[str, int] = {
    "experience": 3,
    "education": 2,
    "skills": 1,
    "soft_signals": 1,
}
MIN_CV_SCORE = 3

_SKILL_TERM_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Python", ("python",)),
    ("SQL", ("sql", "postgresql", "mysql", "bigquery", "snowflake")),
    ("PyTorch", ("pytorch",)),
    ("TensorFlow", ("tensorflow",)),
    ("scikit-learn", ("scikit-learn", "sklearn")),
    ("pandas", ("pandas",)),
    ("Spark", ("spark", "pyspark", "databricks")),
    ("Airflow", ("airflow",)),
    ("dbt", ("dbt",)),
    ("Docker", ("docker",)),
    ("Kubernetes", ("kubernetes",)),
    ("Kafka", ("kafka",)),
    ("MLflow", ("mlflow",)),
    ("LightGBM", ("lightgbm",)),
    ("XGBoost", ("xgboost",)),
    ("Looker", ("looker",)),
    ("Tableau", ("tableau",)),
    ("Power BI", ("power bi", "powerbi")),
    ("AWS", ("aws",)),
    ("Azure", ("azure",)),
    ("GCP", ("gcp", "google cloud")),
    ("Terraform", ("terraform",)),
    ("FastAPI", ("fastapi",)),
    ("LLM", ("llm", "large language model", "large language models")),
    ("RAG", ("rag", "retrieval augmented")),
    ("vector databases", ("vector database", "vector databases")),
)
# Soft-signal needles use a trailing "*" to mark stem matches — e.g. ``mentor*``
# matches "mentor", "mentored", "mentoring", "mentorship". Bare needles are
# exact-word: ``led`` matches "led" but not "ledger".
_SOFT_SIGNAL_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("leadership", ("led", "lead", "managed", "managed two", "řídil", "řídila")),
    ("mentorship", ("mentor*", "coached", "trained", "kouč*", "školil")),
    (
        "stakeholder communication",
        ("stakeholder*", "executive*", "presented", "communicated", "prezentoval*"),
    ),
    ("cross-team work", ("cross-team", "cross functional", "cross-functional", "napříč týmy")),
    ("ownership", ("owned", "ownership", "accountable", "zodpověd*", "vlastnil")),
)
_HEADER_PREFIX = "#"
_BULLET_PREFIXES = ("- ", "* ", "• ", "· ")


def _compile_needle(needle: str) -> re.Pattern[str]:
    if needle.endswith("*"):
        return re.compile(rf"\b{re.escape(needle[:-1])}\w*")
    return re.compile(rf"\b{re.escape(needle)}\b")


def _compile_groups(
    groups: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[tuple[str, tuple[re.Pattern[str], ...]], ...]:
    return tuple(
        (label, tuple(_compile_needle(needle) for needle in needles)) for label, needles in groups
    )


_SKILL_TERM_PATTERNS = _compile_groups(_SKILL_TERM_GROUPS)
_SOFT_SIGNAL_PATTERNS = _compile_groups(_SOFT_SIGNAL_GROUPS)


def _cv_composite_score(kept_lists: dict[str, list[ProfileItem]]) -> int:
    """Sum of best weights for distinct post-verification evidence anchors."""
    evidence_weights: dict[str, int] = {}
    for field in _LIST_FIELDS:
        field_weight = _CV_EVIDENCE_WEIGHTS[field]
        for item in kept_lists[field]:
            key = _evidence_key(item.anchor.quote)
            evidence_weights[key] = max(field_weight, evidence_weights.get(key, 0))
    return sum(evidence_weights.values())


def _evidence_key(quote: str) -> str:
    """Normalize an anchor quote so duplicate evidence counts once."""
    return " ".join(unicodedata.normalize("NFC", quote).casefold().split())


def _strip_bullet(line: str) -> str:
    stripped = line.strip()
    for prefix in _BULLET_PREFIXES:
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip().rstrip(".")
    if len(stripped) > 3 and stripped[0].isdigit() and stripped[1:3] in {". ", ") "}:
        return stripped[3:].strip().rstrip(".")
    return stripped.rstrip(".")


def _iter_anchorable_lines(source: str) -> list[tuple[str, str | None]]:
    """Return source lines long enough to satisfy the verifier's quote floor."""
    candidates: list[tuple[str, str | None]] = []
    section: str | None = None
    for raw_line in source.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith(_HEADER_PREFIX):
            section = stripped.lstrip("#").strip() or None
            continue
        quote = _strip_bullet(stripped)
        if len(quote.split()) >= 6:
            candidates.append((quote, section))
    return candidates


def _matched_labels(
    text: str, patterns: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...]
) -> list[str]:
    """Return labels whose needles match `text` on word boundaries.

    Short cues like ``aws``, ``rag``, ``sql`` need real token boundaries — raw
    substring checks falsely match ``draws``/``storage``/``rags``.
    """
    haystack = unicodedata.normalize("NFC", text).casefold()
    labels: list[str] = []
    for label, label_patterns in patterns:
        if any(pattern.search(haystack) for pattern in label_patterns):
            labels.append(label)
    return labels


def _salvage_item(
    source: str,
    *,
    field: str,
    patterns: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...],
    used_quotes: set[str],
) -> ProfileItem | None:
    for quote, section in _iter_anchorable_lines(source):
        key = _evidence_key(quote)
        if key in used_quotes:
            continue
        labels = _matched_labels(quote, patterns)
        if not labels:
            continue
        if not verify_quote(quote, source, section=section):
            continue
        label_text = ", ".join(labels[:4])
        if field == "skills":
            text = f"Named tooling evidenced in CV: {label_text}"
        else:
            text = f"Professional signal evidenced in CV: {label_text}"
        return ProfileItem(text=text, anchor=Anchor(quote=quote, section=section))
    return None


def _salvage_missing_profile_evidence(kept_lists: dict[str, list[ProfileItem]], source: str) -> int:
    """Rescue skills/soft evidence from long verified CV lines when LLM omitted it.

    This deliberately does not lower the 6-word quote floor. Compact skills
    sections act as cues only; the salvaged item still anchors to a longer
    literal line from the CV.
    """
    added = 0
    used_quotes = {
        _evidence_key(item.anchor.quote) for items in kept_lists.values() for item in items
    }
    salvage_specs = (
        ("skills", _SKILL_TERM_PATTERNS),
        ("soft_signals", _SOFT_SIGNAL_PATTERNS),
    )
    for field, patterns in salvage_specs:
        if kept_lists[field]:
            continue
        item = _salvage_item(source, field=field, patterns=patterns, used_quotes=used_quotes)
        if item is None:
            continue
        kept_lists[field].append(item)
        used_quotes.add(_evidence_key(item.anchor.quote))
        added += 1
        obs.emit(
            "extract",
            "evidence_salvaged",
            field=field,
            section=item.anchor.section,
            quote_words=len(item.anchor.quote.split()),
        )
    return added


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
            model="extract",
            max_retries=2,
            max_tokens=3000,
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

        total_kept += _salvage_missing_profile_evidence(kept_lists, redacted.text)

        # Document-level evidence gate (T38). Per-claim anchor verification can
        # leave a profile completely empty when the upload isn't a CV (or is a
        # CV the extractor failed on); without this gate, downstream stages
        # would fabricate a salary on no evidence. We frame this honestly: we
        # don't know the file is "not a CV", only that we couldn't find the
        # fields we expect — the user message reflects that.
        composite = _cv_composite_score(kept_lists)
        if composite < MIN_CV_SCORE:
            counts = {field: len(kept_lists[field]) for field in _LIST_FIELDS}
            obs.emit(
                "extract",
                "low_evidence",
                composite=composite,
                threshold=MIN_CV_SCORE,
                **counts,
            )
            return StageFailure(
                stage="profile",
                user_message=LOW_EVIDENCE_MSG,
                debug_detail=(
                    f"composite={composite} threshold={MIN_CV_SCORE} "
                    f"kept={counts} dropped={total_dropped}"
                ),
            )

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
        # Pull title candidates from the LLM's experience-entry summaries in
        # CV order. Anchor quotes can be full evidence sentences, so the role
        # normalizer filters and rejects non-title-shaped strings rather than
        # treating arbitrary evidence text as a salary-query role.
        years_for_normalize = update.get(
            "detected_years_experience", profile.detected_years_experience
        )
        assert isinstance(years_for_normalize, int)
        experience_titles: list[str] = []
        for item in kept_lists["experience"]:
            experience_titles.append(item.text)
        normalized = await normalize_role_with_llm_fallback(
            profile.detected_role, years_for_normalize, experience_titles
        )
        update["canonical_role"] = normalized.canonical_role
        update["seniority_band"] = normalized.seniority_band
        update["is_management"] = normalized.is_management
        update["role_normalization_source"] = normalized.source

        verified = profile.model_copy(update=update)
        obs.emit("extract", "verify", dropped=total_dropped, kept=total_kept)
        obs.emit("extract", "done", duration_ms=_ms(), kept=total_kept)
        return verified

    assert cm.failure is not None  # stage_boundary caught an exception
    return cm.failure
