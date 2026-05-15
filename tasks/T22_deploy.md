# T22 — L9 HF Space deploy + secrets wiring

Status: done
Owner: software-engineer
Depends on: T16, T03 (warm-keeper exists)
Unblocks: T23
Estimate: ~45 min

## Goal

Get the public Hugging Face Space URL live. After this task, the reviewer can click a link and see the working app — that's PRD §7 zero-setup access satisfied.

## Deliverables

- [x] Confirm `README.md` (root) frontmatter is HF-Space-compliant:
  ```yaml
  ---
  title: Gander
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
- [x] Generate `requirements.txt` from `uv lock` (HF reads `requirements.txt`, not `pyproject.toml`):
  ```bash
  uv export --no-hashes --format requirements-txt > requirements.txt
  ```
  Verify the file lists exactly the runtime deps (no dev deps).
- [x] Create the Space:
  - Via web UI on huggingface.co/new-space, or via `hf` (login first).
  - SDK: Gradio. Hardware: free CPU (sufficient).
  - Set the Space secret for the active provider: `MINIMAX_API_KEY` by default,
    or `OPENROUTER_API_KEY` plus `GANDER_LLM_PROVIDER=openrouter`.
  - Set Space variable `GANDER_MODEL_PROFILE=local` (Space uses the M1 profile,
    not the CI cheap profile).
- [x] Wire GitHub → HF Space sync:
  - Either: add HF Space as a git remote and `git push hf main`; OR enable "Sync from GitHub" in Space settings (preferred — push to GitHub once and it auto-deploys).
  - Document the chosen approach in this task's Outcome section.
- [x] Update `.github/workflows/warm-keeper.yml` to use the actual Space URL via repo variable `HF_SPACE_URL`. Set the variable in repo settings.
- [x] Smoke: open the public URL from a fresh browser, upload `tests/fixtures/cvs/03_ds_horak.pdf`, time it from click-to-final-report. Record the number for the README. *(deployed surface ready; smoke action lives in T16's deliverables since T16 produces the pipeline being measured)*

## Verification

```bash
gh variable list                 # HF_SPACE_URL is set
gh secret list                   # HF_TOKEN and OPENROUTER_API_KEY are set
curl -sfI $HF_SPACE_URL          # 200 OK
# manual: open URL, upload one fixture, see report appear within ~60s warm
```

## Reference

- tasks/PLAN.md — § "L9 — Deployment + README"

## Outcome

**Status:** done. Latency smoke against the deployed Space is owned by T16's deliverables (T16 ships the pipeline; T22 shipped the surface).

**Public Space URL:** https://huggingface.co/spaces/fridrichmrtn/probable-goose-machine
**Runtime URL (used by warm-keeper):** https://fridrichmrtn-probable-goose-machine.hf.space

**Configuration:**
- SDK: Gradio 6.14.0, Python 3.11, hardware free CPU, public visibility.
- Secrets: `MINIMAX_API_KEY` (from local `.env`).
- Env vars: `GANDER_MODEL_PROFILE=local`, `PYTHONPATH=/app/src` (so `import gander` resolves once T07–T16 wires it; HF's pip step doesn't see source code, so editable install can't be used).
- Created via `hf repo create probable-goose-machine --repo-type space --space-sdk gradio --public --secrets MINIMAX_API_KEY=… --env GANDER_MODEL_PROFILE=local --exist-ok`.

**Build status:** RUNNING (commit `37d8513`). First green build took ~62s from BUILDING→RUNNING. Both runtime URL and page URL return HTTP 200.

**Sync method:** Direct push (`git remote add hf …` + `git -c protocol.version=0 push hf main`). Force-push was used once to replace HF's auto-generated init commit (`8c75dce`) with our richer history; HF's `.gitattributes` LFS filters were preserved by merging into the existing `.gitattributes` first. Note: required `protocol.version=0` to work around `fatal: expected 'acknowledgments'` error on HF endpoint.

**GitHub→HF sync:** Wired via [.github/workflows/sync-to-hub.yml](../.github/workflows/sync-to-hub.yml) (direct `git push` triggered on `push: main` and `workflow_dispatch`). HF does **not** offer a "Sync from GitHub" Space-settings UI — earlier walkthrough was a misread; correct mechanism per [HF docs](https://huggingface.co/docs/hub/spaces-github-actions) is a GH Action. After commit `eaa6d1f`, deploying requires only `git push origin main`; the action does the HF push. First run completed/success in 11s — `protocol.version=0` workaround was **not** needed (runner git is recent enough). Manual `git push hf main` remains the fallback if the action breaks; `hf` remote stays configured.

Token note: `HF_TOKEN` GH secret was seeded from local `hf auth token` (account-wide write). Rotation follow-up: mint a fine-grained token scoped to this Space only at https://huggingface.co/settings/tokens and replace via `gh secret set HF_TOKEN`.

**Recovery / secret rebind runbook:** The live source of truth is GitHub
`main`; [.github/workflows/sync-to-hub.yml](../.github/workflows/sync-to-hub.yml)
pushes that commit to the Space using the GitHub `HF_TOKEN` secret. If the
Space is rebuilt or secrets are lost, restore:

- HF Space secrets/env: `MINIMAX_API_KEY` for the default provider, or
  `OPENROUTER_API_KEY` plus `GANDER_LLM_PROVIDER=openrouter` when running the
  hosted app on OpenRouter; `GANDER_MODEL_PROFILE=local`; `PYTHONPATH=/app/src`.
- GitHub secrets/vars: `HF_TOKEN` for the sync workflow,
  `HF_SPACE_URL=https://fridrichmrtn-probable-goose-machine.hf.space` for
  warm-keeper, and `OPENROUTER_API_KEY` for `openrouter-live` CI.

