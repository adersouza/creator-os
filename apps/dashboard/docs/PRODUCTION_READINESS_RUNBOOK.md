# Production Readiness Runbook

Use this when moving Juno33 from local confidence to a live production deploy. The static audits prove the code and config are wired correctly; the live audit proves external services answer with the production credentials currently loaded.

## 1. Pre-Deploy Static Checks

Run this from the repo root before deploying:

```bash
npm run audit
```

This covers:

- Vercel cron routes, function duration config, cron auth, and environment docs.
- API auth/signature coverage for sensitive routes.
- Supabase RLS/storage migration readiness.
- Compatibility checks, typecheck, lint, unit tests, and production build.

For a narrower re-check after production hardening changes:

```bash
npm run audit:prod
npm run audit:security
npm run audit:supabase
npm run ai:eval:golden
```

## 2. Database And Storage

Apply the latest Supabase migrations before the first production deploy. The production readiness audit expects the storage readiness migration to exist, and the live audit expects these buckets to exist in the target Supabase project:

- `media`
- `post-media`
- `avatars`
- `whitelabel`

The migration `supabase/migrations/20260510170000_storage_bucket_readiness.sql` creates/normalizes those buckets and policies.

## 3. Production Environment

Load production env values before running live checks. With a linked Vercel project, the usual flow is:

```bash
vercel env pull .env.production.local --environment=production
set -a
source .env.production.local
set +a
npm run audit:live
```

Expected successful output includes:

- `redis: ok`
- `supabase: ok`
- `qstash: ok`

If a service says `skipped`, that environment variable was not loaded. That is acceptable for local development, but not enough for launch confidence.

After the Vercel deployment is live, run the HTTP smoke probe:

```bash
DEPLOY_SMOKE_URL=https://juno33.com npm run audit:deploy-smoke
```

With `CRON_SECRET` loaded, this checks the authenticated job-health route too. Without it, the script still verifies the app shell and public health endpoint.

## 4. Meta, Instagram, And Threads

After production URL or webhook secrets change:

1. Confirm the Meta app dashboard points to the production callback URLs.
2. Confirm `META_WEBHOOK_VERIFY_TOKEN` and `META_APP_SECRET` in Vercel match the Meta app.
3. Run `npm run resubscribe:instagram-webhooks` after loading production Supabase and Meta credentials.
4. Verify at least one real Instagram account and one real Threads account can reconnect, pass token health, and reach the post preflight checker.

The codebase includes webhook subscribe endpoints, but Meta account-level webhook state still needs real app credentials and connected accounts to verify end to end.

## 5. Launch Smoke Tests

Run these on production after deploy:

- Connect one Instagram Business account and one Threads account.
- Create a draft post, run preflight, and confirm token health, media URL accessibility, caption limits, hashtag limits, collaborator limits, paid partnership fields, Trial Reel rules, and Threads rules return actionable results.
- Publish one low-risk Threads post.
- Publish or schedule one low-risk Instagram media post if the connected account has the required permissions.
- Open dashboard all-accounts, group, and individual account views and verify widget actions still route to the expected workflows.
- Open analytics and listening views, create a post idea from an alert, mark an item handled, and confirm the workflow record persists.
- Send one AI command scoped to a single account and one scoped to an account group. Confirm the answer names the scope, cites available data, and admits missing data instead of inventing numbers.
- Run `DEPLOY_SMOKE_URL=https://juno33.com npm run audit:deploy-smoke` and confirm the app shell, public health, and jobs health checks pass.

## 6. Ongoing Monitors

Check these every morning during the first production week:

- Vercel cron executions for publish, scheduler, webhook, analytics, health, inbox, and account-state jobs.
- QStash DLQ count.
- Supabase storage bucket errors.
- Failed Meta webhook deliveries in the Meta dashboard.
- Token health failures and accounts that require reconnect.
- AI golden eval failures after prompt or routing changes.
