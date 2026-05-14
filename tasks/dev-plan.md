# dev-plan — Gander UI polish, pass 2

Source of truth: `/home/mf/.claude/plans/i-want-ux-engineer-jolly-wadler.md`.
One commit, CSS + small handler refactor only. No backend / schema / test changes.

## Files to modify

| Path | Steps that touch it | Expected net delta |
|------|---------------------|--------------------|
| `app.py` | Steps 1, 2, 3, 4, 6 | ~+10 lines net (~30 changed) |
| `src/gander/report.py` | Step 5 | ~+22 lines (appended to `_CSS`) |

No other files change. No tests added or modified.

## Ordered checklist of edits

Tick in order. Each item cites the source step and the file:line range from the approved plan's §3 / §4.

### Step 1 — Kill the orange overlay (F1)
- [ ] `app.py:~101` — add `show_progress="hidden"` to `file_in.change(...)`.
- [ ] `app.py:~134` — add `show_progress="hidden"` to `run_btn.click(...)`.
- [ ] Checkpoint 1: refresh, upload CV, click Analyze. No amber bar above/below tracker or report during streaming. CSS pill pulse continues.

### Step 2 — Hide empty outputs pre-click (F2)
- [ ] `app.py:~98` — declare `tracker_html = gr.HTML(value="", visible=False, elem_classes=["gander-output"])`.
- [ ] `app.py:~99` — declare `report_md = gr.Markdown(value="", visible=False, elem_classes=["gander-output"])`.
- [ ] `app.py:~108–132` — rewrite all 4 `yield` statements in `handle()` to use `gr.update(visible=..., value=...)` per §3 Step 2 snippet. Cover: no-file-selected branch, OSError branch, first "Reading file…" yield, and the in-loop streaming yield.
- [ ] Checkpoint 2: refresh; pre-click layout is hero → file input → caption → Analyze button with no dead vertical band. On click, pill row + "*Reading file…*" appear together.

### Step 3 — Disabled-button visibility + primary color shift (F3, F4)
- [ ] `app.py:~61–67` — replace primary-button CSS in `_HERO_CSS` with the 4-rule block from §3 Step 3:
  - base: `background: #92400e !important; border-color: #92400e !important; color: #ffffff !important;`
  - hover: `#7c2d12`
  - focus-visible: `outline: 2px solid #1d4ed8; outline-offset: 2px;` (keep existing)
  - `:disabled` (new): `background: #fdba74 !important; border-color: #fdba74 !important; color: #ffffff !important; cursor: not-allowed; opacity: 0.85;`
- [ ] Checkpoint 3: pre-upload button is light-amber `#fdba74` with `not-allowed` cursor; after upload it flips to `#92400e`; hover → `#7c2d12`; focus ring blue in both modes.

### Step 4 — Responsive hero + hero dark-mode (F7, F8)
- [ ] `app.py:~50` — add `flex-wrap: wrap;` to `.gander-hero` rule alongside the existing `display: flex; align-items: center; gap: 1.25rem;`.
- [ ] `app.py:~70` (new, end of `_HERO_CSS`) — append `@media (prefers-color-scheme: dark) { ... }` block per §3 Step 4 covering: `.gander-hero h1` `#f4f4f5`, `.gander-hero p` `#d4d4d8`, `.gander-hero .mascot` `#d4d4d8`, `.gander-caption` `#a1a1aa`, plus a dark `button.primary:disabled` override (`#7c2d12` bg/border, `#fed7aa` text, `opacity: 0.7`).
- [ ] Checkpoint 4: resize to <400 px width → mascot + headline wrap cleanly. Toggle OS to dark + hard refresh → hero text legible, no contrast collapse.

