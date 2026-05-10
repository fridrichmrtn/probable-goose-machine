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
- Secrets: `MINIMAX_API_KEY` (from local `.env`).
- Env vars: `JOBFIT_MODEL_PROFILE=local`, `PYTHONPATH=/app/src` (so `import jobfit` resolves once T07–T16 wires it; HF's pip step doesn't see source code, so editable install can't be used).
- Created via `hf repo create probable-goose-machine --repo-type space --space-sdk gradio --public --secrets MINIMAX_API_KEY=… --env JOBFIT_MODEL_PROFILE=local --exist-ok`.

**Build status:** RUNNING (commit `37d8513`). First green build took ~62s from BUILDING→RUNNING. Both runtime URL and page URL return HTTP 200.

**Sync method:** Direct push (`git remote add hf …` + `git -c protocol.version=0 push hf main`). Force-push was used once to replace HF's auto-generated init commit (`8c75dce`) with our richer history; HF's `.gitattributes` LFS filters were preserved by merging into the existing `.gitattributes` first. Note: required `protocol.version=0` to work around `fatal: expected 'acknowledgments'` error on HF endpoint.

**GitHub→HF sync:** Wired via [.github/workflows/sync-to-hub.yml](../.github/workflows/sync-to-hub.yml) (direct `git push` triggered on `push: main` and `workflow_dispatch`). HF does **not** offer a "Sync from GitHub" Space-settings UI — earlier walkthrough was a misread; correct mechanism per [HF docs](https://huggingface.co/docs/hub/spaces-github-actions) is a GH Action. After commit `eaa6d1f`, deploying requires only `git push origin main`; the action does the HF push. First run completed/success in 11s — `protocol.version=0` workaround was **not** needed (runner git is recent enough). Manual `git push hf main` remains the fallback if the action breaks; `hf` remote stays configured.

Token note: `HF_TOKEN` GH secret was seeded from local `hf auth token` (account-wide write). Rotation follow-up: mint a fine-grained token scoped to this Space only at https://huggingface.co/settings/tokens and replace via `gh secret set HF_TOKEN`.

**Build issues encountered & fixed during deploy:**
1. `uv export` writes its `Resolved N packages …` status line to stdout, not stderr — it became line 1 of `requirements.txt` and pip rejected with `Invalid requirement`. Fix: re-export with `--quiet`.
2. `uv export` emits `-e .` for the project itself; HF's pip-install step has only `requirements.txt` mounted (project source is COPYd to `/app` afterwards), so `-e .` resolved to an empty dir and failed with "neither setup.py nor pyproject.toml found". Fix: add `--no-emit-project` to the export, set `PYTHONPATH=/app/src` Space env var so `import jobfit` works post-COPY.
3. HF auto-injects `gradio[oauth,mcp]==6.14.0` into the build's pip install. The `[mcp]` extra requires `pydantic<=2.12.5,>=2.11.10`; our unbounded `pydantic>=2` resolved to 2.13.4 and pip hit `ResolutionImpossible`. Fix: `pydantic>=2,<2.13` in pyproject.toml; `uv lock` resolved to 2.12.5.

**Warm-keeper plumbing:**
- `gh variable set HF_SPACE_URL=https://fridrichmrtn-probable-goose-machine.hf.space` ✓
- Manual `gh workflow run warm-keeper.yml` against the stub → completed/success.

**Outstanding (deferred to T16):**
- Warm-path latency smoke with `tests/fixtures/cvs/03_ds_horak.pdf` (<60s target). app.py is currently the 9-line stub, so end-to-end CV upload is meaningless until T16 wires the pipeline.
