- Date: 2026-05-10
- Correction: Flagged `"effortLevel": "max"` as invalid based on the JSON schema's enum (`low|medium|high|xhigh`), but the runtime UI clearly accepts and displays "Max" as the highest tier.
- Pattern: Treating the published settings JSON schema as ground truth for what the runtime accepts.
- Rule: Schema diagnostics are advisory, not authoritative. When a user's existing config "looks invalid" per the schema but the app is running fine, do not propose changes — the schema may lag the runtime, or the value may be a legacy/alias accepted at parse time. Only flag if the user reports a behavior problem.

- Date: 2026-05-10
- Correction: CI went red because MiniMax retired `abab6.5s-chat` and `MiniMax-M1`; pinned model strings in `src/jobfit/llm.py` and `tasks/PLAN.md` were stale. After swapping to `MiniMax-M2.7-highspeed`, a second failure surfaced: M2.x prepends `<think>...</think>` reasoning blocks to chat output, breaking naive `json.loads`.
- Pattern: External model identifiers rot, and reasoning-class models change response shape, not just behavior. Pinning a name with no audit cadence is a latent failure that surfaces as a hard CI break the day the provider rotates the catalog.
- Rule: When pinning a provider-side model identifier, leave a `# re-verify on provider catalog change` comment next to the constant, and re-verify during T05 spike + at every provider release note. When swapping to a reasoning-class model, sanity-check the raw response shape (think-blocks, tool-call wrappers, fenced code) before assuming the parser still works.
