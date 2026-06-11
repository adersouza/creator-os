# Meta Integration Audit — Fix Tracker

## Status: COMPLETE (20/20 fixed)
## Started: 2025-02-25

---

## CRITICAL

### 1. ANALYTICS-2: Deprecated Instagram Metrics
- **Status**: DONE
- **Files**: `api/_lib/instagramApi.ts`, `api/_lib/analytics/instagramRefresh.ts`
- **Problem**: Still requesting `impressions`, `plays`, `video_views` (deprecated v22.0+, all versions after April 21, 2025)
- **Fix**: Replaced with `views` as primary metric. Batch request now uses `views,reach,likes,comments,shares,saved`. Removed deprecated `plays`, `video_views`, `reposts`, `reels_skip_rate`, `crossposted_views` from request. Updated fallback chains to use `views` instead of `impressions`. Deprecated fields in IGPostMetrics kept at 0 for backwards compat. FB Login account insights removed `impressions` from metric list.

---

## HIGH

### 2. POST-4: Instagram 100 post/24h limit not enforced
- **Status**: DONE
- **Files**: `api/cron/scheduled-posts.ts`, `api/_lib/handlers/auto-post/queue.ts`
- **Fix**: Updated all `ig_check_and_increment_rate_limit` RPC calls from `p_daily_limit: 50` to `p_daily_limit: 100` (Meta's actual IG limit). 5 call sites updated across scheduled posts and auto-poster queue.

### 3. POST-2 + MEDIA-2: PNG images accepted for Instagram (JPEG only)
- **Status**: DONE
- **Files**: `api/_lib/instagramApi.ts`
- **Fix**: Added early validation in `postToInstagram()` that rejects PNG/WebP images before container creation. Checks single IMAGE, CAROUSEL children, and STORIES. Returns clear error message suggesting JPEG conversion.

### 4. MEDIA-1: No EXIF stripping
- **Status**: DONE
- **Files**: New `api/_lib/exifStrip.ts`, modified `api/_lib/mediaStorage.ts`, new `api/_lib/__tests__/exifStrip.test.ts`
- **Fix**: Pure-JS EXIF stripping utility (no native deps, works on Vercel). Strips APP1 (EXIF) and APP13 (IPTC) segments from JPEG buffers. Integrated into `storeMediaFromUrl()` pipeline. 15 unit tests added.

### 5. ANALYTICS-3: Inconsistent engagement rate formulas
- **Status**: DONE
- **Files**: `api/_lib/metricCalculators.ts`, `api/_lib/engagementRate.ts`
- **Fix**: Added `quotes` to PostMetrics interface and Threads formula in metricCalculators.ts. Rewrote engagementRate.ts to delegate to calculateEngagementRate (marked @deprecated). Single source of truth now.

### 6. AUTH-1: No proactive token refresh
- **Status**: DONE
- **Files**: New `api/cron/token-refresh.ts`, modified `vercel.json`
- **Fix**: Created dedicated cron (daily 3AM UTC) that refreshes Threads and Instagram tokens within 7 days of expiry. Handles both IG login types. Added to vercel.json crons array.

---

## MEDIUM

### 7. POST-1: reply_config param may not match Meta docs
- **Status**: DONE
- **Files**: `api/_lib/threadsApi.ts`
- **Fix**: Changed from `reply_config: JSON.stringify({ reply_approval_mode: "MANUAL_APPROVAL" })` to `enable_reply_approvals: "true"` per Meta docs.

### 8. POST-5: Max 5 links/post (Threads) not validated
- **Status**: DONE
- **Files**: `api/_lib/threadsApi.ts`
- **Fix**: Added URL regex validation before container creation. Returns early with clear error if >5 links detected.

### 9. POST-7: Using IG API v24.0 vs current v25.0
- **Status**: DONE
- **Files**: All API files and documentation updated (16+ files)
- **Fix**: Updated `/v24.0/` to `/v25.0/` across all API routes, auth callbacks, webhook subscriptions, scripts, and docs.

### 10. MEDIA-3: No resumable video upload for Instagram
- **Status**: DONE
- **Files**: New `api/_lib/ruploadService.ts`, modified `api/_lib/instagramApi.ts`
- **Fix**: Created `ruploadService.ts` with chunked upload support via `rupload.facebook.com`. Integrated into `postToInstagram()` — auto-detects videos >50MB via HEAD request and switches to resumable upload. Also supports forced mode via `useResumableUpload` flag. URL mode (Meta fetches from URL) and buffer mode (chunked byte upload) both supported.

### 11. MEDIA-4: WebP in allowed types but Threads only supports JPEG/PNG
- **Status**: DONE
- **Files**: `api/_lib/threadsApi.ts`
- **Fix**: Added validation in `postToThreads()` that rejects WebP image URLs before container creation.

### 12. AUTH-2: Token refresh endpoints lack rate limiting
- **Status**: DONE
- **Files**: `api/auth/threads/refresh.ts`, `api/auth/instagram/refresh.ts`
- **Fix**: Added 10/hour per user rate limiting using existing `checkRateLimit` helper. Returns 429 with Retry-After header when exceeded. Fail-open if Redis unavailable.

### 13. WEBHOOK-1: Threads `delete` webhook not subscribed
- **Status**: DONE
- **Files**: `api/threads/webhook-subscribe.ts`, `api/cron/webhook-processor.ts`, `api/threads/webhook.ts`
- **Fix**: Added `delete` to `THREADS_WEBHOOK_FIELDS`. Created `processThreadsDeleteEvent` handler that marks posts as `status: 'deleted'` in DB. Wired into webhook processor switch.

### 14. WEBHOOK-3: IG story_insights webhook requires Facebook Login
- **Status**: DONE
- **Files**: `api/instagram/webhook-subscribe.ts`, `scripts/resubscribe-instagram-webhooks.ts`
- **Fix**: Added documentation comments explaining that `story_insights` events are only available for Facebook Login accounts, not Instagram Login.

### 15. COMP-1: No rate limit tracking for competitor lookups
- **Status**: DONE
- **Files**: `api/cron/sync-orchestrator.ts`, `api/_lib/handlers/competitors/threads/sync.ts`
- **Fix**: Added 300ms delay between competitor profile lookup and posts fetch API calls to prevent rate limiting.

### 16. ANALYTICS-5: Story metrics 24h window tight
- **Status**: DONE
- **Files**: `api/_lib/analytics/instagramRefresh.ts`
- **Fix**: Changed archival window from 20-24h to 14-23h. Now captures story metrics starting at 14h (well within safe zone) with a 9-hour window instead of the previous 4-hour window.

---

## LOW

### 17. ANALYTICS-1: `clicks` not a per-post Threads metric
- **Status**: DONE
- **Files**: `api/_lib/analytics/threadsRefresh.ts`
- **Fix**: Removed `clicks` from per-post insight request. Account-level insights still correctly include `clicks`.

### 18. ANALYTICS-4: Threads pre-April 2024 date not guarded
- **Status**: DONE
- **Files**: `api/_lib/analytics/threadsRefresh.ts`
- **Fix**: Added comment documenting minimum timestamp (1712991600 = April 13, 2024) for `since`/`until` params. No code change needed since current code doesn't use date range params for account insights.

### 19. WEBHOOK-2: No jitter on retry backoff
- **Status**: DONE
- **Files**: `api/_lib/retryUtils.ts`
- **Fix**: Added random jitter (0-25% of delay) to both `calculateBackoff()` and `withRetry()` functions to prevent thundering herd.

### 20. INBOX-1: 3x fetch limit memory pressure
- **Status**: DONE
- **Files**: `api/inbox/unified.ts`
- **Fix**: Reduced multiplier from 3x to 2x, cutting per-source fetch from 150 to 100 rows (~33% memory reduction).
