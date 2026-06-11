# Environment Variables Manifest

Complete reference for all environment variables used in Juno33. Variables prefixed with `VITE_` are exposed to the frontend; all others are server-side only.

---

## 🗄 Database (Supabase)

| Name | Required | Description | Example |
|------|----------|-------------|---------|
| `VITE_SUPABASE_URL` | ✅ | Supabase project URL (frontend) | `https://abc123.supabase.co` |
| `VITE_SUPABASE_ANON_KEY` | ✅ | Supabase anonymous/public key (frontend) | `eyJhbGciOi...` |
| `SUPABASE_URL` | ✅ | Supabase project URL (server-side) | `https://abc123.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | Supabase service role key (admin access) | `eyJhbGciOi...` |
| `SUPABASE_SERVICE_KEY` | ❌ | Legacy alias for `SUPABASE_SERVICE_ROLE_KEY` | — |
| `SUPABASE_ANON_KEY` | ❌ | Server-side anon key (fallback) | — |

## 🔐 Auth & Security

| Name | Required | Description | Example |
|------|----------|-------------|---------|
| `ENCRYPTION_KEY` | ✅ | 32-byte base64 key for encrypting stored tokens | `openssl rand -base64 32` |
| `CRON_SECRET` | ✅ | Shared secret to authorize cron job requests | Any random string |

## 🧵 Threads / Meta

| Name | Required | Description | Example |
|------|----------|-------------|---------|
| `VITE_THREADS_CLIENT_ID` | ✅ | Threads app ID (frontend OAuth flow) | `123456789` |
| `THREADS_CLIENT_ID` | ✅ | Threads app ID (server-side) | `123456789` |
| `THREADS_CLIENT_SECRET` | ✅ | Threads app secret | `abc123secret` |
| `VITE_THREADS_REDIRECT_URI` | ✅ | OAuth redirect URI (frontend) | `https://juno33.com/auth/threads/callback` |
| `THREADS_REDIRECT_URI` | ❌ | OAuth redirect URI (server fallback) | `https://juno33.com/auth/threads/callback` |
| `META_APP_SECRET` | ✅ | Meta app secret for webhook HMAC verification | `abc123...` |
| `META_WEBHOOK_VERIFY_TOKEN` | ✅ | Custom token for webhook subscription verification | Any random string |

## 📸 Instagram

| Name | Required | Description | Example |
|------|----------|-------------|---------|
| `VITE_INSTAGRAM_CLIENT_ID` | ✅* | Instagram Basic Display app ID (frontend) | `123456789` |
| `INSTAGRAM_CLIENT_ID` | ✅* | Instagram app ID (server) | `123456789` |
| `INSTAGRAM_CLIENT_SECRET` | ✅* | Instagram app secret | `abc123secret` |
| `VITE_INSTAGRAM_REDIRECT_URI` | ❌ | Instagram OAuth redirect URI | `https://juno33.com/auth/instagram/callback` |
| `INSTAGRAM_REDIRECT_URI` | ❌ | Server-side redirect URI fallback | `https://juno33.com/auth/instagram/callback` |

_*Required if Instagram features are enabled._

## 📘 Facebook

| Name | Required | Description | Example |
|------|----------|-------------|---------|
| `VITE_FACEBOOK_APP_ID` | ✅* | Facebook app ID (frontend, for IG Business) | `123456789` |
| `FACEBOOK_APP_ID` | ✅* | Facebook app ID (server) | `123456789` |
| `FACEBOOK_APP_SECRET` | ✅* | Facebook app secret | `abc123secret` |
| `VITE_FACEBOOK_REDIRECT_URI` | ❌ | Facebook OAuth redirect URI | `https://juno33.com/auth/facebook/callback` |
| `FACEBOOK_REDIRECT_URI` | ❌ | Server-side redirect URI fallback | `https://juno33.com/auth/facebook/callback` |

_*Required if Instagram Business account features are enabled._

## 🔴 Redis (Upstash)

| Name | Required | Description | Example |
|------|----------|-------------|---------|
| `UPSTASH_REDIS_REST_URL` | ✅ | Upstash Redis REST endpoint | `https://us1-abc.upstash.io` |
| `UPSTASH_REDIS_REST_TOKEN` | ✅ | Upstash Redis auth token | `AXxxAAI...` |

## 🤖 AI

| Name | Required | Description | Example |
|------|----------|-------------|---------|
| `GEMINI_API_KEY` | ❌ | Server-side fallback Gemini key (users provide their own) | `AIzaSy...` |

## 💳 Stripe

