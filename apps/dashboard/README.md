# Juno33

**The all-in-one analytics and management dashboard for Threads, Instagram, and beyond.**

Juno33 helps creators and agencies grow their social presence with deep analytics, AI-powered content tools, scheduled posting, competitor tracking, and team collaboration — all from a single operator dashboard.

🌐 **Live:** [juno33.com](https://juno33.com)

---

## ✨ Features

- **Multi-platform analytics** — Threads & Instagram metrics, engagement rates, follower growth, best posting times
- **Scheduled & auto-posting** — Queue posts with smart timing, approval workflows, and multi-platform publishing
- **AI content studio** — Generate ideas, repurpose content, voice/style DNA extraction (Google Gemini)
- **Competitor tracking** — Benchmark against competitors with automated snapshots
- **Social listening** — Keyword/brand monitoring with sentiment analysis and threshold alerts
- **Unified inbox** — Manage conversations across Threads & Instagram, AI reply suggestions, team assignment with live presence
- **Push & email notifications** — Web Push via Service Worker + Resend email with user preference routing
- **Team collaboration** — Invite members, role-based permissions, audit logs
- **Weekly reports** — Automated email digests with PDF export
- **Trend forecasting** — 7-dimension analysis engine with confidence scoring
- **RSS feed auto-posting** — Import RSS feeds into content pipeline for automated publishing
- **Creator hub** — Inspiration feeds, trending content discovery, saved media, hashtag tracking
- **Link-in-bio pages** — Custom branded link pages (`/@handle` or `/l/slug`)
- **Stripe billing** — Pro / Empire tiers with per-seat add-ons
- **GDPR/CCPA compliance** — Full account deletion (20+ tables), data export, token revocation

---

## 🛠 Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | React 19, TypeScript, Vite, Tailwind CSS |
| **UI** | Radix UI primitives, shadcn/ui, Tailwind v4 tokens in `src/index.css` |
| **State** | Zustand, React Context |
| **Backend** | Vercel Serverless Functions (Node.js) |
| **Database** | Supabase (PostgreSQL + Auth + Realtime + Storage) |
| **Cache/Queue** | Upstash Redis (REST) |
| **AI** | Google Gemini (`@google/genai`) |
| **Payments** | Stripe (Checkout, Webhooks, Customer Portal) |
| **Email** | Resend |
| **Monitoring** | Sentry (frontend + serverless) |
| **Product Analytics** | PostHog (user behavior, funnels, session replay) |
| **Deployment** | Vercel (cron jobs, edge headers, rewrites) |
| **Rich Text** | Tiptap |
| **Charts** | Recharts |

---

## 🚀 Getting Started

### Prerequisites

- **Node.js** ≥ 18
- **npm** ≥ 9
- A [Supabase](https://supabase.com) project
- A [Threads/Meta Developer](https://developers.facebook.com) app (for OAuth)
- Optional: Stripe, Upstash Redis, Resend, Sentry, PostHog accounts

### Setup

```bash
# Clone
git clone https://github.com/your-org/ThreadsDashboard.git
cd ThreadsDashboard

# Install dependencies
npm install

# Configure environment
cp .env.example .env
# Edit .env with your values (see ENV.md for full reference)

# Start dev server
npm run dev
```

The app runs at `http://localhost:3000` (Vite dev server). API routes are in `/api` and are served by Vercel in production.

### Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start Vite dev server |
| `npm run build` | Production build |
| `npm run preview` | Preview production build locally |
| `npm test` | Run Vitest in watch mode |
| `npm run test:run` | Run tests once |
| `npm run test:coverage` | Tests with coverage |
| `npm run test:e2e` | Playwright end-to-end tests |

---

## 📁 Project Structure

```
ThreadsDashboard/
├── api/                    # Vercel Serverless Functions (backend)
│   ├── _lib/               # Shared server utilities (supabase, redis, email, encryption)
│   ├── auth/               # OAuth callbacks (Threads, Instagram, Facebook)
│   ├── cron/               # Scheduled cron jobs (16 jobs)
│   ├── threads/            # Threads webhook endpoints
│   ├── instagram/          # Instagram webhook endpoints
│   ├── ai/                 # AI proxy endpoints
│   ├── admin/              # Admin API routes
│   ├── link-page/          # Link-in-bio page renderer
│   ├── subscription.ts     # Stripe checkout & portal
│   ├── webhook.ts          # Stripe webhook handler
│   ├── analytics.ts        # Analytics data API
│   ├── posts.ts            # Post CRUD
│   ├── competitors.ts      # Competitor data API
│   ├── team.ts             # Team management API
│   └── ...
├── src/                    # Frontend source
│   ├── components/         # React components by feature
│   │   ├── glass/          # Glassmorphic design system components
│   │   ├── analytics/      # Charts, metrics, insights
│   │   ├── dashboard/      # Main dashboard views
│   │   ├── settings/       # Settings panels
│   │   ├── ai-studio/      # AI content generation UI
│   │   ├── competitors/    # Competitor tracking UI
│   │   ├── auto-poster/    # Auto-post queue & scheduling
│   │   ├── team/           # Team management UI
│   │   ├── landing/        # Marketing landing page
│   │   └── ...
│   ├── pages/              # Route-level page components
│   ├── hooks/              # Custom React hooks
│   ├── stores/             # Zustand stores
│   ├── lib/                # Utility libraries
│   └── services/           # Frontend API service layer
├── services/               # Shared service layer (client-side)
│   ├── supabase.ts         # Supabase client init
│   ├── api/                # API client functions
│   ├── ai/                 # AI service clients
│   └── ...
├── config/                 # App configuration (Sentry, etc.)
├── contexts/               # React Context providers
├── types/                  # TypeScript type definitions
├── utils/                  # Shared utilities
├── supabase/               # Supabase migrations
│   └── migrations/         # SQL migration files
├── scripts/                # Maintenance & admin scripts
├── public/                 # Static assets
├── vercel.json             # Vercel config (crons, rewrites, headers, functions)
├── src/index.css           # Tailwind v4 theme tokens + app design system
├── vite.config.ts          # Vite configuration
└── package.json
```

---

## 🔐 Environment Variables

See **[ENV.md](./ENV.md)** for the complete environment variable manifest with descriptions and examples.

**Quick summary:**

| Category | Count | Key vars |
|----------|-------|----------|
| Supabase | 4 | `VITE_SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` |
| Threads/Meta | 6 | `THREADS_CLIENT_ID`, `THREADS_CLIENT_SECRET`, `META_APP_SECRET` |
| Instagram | 3 | `INSTAGRAM_CLIENT_ID`, `INSTAGRAM_CLIENT_SECRET` |
| Facebook | 4 | `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET` |
| Stripe | 8+ | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, price IDs |
| Redis | 2 | `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` |
| AI | 1 | `GEMINI_API_KEY` |
| Email | 2 | `RESEND_API_KEY`, `EMAIL_FROM` |
| Cron | 1 | `CRON_SECRET` |
| Monitoring | 3 | `SENTRY_DSN`, `VITE_SENTRY_DSN`, `DISCORD_ALERT_WEBHOOK_URL` |
| Analytics | 2 | `VITE_POSTHOG_KEY`, `VITE_POSTHOG_HOST` |
| Security | 1 | `ENCRYPTION_KEY` |

---

## ☁️ Deployment

Juno33 deploys to **Vercel**:

1. Connect the repo to Vercel
2. Framework preset: **Vite**
3. Build command: `npm run build`
4. Output directory: `dist`
5. Add all environment variables from [ENV.md](./ENV.md) to Vercel project settings
6. Cron jobs are auto-configured via `vercel.json` (24 scheduled jobs)

Before handing the app to real users, run the production checklist in
**[docs/PRODUCTION_READINESS_RUNBOOK.md](./docs/PRODUCTION_READINESS_RUNBOOK.md)**.
The short version is `npm run audit`, then run `npm run audit:live` from an environment
that has the production Vercel/Supabase/Upstash secrets loaded.

### Cron Jobs

| Job | Schedule | Description |
|-----|----------|-------------|
| `webhook-processor` | Every 2 min | Safety net that replays webhook events when inline processing fails |
| `publish-worker` | Every 5 min | Publish scheduled posts |
| `sync-orchestrator` | Every 15 min | Account sync orchestration |
| `analytics-pipeline` | Daily 2 AM | Full analytics aggregation |
| `daily-orchestrator` | Daily 1 AM | Daily maintenance phases |
| `daily-orchestrator-late` | Daily 1:30 AM | Late daily maintenance phases |
| `health-monitor` | Every 4 hours | System health checks |
| `six-hour-pipeline` | Every 6 hours | Mid-frequency maintenance |
| `weekly-reports` | Mon 8 AM | Send weekly email reports |
| `cost-digest` | Daily 8 AM | AI/API cost digest |
| `monthly-kpi` | 1st of month 8 AM | Monthly KPI rollup |
| `trend-scanner` | Every 2 hours | Trend detection |
| `auto-learning` | Daily 6 AM | AI learning and tuning refresh |
| `autoposter-watchdog` | Twice hourly | Autoposter queue health watchdog |
| `auto-reply-worker` | Every 15 min | Auto-reply queue processing |
| `inbox-suggestions` | Every 5 min | Inbox suggestion generation |
| `reply-farming-worker` | Every 30 min | Reply farming queue processing |
| `dawn-planner` | Every 4 hours | Planning refresh |
| `account-state-evaluator` | Every 15 min | Account state scoring |
| `cta-reply-worker` | Twice hourly | CTA reply queue processing |
| `scheduler` | Every 5 min | General scheduled job dispatcher |
| `reconcile-daily` | Daily 3:30 AM | Daily reconciliation |
| `overnight-brief` | Daily 1:55 AM | Overnight brief generation |
| `originality-capture` | Daily 3:17 AM | Originality signal capture |

---

## 🛠 Maintenance Scripts

| Script | Description | Prereqs |
|--------|-------------|---------|
| `npm run resubscribe:instagram-webhooks` | Iterates every row in `instagram_accounts`, decrypts tokens, and re-calls the Meta subscribed_apps endpoints for both Instagram and Facebook login types. Use this after rotating webhook verify tokens or when Meta expires subscriptions. | Requires local `.env` to include `SUPABASE_URL` and a service role key (`SUPABASE_SERVICE_ROLE_KEY` or `SUPABASE_SERVICE_KEY`). No SQL migrations are needed. |
| `npm run audit` | Runs static production, security, Supabase, compatibility, type, lint, test, and build checks. | Local dependencies installed. |
| `npm run audit:live` | Pings live Redis, Supabase Storage buckets, and QStash with the current environment. Missing env values are reported as skipped. | Production env values loaded locally or in CI. |
| `npm run audit:deploy-smoke` | Checks the deployed app shell, public health endpoint, and authenticated job-health endpoint when `CRON_SECRET` is loaded. | `DEPLOY_SMOKE_URL` or `APP_URL` points to the deployed app. |
| `npm run ai:eval:golden` | Runs the AI operator golden tests so command/copilot behavior does not drift into vague or invented answers. | Local dependencies installed. |

Running the script prints a success/failed tally so you can retry any problem accounts manually.

---

## 📖 Architecture

See **[CLAUDE.md](./CLAUDE.md)** and the focused docs under `docs/claude/` for current implementation guidance.

---

## 📄 License

Proprietary. All rights reserved.
