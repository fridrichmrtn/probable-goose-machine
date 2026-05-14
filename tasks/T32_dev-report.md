# T32 dev-report — MiniMax vision capability spike (re-run, 2026-05-14)

**Verdict: Image Understanding quota exists on this MiniMax account, but no
model in this API key's catalog can actually consume it. `MiniMax-Text-01`
(the docs-canonical vision-capable model) is fully plan-gated even for
text-only calls. M2.x models bill against the Image Understanding meter
but have no vision encoder — they silently drop the image and confabulate
plausible-looking text.**

This re-run supersedes the original T32 dev-report (which concluded "no
vision on MiniMax" based on a wrong endpoint guess). The re-run correctly
targets the native `/v1/text/chatcompletion_v2` endpoint AND the
`/anthropic/v1/messages` endpoint per docs, and identifies the actual
blocker: API-key plan tier.

## What was probed (definitive)

- **Endpoints**: `/v1/text/chatcompletion_v2` (MiniMax native) and
  `/anthropic/v1/messages` (Anthropic-compatible shim).
- **Hosts**: `api.minimaxi.chat` and `api.minimax.io` — identical behavior.
- **Content block shapes**:
  - MiniMax `image_url` block with public HTTPS URL (docs-canonical example
    image from `cdn.hailuoai.com`).
  - MiniMax `image_url` block with `data:image/png;base64,...` (200 DPI render).
  - MiniMax `image_url` block with `data:image/png;base64,...` (512px-resized
    render, well under any context-window concern — 48 KB / 64 KB base64).
  - Anthropic `image` block with `source.type=base64`.
- **Models probed**: M2.x line (in catalog), `MiniMax-Text-01`,
  `MiniMax-VL-01`, `MiniMax-VL`, `MiniMax-Vision-01`, `MM-Vision-01`,
  `abab6.5-vision`, `abab6.5s-vision`, `abab7-chat-vision`.

## The `/v1/models` discovery

```json
{
  "object": "list",
  "data": [
    {"id": "MiniMax-M2.7",            "owned_by": "minimax"},
    {"id": "MiniMax-M2.7-highspeed",  "owned_by": "minimax"},
    {"id": "MiniMax-M2.5",            "owned_by": "minimax"},
    {"id": "MiniMax-M2.5-highspeed",  "owned_by": "minimax"},
    {"id": "MiniMax-M2.1",            "owned_by": "minimax"},
    {"id": "MiniMax-M2.1-highspeed",  "owned_by": "minimax"},
    {"id": "MiniMax-M2",              "owned_by": "minimax"}
  ]
}
```

No vision model is listed for this API key. `/v1/models` reflects the
account's *catalog scope*, not the full vendor surface.

## The 2013 vs 2061 distinction

- `2013 invalid params, unknown model 'X'`: identifier `X` does not exist
  anywhere in MiniMax's catalog — or was renamed/deprecated. Examples:
  `MiniMax-VL-01`, `MiniMax-Vision-01`, `abab*-vision`, `abab6.5s-chat`.
  These returned 2013 regardless of endpoint or content shape.
- `2061 your current token plan not support model, MiniMax-Text-01`:
  identifier *does* exist somewhere in MiniMax's catalog but is gated
  outside this account's plan tier. **The same 2061 fires on text-only
  calls** — not vision-specific. The whole model is plan-gated.

This pattern proves `MiniMax-Text-01` is the gating boundary: it exists on
MiniMax's surface, it's the vision-carrying model per official docs, and
it's not in this account's plan.

## The Image Understanding meter / hallucination contradiction

Your platform UI shows: `Image Understanding · 2026/05/14 10:00–15:00 ·
1,294 / 4,500 · 29% Used`. This is real billing data. But none of the M2.x
models actually process images:

- `MiniMax-M2.7` / `M2.7-highspeed`: response is literally
  `"I don't see any image attached to your message."`
- `MiniMax-M2.5`: same in the direct-inspection probe, but under the v2
  spike's transcription prompt it confabulated CV-shaped prose containing
  the generic token `"Data Scientist"` (which the spike's coarse marker
  check mistook for evidence of image consumption). The actual
  `verify_quote` gate scored **0/10 anchors** on all three fixtures.
- `MiniMax-M2.1`: under the transcription prompt, confabulated **a
  chicken liver recipe** in response to a single-column EN Data Scientist
  CV. Definitive proof no pixels reach the model.
- `MiniMax-M2`: silent-drop with the same "I don't see any image" string.

So how does the Image Understanding meter increment? Most likely the meter
counts requests that *contain* image_url content blocks regardless of
whether the model actually consumed them — billing on intent, not on use.
Every M2.x call the v2 spike made (≈ 18 page-calls + diagnostic probes)
carried `image_url` content blocks; all of them billed against the meter;
none of them produced real transcripts. **This is the worst-case dark
pattern**: spend accumulates against image-understanding quota while the
model has no vision encoder.

## 7-gate evaluation: structurally unrunnable

For forensic completeness, the v2 spike did execute all 7 gates against
`MiniMax-M2.5` (which "passed" the coarse marker probe) across the 3
fixtures. Every quality gate failed because the model was hallucinating,
not transcribing:

| Fixture | G1 anchor | G2 column | G3 CZ-tokens | G4 jaccard | G5 cost | G6 p95 | G7 determinism |
|---|---|---|---|---|---|---|---|
| `profile_pdf` (3p multi-col CZ+EN) | FAIL 0/10 | PASS* | FAIL 6 missing | n/a | PASS | FAIL 15.5s | FAIL all pages differ across 3 runs |
| `07_senior_ds_holub` (2p single-col EN) | FAIL 0/10 | n/a | FAIL 3 missing | FAIL 0.001 | PASS | FAIL 15.8s | FAIL |
| `03_ds_horak` (1p single-col EN+CZ) | FAIL 0/10 | n/a | FAIL 3 missing | FAIL 0.000 | PASS | FAIL 16.2s | FAIL |

*G2 PASS is a false positive — sidebar tokens are common LinkedIn
vocabulary that M2.5 generates from priors, not from the actual image.

Total spend on the failed eval: **$0.108 across 18 vision calls**, all
billed against the Image Understanding meter.

## What this means for the vision tier plan

The plan was: "MiniMax is the sole provider; the vision tier uses
`MiniMax-VL-01` (later corrected to `MiniMax-Text-01`) on
`/v1/text/chatcompletion_v2`; no new deps." That path is **not reachable
from this API key without a plan change**. The current key cannot hit any
vision-capable MiniMax model on any endpoint with any content shape.

## Unblock options

Each option resolves the blocker. None should be picked without user
sign-off — the user's no-unprompted-pivots / no-unprompted-deps rules apply.

### Option A: Upgrade the MiniMax plan to unlock `MiniMax-Text-01`

- **What it changes**: removes the 2061 gate on `MiniMax-Text-01`. Vision
  works via the exact transport + payload shape the v2 spike already
  built. Zero code change to the seam.
- **What to check**: the MiniMax platform UI → Plans / Billing → does any
  upgrade option list `MiniMax-Text-01` (or the renamed equivalent) in
  the allowed-models list? Pricing for that tier needs to be visible
  before committing.
- **Re-spike requirement**: after upgrade, re-run
  `scripts/spike_minimax_vision_v2.py` against `MiniMax-Text-01` to
  confirm vision actually works for this account; only after pass does
  T34 wire it.

### Option B: Use a different MiniMax API key (if one with vision exists)

- **What to check**: the MiniMax platform UI → API Keys section — does
  *any* of your existing keys list `MiniMax-Text-01` in its allowed-models
  list? Different keys can be on different plan tiers.
- If yes: drop that key into `.env` as `MINIMAX_API_KEY` and re-spike.

### Option C: Add Anthropic Claude as a vision-only carve-out

- **What it changes**: text stages stay on MiniMax. Only the new
  `complete_vision_text` seam routes to Anthropic via a per-call provider
  override (not a process-wide flip). Single-provider invariant relaxes
  to "single-provider per stage" instead of "single-provider per process."
- **New deps**: `anthropic` (~12 transitive deps), `ANTHROPIC_API_KEY` in
  `.env`.
- **Cost**: Sonnet 4.6 vision is ~$3/1M input + ~$15/1M output → roughly
  $0.20–0.40 per 3-page CV vs MiniMax's $0.058. Above the current
  $0.05/page ceiling — would need an explicit budget bump or a finer-
  grained per-stage budget gate.
- **Why now**: this was withdrawn in the previous plan revision on the
  belief that MiniMax-Text-01 was reachable. With Text-01 confirmed
  plan-gated, Anthropic comes back as a real option.

### Option D: Column-aware text extraction (no vision provider at all)

- **What it changes**: replace the vision tier with
  `pdfplumber.extract_words` bbox-based column detection. Linearize each
  geometric column top-to-bottom, sidebar first.
- **Strength**: no provider dependency, no plan question, no per-call
  cost.
- **Weakness**: brittle for non-LinkedIn layouts; can't help with scanned
  PDFs (the current `SCANNED_MSG` flow stays). For Profile.pdf
  specifically — which is the immediate blocker — this works because
  Profile.pdf is a structured PDF with extractable text runs and clean
  column geometry.

### Option E: Halt the vision tier

- The Profile.pdf bilingual-sidebar blocker stays open; T29 / T30 phase 2
  cannot pass; users with similar LinkedIn-export CVs continue to get
  scrambled L1 transcripts.

## Recommendation

Surface options A–E to the user. The data points strongly toward **Option B
first (cheap diagnostic: does any existing key have Text-01?)**, then **A
or C depending on cost tolerance**. Option D is a real backup that
sidesteps the provider question entirely.

## Files produced this spike

- `scripts/spike_minimax_vision_v2.py` — corrected re-spike (native
  endpoint, host + model probe, 7-gate eval).
- `scripts/inspect_minimax_vision_transcripts.py` — dump raw outputs from
  M2.x / VL / abab variants to expose silent-drop and confabulation.
- `scripts/inspect_minimax_vision_v3.py` — probe public-URL + base64 +
  Anthropic-endpoint variants on Text-01 and M2.5.
- `scripts/inspect_minimax_key_capabilities.py` — `/v1/models` discovery
  + text-only probes proving Text-01 is fully plan-gated (not just
  vision-gated).
- This dev-report.