### Step 5 — Report body max-width + table borders + report dark-mode (F5)
- [ ] `src/gander/report.py:~99` (end of `_CSS`) — append the four blocks per §3 Step 5:
  - `.gander-output .prose, .gander-output .md { max-width: 72ch; margin-inline: auto; }`
  - `.gander-output table { border-collapse: collapse; margin: 0.5rem 0; }`
  - `.gander-output th, .gander-output td { border: 1px solid #e4e7ec; padding: 0.4rem 0.6rem; text-align: center; }`
  - `@media (prefers-color-scheme: dark) { ... }` — `.pill` base + `.pending` / `.running` / `.done` / `.failed` / `.skipped` palette, `.gander-callout` dark-red, and `.gander-output th, .gander-output td { border-color: #3f3f46; }`.
- [ ] Checkpoint 5: full E2E run; score table has 1 px borders; report body bounded to ~720 px on wide windows and centered. Dark mode → pills/table/callouts use dark palette.

### Step 6 — Caption copy (F6)
- [ ] `app.py:~96` — update caption HTML to: `PDF or DOCX, max 10 MB. Text-based PDFs only — scanned/image PDFs aren't supported. Not retained after processing.`
- [ ] Checkpoint 6: refresh; caption reads as a single line that mentions scanned/image PDFs.

## Tests to write or update

**No test changes.** Rationale (verified against §1 and §8 of the source plan):
- All edits are CSS additions inside string literals plus handler-yield wrapper changes that produce the same rendered Markdown / HTML strings.
- `tests/test_render.py` uses substring assertions over `render_body()` / `render_tracker()` output; appending rules to `_CSS` and toggling Gradio component visibility do not affect those substrings.
- No `tests/test_app.py` exists; Gradio handler shape is not under test.

## Risks to keep visible during implementation

(Verbatim from §7 of source plan.)

| Risk | Likelihood | Impact | Mitigation |
|------|:----------:|:------:|------------|
| `gr.update(visible=True, value=...)` doesn't compose with AsyncIterator yields | Low | High | Verified `update()` exists at helpers.py:1075; this is the documented streaming pattern. If Checkpoint 2 fails, fall back to `visible=True` always + CSS `:has(:empty)` collapse. |
| `show_progress="hidden"` also hides genuinely useful runtime info | Low | Low | Pill tracker + footer cost/latency cover it. Follow-up to `"minimal"` if users miss it. |
| Dark-mode `prefers-color-scheme` fires inside Gradio's iframe but Gradio also applies its own dark class | Medium | Medium | Media queries don't compete with classes; both apply. If contrast still fails, follow up with `.dark .gander-hero h1 { ... }` selectors. |
| `.gander-output .prose` selector misses Gradio's actual markdown wrapper class | Medium | Low | Audit confirmed `.md.prose`; dual selector covers both. Dev tools to confirm if max-width misses. |
| Disabled-state CSS leaks to non-primary buttons | Very low | Low | All rules scoped to `button.primary` / `.gradio-container button.primary`. |
| `gr.update` import not needed | n/a | n/a | `gr.update` lives on the already-imported `gr` namespace. |

## Pre-merge verification

Implementer-run gates (must pass before review):
- [ ] `pre-commit run --all-files`
- [ ] `uv run pytest -m fast`

User-run manual browser pass (matrix from §6 of source plan):

| Surface | Light pre-click | Light streaming | Light done | Dark pre-click | Dark streaming | Dark done |
|---------|:--:|:--:|:--:|:--:|:--:|:--:|
| Hero | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| File input | ✓ | n/a | n/a | ✓ | n/a | n/a |
| Caption | ✓ | n/a | n/a | ✓ | n/a | n/a |
| Analyze button | ✓ (disabled) | ✓ (disabled during stream) | ✓ (enabled) | ✓ | ✓ | ✓ |
| Pill row | hidden | visible+pulse | all done | hidden | visible+pulse | all done |
| Report body | hidden | "Generating…" | full report | hidden | "Generating…" | full report |

Run path: cold load → upload `Profile.pdf` → click Analyze → wait for pipeline → repeat with OS dark mode toggled.
