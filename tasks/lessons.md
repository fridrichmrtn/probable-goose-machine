- Date: 2026-05-10
- Correction: Flagged `"effortLevel": "max"` as invalid based on the JSON schema's enum (`low|medium|high|xhigh`), but the runtime UI clearly accepts and displays "Max" as the highest tier.
- Pattern: Treating the published settings JSON schema as ground truth for what the runtime accepts.
- Rule: Schema diagnostics are advisory, not authoritative. When a user's existing config "looks invalid" per the schema but the app is running fine, do not propose changes — the schema may lag the runtime, or the value may be a legacy/alias accepted at parse time. Only flag if the user reports a behavior problem.

- Date: 2026-05-10
- Correction: CI went red because MiniMax retired `abab6.5s-chat` and `MiniMax-M1`; pinned model strings in `src/jobfit/llm.py` and `tasks/PLAN.md` were stale. After swapping to `MiniMax-M2.7-highspeed`, a second failure surfaced: M2.x prepends `<think>...</think>` reasoning blocks to chat output, breaking naive `json.loads`.
- Pattern: External model identifiers rot, and reasoning-class models change response shape, not just behavior. Pinning a name with no audit cadence is a latent failure that surfaces as a hard CI break the day the provider rotates the catalog.
- Rule: When pinning a provider-side model identifier, leave a `# re-verify on provider catalog change` comment next to the constant, and re-verify during T05 spike + at every provider release note. When swapping to a reasoning-class model, sanity-check the raw response shape (think-blocks, tool-call wrappers, fenced code) before assuming the parser still works.

- Date: 2026-05-10
- Correction: Pre-allowed `Bash(codex *)` and `Bash(cd * && codex *)` in `.claude/settings.json`; reviewer flagged it as over-broad for an agent CLI with arbitrary subcommands. Investigation also showed the actual /dev invocation is `printf … | timeout 300 codex exec -C "$WT" -s read-only - 2>&1` — the wildcard didn't reliably match the legitimate use case (right-hand side of a pipe) anyway, so the allow was simultaneously too permissive for ad-hoc use and useless for the real path.
- Pattern: Pre-allowing a CLI by tool-name wildcard (`Bash(<tool> *)`) without checking how it is actually invoked.
- Rule: Before adding a `Bash(<tool> *)` allow, grep skills/scripts/CI for the exact invocation shape. If the actual command involves a wrapper (`timeout`, `cd && …`, pipes, `2>&1`), wildcard-on-tool-name may not match — pre-allowing it is simultaneously useless for the legitimate path and too permissive for ad-hoc use. Allow the narrowest sub-command shape that covers the real use case (e.g. `Bash(codex exec -C * -s read-only -*)` not `Bash(codex *)`).
