# Security Documentation - Juno33

**Last Updated:** April 18, 2026
**Status:** Production

---

## 1. Security Overview

Juno33 is a Threads and Instagram management SaaS platform with multi-account support, scheduling, AI content generation, analytics, and cross-posting.

**Stack:**
- **Frontend:** React 19 + Vite + TypeScript (SPA)
- **Backend:** Supabase (PostgreSQL + Auth) + Vercel Serverless API
- **Production URL:** https://juno33.com
- **Infrastructure:** Vercel (hosting + serverless), Supabase (database + auth), Upstash Redis (job queuing + caching)

---

## 2. Authentication & Authorization

### Supabase Auth (JWT-based)

- All user authentication is handled by Supabase Auth, which issues JWTs upon login
- The frontend stores the session token via the Supabase client SDK
- API routes validate the Bearer token using `getAuthUserOrError(req, res)` from `api/_lib/apiResponse.ts` -- this extracts and verifies the JWT on every request
- If the token is invalid or missing, the API returns 401 immediately

### Authorization Layers

- **User ownership validation:** All data queries are scoped to the authenticated user's ID. Row Level Security (RLS) policies enforce this at the database level.
- **Subscription tier enforcement:** Features are gated by subscription tier (Free / Pro / Empire). The subscription tier is checked from the user's profile before allowing tier-restricted operations (e.g., auto-poster requires Empire, team invites require Pro+).
- **Workspace ownership:** Workspace operations verify the requesting user is either the owner or a member with the appropriate role (owner / admin / member).
- **Platform admin access:** `withAdminRole()` (in `api/_lib/middleware.ts`) gates all `/api/admin/*` routes on (1) caller's user ID appearing in `PLATFORM_ADMIN_IDS` env var and (2) when `REQUIRE_ADMIN_MFA=1` is set, the JWT carrying `aal=aal2` (MFA-verified session). Returns `MFA_ENROLLMENT_REQUIRED` when no TOTP factor exists, `MFA_STEP_UP_REQUIRED` when factor exists but session is stale `aal1`. Operational rollout: enroll TOTP in Settings → Security → set `REQUIRE_ADMIN_MFA=1` → redeploy.
- **Destructive user routes (non-admin):** `requireStepUp(req, res, userId)` middleware enforces MFA on the end-user's own destructive operations (account deletion, subscription cancel, developer API key rotation). Policy: AAL2 passes; AAL1 passes only when the caller has no verified MFA factor (don't lock unenrolled users out of their own account); AAL1 + verified factor returns 403 `MFA_STEP_UP_REQUIRED`. The juno33 frontend handles the 403 via `handleMfaStepUp()` which clears the local session and redirects to `/login` for re-verification.
- **Cron job authentication:** All 17 cron jobs are protected by `verifyCronAuth(req, res)`, which checks the `Authorization: Bearer <CRON_SECRET>` header. Only Vercel's cron scheduler knows this secret.

### Multi-Factor Authentication (TOTP)

- **Factor type:** Supabase-native TOTP (RFC 6238). Enrollment surfaces QR + secret in Settings → Security; verification runs through `supabase.auth.mfa.verify()`.
- **Backup codes:** Ten 12-character hex codes are issued once after first enrollment, stored server-side as `scrypt$16384$8$1$<salt>$<digest>` hashes in the `recovery_codes` table. Plaintext is returned to the user exactly once and never persisted. Users can regenerate (destroys the old set) and the count surfaces in the Settings panel; backend endpoint `/api/auth/mfa-backup` handles `generate` (AAL2-gated), `verify` (deletes the TOTP factor on accept, clearing the gate), and `count`. RLS on `recovery_codes` is service-role only.
- **Login flow:** After password success, if a verified factor exists the frontend freezes on an MFA challenge screen until a valid 6-digit code or backup code is presented. OAuth callback reaches the same gate via `getMfaStatus()`.
- **Session management:** `supabase.auth.signOut({ scope: 'others' })` is wired to Settings → Active session to revoke every other refresh token while keeping the current tab authenticated. `signOut({ scope: 'global' })` is the nuclear "sign out everywhere" in Danger zone.

---

## 3. Data Protection

### Token Encryption at Rest

