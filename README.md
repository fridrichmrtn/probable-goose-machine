---
title: Gander
emoji: 🪿
colorFrom: gray
colorTo: yellow
sdk: gradio
sdk_version: "6.14.0"
app_file: app.py
python_version: "3.11"
pinned: false
---

<p align="center">
  <img src="assets/gander.svg" width="120" alt="Gander logo: a goose with a monocle"/>
</p>

<p align="center"><em>a closer look at any CV</em></p>

**Public Space:** https://huggingface.co/spaces/fridrichmrtn/probable-goose-machine

First request may take about 20 seconds if the Space is asleep; the warm-keeper
cron usually prevents that. Local run:

```bash
uv sync && OPENROUTER_API_KEY=... uv run python app.py
```

Fresh-clone check:

```bash
git clone https://github.com/fridrichmrtn/probable-goose-machine gander
cd gander
uv sync
OPENROUTER_API_KEY=... uv run python app.py
```

Open the printed local Gradio URL, upload `tests/fixtures/cvs/03_ds_horak.pdf`
or another PDF/DOCX CV, and wait for the final report. A healthy run has a
non-empty score (`score.total > 0`) and either populated Salary, Confidence,
and Plan sections or clear inline `StageFailure` copy when a live dependency
does not have enough evidence. The committed PDF/DOCX fixtures use Git LFS; if
a fixture opens as pointer text after cloning, run `git lfs pull`.

## What It Does

Gander accepts a PDF or DOCX CV and returns a seniority report with four blocks:
score, salary range, confidence, and a growth plan. It is built around one rule:
every CV-derived claim must be grounded in a literal quote from the CV.

```
Upload
  -> ingest/redact/profile
  -> score + salary
  -> confidence + growth
  -> report
```

- **Profile** extracts skills, experience, education, soft signals, role,
  country, location, and tenure from the redacted CV.
- **Score** computes a weighted 0-100 score across skills, experience,
  education, and soft signals.
- **Salary** searches live market snippets and asks an LLM to produce a
  source-grounded range.
- **Confidence** judges the salary evidence independently and caps the tier
  when CV parsing was thin.
- **Plan** suggests 3-5 grounded next actions, each tied back to verified CV
  evidence without asking the candidate to redo old work.

### Grounding

Substring verification is the main reliability choice. The extractor and
scorer can only keep an item if its anchor quote appears in the redacted CV.
The verifier also supports section-local matching, so an education quote
cannot accidentally validate against a skills line. See `src/gander/verify.py`.

### Confidence Isolation

The confidence stage does not read the salary estimator's reasoning. It
recomputes an evidence tier from the sources, then deterministic code applies
CV-quality caps when role, location, or score components are weak. See
`src/gander/confidence.py`.

### Observability

Every stage emits structured events for duration, provider usage, token cost
where available, and failure reasons. The UI footer surfaces total latency and
cost for the run. See `src/gander/obs.py` and `src/gander/pipeline.py`.

## Decisions

I started with MiniMax because the project brief rewards practical AI-first
judgment, not defaulting to the most familiar frontier provider. The T05 spike
validated the core jobs on `MiniMax-M2.7-highspeed`: 100% anchor verification
on the junior and senior fixtures, scores of 22 and 87, and average latencies
of 14.9s and 18.3s. Later work moved the runtime to OpenRouter/Gemini so the
same pipeline can run Gemini/Claude-family model slugs without per-provider
SDK branches.

DuckDuckGo/DDGS is deliberately used instead of a paid search API. It keeps the
reviewer setup at zero accounts beyond the LLM key, and it makes the salary
stage easy to run locally. The cost is real: DDG can rate-limit or return thin
results. The salary stage fails closed when fewer than two usable sources
survive, and T37 tracks deterministic DDG cassettes for the live suite.

Gradio on Hugging Face Spaces was chosen for speed and reviewability. The app
is one public URL, one upload control, and no account system. That constraint
kept the product honest: no persistence, no user database, no hidden batch
queue, and no state that would complicate the privacy story.

PII redaction is regex-first rather than LLM-first. Names, emails, phone
numbers, URLs, postal codes, and date-like values are removed before scoring.
This avoids adding another model failure mode at the privacy boundary. It does
not remove every possible demographic or prestige signal, so the report copy
frames outputs as reviewer hypotheses, not authoritative judgments.

The biggest cuts are intentional: no OCR, no auth, no persistence, no batch
mode, no LLM PII pass, and no claim of fairness validation across protected
groups. The pipeline is designed to fail loudly on scanned or low-evidence
files instead of pretending it understood them.

## Providers

Gander uses OpenRouter by default:

```bash
OPENROUTER_API_KEY=...
GANDER_LLM_PROVIDER=openrouter
```

The current supported provider value is `openrouter`.
OpenRouter model slugs may point at Anthropic, Gemini, OpenAI, or other hosted
models, but Gander does not use the direct Anthropic SDK/provider path.

