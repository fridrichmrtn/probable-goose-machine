# T45 — Gemini extraction routing + prompt stability

Status: done
Owner: ai-ml-engineer
Depends on: T41
Unblocks: cleaner Profile.pdf / Profile_new.pdf reruns and stable L3 extraction
Estimate: ~75 min

## Goal

Make L3 profile extraction run on Gemini via OpenRouter without moving the
downstream salary, confidence, or growth stages off their configured global
provider. Keep the stage LLM-first: Gemini owns the extraction decision, while
Python keeps verification, schema validation, retries, telemetry, and
fail-closed behavior.

## Findings

Live extraction-only checks against the two local PDFs used deterministic text
ingest, local redaction, and OpenRouter `google/gemini-2.5-flash` for
`extract_profile`.

- `Profile.pdf`: Gemini returned clean JSON, kept 21 anchors, dropped 11
  anchors, preserved 3 education items, and required role-normalization LLM
  fallback from `Senior Manager AI & Data Science` to `head of data science`.
- `Profile_new.pdf`: near-identical source text except duration strings, but
  Gemini kept 18 anchors, dropped 14 anchors, returned 0 verified education
  items, and chose `Data Gardener | AI, Data Science & Engineering` as
  `detected_role`.
- The current prompt still allows unstable behavior around line-wrapped literal
  anchors, stitched sidebar skills, education omission, and role-title choice.
  Fix this at the extraction prompt/model-routing layer rather than adding
  profile-specific Python reconstruction.

## Implementation

- `src/gander/llm.py`: add per-logical-model provider routing so
  `GANDER_LLM_PROVIDER_EXTRACT=openrouter` routes only `model="extract"` calls
  through OpenRouter/Gemini while `GANDER_LLM_PROVIDER` remains the global
  default for other stages.
- `src/gander/normalize.py`: ensure the role canonicalization fallback called
  from extraction uses `model="extract"` so extraction-only Gemini routing also
  covers the profile role-normalization retry.
- `src/gander/prompts/extract.md`: tighten the extraction contract:
  `detected_role` must prefer the most recent formal Work Experience title;
  education must be extracted when the Education/Vzdělání section contains
  degree/program lines with valid 6+ word anchors; short sidebar lines must not
  be stitched together to satisfy the quote floor; and `anchor.section` should
  use the parent CV section when employer subheaders appear inside Work
  Experience.
- `src/gander/extract.py`: keep deterministic code limited to verification and
  fail-closed evidence gates. Do not add education reconstruction or
  source-derived role hints unless a later task explicitly changes the
  extraction architecture.
- `.env.example`: document `GANDER_LLM_PROVIDER_EXTRACT=openrouter` and the
  existing `OPENROUTER_MODEL_EXTRACT` / fallback settings as the recommended
  extraction-only Gemini configuration.

## Verification

- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_llm.py tests/test_extract.py tests/test_normalize.py -m fast --strict-markers -v`
- `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/gander/llm.py src/gander/extract.py src/gander/normalize.py tests/test_llm.py tests/test_extract.py tests/test_normalize.py`
- `UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check src/gander/llm.py src/gander/extract.py src/gander/normalize.py tests/test_llm.py tests/test_extract.py tests/test_normalize.py`
- `UV_CACHE_DIR=/tmp/uv-cache uv run mypy src/gander/llm.py src/gander/extract.py src/gander/normalize.py`
- Optional live check, only with explicit approval to send resume-derived text
  externally: rerun extraction-only validation for `Profile.pdf` and
  `Profile_new.pdf` with `GANDER_LLM_PROVIDER_EXTRACT=openrouter` and confirm
  stable role, non-empty verified education, and materially lower anchor drops.

## Outcome

Implemented on 2026-05-15 as an LLM-first extraction change:

- Added per-logical-model provider routing with
  `GANDER_LLM_PROVIDER_EXTRACT=openrouter`. The configured global provider
  still builds at `LLMClient()` construction time so missing API keys fail fast;
  override providers are built lazily when their logical model slot is used.
- Routed role canonicalization fallback through `model="extract"` so Gemini
  handles the profile extraction retry path too.
- Tightened `extract.md` for multi-column/line-wrapped CV reasoning, literal
  non-stitched anchors, education extraction, parent section naming, and formal
  work-experience role selection.
- Documented the extraction-only OpenRouter/Gemini env setting in
  `.env.example`.
- Verified with focused fast tests, ruff, ruff format check, and mypy. The
  optional private `Profile.pdf` / `Profile_new.pdf` live rerun remains gated on
  explicit approval to send resume-derived text externally.
