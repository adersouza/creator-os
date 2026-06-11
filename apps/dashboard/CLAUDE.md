# CLAUDE.md

## Project Overview

Juno33 — Threads & Instagram management SaaS with multi-account support, scheduling, AI content generation, analytics, and cross-posting.

**Stack:** React 19 + Vite + TypeScript + Tailwind v4 | Supabase (PostgreSQL + Auth) | Vercel Serverless
**Production:** https://juno33.com
**Vercel Team:** Vulcan Tech (`team_WBT8LccEmcqg2qWiaPfZaHw6`)
**Vercel Project ID:** `prj_EuuY1qvIjvq7huam0CXsf98RCuox`

## Commands

```bash
npm run dev          # Dev server (port 3000, proxies /api to production)
npm run build        # Production build (ALWAYS run before committing)
npm run compat:check # Lint for banned APIs + broken lazy routes
npx vitest run       # Run unit tests
git push origin main # Auto-deploys to Vercel
```

## Docs Index

Load only the doc that applies to the task:

- [`docs/claude/PATTERNS.md`](docs/claude/PATTERNS.md) — critical code patterns (tokens, lazy imports, accountId ALL, Zod shim, AI streaming, null-safe Supabase, publish helpers)
- [`docs/claude/GOTCHAS.md`](docs/claude/GOTCHAS.md) — error table + platform-specific notes (webhooks, cross-browser, Meta API, Tailwind)
- [`docs/claude/FEATURES.md`](docs/claude/FEATURES.md) — notifications, listening, billing, GDPR, scheduled reports
- [`docs/claude/AUTONOMOUS_OPERATOR.md`](docs/claude/AUTONOMOUS_OPERATOR.md) — autonomous marketing operator rules, phases, tool selection, safety

When working with third-party libraries, APIs, SDKs, setup steps, or version-specific
framework behavior, use Context7 for current documentation before implementing.

UI/design docs that locked old visual directions were removed. For visual work,
trust the current code first (`src/index.css`, shared components, and live
screens), then derive a focused plan from the user's current reference images
or transcript. Do not resurrect old "glassmorphic", Neptune, Raycast, or
mono-label rules from deleted docs.

## Top-Priority Rules (read before acting)

1. **Always `npm run build`** before committing — Vite + Vercel have separate TS.
2. **Zod in API routes**: import from `api/_lib/zod`, not `'zod'` directly.
3. **Supabase `.neq` on nullable columns**: use `neqOrNull` helper — `.neq()` drops NULL rows.
4. **Lazy route paths**: `npm run compat:check` catches broken imports at CI.
5. **`accountId === "ALL"`**: guard on frontend; use `getAccountIdsForContext` on backend.
6. **Core ID columns are TEXT** except `instagram_accounts.id` (UUID). `voice_profile` lives on `account_groups`.
7. **Meta transient errors**: the `code=1, type=OAuthException` is Meta's 500, NOT dead token. See `queue.ts:isOAuthError()`.
8. **Autonomous operator**: starts in DRY_RUN every session. Read `docs/claude/AUTONOMOUS_OPERATOR.md` first.
9. **Tailwind v4**: tokens defined in `src/index.css` via `@theme {}` block. There is NO `tailwind.config.js`. The `withOpacity()` helper from v3 was removed — use `color-mix(in srgb, var(--color-X) Y%, transparent)` directly or the `--alpha(...)` v4 helper. `@theme inline` is **valid** in v4 (older notes that banned it predate the migration).
10. **Agent circuit breaker** (in `api/_lib/agentCircuitBreaker.ts`): 250/hr cap, 3 consecutive failures, 25 dedup, 200/4hr session.