By default, PDF pages are rendered to images and uploaded unredacted to
OpenRouter/Gemini for transcription. DOCX files use deterministic local text
extraction unless `GANDER_DOCX_INGEST_MODE=llm` is set. Uploaded files are not
retained by Gander after processing.

To avoid PDF vision upload and use deterministic local PDF text extraction
instead:

```bash
GANDER_PDF_INGEST_MODE=text uv run python app.py
```

`GANDER_INGEST_MODE` remains as a legacy fallback when file-specific modes are
unset. Private real-CV live testing is opt-in only.

## Deployment Recovery

The public Space page is
`https://huggingface.co/spaces/fridrichmrtn/probable-goose-machine`; the warm
runtime URL is `https://fridrichmrtn-probable-goose-machine.hf.space`.
GitHub `main` is the source of truth. Pushing to `main` triggers
`.github/workflows/sync-to-hub.yml`, which pushes the same commit to the Space
using the GitHub `HF_TOKEN` secret.

Required Hugging Face Space configuration:

- Secret: `OPENROUTER_API_KEY`.
- Variables: `GANDER_MODEL_PROFILE=local` and `PYTHONPATH=/app/src`.

Required GitHub configuration:

- Secret: `HF_TOKEN` with write access to the Space.
- Variable: `HF_SPACE_URL=https://fridrichmrtn-probable-goose-machine.hf.space`
  for the warm-keeper workflow.
- Secret: `OPENROUTER_API_KEY` for the required `openrouter-live` CI job.

Rebind an existing Space through the Space settings page
(`Settings -> Variables and secrets`), then run the sync workflow. To recreate
the Space with the CLI:

```bash
hf repos create fridrichmrtn/probable-goose-machine --type space --space-sdk gradio --public --secrets OPENROUTER_API_KEY=... --env GANDER_LLM_PROVIDER=openrouter --env GANDER_MODEL_PROFILE=local --env PYTHONPATH=/app/src --exist-ok
gh secret set HF_TOKEN
gh variable set HF_SPACE_URL --body https://fridrichmrtn-probable-goose-machine.hf.space
gh workflow run sync-to-hub.yml
```

## Evaluation

Fast unit coverage is the normal local gate:

```bash
uv run pytest -m fast -q
uv run ruff check .
uv run mypy src/
```

Live tests are marked `live` and require provider keys plus network:

```bash
GANDER_LLM_PROVIDER=openrouter OPENROUTER_API_KEY=... uv run pytest -m live -v
```

Corpus regeneration:

```bash
GANDER_LLM_PROVIDER=openrouter OPENROUTER_API_KEY=... uv run python scripts/eval_corpus.py --output-dir reports/repro --allow-provider-upload
```

Corpus regeneration sends the committed fixture CV contents to the configured
LLM provider. Run it only when that provider upload is acceptable for the
fixtures in scope.

Opt-in arbitrary-CV smoke:

```bash
GANDER_SMOKE_CV=/absolute/path/to/cv.pdf GANDER_LLM_PROVIDER=openrouter OPENROUTER_API_KEY=... uv run pytest tests/test_arbitrary_cv_smoke.py -m live -q
```

Current checked-in live corpus numbers are still pending an explicitly
approved fresh provider-upload run; see `reports/SUMMARY.md`. The OpenRouter
defaults use Gemini Flash-Lite primary with Gemini Flash as the per-slot
fallback. The earlier spike that motivated the OpenRouter move measured Gemini
Flash at 1.4s p50 for the four-call extract/score probe, with $0.0043
provider-reported cost for those four calls. MiniMax M2.7-highspeed was slower
on the same probe, around 16.6s p50, but had strong anchor survival.

## Bias And Limits

Gander removes obvious identity and contact fields before scoring, but it
cannot erase every bias channel. Employer names, language patterns, country,
and school names can still leak socioeconomic or prestige signals. The school
prestige smoke test compares the same research CV with and without the MFF UK /
Charles University header and records the score delta; the live number is
captured by `tests/test_bias_smoke.py` / `scripts/run_bias_smoke.py` when keys
are available and provider upload of the paired fixtures has been approved.

Known limitations:

- English and Czech CV shapes have the most coverage; other languages are best
  effort.
- Scanned PDFs are rejected unless their text is selectable.
- Salary quality depends on live search availability.
- Non-CZ market salary support is country-aware, but not yet locally tuned per
  labor market.
- Fairness across protected groups has not been validated.

## Reviewer Cheat Sheet

- **Grounded claims:** `src/gander/verify.py` rejects unverified anchors.
- **Separate confidence:** `src/gander/confidence.py` recomputes evidence
  quality and applies CV-quality caps.
- **Observable pipeline:** `src/gander/obs.py` and `src/gander/pipeline.py`
  emit per-stage cost, latency, and failure signals.
- **Graceful failure:** `StageFailure` blocks render inline without hiding the
  rest of the report.