| Name | Required | Description | Example |
|------|----------|-------------|---------|
| `STRIPE_SECRET_KEY` | ✅ | Stripe secret API key | `sk_live_...` |
| `STRIPE_WEBHOOK_SECRET` | ✅ | Stripe webhook endpoint signing secret | `whsec_...` |
| `STRIPE_PRICE_PRO_MONTHLY` | ✅ | Stripe Price ID for Pro monthly | `price_1Abc...` |
| `STRIPE_PRICE_PRO_YEARLY` | ✅ | Stripe Price ID for Pro yearly | `price_1Abc...` |
| `STRIPE_PRICE_EMPIRE_MONTHLY` | ✅ | Stripe Price ID for Empire monthly | `price_1Abc...` |
| `STRIPE_PRICE_EMPIRE_YEARLY` | ✅ | Stripe Price ID for Empire yearly | `price_1Abc...` |
| `STRIPE_PRICE_EXTRA_ACCOUNT` | ❌ | Stripe Price ID for extra account add-on | `price_1Abc...` |
| `STRIPE_PRICE_EXTRA_TEAM_MEMBER` | ❌ | Stripe Price ID for extra team seat add-on | `price_1Abc...` |
| `VITE_STRIPE_PRO_MONTHLY` | ❌ | Frontend price ID reference (Pro monthly) | `price_1Abc...` |
| `VITE_STRIPE_PRO_YEARLY` | ❌ | Frontend price ID reference (Pro yearly) | `price_1Abc...` |
| `VITE_STRIPE_AGENCY_MONTHLY` | ❌ | Frontend price ID reference (Agency monthly) | `price_1Abc...` |
| `VITE_STRIPE_AGENCY_YEARLY` | ❌ | Frontend price ID reference (Agency yearly) | `price_1Abc...` |
| `VITE_STRIPE_EMPIRE_MONTHLY` | ❌ | Frontend price ID reference (Empire monthly) | `price_1Abc...` |
| `VITE_STRIPE_EMPIRE_YEARLY` | ❌ | Frontend price ID reference (Empire yearly) | `price_1Abc...` |
| `VITE_STRIPE_ADDON` | ❌ | Frontend price ID reference (add-on account) | `price_1Abc...` |

## 📧 Email (Resend)

| Name | Required | Description | Example |
|------|----------|-------------|---------|
| `RESEND_API_KEY` | ✅ | Resend API key for transactional email | `re_abc123...` |
| `EMAIL_FROM` | ❌ | Sender address for emails | `Juno33 <noreply@juno33.com>` |

## 📡 Monitoring & Alerts

| Name | Required | Description | Example |
|------|----------|-------------|---------|
| `VITE_SENTRY_DSN` | ❌ | Sentry DSN for frontend error tracking | `https://abc@o123.ingest.sentry.io/456` |
| `SENTRY_DSN` | ❌ | Sentry DSN for serverless function tracking | `https://abc@o123.ingest.sentry.io/456` |
| `VITE_ENABLE_SENTRY` | ❌ | Enable Sentry in development (`true`/`false`) | `false` |
| `VITE_APP_VERSION` | ❌ | App version reported to Sentry | `2.1.0` |
| `DISCORD_ALERT_WEBHOOK_URL` | ❌ | Discord webhook for server-side alerting | `https://discord.com/api/webhooks/...` |

## 🌐 App & Deployment

| Name | Required | Description | Example |
|------|----------|-------------|---------|
| `APP_URL` | ❌ | Base URL of the app (fallback for email links etc.) | `https://juno33.com` |
| `VERCEL_URL` | Auto | Auto-set by Vercel; used for dynamic base URL | `juno33.vercel.app` |
| `VERCEL_ENV` | Auto | Auto-set by Vercel (`production`/`preview`/`development`) | `production` |
| `VITE_USE_EMULATORS` | ❌ | Use local emulators in dev | `false` |

## ☁️ Cloudflare (Optional)

| Name | Required | Description | Example |
|------|----------|-------------|---------|
| `CLOUDFLARE_WORKER_URL` | ❌ | Cloudflare Worker URL for link page edge cache | `https://deeplink.workers.dev` |
| `CLOUDFLARE_API_KEY` | ❌ | API key for Cloudflare Worker auth | `cf_api_key_...` |

## ⚙️ Tuning

| Name | Required | Description | Example |
|------|----------|-------------|---------|
| `ANALYTICS_CONCURRENCY` | ❌ | Max concurrent accounts in analytics refresh (default: 5) | `5` |
| `SYNC_CONCURRENCY` | ❌ | Max concurrent accounts in sync worker (default: 3) | `3` |
