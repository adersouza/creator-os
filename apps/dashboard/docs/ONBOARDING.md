# Developer Onboarding Guide

Welcome to the ThreadsDashboard repo for **Juno33** (production: https://juno33.com).

This is a Threads & Instagram management SaaS with multi-account support, scheduling, AI content generation, analytics, cross-posting, and an autonomous marketing operator (autoposter).

---

## Table of Contents

1. [Tech Stack](#tech-stack)
2. [Getting Started](#getting-started)
3. [Directory Structure](#directory-structure)
4. [Architecture Patterns](#architecture-patterns)
5. [Subscription Tiers](#subscription-tiers)
6. [Cron Jobs](#cron-jobs)
7. [Autoposter System](#autoposter-system)
8. [Testing](#testing)
9. [Security](#security)
10. [Notifications](#notifications)
11. [Gotchas That Will Bite You](#gotchas-that-will-bite-you)
12. [Deploy Workflow](#deploy-workflow)
13. [Key Documentation](#key-documentation)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19 + Vite + TypeScript |
| Backend | Vercel Serverless Functions (Node.js) |
| Database | Supabase (PostgreSQL + Auth + Realtime + Storage) |
| Cache / Rate Limiting | Upstash Redis |
| Task Queue | QStash (delayed dispatch) |
| Payments | Stripe |
| AI | Gemini (default) + xAI/Grok (fallback) |
| Monitoring | Sentry, PostHog, Discord alerts |
| Hosting | Vercel (auto-deploys from `main`) |

---

## Getting Started

### Prerequisites

- Node.js (LTS)
- npm
- Git access to the repository

### Setup

```bash
npm install
npm run dev          # Dev server on port 3000, proxies /api to production
npm run build        # MUST pass before every commit
npx vitest run       # Unit tests (1074+)
git push origin main # Auto-deploys to Vercel
```

The dev server proxies API requests to production Vercel, so you do not need local Supabase or backend services for frontend work.

---

## Directory Structure

```
ThreadsDashboard/
├── src/                          # All frontend code
│   ├── components/               # 31 subdirectories of React components
│   ├── hooks/                    # 7 directories of custom hooks
│   ├── stores/                   # 7 Zustand stores
│   ├── pages/                    # 7 page directories
│   ├── lib/                      # Utilities (posthog, uuid, metricRegistry)
│   └── types/                    # TypeScript types (supabase.ts is auto-generated)
├── services/                     # Frontend services (root level, NOT in src/)
├── contexts/                     # React contexts (root level)
├── api/                          # Vercel serverless functions
│   ├── _lib/                     # Shared backend code
│   │   ├── handlers/{dir}/       # Route handlers (lazy-imported)
│   │   └── cron/                 # Cron sub-handlers (not HTTP-callable)
│   └── {dir}.ts                  # Thin router files
├── docs/                         # Documentation
├── scripts/                      # Utility scripts (health-check.sql, etc.)
└── CLAUDE.md                     # Full project reference (source of truth)
```

---

## Architecture Patterns

### API Route Pattern

Thin router files at `api/{dir}.ts` switch on `req.query.action` and lazy-import handlers from `api/_lib/handlers/{dir}/`. Vercel rewrites in `vercel.json` map `/api/{dir}/:action` to `/api/{dir}?action=:action`, so frontend URLs stay clean.

```typescript
// api/posts.ts (thin router)
const { handler } = await import("./_lib/handlers/posts/someAction");
```

### Auth

Every API route uses the standardized helpers:

```typescript
import { apiError, apiSuccess, getAuthUserOrError } from './_lib/apiResponse';

const user = await getAuthUserOrError(req, res);
if (!user) return; // already sent 401
// ... logic ...
return apiSuccess(res, data);
```

### Import Alias

`@` = project root. Always include `src/` in the path:

```typescript
import { cn } from '@/src/lib/utils';    // CORRECT
import { cn } from '@/lib/utils';        // WRONG
```

### Token Encryption

```typescript
import * as crypto from "crypto";  // MUST use * as for Vercel compatibility
// NEVER decrypt on frontend -- only in API routes
```

### State Management

Zustand stores (migrated from Context). `ThemeContext` and `PreferencesContext` are intentionally kept as React contexts.

### Realtime Subscriptions

All Supabase Realtime subscriptions go through `services/realtimeManager.ts`:

```typescript
subscribe(key, factory, onReconnect?)  // refcounted, abort-signal safe
```

### UI Components

Built on **uitripled** (207 components) + **shadcn/ui** (Radix wrappers) + **Framer Motion**. Always prefer these over custom code.

### Meta API Retry

```typescript
import { withRetry, isRetryableMetaError } from './_lib/retryUtils';
const data = await withRetry(() => fetchFromMeta(url), { isRetryable: isRetryableMetaError });
```

---

## Subscription Tiers

| Tier | Accounts | Team Members | Autoposter |
|---|---|---|---|
| Free | 1 | -- | No |
| Pro | 5 | 4 | No |
| Empire | Unlimited | Unlimited | Yes |

Billing is via Stripe. Stripe webhooks handle `payment_failed` transitions. `enforceAccountLimits()` deactivates excess accounts on downgrade.

---

## Cron Jobs

All defined in `vercel.json`, authenticated via `verifyCronAuth` + `CRON_SECRET`. Sub-handlers live in `api/_lib/cron/` (not HTTP-callable, only imported by orchestrators).

| Job | Schedule | Purpose |
|---|---|---|
| `publish-worker` | */5 min | Publishes scheduled posts |
| `webhook-processor` | */2 min | Processes queued webhooks |
| `sync-orchestrator` | */15 min | Account data sync |
| `daily-orchestrator` | 1 AM | 12-phase daily maintenance |
| `health-monitor` | */4 hr | System health checks |
| `six-hour-pipeline` | */6 hr | Mid-frequency maintenance |
| `trend-scanner` | */2 hr | Trend detection |
| `analytics-pipeline` | 2 AM | Daily analytics aggregation |
| `weekly-reports` | Mon 8 AM | Weekly report generation |
| `monthly-kpi` | 1st of month 8 AM | Monthly KPI rollup |

---

## Autoposter System

The autoposter is the autonomous content engine. It has a two-table config:

- `auto_post_config` -- workspace-level gateway (on/off for the whole workspace)
- `auto_post_group_config` -- per-group settings (content strategy, schedule, caps)

Both must be enabled for posts to flow.

### Pipeline

```
AI generates content
  -> Regex blacklist filter (free)
  -> LLM judge scorer (5-dimension: hook/voice/safety/quality/novelty)
  -> Embedding dedup check
  -> Insert into auto_post_queue
  -> QStash dispatches at scheduled time
  -> Publish to Threads/Instagram
  -> Engagement sync at 1h/6h/24h post-publish
```

### AI Providers

- **Gemini** (default)
- **xAI/Grok** (fallback, minimal content filtering)
- Auto-fallback to Gemini on xAI failure

### Content Scoring Thresholds

- Overall score >= 3.5 to pass
- Safety < 3: hard fail
- Voice < 2: hard fail

---

## Testing

| Command | Purpose |
|---|---|
| `npx vitest run` | Run all unit tests (1074+) |
| `npm run build` | Build check (MUST pass before committing) |
| `npm run compat:check` | Greps for banned patterns (`crypto.randomUUID()`, `Array.at()`) |

Always run `npm run build` before committing. The Vite build compiles frontend; Vercel compiles API routes separately with its own TypeScript.

---

## Security

| Measure | Detail |
|---|---|
| CORS | Locked to `https://juno33.com` |
| Token storage | Encrypted at rest (AES-256-GCM), never logged |
| Webhook verification | HMAC-SHA256 (Threads + Instagram) |
| Rate limiting | Upstash Redis on 48 endpoints |
| User content | `sanitizeHtml()` on all user input |
| RLS | Row-level security on all Supabase tables |

---

## Notifications

Discord only. Push and email delivery were removed in April 2026.

All alerts fire through `api/_lib/deliverNotification.ts` via `alerting.ts` for 8 critical event types.

---

## Gotchas That Will Bite You

These are real production issues that have caused outages or bugs. Read all of them.

### 1. Column types: TEXT vs UUID

Core IDs (`profiles`, `accounts`, `posts`, `workspaces`, `account_groups`) are **TEXT**. But `instagram_accounts.id` is **UUID**. Never mix them. RLS policies require a cast:

```sql
auth.uid()::text = user_id
```

### 2. Zod on Vercel

Vercel bundles TS 5.9, which crashes on certain Zod methods. Always cast:

```typescript
// WRONG -- crashes on Vercel
platform: z.enum(["threads", "instagram"])

// CORRECT
platform: (z as any).enum(["threads", "instagram"])
```

This applies to `z.enum()`, `z.literal()`, `z.unknown()`, and `z.record()`.

### 3. accountId === "ALL"

When no specific account is selected, `accountId` is `"ALL"`. Backend must use the workspace-scoped resolver:

```typescript
import { getAccountIdsForContext } from './_lib/workspaceAccounts';
const accountIds = await getAccountIdsForContext(userId, workspaceId, platform);
```

Frontend must guard with an early return:

```typescript
if (!accountId || accountId === "ALL") {
  setData(null);
  return;
}
```

### 4. voice_profile location

`voice_profile` lives on `account_groups`, NOT `accounts`. Querying `accounts.voice_profile` will fail silently or error.

### 5. Supabase .neq() excludes NULLs

`.neq("col", "val")` compiles to `col <> 'val'`, which returns NULL (not true) for NULL rows, excluding them from results. Fix:

```typescript
.or("col.is.null,col.neq.val")
```

### 6. Meta transient errors

```
"An unknown error has occurred (code=1, type=OAuthException)"
```

This is Meta's **transient 500**, NOT a dead token. Do not flag `needs_reauth`. See `queue.ts:isOAuthError()` for the canonical check.

### 7. crypto.randomUUID()

Breaks Safari <15.4. Always import from the polyfill:

```typescript
import { randomUUID } from '@/src/lib/uuid';
```

Never call `crypto.randomUUID()` directly.

### 8. Array.at() is banned

ES2022-only, breaks older browsers. Use:

```typescript
arr[arr.length - 1]   // instead of arr.at(-1)
```

### 9. tokens.css

Never use `@layer base` wrapper in `tokens.css`. It causes a PostCSS error.

### 10. Vercel build times

Builds take approximately 10 minutes. Always run `npm run build` locally before pushing to catch errors early.

---

## Deploy Workflow

1. Run `npm run build` locally -- must pass
2. Run `npx vitest run` -- tests must pass
3. Push to `main` -- auto-deploys to Vercel
4. After deploy completes (~10 min), run `scripts/health-check.sql` against the database
5. Verify DB config matches code defaults

There is no staging environment. `main` is production.

---

## Key Documentation

| Document | Location | Purpose |
|---|---|---|
| `CLAUDE.md` | Project root | **Source of truth** -- full project reference |
| `API_REFERENCE.md` | `docs/` | All 260+ API endpoints |
| `ARCHITECTURE_DIAGRAMS.md` | `docs/` | Mermaid diagrams of system flows |
| `threads-api.md` | `docs/` | Threads API v1.0 reference |
| `instagram-api.md` | `docs/` | Instagram API v25.0 reference |
| `THREADS_OPS_TRACKER.md` | `docs/` | Operational priorities and status |

When in doubt, start with `CLAUDE.md`. It covers every pattern, gotcha, and architectural decision in the project.
