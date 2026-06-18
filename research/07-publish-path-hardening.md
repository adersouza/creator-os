# Research 07 — Publish-Path Hardening: Errors, Retry, Idempotency, Tokens (2026)

> Owner-supplied research (two deliverables consolidated). 100% legitimate publish-worker engineering. Feeds AUTOPOSTER_HARDENING_PLAN AP1.

## Container model (both platforms)
- **IG:** `POST /<IG_ID>/media` (create) → `GET /<container>?fields=status_code` (poll) → `POST /<IG_ID>/media_publish` (creation_id). Host `graph.facebook.com` / `graph.instagram.com`.
- **Threads:** `POST /<uid>/threads` → `GET /<container>?fields=status,error_message` → `POST /<uid>/threads_publish`. Host `graph.threads.net/v1.0/`. Wait ~30s before publish.
- Status enum (both): `IN_PROGRESS / FINISHED / ERROR / EXPIRED / PUBLISHED`. **Poll once/min, ≤5 min.** Containers expire 24h. **creation_id is one-time-use** — on ERROR/EXPIRED, create a NEW container, never re-publish a failed one.
- Threads `error_message` enum on ERROR: `FAILED_DOWNLOADING_VIDEO`, `FAILED_PROCESSING_VIDEO/AUDIO`, `INVALID_ASPEC_RATIO`(sic), `INVALID_BIT_RATE/DURATION/FRAME_RATE/AUDIO_CHANNELS`, `UNKNOWN`.

## Error taxonomy (drive retry from this)

**TRANSIENT — exponential backoff + full jitter (base ~2s, cap ~5–10min, ~5–8 attempts):**
`1` (API unknown), `2` (service unavailable), `4`/2207051 (`is_transient:true`, app rate limit), `17` (user rate limit), `32` (page limit), `341` (app limit), `368`/1390008 (temp policy block — investigate if recurring), `80001–80014` (BUC rate codes), `613` (calls limit), `9007`/2207027 (media not ready → **poll, don't blind-retry**), `-1`/2207001/2207082/2207053 (server-side publish fail → retry/recreate), `25`/2207050 (account restricted — verify).

**WINDOW-CAP — requeue with delay, NOT immediate retry:**
`9`/2207042 (IG daily publishing cap). Before retry, query the limit endpoint; publish only when `quota_usage < quota_total`.

**TOKEN — refresh then retry once, else dead-letter to re-auth queue:**
`190`/463 (expired) or near-expiry → refresh + retry. `190` no-subcode / 467 (invalid) / 460 (password changed) / 458 (app not installed) / 490 (checkpoint) / `102` (session) / refresh-failed → **dead-letter, user re-auth**.

**PERMANENT — dead-letter immediately (capture message/error_user_msg/fbtrace_id):**
`100` (bad param), `9004`/2207052 (media URI invalid), `352`/2207026 (unsupported format), `10`/200–299 (permission/scope), `506` (duplicate post — backstop only).

**`is_transient` flag:** positive hint only (code 4 sets it); not exhaustive (9007/2207001 don't). Never the sole basis to dead-letter.

## Rate-limit headers (read on EVERY response)
`X-Business-Use-Case-Usage` (primary for publishing): per-id array of `{call_count, total_cputime, total_time}` (all % 0–100) + **`estimated_time_to_regain_access`** (minutes). Block at 100%; **sleep `estimated_time_to_regain_access` minutes** — authoritative. Also `X-App-Usage`. Proactively throttle (token bucket) at **~70–80%**. BUC formula: calls/24h = 4,800 × impressions (floor ~48k/day); platform 200×users/hr; BUC takes precedence.

## Dynamic quota gating (query before publish — never hard-code)
- IG: `GET /<IG_ID>/content_publishing_limit?fields=quota_usage,config` → `config.quota_total` (50 or 100 — endpoint is authoritative per account) / `quota_duration:86400`. Gate publish on usage < total.
- Threads: `GET /<uid>/threads_publishing_limit?fields=quota_usage,config,reply_quota_usage,reply_config,delete_quota_usage,delete_config,...` → posts 250 / replies 1000 / deletes 100 / loc 500.

## Idempotency (publish is NOT idempotent; no idempotency-key header)
1. Persist `creation_id` → resulting `media_id` per job. Never re-publish a creation_id that already returned a media_id.
2. On publish timeout/no-response: **GET container status first** — if `PUBLISHED`, record success, don't retry.
3. Dedup store keyed by your own job id (DB UNIQUE / Redis SETNX), TTL >24h.
4. Code 506 (consecutive duplicate) = backstop, not primary guard.

## Tokens
Short-lived ~1h → exchange → long-lived 60d. IG refresh: `GET graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token` (token must be ≥24h old, valid). Threads: `th_exchange_token` → 60d; `th_refresh_token` refresh (≥24h old, not expired, `threads_basic` granted); private-profile grants 90d. **Not refreshed within 60d → permanent expiry, unrecoverable → dead-letter to re-auth.** Prefer system-user tokens for server stability.

## Media specs
IG: JPEG only, no text-only, REELS replacing VIDEO; reels params `share_to_feed`/`cover_url`/`thumb_offset`/`audio_name`/`trial_params`(MANUAL|SS_PERFORMANCE); resumable upload via `rupload.facebook.com` (honor `debug_info.retriable`). Threads: TEXT/IMAGE/VIDEO/CAROUSEL(≤20), text-only OK, 500-char, video ≤5min ≤1GB, image JPEG/PNG ≤8MB.

## Version hygiene
Basic Display API dead (Dec 4 2024). Scope renames `instagram_basic`→`instagram_business_basic` etc. (Jan 2025). Use v25.0 (2026); each version supported ≥2yr; deprecated → 400. Pin + migrate proactively, re-verify quotas each quarter.

## Maps to AP1
- AP1-1 retry: this error taxonomy + backoff-from-`estimated_time_to_regain_access` replaces the code-baked 3/12 thresholds.
- New: dynamic quota gate before enqueue/publish; idempotency dedup store; token refresh-vs-deadletter state machine.
