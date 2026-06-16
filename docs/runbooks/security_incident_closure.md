# Security Incident Closure Runbook

Use this when a real secret file, token, `.env*`, `.mcp.json`, database, or generated export was committed to any Creator OS repository history.

## Required Closure

1. Freeze affected branches and make a backup clone visible only to the owner.
2. Rotate every credential that appeared in the leaked file, including:
   - Stripe live and restricted keys
   - Supabase service-role, anon, and publishable keys when exposed
   - `CRON_SECRET`
   - `ENCRYPTION_KEY`
   - Upstash/QStash/Redis credentials
   - Meta, Instagram, Threads, and Facebook app secrets or access tokens
   - Vercel tokens and webhook secrets
3. Re-encrypt stored OAuth/user tokens with the new `ENCRYPTION_KEY`.
4. Purge repository history with `git filter-repo` or BFG after coordination.
5. Force-push only after all active branches are accounted for.
6. Invalidate or delete old clones and CI caches that may still contain the leaked object.
7. Run:

```bash
pnpm security:secrets
pnpm check:artifacts
```

8. Run a full-history scan against the purged repository before reopening normal work.

## What Not To Do

- Do not assume deleting the latest `.env.production` closes the incident.
- Do not paste leaked values into tickets, chats, reports, logs, or PR comments.
- Do not keep using old OAuth/user token ciphertext after rotating `ENCRYPTION_KEY`.
- Do not merge unrelated feature work during the purge window.

## Current Code Guardrails

- `scripts/security/secret-scan.sh` includes Creator OS-specific secret patterns.
- `scripts/check-runtime-artifacts.sh` rejects tracked env files, `.mcp.json`, DBs, generated outputs, model weights, and runtime media.
- CI runs CodeQL, TruffleHog, Trivy, dependency review, and artifact hygiene checks.

These guardrails prevent recurrence; they do not rotate external credentials.
