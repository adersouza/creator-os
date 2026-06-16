# Secret Incident Closure - 2026-06-16

Status: `open_p0`

## What Is Confirmed

`ThreadsDashboard` git history contains `.env.production` in these commits:

- `a5c6dcf39c369c2dee8b9eaa74b832359ea0a82e` from 2026-02-18
- `c42e8bfb93fed227d108b3451e9f6b4049bb033c` from 2026-02-18

Current tracked env-like files checked on 2026-06-16:

- `ThreadsDashboard`: no tracked `.env.production`; `.env.example` only, plus normal Supabase migration SQL containing service-role policy names.
- `creator-os`: no tracked `.env.production`; normal Supabase migration SQL containing service-role policy names.
- `reel_factory`: no tracked env-like files found.

This is still a real incident because secrets in git history must be treated as exposed.

## Closure Order

1. Rotate all possibly exposed provider secrets in the provider dashboards.
2. Re-encrypt stored OAuth/user tokens using the new `ENCRYPTION_KEY`.
3. Confirm production, preview, local operator machines, and CI all use the new values.
4. Purge `.env.production` from git history with `git filter-repo` or BFG.
5. Force-push only after coordinating backups, open PRs, and branch owners.
6. Invalidate old clones or require every clone to reclone from the rewritten history.
7. Run full-history secret scanning after the purge.

Do not mark this incident closed before both rotation and history purge are complete.

## Rotate These Secret Families

- Supabase service-role keys.
- Supabase anon/publishable keys if present in the historical file.
- Stripe live/test secret keys and webhook secrets.
- Meta, Instagram, Threads app secrets and access tokens.
- Upstash/QStash tokens and signing keys.
- Vercel tokens and deploy hooks.
- `CRON_SECRET`.
- `ENCRYPTION_KEY`.
- Any MCP, OpenAI, Hugging Face, or local operator keys found in the historical file.

## History Purge Notes

`git-filter-repo` was not installed on this machine when checked on 2026-06-16.

Example purge command after rotation and coordination:

```bash
git filter-repo --path .env.production --invert-paths
```

After rewriting history:

```bash
git log --all --name-only -- .env.production
```

must return no `.env.production` entries.

## Non-Closure Evidence

These are useful but not sufficient:

- Current tree no longer tracks `.env.production`.
- CI secret scanning passes on the current tree.
- `.env.production` is ignored.

Those facts reduce recurrence risk but do not invalidate secrets that were already exposed in history.
