# API Reference

> **Last updated:** 2026-04-15
> **Base URL:** `https://juno33.com/api`
> **Vercel rewrites:** All action-based routers use `/api/{dir}/:action` rewritten to `/api/{dir}?action=:action`

---

## Summary

| Metric | Count |
|---|---|
| Top-level router files | 53 |
| Cron jobs | 19 |
| Instagram standalone routes | 10 |
| Auth/OAuth routes | 7 |
| Meta compliance routes | 3 |
| Total actions (approx.) | 260+ |

---

## Table of Contents

- [Routers](#routers)
  - [accounts](#accounts)
  - [admin](#admin)
  - [agent](#agent)
  - [ai](#ai)
  - [analytics](#analytics)
  - [auto-post](#auto-post)
  - [beta](#beta)
  - [competitors](#competitors)
  - [developer](#developer)
  - [discover](#discover)
  - [health](#health)
  - [inbox](#inbox)
  - [influencer-collabs](#influencer-collabs)
  - [inspiration](#inspiration)
  - [instagram](#instagram)
  - [jobs](#jobs)
  - [links](#links)
  - [listening](#listening)
  - [media](#media)
  - [onboarding](#onboarding)
  - [operator](#operator)
  - [posts](#posts)
  - [push](#push)
  - [quickwins](#quickwins)
  - [recap](#recap)
  - [referrals](#referrals)
  - [replies](#replies)
  - [reports](#reports)
  - [smart-links](#smart-links)
  - [subscription](#subscription)
  - [sync](#sync)
  - [tags](#tags)
  - [team](#team)
  - [threads](#threads)
  - [trends](#trends)
  - [user](#user)
  - [v1 (Public API)](#v1-public-api)
- [Standalone Endpoints](#standalone-endpoints)
  - [QStash-Triggered (Internal)](#qstash-triggered-internal)
  - [Webhooks (External)](#webhooks-external)
  - [OAuth Callbacks](#oauth-callbacks)
  - [Public Endpoints](#public-endpoints)
- [Instagram Standalone Routes](#instagram-standalone-routes)
- [Other Standalone](#other-standalone)
- [Cron Jobs](#cron-jobs)

---

## Routers

### accounts

**Base path:** `/api/accounts`
**Auth:** `withAuth`
**Rate limit:** 60/min

| Action | Method | Description |
|---|---|---|
| *(none)* | GET | List all Threads + Instagram accounts |
| `bulk-cap-status` | GET | Check publish cap for all accounts |
| `bio-audit` | GET | Audit account bios |

---

### admin

**Base path:** `/api/admin`
**Auth:** `withAdminRole` (admin-only)

| Action | Method | Description |
|---|---|---|
| `health` | GET | System health check |
| `dead-letters` | GET | View dead-letter queue entries |
| `feature-usage` | GET | Feature usage stats |
| `monthly-kpi` | GET | Monthly KPI data |
| `north-star` | GET | North star metrics |
| `power-users` | GET | Power user stats |
| `arl` | GET | Account risk levels |
| `token-health` | GET | Token health overview |

---

### agent

**Base path:** `/api/agent`
**Auth:** `withCors`

| Action | Method | Description |
|---|---|---|
| `approvals` | GET/POST | Agent approval requests |
| `cap-status` | GET | Publish cap status |
| `circuit-breaker` | GET | Circuit breaker status |
| `content-strategy` | GET/POST | Content strategy CRUD |
| `groups` | GET | Account groups |
| `log` | GET | Agent activity log |
| `notes` | GET/POST | Agent notes CRUD |
| `settings` | GET/POST | Agent settings |
| `weekly-state` | GET | Weekly cycle state |
| `crisis-status` | GET | Crisis status check |

---

### ai

**Base path:** `/api/ai`
**Auth:** per-handler (varies)

| Action | Method | Description |
|---|---|---|
| `generate` | POST | AI content generation |
| `copilot` | POST | AI copilot chat |
| `feedback` | POST | AI feedback/revision |
| `keys` | GET/POST | AI API key management |
| `generate-image` | POST | AI image generation |
| `growth-simulator` | POST | Growth simulation |
| `analytics-advisor` | POST | AI analytics advisor |
| `stream` | POST | Streaming AI response |
| `sandbox` | POST | AI sandbox/testing |
| `insight-to-caption` | POST | Convert insight to post caption |
| `low-hanging-fruit` | POST | Low-effort high-impact ideas |
| `style-bible` | POST | Voice style bible |
| `dismiss-recommendation` | POST | Dismiss AI recommendation |
| `vision-score` | POST | AI vision scoring for images |
| `generate-single` | POST | Single post generation |

---

### analytics

**Base path:** `/api/analytics`
**Auth:** `withAuth`
**Rate limit:** 60/min
**Methods:** GET/POST

| Action | Method | Description |
|---|---|---|
| `refresh` | POST | Refresh Threads analytics |
| `ig-refresh` | POST | Refresh Instagram analytics |
| `sync-batch` | POST | Batch analytics sync |
| `queue-sync` | POST | Queue analytics sync job |
| `bulk-sync` | POST | Bulk sync all accounts |
| `job-status` | GET | Check sync job status |
| `backfill` | POST | Backfill historical data |
| `rebackfill` | POST | Re-run backfill |
| `demographics` | GET | Fetch demographics |
| `fix-baselines` | POST | Fix baseline metrics |
| `group-analytics` | GET | Group-level analytics |
| `competitor-patterns` | GET | Competitor patterns |
| `cross-insights` | GET | Cross-account insights |
| `daily-activity` | GET | Daily activity data |
| `feature-usage` | GET | Feature usage tracking |
| `forecasts` | GET | Growth forecasts |
| `model-comparison` | GET | AI model comparison |
| `post-metrics-history` | GET | Post metrics over time |
| `reach-anomaly` | GET | Shadowban detection |
| `revenue` | GET | Revenue tracking |
| `self-compare` | GET | Compare own periods |
| `top-elements` | GET | Top performing elements |
| `while-away` | GET | "While you were away" summary |
| `network` | GET | Network graph |
| `health-snapshots` | GET | Account health snapshots |
| `account-health` | GET | Account health metrics |
| `funnel-correlation` | GET | Funnel correlation |
| `competitor-trends` | GET | Competitor trend lines |
| `demographics-db` | GET | Demographics from DB |
| `benchmarks` | GET | Industry benchmarks |
| `annotations` | GET/POST | Chart annotations |
| `hashtag-performance` | GET | Hashtag performance |
| `top-engagers` | GET | Top engagers list |
| `team-performance` | GET | Team member stats |
| `engager-retention` | GET | Engager retention |
| `audience-overlap` | GET | Cross-account audience overlap |

---

### auto-post

**Base path:** `/api/auto-post`
**Auth:** `withAuth`
**Method:** POST only
**Actions:** 43

| Action | Method | Description |
|---|---|---|
| `log-activity` | POST | Log autoposter activity |
| `sync-engagement` | POST | Sync post engagement |
| `fetch-engagement` | POST | Fetch engagement data |
| `get-group-configs` | POST | Get group configs |
| `get-workspace-config` | POST | Get workspace config |
| `upsert-workspace-config` | POST | Create/update workspace config |
| `upsert-group-config` | POST | Create/update group config |
| `delete-group-config` | POST | Delete group config |
| `toggle-group-mode` | POST | Toggle group auto-post mode |
| `get-group-queue` | POST | Get group queue items |
| `health-check` | POST | Autoposter health check |
| `get-auto-reply-queue` | POST | Get auto-reply queue |
| `toggle-auto-reply` | POST | Toggle auto-reply |
| `get-account-overrides` | POST | Get account overrides |
| `upsert-account-override` | POST | Create/update override |
| `delete-account-override` | POST | Delete account override |
| `bulk-clear-queue` | POST | Clear queue for group |
| `bulk-clear-all-queues` | POST | Clear all queues |
| `get-queue-counts` | POST | Queue count per group |
| `delete-queue-item` | POST | Delete single queue item |
| `stats` | POST | Autoposter stats |
| `get-reply-chain-stats` | POST | Reply chain stats |
| `queue-content-audit` | POST | Content audit for queue |
| `bulk-update-group-configs` | POST | Bulk update configs |
| `bulk-set-content-strategy` | POST | Bulk set strategy |
| `get-account-bios` | POST | Get account bios |
| `competitor-posts-sample` | POST | Sample competitor posts |
| `ops-dashboard` | POST | Ops dashboard data |
| `verify-autoposter-state` | POST | Pre-flight check |
| `get-publish-log` | POST | Publish activity log |
| `get-account-health` | POST | Account health check |
| `retry-dead-letter` | POST | Retry dead letter item |
| `trigger-queue-fill` | POST | Trigger AI queue fill |
| `get-filter-rejections` | POST | View filter rejections |
| `get-account-states` | POST | Account states |
| `get-queue-fill-explain` | POST | Why fill produced 0 items |
| `override-account-state` | POST | Force account state |
| `get-autoposter-snapshot` | POST | Full system snapshot |
| `variants` | POST | Get content variants |
| `promote-variant` | POST | Promote a variant |

---

### beta

**Base path:** `/api/beta`
**Auth:** none

| Action | Method | Description |
|---|---|---|
| `claim` | POST | Claim beta access |
| `feedback` | POST | Submit beta feedback |
| `status` | GET | Check beta status |

---

### competitors

**Base path:** `/api/competitors`
**Auth:** `withAuth`
**Tier:** Pro+
**Rate limit:** 60/min

| Action | Method | Description |
|---|---|---|
| `list` | GET | List tracked competitors |
| `search` | POST | Search Threads users |
| `add` | POST | Add Threads competitor |
| `remove` | POST | Remove competitor |
| `bulk-remove` | POST | Bulk remove competitors |
| `bulk-add` | POST | Bulk add competitors |
| `sync` | POST | Sync competitor data |
| `queue-sync-all` | POST | Queue sync for all competitors |
| `oembed` | POST | Fetch oEmbed data |
| `fetch-top-posts` | POST | Fetch top posts (API) |
| `top-posts` | GET | Get top posts (DB) |
| `aggregated-top-posts` | GET | Aggregated top posts |
| `lookup-post` | POST | Lookup single post |
| `ig-search` | POST | Search IG users |
| `ig-add` | POST | Add IG competitor |
| `ig-sync` | POST | Sync IG competitor |
| `ig-business-discovery` | POST | IG business discovery |
| `ig-benchmarks` | GET | IG benchmarks |
| `ig-content-breakdown` | GET | IG content breakdown |
| `ig-comparison-history` | GET | IG comparison history |
| `ig-detect-alerts` | POST | IG anomaly alerts |
| `analyze` | POST | Analyze competitor |
| `avatar` | GET | Competitor avatar proxy |
| `media` | GET | Competitor media proxy |

---

### developer

**Base path:** `/api/developer`
**Auth:** none
**API key safety:** Keys support scopes (`read`, `write`, `admin`, `mcp`) and optional `allowed_account_ids` allowlists. Empty allowlists mean all owned accounts; non-empty allowlists restrict public API v1 access to those accounts.

| Action | Method | Description |
|---|---|---|
| `keys` | GET/POST | API key management |
| `openapi` | GET | OpenAPI spec |

---

### discover

**Base path:** `/api/discover`
**Auth:** `withAuth`
**Rate limit:** 30/min

| Action | Method | Description |
|---|---|---|
| `search` | POST | Keyword/hashtag search |
| `check-limits` | GET | Check search limits |
| `save-search` | * | *Removed (410)* |
| `get-searches` | * | *Removed (410)* |
| `delete-search` | * | *Removed (410)* |
| `refresh-search` | * | *Removed (410)* |
| `get-snapshots` | * | *Removed (410)* |

---

### health

**Base path:** `/api/health`
**Auth:** none

| Action | Method | Description |
|---|---|---|
| `jobs` | GET | Health check for jobs |

---

### inbox

**Base path:** `/api/inbox`
**Auth:** none at router level

| Action | Method | Description |
|---|---|---|
| `assign` | POST | Assign inbox items |
| `mark-read` | POST | Mark items as read |
| `unified` | GET | Unified inbox feed |
| `rules` | GET/POST | Inbox rules CRUD |

---

### influencer-collabs

**Base path:** `/api/influencer-collabs`
**Auth:** `withAuth`
**Tier:** Empire

| Action | Method | Description |
|---|---|---|
| `list` | GET | List collaborations |
| `get` | GET | Get single collab + ROI |
| `roi` | GET | ROI calculation |
| `leaderboard` | GET | Influencer leaderboard |
| `create` | POST | Create collaboration |
| `update` | PUT | Update collaboration |
| `delete` | DELETE | Delete collaboration |
| `link-post` | POST | Link post to collab |
| `unlink-post` | DELETE | Unlink post from collab |

---

### inspiration

**Base path:** `/api/inspiration`
**Auth:** `withAuth`
**Rate limit:** 30/min

| Action | Method | Description |
|---|---|---|
| `get-ideas` | GET | Get inspiration ideas |
| `save` | POST | Save an idea |
| `dismiss` | POST | Dismiss an idea |
| `queue` | POST | Queue an idea |
| `bulk-queue` | POST | Bulk queue ideas |
| `regenerate` | POST | Regenerate ideas |
| `refresh` | POST | Refresh ideas |
| `get-config` | GET | Get inspiration config |
| `update-config` | POST | Update inspiration config |
| `get-counts` | GET | Get idea counts |
| `get-competitors` | GET | Get competitors for ideas |
| `save-external` | POST | Save external idea |

---

### instagram

**Base path:** `/api/instagram`
**Auth:** none at router level

| Action | Method | Description |
|---|---|---|
| `avatar` | GET | Instagram avatar proxy |
| `flush-insights-cache` | POST | Flush insights cache |
| `media-proxy` | GET | Instagram media proxy |
| `online-followers` | GET | Online followers data |
| `saved-media` | GET | Saved media |
| `stories` | GET | Instagram stories |

---

### jobs

**Base path:** `/api/jobs`
**Auth:** none

| Action | Method | Description |
|---|---|---|
| `export-worker` | POST | Data export worker |

---

### links

**Base path:** `/api/links`
**Auth:** `withAuth`
**Note:** Action read from body (POST) or query (GET)

| Action | Method | Description |
|---|---|---|
| `domains` | GET/POST | Domain management |
| `track` | POST | Track link click |
| `create-page` | POST | Create link page |
| `update-page` | POST | Update link page |
| `get-page` | GET | Get link page |
| `list-pages` | GET | List link pages |
| `add-link` | POST | Add link to page |
| `update-link` | POST | Update link |
| `reorder` | POST | Reorder links |
| `delete-link` | POST | Delete link |
| `delete-page` | POST | Delete link page |
| `analytics` | GET | Link analytics |

---

### listening

**Base path:** `/api/listening`
**Auth:** none at router level

| Action | Method | Description |
|---|---|---|
| `alerts` | GET/POST | Social listening alerts CRUD |
| `monitor` | POST | Run keyword monitoring |

---

### media

**Base path:** `/api/media`
**Auth:** `withAuth`
**Rate limit:** 60/min

| Action | Method | Description |
|---|---|---|
| `random` | GET | Get random media |
| `upload` | POST | Upload media |
| `bulk-register` | POST | Bulk register media |
| `spotlight-queue` | GET | Spotlight queue |
| `share` | POST | Share media folder |
| `refresh` | POST | Refresh media URLs |
| `giphy` | GET | Giphy search (via handler) |

---

### onboarding

**Base path:** `/api/onboarding`
**Auth:** none

| Action | Method | Description |
|---|---|---|
| `instant-analysis` | POST | Instant account analysis |

---

### operator

**Base path:** `/api/operator`
**Auth:** `withAuth`
**Purpose:** Codex/operator control plane for dry-runs, exact approvals, execution, task queue, manager snapshot, and machine-readable action manifest.

| Action | Method | Description |
|---|---|---|
| `snapshot` | GET | Operator snapshot with tasks, approvals, failed posts, manager brain, Ops Health, fleet capacity, and AI eval summary |
| `manifest` | GET | Machine-readable action manifest with risk, approval, idempotency, dry-run, and rollback/compensation metadata |
| `dry-run` | POST | Create an immutable action intent without side effects |
| `request-approval` | POST | Bind a human approval request to an exact dry-run intent |
| `execute` | POST | Execute an approved matching intent through existing production handlers |
| `tasks` | GET/PATCH | List or transition durable operator tasks |
| `source-workflow` | PATCH | Resolve, ignore, or snooze source-backed workflow items |
| `revise-approval` | POST | Create a revised exact intent and supersede the previous approval/task |

The manifest action entries include `toolName`, `riskLevel`, `sideEffectType`,
`requiresApproval`, `requiresIdempotencyKey`, `supportsDryRun`,
`hostedAvailable`, `rollbackSupport`, `compensationActionName`,
`compensationDescription`, `compensationRequiresApproval`, and
`rollbackWindowHours`.

See [`OPERATOR_ACTION_MANIFEST.md`](OPERATOR_ACTION_MANIFEST.md) for the manifest field contract and rollback/compensation classes.

---

### posts

**Base path:** `/api/posts`
**Auth:** `withAuth`
**Rate limit:** 60/min (200/min for `reflection`)

| Action | Method | Description |
|---|---|---|
| `publish` | POST | Publish a post |
| `delete` | POST | Delete a post |
| `thread-chain` | POST | Create thread chain |
| `lookup` | GET | Lookup post details |
| `search-locations` | GET | Search locations |
| `approve` | POST | Approve scheduled post |
| `reject` | POST | Reject scheduled post |
| `repost` | POST | Repost on Threads |
| `refresh-metrics` | POST | Refresh post metrics |
| `import-posts` | POST | Import posts |
| `delete-bulk` | POST | Bulk delete posts |
| `reschedule` | POST | Reschedule a post |
| `update-draft` | POST | Update draft |
| `schedule` | POST | Schedule a post |
| `ghost-posts` | GET | Get ghost posts |
| `bulk-schedule-groups` | POST | Bulk schedule for groups |
| `autopsy` | POST | AI post autopsy |
| `bulk-cancel` | POST | Bulk cancel scheduled |
| `classify` | POST | Classify post |
| `comments` | GET | Get post comments |
| `evergreen` | GET/POST | Evergreen post management |
| `reflection` | GET | Post reflection data |
| `sentiment-scan` | POST | Sentiment scan |
| `sentiment-summary` | GET | Sentiment summary |
| `signal` | POST | Signal/flag post |
| `draft-folders` | GET/POST | Draft folder management |
| `templates` | GET/POST | Post templates |

---

### push

**Base path:** `/api/push`
**Auth:** none

| Action | Method | Description |
|---|---|---|
| `subscribe` | POST | Subscribe to push notifications |
| `vapid-key` | GET | Get VAPID public key |

---

### quickwins

**Base path:** `/api/quickwins`
**Auth:** none

| Action | Method | Description |
|---|---|---|
| `bulk-apply` | POST | Bulk apply quick wins |

---

### recap

**Base path:** `/api/recap`
**Auth:** none

| Action | Method | Description |
|---|---|---|
| `generate` | POST | Generate AI recap |
| `image` | POST | Generate recap image |

---

### referrals

**Base path:** `/api/referrals`
**Auth:** `withAuth`

| Action | Method | Description |
|---|---|---|
| *(none)* | GET | Get referral code + stats |
| `create-code` | POST | Create referral code |
| `validate-code` | POST | Validate referral code |
| `apply-code` | POST | Apply referral code |
| `stats` | POST | Get referral stats |

---

### replies

**Base path:** `/api/replies`
**Auth:** `withAuth`
**Rate limit:** 15-30/min
**Method:** POST only

| Action | Method | Description |
|---|---|---|
| `post` | POST | Post a reply |
| `sync` | POST | Sync replies |
| `fetch-mentions` | POST | Fetch mentions |
| `manage` | POST | Manage replies |
| `sync-metrics` | POST | Sync reply metrics |
| `conversation` | POST | Get conversation thread |

---

### reports

**Base path:** `/api/reports`
**Auth:** `withAuth`
**Tier:** Pro+
**Method:** POST only

| Action | Method | Description |
|---|---|---|
| `generate` | POST | Generate PDF report |

---

### smart-links

**Base path:** `/api/smart-links`
**Auth:** `withAuth`
**Tier:** Pro+
**Rate limit:** 60/min

| Action | Method | Description |
|---|---|---|
| `list` | GET | List smart links |
| `create` | POST | Create smart link |
| `update` | POST | Update smart link |
| `delete` | POST | Delete smart link |
| `analytics` | GET | Smart link analytics |
| `revenue-summary` | GET | Revenue summary |
| `link-conversions` | GET | Link conversions |
| `post-links` | GET | Links by post |
| `revenue-trend` | GET | Revenue trend data |
| `post-attribution` | GET | Post attribution data |

---

### subscription

**Base path:** `/api/subscription`
**Auth:** `withAuth`
**Rate limit:** 10/min
**Method:** POST only

| Action | Method | Description |
|---|---|---|
| `create-checkout` | POST | Create Stripe checkout session |
| `create-portal` | POST | Create Stripe billing portal |
| `cancel` | POST | Cancel subscription |
| `check-trial` | POST | Check trial status |
| `update-addons` | POST | Update add-ons |
| `upgrade-empire` | POST | Upgrade to Empire tier |

---

### sync

**Base path:** `/api/sync`
**Auth:** none at router level

| Action | Method | Description |
|---|---|---|
| `threads-account` | POST | Sync Threads account |
| `ig-account` | POST | Sync Instagram account |
| `post-engagement` | POST | Sync post engagement |

---

### tags

**Base path:** `/api/tags`
**Auth:** `withAuth`

| Action | Method | Description |
|---|---|---|
| `list` | GET | List tags |
| `create` | POST | Create tag |
| `delete` | POST | Delete tag |
| `assign` | POST | Assign tag to post |
| `unassign` | POST | Unassign tag from post |
| `by-post` | GET | Get tags by post |
| `campaign` | GET | Get campaign tags |

---

### team

**Base path:** `/api/team`
**Auth:** mixed

| Action | Method | Description |
|---|---|---|
| `send-invite-email` | POST | Send team invite email (`withAuth`) |
| `invite-details` | GET | Get invite details (public) |
| `team-stats` | GET | Get team stats (`withAuth`) |

---

### threads

**Base path:** `/api/threads`
**Auth:** `withCors`

| Action | Method | Description |
|---|---|---|
| `avatar` | GET | Threads avatar proxy |
| `profile` | GET | Threads profile data |
| `quota` | GET | Threads API quota |
| `reply-approvals` | GET/POST | Reply approval management |

---

### trends

**Base path:** `/api/trends`
**Auth:** `withAuth`

| Action | Method | Description |
|---|---|---|
| `search` | POST | Trend search |
| `config` | GET/POST | Trending configuration |

---

### user

**Base path:** `/api/user`
**Auth:** none at router level

| Action | Method | Description |
|---|---|---|
| `growth-journal` | GET/POST | Growth journal entries |
| `branding` | GET/POST | Agency branding |
| `annual-recap` | GET | Annual recap |
| `data-contribution` | GET/POST | Data contribution settings |
| `delete` | POST | Delete account (GDPR, cascading 27+ tables) |
| `export-status` | GET | Check export job status |
| `export` | POST | Export user data (JSON, 40+ tables) |
| `rec-profile` | GET/POST | Recommendation profile |

---

### v1 (Public API)

**Base path:** `/api/v1`
**Auth:** API key

| Action | Method | Description |
|---|---|---|
| `accounts` | GET | List accounts |
| `posts` | GET | List posts |
| `analytics` | GET | Get analytics |
| `insights` | GET | Get insights |

---

## Standalone Endpoints

### QStash-Triggered (Internal)

These endpoints are called by QStash (Upstash) for async job processing. They verify the QStash signature and are not directly callable.

| Path | Method | Description |
|---|---|---|
| `/api/auto-post-publish` | POST | Publish autoposter queue item |
| `/api/auto-reply` | POST | Post self-comment reply (15s delay) |
| `/api/auto-reply-harvest` | POST | Harvest comments 15min post-publish |
| `/api/cross-reply-publish` | POST | Cross-account reply |
| `/api/qstash-failure` | POST | DLQ failure callback |
| `/api/queue-fill` | POST | AI content generation fill |
| `/api/scheduled-post-publish` | POST | Publish user-scheduled post |
| `/api/dispatch-manual-queue` | POST/GET | Dispatch QStash for orphan items |

---

### Webhooks (External)

Incoming webhooks from third-party services. Verified via HMAC-SHA256 or Stripe signature.

| Path | Method | Description |
|---|---|---|
| `/api/webhook` | POST | Stripe webhook (checkout, subscription, invoice) |
| `/api/threads/webhook` | GET/POST | Threads webhook (HMAC-SHA256 via `THREADS_APP_SECRET`) |
| `/api/threads/webhook-subscribe` | POST | Subscribe to Threads webhooks |
| `/api/instagram/webhook` | GET/POST | Instagram webhook (HMAC-SHA256) |
| `/api/instagram/webhook-subscribe` | POST | Subscribe to IG webhooks |
| `/api/meta/data-deletion` | POST | Meta data deletion callback |
| `/api/meta/deauthorize` | POST | Meta deauthorize callback |
| `/api/meta/process-deletion` | POST | Process cascading deletion |

---

### OAuth Callbacks

OAuth flow endpoints for Threads and Instagram authentication.

| Path | Method | Description |
|---|---|---|
| `/api/auth/threads/callback` | GET | Threads OAuth callback |
| `/api/auth/threads/refresh` | POST | Refresh Threads token |
| `/api/auth/instagram/callback` | GET | IG Login OAuth callback |
| `/api/auth/instagram/fb-callback` | GET | Facebook Login OAuth callback |
| `/api/auth/instagram/refresh` | POST | Refresh IG token |
| `/api/auth/apply-referral` | POST | Apply referral during signup |
| `/api/auth/oauth-state` | POST | Store OAuth CSRF state |

---

### Public Endpoints

No authentication required. Available to all clients.

| Path | Method | Description |
|---|---|---|
| `/api/health/ping` | GET | Uptime monitoring |
| `/api/check-deletion-status` | POST | Check Meta deletion status |
| `/api/favicon` | GET | Favicon proxy with Redis caching |
| `/api/shared-report` | GET | View shared public report |
| `/api/sitemap` | GET | XML sitemap |
| `/api/sentry-tunnel` | POST | Sentry proxy tunnel |
| `/api/link-page/[slug]` | GET | Public link page |
| `/api/link-page/domain` | GET | Custom domain resolver |
| `/api/go/[code]` | GET | Smart link redirect |
| `/api/go/convert` | GET | Conversion postback |
| `/api/go/r/[redirectId]` | GET | Masked link redirect |
| `/api/media/[id]` | GET | Media proxy (`withAuth`) |

---

## Instagram Standalone Routes

Separate route files under `/api/instagram/` with their own handlers.

| Path | Description |
|---|---|
| `/api/instagram/auto-responders` | IG auto-responder CRUD |
| `/api/instagram/collaboration` | IG collab posts |
| `/api/instagram/comments` | IG comment management |
| `/api/instagram/dm-templates` | IG DM templates CRUD |
| `/api/instagram/hashtags` | IG hashtag search |
| `/api/instagram/insights` | IG account/post insights |
| `/api/instagram/media` | IG media management |
| `/api/instagram/mentions` | IG mentions |
| `/api/instagram/messages` | IG DMs |
| `/api/instagram/messenger-profile` | IG messenger profile settings |

---

## Other Standalone

| Path | Method | Description |
|---|---|---|
| `/api/webhooks` | GET/POST | Outgoing webhook subscriptions CRUD |
| `/api/trending-config` | GET/POST | Trending config (query params) |
| `/api/mcp` | POST | MCP Streamable HTTP (198 tools, 24 modules) |

---

## Cron Jobs

19 cron jobs, all authenticated via `verifyCronAuth` / `CRON_SECRET`.

| Path | Schedule | Timeout | Description |
|---|---|---|---|
| `/api/cron/webhook-processor` | `*/2 * * * *` | 60s | Process queued webhook events |
| `/api/cron/publish-worker` | `*/5 * * * *` | 180s | Publish scheduled posts |
| `/api/cron/sync-orchestrator` | `2,17,32,47 * * * *` | 180s | Orchestrate account syncs |
| `/api/cron/analytics-pipeline` | `0 2 * * *` | 300s | Daily analytics pipeline |
| `/api/cron/daily-orchestrator` | `0 1 * * *` | 300s | Daily maintenance (12 phases) |
| `/api/cron/daily-orchestrator-late` | `30 1 * * *` | 300s | Late daily tasks |
| `/api/cron/health-monitor` | `0 */4 * * *` | 300s | System health monitoring |
| `/api/cron/six-hour-pipeline` | `0 */6 * * *` | 300s | Six-hour pipeline |
| `/api/cron/weekly-reports` | `0 8 * * 1` | 300s | Weekly reports (Mon 8AM) |
| `/api/cron/monthly-kpi` | `0 8 1 * *` | 120s | Monthly KPI (1st of month 8AM) |
| `/api/cron/trend-scanner` | `0 */2 * * *` | 300s | Trend scanning |
| `/api/cron/auto-learning` | `0 6 * * *` | 300s | Auto-learning |
| `/api/cron/autoposter-watchdog` | `15,45 * * * *` | 120s | Autoposter watchdog |
| `/api/cron/auto-reply-worker` | `*/15 * * * *` | 60s | Process auto-reply queue |
| `/api/cron/reply-farming-worker` | `*/30 * * * *` | 60s | Reply farming |
| `/api/cron/dawn-planner` | `5 */4 * * *` | 120s | Dawn planning |
| `/api/cron/account-state-evaluator` | `*/15 * * * *` | -- | Evaluate account states |
| `/api/cron/cta-reply-worker` | `10,40 * * * *` | -- | CTA reply posting |
| `/api/cron/scheduler` | `*/5 * * * *` | 180s | Scheduler dispatch |