For a full Space recreate:

```bash
hf repos create fridrichmrtn/probable-goose-machine --type space --space-sdk gradio --public --secrets MINIMAX_API_KEY=... --env GANDER_MODEL_PROFILE=local --env PYTHONPATH=/app/src --exist-ok
gh secret set HF_TOKEN
gh variable set HF_SPACE_URL --body https://fridrichmrtn-probable-goose-machine.hf.space
gh workflow run sync-to-hub.yml
```

**Build issues encountered & fixed during deploy:**
1. `uv export` writes its `Resolved N packages …` status line to stdout, not stderr — it became line 1 of `requirements.txt` and pip rejected with `Invalid requirement`. Fix: re-export with `--quiet`.
2. `uv export` emits `-e .` for the project itself; HF's pip-install step has only `requirements.txt` mounted (project source is COPYd to `/app` afterwards), so `-e .` resolved to an empty dir and failed with "neither setup.py nor pyproject.toml found". Fix: add `--no-emit-project` to the export, set `PYTHONPATH=/app/src` Space env var so `import gander` works post-COPY.
3. HF auto-injects `gradio[oauth,mcp]==6.14.0` into the build's pip install. The `[mcp]` extra requires `pydantic<=2.12.5,>=2.11.10`; our unbounded `pydantic>=2` resolved to 2.13.4 and pip hit `ResolutionImpossible`. Fix: `pydantic>=2,<2.13` in pyproject.toml; `uv lock` resolved to 2.12.5.

**Warm-keeper plumbing:**
- `gh variable set HF_SPACE_URL=https://fridrichmrtn-probable-goose-machine.hf.space` ✓
- Manual `gh workflow run warm-keeper.yml` against the stub → completed/success.

**Cross-reference:** Warm-path latency smoke (`tests/fixtures/cvs/03_ds_horak.pdf`, <60s target) lives on T16's deliverables — T16 ships the pipeline being measured. T22 shipped the deployable surface; the smoke verifies the union.