- All OAuth access tokens (Threads, Instagram, Facebook Page) are encrypted before storage using **AES-256-GCM** (`api/_lib/encryption.ts`)
- Key derivation: **PBKDF2-HMAC-SHA256 with 600,000 iterations** (OWASP 2023 recommendation, `v2` format). Legacy `v1` (100k iterations) tokens remain decryption-compatible but new writes always produce `v2`.
- Fresh 32-byte salt and 12-byte IV per record — derived keys are unique per token, eliminating the GCM nonce-reuse attack class even under birthday-collision odds.
- Ciphertext format: `v2:base64(salt[32] + iv[12] + tag[16] + ciphertext)`
- Derived-key cache (max 500 entries, 60s TTL, configurable via `ENCRYPTION_KEY_CACHE_TTL_MS`) avoids redundant PBKDF2 computations.
- The encryption key (`ENCRYPTION_KEY`) is stored as a Vercel environment variable in a **separate system from Postgres** — a DB dump alone cannot decrypt stored tokens.
- Current state: **0 legacy v1 tokens**, **292 v2 tokens** (as of 2026-04-16).
- **Envelope encryption (in progress):** Phase 0 shipped a tested helper at `api/_lib/envelope.ts` — AES-256-GCM payload + per-row DEK wrapped by a KMS-abstracted client (testable seam for the real AWS KMS binding that lands in Phase 1). Wire format `v3:<kek_version>:<blob>:<iv>:<tag>:<payload>`. Not yet wired to any call site; rollout plan (shadow-write → cutover → backfill → legacy drop, 6 phases, ~6 weeks calendar) lives in `docs/ENVELOPE_ENCRYPTION_PLAN.md`.

### Token Handling Practices

- Tokens are **never logged** -- the structured logger (`api/_lib/logger.ts`) scrubs sensitive fields (`token`, `password`, `secret`, `authorization`, `cookie`) from all log output
- Tokens are passed via **Authorization headers only**, never in URL parameters
- Token decryption happens **exclusively in API routes** (server-side) -- the frontend never has access to raw access tokens
- Token refresh is handled by `api/_lib/cron/token-refresh.ts` within `daily-orchestrator` Phase 11. Refreshes tokens expiring within 10 days; includes a lazy v1→v2 re-encryption pass (up to 100 tokens per run). Alerts via Discord (`alertWarn`) if any batch fails to upgrade legacy tokens (stuck-migration signal).

### Sensitive Data Exclusion

- `.env` files are excluded from version control via `.gitignore`
- No hardcoded API keys or secrets exist in source code
- Environment variables are used for all sensitive configuration
- Environment variable validation runs on startup (`api/_lib/envValidation.ts`) to catch missing required values early

---

## 4. API Security

### CORS Policy

All 33+ API route files return a specific CORS origin:

```
Access-Control-Allow-Origin: https://juno33.com
```

Wildcard (`*`) origins are never used. This prevents cross-origin requests from unauthorized domains.

### Security Headers

The following security headers are configured in `vercel.json` and applied to all responses:

| Header | Value | Purpose |
|--------|-------|---------|
| `X-Frame-Options` | `DENY` | Prevents clickjacking |
| `X-Content-Type-Options` | `nosniff` | Prevents MIME-type sniffing |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains; preload` | Enforces HTTPS |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limits referrer leakage |
| `Permissions-Policy` | Restricted | Limits browser API access |

### Input Validation

- **Zod schemas** are applied to all POST endpoint request bodies (`api/_lib/validation.ts`)
- Invalid input returns a 400 error with a safe, descriptive message (no internal details leaked)
- All user-generated content is sanitized with `sanitizeHtml()` from `api/_lib/sanitize.ts` to prevent XSS

### Error Response Safety

- API handlers use standardized response helpers: `apiError(res, statusCode, message)` and `apiSuccess(res, data)`
- On 500 errors, the API returns `"Internal server error"` -- never `error.message` or stack traces
- Error details are logged server-side via Sentry and the structured logger but never exposed to clients

### Rate Limiting

#### Platform Publishing Limits (Database-Backed)

Rate limits are enforced via **database-backed counters** with row-level locking (no in-memory state that resets between function invocations):

| Platform | Limit | Safety Buffer | Table | Function |
|----------|-------|---------------|-------|----------|
| Threads | 250 posts/day | 200/day, 25/hour | `rate_limit_tracking` | `check_and_increment_rate_limit()` |
| Instagram | 50 posts/day | 25/day | `ig_rate_limit_tracking` | `ig_check_and_increment_rate_limit()` |
| IG Comments | 60/hour, 500/day | -- | `ig_endpoint_rate_limits` | `check_ig_endpoint_limit()` |
| IG Messages | 100/hour | -- | `ig_endpoint_rate_limits` | `check_ig_endpoint_limit()` |
| IG Hashtags | 30/day | -- | `ig_endpoint_rate_limits` | `check_ig_endpoint_limit()` |

**Rate limits fail closed:** If the database function encounters an error, it returns `allowed: false` (deny by default), preventing rate limit bypass on transient failures.

#### API Endpoint Rate Limiting (Redis-Backed)

20 endpoints are protected by **Upstash Redis distributed rate limiting** (`api/_lib/rateLimiter.ts`):

| Endpoint Category | Examples | Limit | Fail Mode |
|---|---|---|---|
| AI generation | `/api/ai/generate`, `/api/ai/stream`, `/api/ai/copilot` | Tier-aware (Free: 20/hr, Pro: 100/hr, Empire: 500/hr) | open |
| AI image gen | `/api/ai/generate-image` | Tier-aware daily (Free: 5/day, Pro: 15, Empire: 50) | open |
| AI analysis | `/api/ai/growth-simulator`, `/api/ai/low-hanging-fruit` | 20-30/hour per user | open |
| Content analysis | `/api/posts/autopsy`, `/api/posts/classify` | 20-30/min per user | open |
| Billing | `/api/subscription` | 10/min per user | **closed** |
| GDPR deletion | `/api/user/delete` | 3/hour per user | **closed** |
| GDPR export | `/api/user/export` | 5/hour per user | **closed** |
| Replies | `/api/replies` | 30/min per user | **closed** |
| Competitor analysis | `/api/competitors/analyze` | 5/hour per user | open |
| Link shortener | `/api/go/[code]`, `/api/go/convert` | 100-1000/hour per IP | open |
| Token refresh | `/api/auth/*/refresh` | 10/hour per user | open |
| Link tracking | `/api/link-page/track` | 100/hour per IP | open |
| Social listening | `/api/listening/monitor` | 60/60s per user | open |

- **Fail mode:** Configurable per-endpoint — `fail-closed` for destructive/billing operations (denies request if Redis unavailable), `fail-open` for read-heavy endpoints
- **Frontend integration:** `RateLimitBanner` component shows remaining quota warnings
- **Response headers:** Returns `X-RateLimit-Remaining` and `X-RateLimit-Reset` timestamps

---

## 5. Webhook Security

### HMAC-SHA256 Verification

Both Threads and Instagram webhook endpoints verify the integrity of incoming requests using HMAC-SHA256 signatures:

- **Threads webhooks** (`api/threads/webhook.ts`): Verifies `X-Hub-Signature-256` header against the payload using `THREADS_APP_SECRET`
- **Instagram webhooks** (`api/instagram/webhook.ts`): Verifies `X-Hub-Signature-256` header using `META_APP_SECRET`

Requests with missing or invalid signatures are rejected with 401.

### Webhook Reliability

- Webhooks return **HTTP 500 on database insert failure** (not 200), which causes Meta to retry the event delivery
- Failed webhook events are queued in `ig_webhook_events` / `threads_webhook_events` tables with retry tracking
- Events exceeding 5 retries are moved to `dead_letter` status for manual review

---

## 6. Database Security

### Row Level Security (RLS)

RLS is enabled on all user-facing tables. Each table has policies that restrict access to the authenticated user's own data:

- Direct ownership: `(SELECT auth.uid())::text = user_id`
- Through relationship: e.g., "view replies on own posts" checks post ownership
- Workspace scoping: workspace-related tables check membership via `is_workspace_member()` SECURITY DEFINER function

All 174 public-schema policies and storage policies are wrapped in `(SELECT auth.uid())` (initPlan) — Postgres evaluates the call once per query rather than once per row, yielding ~100× speedup on analytics JOINs. Migration `20260417010729_fix_rls_initplan_v4.sql`.

### AAL2-gated writes on sensitive tables (defense in depth)

`accounts`, `instagram_accounts`, `api_keys`, and `webhook_subscriptions` carry additional **RESTRICTIVE** policies that AND-stack with the ownership check. Migration `20260418020000_rls_require_aal2_sensitive.sql` adds eight policies that gate DELETE on account tables and INSERT/UPDATE/DELETE on credential-bearing tables behind the `public.aal2_or_no_mfa()` helper (SECURITY DEFINER, STABLE, locked `search_path = public, auth`). The predicate is `(auth.jwt() ->> 'aal') = 'aal2' OR NOT EXISTS (SELECT 1 FROM auth.mfa_factors WHERE user_id = auth.uid() AND status = 'verified')` — so a user with no enrolled factor is unaffected, but once MFA is on, a stolen AAL1 token cannot destroy accounts or rotate credentials. Service role continues to bypass RLS entirely (crons + webhook handlers unaffected).

### Cross-tenant regression testing

`supabase/tests/rls_cross_tenant.test.sql` (v1.2, 11 tables) seeds two fake users (Alice, Bob) and asserts Alice cannot read/update/delete/insert-as Bob across the highest-risk tables: posts, accounts, instagram_accounts, ai_config, account_analytics, workspaces, workspace_members, auto_post_queue, reports, smart_links, recovery_codes. Also asserts anonymous role sees zero rows. Runs in CI on every PR touching `supabase/migrations/**` or `supabase/tests/**` via `.github/workflows/rls-tests.yml` — blocks merge on any isolation failure.

### SECURITY DEFINER Functions

The `workspaces` and `workspace_members` tables had circular RLS recursion (workspaces policy checks workspace_members, and vice versa, causing infinite recursion in PostgREST). This is solved with two SECURITY DEFINER helper functions:

- `is_workspace_member(ws_id TEXT, uid TEXT)` -- bypasses RLS to check membership
- `is_workspace_owner(ws_id TEXT, uid TEXT)` -- bypasses RLS to check ownership

### Service Role Isolation

- The Supabase service role key (`SUPABASE_SERVICE_ROLE_KEY`) is used **only in server-side API routes**
- It is never exposed to the frontend client
- The frontend Supabase client uses only the public anon key
- Server-only tables (webhook events, cron locks, rate limits) have RLS disabled but are only accessible via the service role

---

## 7. Infrastructure Security

### Distributed Cron Locking

All 17 cron jobs use `withCronLock()` from `api/_lib/cronUtils.ts` to prevent concurrent execution:

- Locks are stored in the `cron_locks` table with a TTL (default 55 seconds)
- `acquire_cron_lock()` uses atomic INSERT ... ON CONFLICT with an expiry check
- If the lock is held by another instance, the cron invocation exits gracefully
- Lock health is tracked in `cron_runs` for monitoring

### Dead Letter Queue

Failed items that exceed `MAX_RETRIES` (5) across retry cycles are moved to `dead_letter` status. This applies to:

- `auto_post_queue`
- `ig_webhook_events`
- `threads_webhook_events`
- `ig_pending_containers`

An admin endpoint (`api/admin/dead-letters.ts`) allows listing, retrying, and purging dead letter items.

### Meta API Retry Pattern

All Meta Graph API calls (7 Threads + 34 Instagram) use `withRetry()` from `api/_lib/retryUtils.ts`:

- Retries on: HTTP 429, 500-504, Meta transient error codes, network failures
- Max 5 retries with exponential backoff (1 min, 2 min, 4 min... max 1 hour)
- `isRetryableMetaError()` classifies which errors warrant retry

### Error Reporting

- Server-side errors are reported to **Sentry** (`api/_lib/sentryServer.ts`)
- All cron jobs include Sentry error capturing
- The structured logger writes JSON logs for Vercel's log drain

### Environment Variable Validation

`api/_lib/envValidation.ts` validates grouped environment variables on startup, catching configuration issues before they cause runtime failures.

---

## 8. Dependency Security

### Maintenance Recommendations

- Run `npm audit` monthly to check for known vulnerabilities
- Review and update dependencies quarterly
- Test the application after dependency updates
- Deploy updates to production via the standard git push flow

### Current State

- React 19, Vite, TypeScript -- actively maintained
- Supabase client SDK -- actively maintained
- No known critical vulnerabilities as of last audit

---

## 9. Environment Variables

### Required (Vercel)

| Variable | Purpose |
|----------|---------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-side database access (never expose to client) |
| `ENCRYPTION_KEY` | AES-256 encryption key for token storage |
| `THREADS_CLIENT_ID` | Threads OAuth app ID |
| `THREADS_CLIENT_SECRET` | Threads OAuth app secret |
| `THREADS_WEBHOOK_VERIFY_TOKEN` | Threads webhook subscription verification |
| `THREADS_APP_SECRET` | Threads webhook HMAC-SHA256 verification |
| `INSTAGRAM_CLIENT_ID` | Instagram OAuth app ID |
| `INSTAGRAM_CLIENT_SECRET` | Instagram OAuth app secret |
| `INSTAGRAM_REDIRECT_URI` | Instagram OAuth callback URL |
| `FACEBOOK_APP_ID` | Facebook Login for Instagram Stories |
| `FACEBOOK_APP_SECRET` | Facebook app secret |
| `FACEBOOK_REDIRECT_URI` | Facebook OAuth callback URL |
| `META_APP_SECRET` | Instagram webhook HMAC-SHA256 verification |
| `STRIPE_SECRET_KEY` | Stripe payment processing |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signature verification |
| `CRON_SECRET` | Vercel cron job authorization token |
| `UPSTASH_REDIS_REST_URL` | Redis for job queuing and caching |
| `UPSTASH_REDIS_REST_TOKEN` | Redis authentication |
| `RESEND_API_KEY` | Email service for reports |

### Optional

| Variable | Purpose |
|----------|---------|
| `CLOUDFLARE_WORKER_URL` | Edge cache for link-in-bio pages |
| `CLOUDFLARE_API_KEY` | Cloudflare KV API access |
| `VITE_POSTHOG_KEY` | PostHog product analytics project token (client-side, public) |
| `VITE_POSTHOG_HOST` | PostHog ingest endpoint (defaults to US cloud) |
| `EMAIL_FROM` | Sender address for outbound emails |

### Frontend (.env)

| Variable | Purpose |
|----------|---------|
| `VITE_SUPABASE_URL` | Supabase project URL (public) |
| `VITE_SUPABASE_ANON_KEY` | Supabase anonymous/public key |
| `VITE_THREADS_CLIENT_ID` | Threads OAuth (public) |
| `VITE_THREADS_REDIRECT_URI` | OAuth callback URL |
| `VITE_FACEBOOK_APP_ID` | Facebook Login (public) |
| `VITE_APP_VERSION` | Used by service worker cache busting |

**Important:** Frontend environment variables prefixed with `VITE_` are embedded in the client bundle at build time. Only public/non-sensitive values should use this prefix.

### Product Analytics Privacy

- **PostHog** (`posthog-js`) is used for product analytics and session replay
- Respects the browser's **Do Not Track** setting (`respect_dnt: true`)
- Person profiles are only created for **identified (logged-in) users** — anonymous visitors are not profiled
- All text inputs are **masked** in session recordings (`maskAllInputs: true`)
- **Autocapture is disabled** — only explicit events defined in `ANALYTICS_EVENTS` are tracked
- PostHog project tokens are designed to be public (embedded in client-side JS) and do not grant write access to analytics data

---

## 10. Incident Response

### In Case of Security Breach

**Immediate Actions:**
1. Revoke compromised API keys and rotate all secrets in Vercel environment variables
2. Rotate the `ENCRYPTION_KEY` using the dual-key runbook below — this does **NOT** invalidate tokens; it re-encrypts in place
3. If session tokens are compromised, revoke all Supabase Auth sessions
4. Check Vercel function logs and Sentry for unauthorized access patterns
5. Review Supabase database logs for unusual query patterns

### Key Rotation Runbook (`ENCRYPTION_KEY`)

Use this for both emergency rotation (suspected leak) and routine rotation (quarterly).

**Step 1 — Mint a new key**
```bash
openssl rand -base64 32
```

**Step 2 — Introduce `ENCRYPTION_KEY_NEXT` alongside `ENCRYPTION_KEY`**

Add to `api/_lib/encryption.ts` temporarily:

```ts
function getEncryptionKeys(): string[] {
  const nextKey = process.env.ENCRYPTION_KEY_NEXT;
  const currentKey = process.env.ENCRYPTION_KEY;
  if (!currentKey) throw new Error("ENCRYPTION_KEY not set");
  return nextKey ? [nextKey, currentKey] : [currentKey];
}
// decrypt(): try each key in order, return first that succeeds.
// encrypt(): always uses keys[0] (the NEXT key when present).
```

Deploy. At this point, new writes use the new key; old reads fall back to the old key.

**Step 3 — Re-encrypt in batches**

One-shot script (in `scripts/` or as a dev-only API route): select all `*_encrypted` columns, decrypt, re-encrypt (which now uses the new key), update with optimistic lock on `updated_at`. Process in batches of 500 with a short pause between batches to avoid Supabase connection exhaustion. Tables to cover:
- `accounts.threads_access_token_encrypted`, `accounts.refresh_token_encrypted`
- `instagram_accounts.instagram_access_token_encrypted`
- `instagram_accounts.facebook_page_access_token_encrypted`
- `ai_config.api_key_encrypted` (if set)

**Step 4 — Flip**

Promote `ENCRYPTION_KEY_NEXT` → `ENCRYPTION_KEY`, delete `_NEXT`, revert the dual-key patch. Deploy.

**Step 5 — Rotate the old key out of all backup storage**

Password managers, Vercel rollback snapshots, developer `.env.local` files, CI secrets stores.

**Step 6 — Post-mortem (breach-response only)**

Assume every token was decrypted. Force re-auth for all affected accounts (set `needs_reauth = TRUE` on `accounts` and `instagram_accounts`). Notify affected users per jurisdiction requirements.

**Investigation:**
1. Review Vercel function invocation logs for the affected time period
2. Check Sentry error reports for unusual patterns
3. Analyze Supabase Auth logs for unauthorized sign-ins
4. Review the `cron_runs` table for unexpected cron executions
5. Check dead letter queues for suspicious webhook events
6. Identify scope of breach and affected users

**Recovery:**
1. Deploy patched code (any security fix should be fast-tracked to main)
2. Update RLS policies if data access was circumvented
3. Rotate all OAuth tokens by triggering the token refresh cron
4. Notify affected users if personal data was exposed
5. Document the incident, root cause, and remediation steps

### Emergency Contacts

- **Vercel Dashboard:** https://vercel.com/vulcan-tech
- **Supabase Dashboard:** https://supabase.com/dashboard
- **Stripe Dashboard:** https://dashboard.stripe.com/
- **Sentry Dashboard:** (project-specific URL)
- **GitHub Security Advisories:** https://github.com/security/advisories

---

## 11. Compliance & Data Privacy

### GDPR/CCPA Compliance

- [x] **Account deletion** — `DELETE /api/user/delete` performs cascading deletion in `api/_lib/handlers/user/deletionCascade.ts` across:
  - **Postgres**: 67+ tables in 5 phases
  - **Supabase Auth**: `auth.users` row removed
  - **Supabase Storage**: full purge of `media` bucket under user's folder
  - **Stripe**: subscription cancelled AND customer record deleted (`stripe.customers.del` — full PII wipe)
  - **Upstash Redis**: known user-scoped prefixes + SCAN sweep for `*${userId}*`
  - **Meta OAuth**: tokens revoked via Graph API
  - **IG webhooks**: subscriptions unsubscribed per account
  - Requires email confirmation. Same cascade runs from the Meta data-deletion webhook.
- [x] **Meta Data Deletion Callback** — `POST /api/meta/data-deletion` verifies HMAC-SHA256 signed request, stores `confirmation_code`, returns Meta-compliant status URL, dispatches async cascade via QStash.
- [x] **Data export** — `GET /api/user/export` returns a JSON bundle of all user data (40+ tables, 10k row cap per table) with `Content-Disposition` header for download.
- [x] **Audit logging** — Deletion initiation and data export are logged before execution; audit rows are retained per GDPR Recital 57.
- [x] **Token revocation** — OAuth permissions are revoked on Meta's end during account deletion.
- [x] **Cross-tenant isolation** — 174 RLS policies with initPlan wrapping; pgTAP regression tests in CI.
- [ ] Privacy policy kept up to date
- [ ] Terms of service reviewed

### Stripe PCI Compliance

- No credit card data is stored locally or in the database
- All payment processing is handled by Stripe via their client-side SDK
- Stripe webhook signatures are verified using `STRIPE_WEBHOOK_SECRET`
- Subscription data (tier, customer ID) is stored; payment details are not

---

## 12. Monthly Security Checklist

### Dependencies Audit

```bash
npm audit
npm outdated
```

### Security Review (Quarterly)

- [ ] Review RLS policies for all tables
- [ ] Audit API route authentication checks
- [ ] Check for exposed secrets in code or logs
- [ ] Review OAuth flows for both Threads and Instagram
- [ ] Verify CORS policy on all API routes
- [ ] Check Supabase Storage bucket permissions
- [ ] Review workspace/team access controls
- [ ] Verify webhook HMAC verification is active
- [ ] Check rate limit function behavior (fail-closed)
- [ ] Review Sentry for recurring security-related errors

---

## Security Resources

- [Supabase Auth Documentation](https://supabase.com/docs/guides/auth)
- [Supabase Row Level Security](https://supabase.com/docs/guides/auth/row-level-security)
- [Vercel Security Documentation](https://vercel.com/docs/security)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Meta Graph API Security](https://developers.facebook.com/docs/graph-api/security)
- [Stripe Security Best Practices](https://stripe.com/docs/security/guide)
