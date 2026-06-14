# PR #45 — merge-prep plan (resolve conflicts + address review comments)

PR: `dev/report-ui-html-render` → `main`. State: **CONFLICTING** (main advanced
7 commits via PR #44 "prod-readiness-p2"). 6 review comments (3 bot, 3 owner).

## Goal

Land the HTML-render + UX + e2e work cleanly on top of main's P2 a11y/salary
work, preserving every fix main added, with all gates green.

## Conflict map (verified via dry-run merge, then aborted — tree clean)

Textual conflicts: `src/gander/report.py` (8 regions), `tests/test_render.py` (2).
`app.py`, `README.md` auto-merge. New main files (`test_a11y_contrast.py`,
`.env.example`, `src/gander/llm.py` p2.4) auto-merge cleanly.

## Review comments → resolution

### Bots
- [ ] **#1 Copilot — invalid HTML (report.py `_component_tile_html`):** `<blockquote>`
  nested in `<summary>` (summary = phrasing content only). Move the blockquote OUT
  of `<summary>`; keep a short toggle label in summary. CSS selector
  `.gander-evidence:not([open]) .gander-component-quote` still clamps. Update the
  render unit test + e2e expectation for the new structure.
- [ ] **#2 Copilot — conftest env (tests/e2e/conftest.py:17):** change
  `os.environ["GANDER_SKIP_ENV_CHECK"] = "1"` → `os.environ.setdefault(...)` (match
  test_app_download.py).
- [ ] **#3 Codex — e2e not opt-in:** a bare `pytest` collects + runs e2e and tries
  to launch Chromium. Fix: add `addopts = ["-m", "not e2e"]` to
  `[tool.pytest.ini_options]`. Verified safe: CI passes explicit `-m fast`/`-m live`
  and local gates pass `-m e2e` / `-m "slow and not live"`; argparse last-`-m`-wins
  means explicit selectors override addopts; only bare `pytest` changes (now skips
  e2e). Defense-in-depth: also skip the e2e module if the Chromium binary is absent
  so an explicit `-m e2e` on an un-provisioned box skips instead of erroring.

### Owner (conflict-resolution guidance — keep main's P2 fixes)
- [ ] **#4 app.py:140 disabled-button contrast:** main fixed light disabled to
  `#fed7aa` bg + `#7c2d12` text @ opacity 1 (was `#fff` on `#fdba74` ≈ 1.7:1).
  Auto-merge already keeps main's block — **verify only** that the merged app.py
  carries `background: #fed7aa` + `color: #7c2d12` and NOT `#fdba74`.
- [ ] **#5 report.py:426 tracker live region:** main moved `aria-live` off the pill
  row (whole-row live region re-read all pills every yield). Resolution: drop inline
  `{_CSS}` (branch centralizes CSS into `STYLE`); pill row =
  `role="group" aria-label="Pipeline progress"`; add separate
  `<p class="gander-sr-only" role="status" aria-live="polite">{announcement}</p>`
  via main's `_tracker_announcement` helper. Pull `_tracker_announcement` (main,
  def ~L310) into the file; add `.gander-sr-only` rule into `STYLE`. Keep branch's
  new `render_status()` (additive, unrelated). Net: exactly one `aria-live` in
  `render_tracker` output.
- [ ] **#6 report.py:628 salary caption:** main added `_salary_context_line(role,
  location)` + caption above the range, anchored to `canonical_role`/`detected_role`
  + `detected_location`. Branch's new `render_html`/`render_markdown` drop it.
  Resolution: thread `role`/`location` through BOTH renderers.
  - `_salary_section_html(salary, role=None, location=None)` — adopt main's
    `_salary_context_line` (HTML, emits `<p class="gander-salary-context">`).
  - `_salary_section_md(salary, role=None, location=None)` — add a markdown caption
    analogue (e.g. `_{role} · {location}_` line above the range).
  - `render_html` / `render_markdown` call with `role=salary_role`,
    `location=report.profile.detected_location` (the `salary_role` fallback line is
    already merged in at report.py ~L888).

## report.py conflict resolutions (the 8 regions)

- [ ] **Pill CSS (158-184):** take branch token redesign; main's contrast fix is
  preserved because branch `--g-fg-subtle` (light) = `#667085` (= main's literal),
  4.84:1 on white. Ensure branch keeps a `.pill:focus-visible` rule (main added one).
- [ ] **Clamp + salary-context CSS (272-299):** keep BOTH the branch clamp/disclosure
  CSS and main's `.gander-salary-context` rule — tokenize the latter
  (`color: var(--g-fg-subtle)`) so dark mode is automatic.
- [ ] **Dark blocks (357-401):** take branch (empty) — tokens drive dark mode; the
  tokenized `.gander-salary-context` needs no explicit dark rule.
- [ ] **render_tracker docstring (515-527):** merge wording (global STYLE +
  labelled-group/separate-live-region).
- [ ] **tracker return + render_status (543-567):** see #5.
- [ ] **salary section (639-787):** keep branch HTML family + `_QUOTE_CLAMP_CHARS`;
  apply #1 (blockquote out of summary) + #6 (role/location).
- [ ] **render_html + md serializer + render_markdown (890-1026):** keep branch's
  split renderers; apply #6 to both; discard main's single-renderer call list.

## test conflicts + a NEW semantic break (not flagged by reviewers)

- [ ] **test_render.py (264-366):** keep branch section header + adopt main's 8
  `test_render_tracker_*` a11y tests. **Adapt** the one assertion
  `assert ".gander-sr-only" in out` — under centralized CSS the rule lives in
  `STYLE`, not in `render_tracker` output; assert the class is USED in markup, and
  cover the CSS rule via a STYLE test.
- [ ] **test_render.py (560-624):** keep branch's
  `test_render_html_escapes_html_in_user_content` + adopt main's 6
  `test_render_body_salary_caption_*` tests, **renamed** to call `render_html`
  (branch renamed `render_body`→`render_html`). These verify #6.
- [ ] **test_a11y_contrast.py (auto-merges, but WILL FAIL):**
  `test_skipped_pill_meets_aa` asserts literal `color: #667085` inside `.pill.skipped`,
  but branch tokenized it to `color: var(--g-fg-subtle)`. Value is identical
  (#667085) so contrast still passes; update the test to follow the token (resolve
  `--g-fg-subtle` from light `:root`, assert `.pill.skipped` uses the token, check
  the resolved value ≥ 4.5:1). Keeps the "change colour ⇒ re-check contrast" intent.

## Verification gate (after resolution)

1. `uv run ruff format . && uv run ruff check . && uv run mypy src/`
2. `uv run pytest -m fast` — incl. adopted tracker + salary-caption + contrast tests
3. `uv run pytest -m "slow and not live"` — 31 (LFS materialized)
4. `uv run pytest -m e2e` — clamp/expand + alignment; confirm bare `pytest` now
   deselects e2e
5. Manual: live demo — salary caption shows role · market; tracker announces once;
   long quote clamps + expands; disabled button peach (#fed7aa) not bad-orange.
6. `git merge origin/main` for real on the branch, resolve, commit, push; confirm
   PR #45 flips to MERGEABLE.

## Risks
- Branch tokenized CSS vs main's hardcoded-hex tests → covered above (skipped-pill
  test + sr-only test adaptation). Watch for any other main test asserting a literal
  colour the branch tokenized.
- Two content renderers (HTML/md) can drift on the salary caption — unit-test both.
