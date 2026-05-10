# T22 — L9 HF Space deploy + secrets wiring

Status: todo
Owner: software-engineer
Depends on: T16, T03 (warm-keeper exists)
Unblocks: T23
Estimate: ~45 min

## Goal

Get the public Hugging Face Space URL live. After this task, the reviewer can click a link and see the working app — that's PRD §7 zero-setup access satisfied.

## Deliverables

- [ ] Confirm `README.md` (root) frontmatter is HF-Space-compliant:
  ```yaml
  ---
  title: Job Fit & Salary Estimator
  emoji: 📊
  colorFrom: blue
  colorTo: indigo
  sdk: gradio
  sdk_version: <pinned in pyproject>
  app_file: app.py
  python_version: "3.11"
  pinned: false
  ---
  ```
- [ ] Generate `requirements.txt` from `uv lock` (HF reads `requirements.txt`, not `pyproject.toml`):
  ```bash
  uv export --no-hashes --format requirements-txt > requirements.txt
  ```
  Verify the file lists exactly the runtime deps (no dev deps).
- [ ] Create the Space:
  - Via web UI on huggingface.co/new-space, or via `huggingface-cli` (login first).
  - SDK: Gradio. Hardware: free CPU (sufficient).
  - Set the Space secret: `MINIMAX_API_KEY`. (And `ANTHROPIC_API_KEY` if T05 spike triggered the swap.)
  - Set repo variable `JOBFIT_MODEL_PROFILE=local` (Space uses the M1 profile, not the CI cheap profile).
- [ ] Wire GitHub → HF Space sync:
  - Either: add HF Space as a git remote and `git push hf main`; OR enable "Sync from GitHub" in Space settings (preferred — push to GitHub once and it auto-deploys).
  - Document the chosen approach in this task's Outcome section.
- [ ] Update `.github/workflows/warm-keeper.yml` to use the actual Space URL via repo variable `HF_SPACE_URL`. Set the variable in repo settings.
- [ ] Smoke: open the public URL from a fresh browser, upload `tests/fixtures/cvs/03_ds_horak.pdf`, time it from click-to-final-report. Record the number for the README.

## Verification

```bash
gh variable list                 # HF_SPACE_URL is set
gh secret list                   # MINIMAX_API_KEY is set
curl -sfI $HF_SPACE_URL          # 200 OK
# manual: open URL, upload one fixture, see report appear within ~60s warm
```

## Reference

- tasks/PLAN.md — § "L9 — Deployment + README"

## Outcome

**Status:** in-progress (latency smoke deferred to T16).

**Public Space URL:** https://huggingface.co/spaces/fridrichmrtn/probable-goose-machine
**Runtime URL (used by warm-keeper):** https://fridrichmrtn-probable-goose-machine.hf.space

**Configuration:**
- SDK: Gradio 6.14.0, Python 3.11, hardware free CPU, public visibility.
- Secrets: `MINIMAX_API_KEY` set (from local `.env`).
- Env vars: `JOBFIT_MODEL_PROFILE=local`.
- Created via `hf repo create probable-goose-machine --repo-type space --space-sdk gradio --public --secrets MINIMAX_API_KEY=… --env JOBFIT_MODEL_PROFILE=local --exist-ok`.

**Sync method:** Direct push (`git remote add hf …` + `git -c protocol.version=0 push hf main`). Force-push was used once to replace HF's auto-generated init commit (`8c75dce`) with our richer history; HF's `.gitattributes` LFS filters were preserved by merging into the existing `.gitattributes` first. Note: required `protocol.version=0` to work around `fatal: expected 'acknowledgments'` error on HF endpoint.

**GitHub→HF sync:** Not yet enabled. To switch from manual `git push hf main` to one-push deploys, enable "Sync from GitHub" in Space Settings (browser-only step). Until then, deploys require pushing to both `origin` and `hf`.

**Warm-keeper plumbing:**
- `gh variable set HF_SPACE_URL=https://fridrichmrtn-probable-goose-machine.hf.space` ✓
- Manual `gh workflow run warm-keeper.yml` → completed/success in 7s.

**Outstanding (deferred to T16):**
- First-build status (Space was still building at hand-off; runtime URL returned 503).
- Warm-path latency smoke with `tests/fixtures/cvs/03_ds_horak.pdf` (<60s target). app.py is currently the stub, so end-to-end CV upload is meaningless until T16 wires the pipeline.
