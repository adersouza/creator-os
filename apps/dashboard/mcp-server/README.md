# Juno33 MCP Server

A Model Context Protocol (MCP) server that gives Claude full control over your Juno33 workspace — 156+ tools covering posts, scheduling, media, AI, analytics, inbox, competitors, auto-poster, reports, and more.

> Compatibility note: the MCP server key remains `threadsdashboard` in examples below so existing local Claude Code setups do not break.

## Quick Start

### 1. Install & Build

```bash
cd mcp-server
npm install
npm run build
```

### 2. Get Your Auth Token

The MCP server authenticates against your Vercel API using a Supabase JWT.

**Option A — From the browser:**
1. Log in to [juno33.com](https://juno33.com)
2. Open DevTools → Application → Local Storage
3. Find the key starting with `sb-` that contains `access_token`
4. Copy the `access_token` value

**Option B — From Supabase dashboard:**
1. Go to your Supabase project → SQL Editor
2. Generate a long-lived JWT for your user ID using `auth.jwt()`

> **Note:** Supabase access tokens expire after 1 hour by default. For persistent use, either refresh the token periodically or configure a longer JWT expiry in your Supabase auth settings.

### 3. Configure Claude Code

The server is already registered in `.mcp.json` at the project root. You just need to set the auth token.

**Option A — Environment variable (recommended):**

Add to your `~/.zshrc` or `~/.bashrc`:

```bash
export TD_AUTH_TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

Then restart your terminal and Claude Code.

**Option B — Direct in `.mcp.json`:**

Edit `.mcp.json` and add the token to the `env` block:

```json
{
  "mcpServers": {
    "threadsdashboard": {
      "type": "stdio",
      "command": "node",
      "args": ["/Users/adercialonedesouza/Projects/ThreadsDashboard/mcp-server/dist/index.js"],
      "env": {
        "TD_API_BASE": "https://juno33.com/api",
        "TD_AUTH_TOKEN": "eyJhbG..."
      }
    }
  }
}
```

> **Warning:** Don't commit `.mcp.json` with your token. It's already in `.gitignore`.

### 4. Verify

Restart Claude Code and run `/mcp` to check the server is connected. You should see `threadsdashboard` with 156+ tools listed.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TD_AUTH_TOKEN` | Yes | — | Supabase JWT for API authentication |
| `TD_API_BASE` | No | `https://juno33.com/api` | API base URL (override for local dev) |

### Local Development

To point the MCP server at your local dev server instead of production:

```bash
export TD_API_BASE="http://localhost:3000/api"
export TD_AUTH_TOKEN="your-local-jwt"
```

---

## Tool Reference

### Accounts

#### `list_accounts`
List all connected social accounts (Threads + Instagram).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| — | — | — | No parameters |

**Example:** "List all my connected accounts"

#### `sync_account`
Trigger a manual sync for an account (refreshes metrics, posts, profile data from Meta API).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Account ID |
| `platform` | `"threads"` \| `"instagram"` | Yes | Platform |

**Example:** "Sync my Threads account abc123"

---

### Posts & Content

#### `publish_post`
Publish a post immediately. Supports text, media attachments, polls (Threads only), and reply chains.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Account to post to |
| `content` | string | Yes | Post text |
| `platform` | `"threads"` \| `"instagram"` | Yes | Target platform |
| `mediaIds` | string[] | No | Media IDs to attach (upload first) |
| `pollOptions` | string[] | No | Poll options (Threads only, 2-4 items) |
| `replyTo` | `{ threadId, accountId }` | No | Reply to existing thread |

**Example:** "Post 'Hello world!' to my Threads account"

#### `schedule_post`
Schedule a post for future publication.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Account to post to |
| `content` | string | Yes | Post text |
| `platform` | `"threads"` \| `"instagram"` | Yes | Target platform |
| `scheduledFor` | string | Yes | ISO 8601 datetime (e.g. `2026-03-10T14:00:00Z`) |
| `mediaIds` | string[] | No | Media IDs to attach |
| `pollOptions` | string[] | No | Poll options (Threads only) |

**Example:** "Schedule a post for tomorrow at 2pm: 'Big announcement coming soon'"

#### `save_draft`
Save content as a draft for later editing.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | Yes | Draft text |
| `accountId` | string | No | Account to associate |
| `mediaIds` | string[] | No | Media to attach |
| `draftFolderId` | string | No | Folder to save in |

#### `delete_post`
Delete a published or scheduled post.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `postId` | string | Yes | Post ID |
| `accountId` | string | Yes | Account ID |

#### `import_posts`
Import posts from a URL.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | URL to import from |

#### `get_posts`
Get recent posts with engagement metrics.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Account ID |
| `limit` | number | No | Number of posts (default: 20) |

#### `manage_evergreen`
Mark posts for automatic recycling, update recycling settings, or list evergreen posts.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | `"toggle"` \| `"update"` \| `"list"` | Yes | Action |
| `postId` | string | For toggle/update | Post ID |
| `isEvergreen` | boolean | For toggle | Mark as evergreen |
| `intervalDays` | number | For update | Days between recycles (7-180) |
| `maxRecycles` | number | For update | Max recycle count (1-50) |
| `accountId` | string | For list | Filter by account |

---

### Media

#### `upload_media`
Upload an image or video from a public URL. Returns a media ID you can pass to `publish_post` or `schedule_post`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `fileName` | string | Yes | File name (e.g. `sunset.jpg`) |
| `fileUrl` | string | Yes | Public URL of the file |
| `mimeType` | string | No | MIME type (auto-detected if omitted) |
| `groupId` | string | No | Account group ID |

**Supported formats:** JPEG, PNG, GIF, WebP, MP4, MOV, WebM (max 50MB)

**Example workflow:**
1. `upload_media` with `fileUrl` → get back `mediaId`
2. `publish_post` with `mediaIds: [mediaId]` → post with image attached

#### `get_random_media`
Get a random media item from the library.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `groupId` | string | No | Filter by account group |
| `imagesOnly` | boolean | No | Only return images |

#### `share_media_folder`
Toggle sharing for a media folder.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `folderId` | string | Yes | Folder ID |
| `isShared` | boolean | Yes | Share or unshare |

---

### Draft Folders

#### `manage_draft_folders`
Organize drafts into folders.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | `"list"` \| `"create"` \| `"update"` \| `"delete"` \| `"move-posts"` | Yes | Action |
| `name` | string | For create/update | Folder name |
| `color` | string | For create/update | Hex color (default: `#6366f1`) |
| `icon` | string | For create/update | Icon name (default: `folder`) |
| `folderId` | string | For update/delete | Folder ID |
| `postIds` | string[] | For move-posts | Posts to move |
| `targetFolderId` | string | For move-posts | Destination folder (null = unfiled) |

---

### AI Features

#### `ai_generate`
Generate content using the account's voice profile. Returns quality-scored output with optional variants.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prompt` | string | Yes | What to generate |
| `accountId` | string | No | Account for voice profile |
| `platform` | `"threads"` \| `"instagram"` | No | Platform (for char limits) |
| `variants` | number | No | Variants to generate (1-3) |

**Timeout:** 30 seconds

**Example:** "Write 3 variants of a caption about morning routines for my Threads account"

#### `ai_copilot`
Conversational AI assistant with access to your real analytics data.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message` | string | Yes | Your question |
| `accountId` | string | Yes | Account for context |
| `platform` | `"threads"` \| `"instagram"` | Yes | Platform |

**Timeout:** 30 seconds

**Example:** "What content type performed best for me last month?"

#### `ai_generate_image`
Generate an AI image using DALL-E 3 or Flux.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prompt` | string | Yes | Image description |
| `provider` | `"dalle"` \| `"flux"` | No | Provider (default: dalle) |
| `style` | string | No | Style (e.g. `vivid`, `natural`) |
| `size` | string | No | Size (e.g. `1024x1024`, `1024x1792`) |

**Timeout:** 30 seconds

#### `ai_vision_score`
Score an image for quality across 5 categories (composition, lighting, color, clarity, engagement potential). Returns 1-100 per category.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `imageUrl` | string | Yes | Public URL of the image |
| `platform` | `"threads"` \| `"instagram"` | No | Platform context |

**Timeout:** 30 seconds

#### `ai_post_autopsy`
Analyze why a post performed well or poorly. Returns contributing factors and recommendations.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `postId` | string | Yes | Post ID to analyze |

**Timeout:** 30 seconds

#### `ai_growth_simulator`
Project follower growth based on 90-day history. Includes milestone forecasting and scenario modeling.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Account ID |
| `platform` | `"threads"` \| `"instagram"` | Yes | Platform |

**Timeout:** 30 seconds

#### `ai_analytics_advisor`
Ask natural language questions about your analytics data.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Account ID |
| `platform` | `"threads"` \| `"instagram"` | Yes | Platform |
| `question` | string | Yes | Your question |

**Timeout:** 30 seconds

**Example:** "Why did my reach drop last Tuesday?"

---

### Analytics & Insights

#### `get_analytics`
Get account-level metrics.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Account ID |
| `period` | `"7d"` \| `"14d"` \| `"30d"` \| `"90d"` | No | Period (default: 30d) |

#### `get_ig_insights`
Get Instagram-specific insights (reach, impressions, saves, profile views, follower growth).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Instagram account ID |
| `period` | `"day"` \| `"week"` \| `"days_28"` | No | Period (default: days_28) |

#### `get_ig_post_insights`
Get detailed metrics for a specific Instagram post.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Instagram account ID |
| `mediaId` | string | Yes | Instagram media ID |

#### `get_demographics`
Audience demographics breakdown (age, gender, location).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Account ID |

#### `get_recap`
Generate a growth recap summary with top post, best times, engagement score.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Account ID |
| `period` | `"7d"` \| `"30d"` \| `"all"` | No | Period (default: 7d) |

---

### Inbox & Replies

#### `get_inbox`
Unified inbox merging Instagram comments/mentions and Threads replies/mentions with priority sorting.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `filter` | `"all"` \| `"comments"` \| `"replies"` \| `"mentions"` | No | Type filter |
| `limit` | number | No | Items to return (default: 20) |

#### `reply_to_message`
Reply to a comment, mention, or thread reply.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Account to reply from |
| `replyToId` | string | Yes | Message ID to reply to |
| `content` | string | Yes | Reply text |

#### `manage_ig_comments`
Full Instagram comment management.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | `"list"` \| `"reply"` \| `"hide"` \| `"private-reply"` | Yes | Action |
| `accountId` | string | Yes | Instagram account ID |
| `mediaId` | string | For list | Media ID |
| `commentId` | string | For reply/hide/private-reply | Comment ID |
| `message` | string | For reply/private-reply | Reply text |
| `hide` | boolean | For hide | Hide or unhide |

#### `manage_inbox_rules`
Auto-reply rules for inbox messages.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | `"list"` \| `"create"` \| `"update"` \| `"delete"` \| `"toggle"` | Yes | Action |
| `workspaceId` | string | For list/create | Workspace ID |
| `ruleId` | string | For update/delete/toggle | Rule ID |
| `triggerType` | string | For create | Trigger type |
| `triggerPattern` | string | For create | Keywords/pattern |
| `replyText` | string | For create | Auto-reply text |
| `isActive` | boolean | For toggle | Active state |

---

### Competitors

#### `list_competitors`
List all tracked competitors and their latest metrics. If `accountId` is omitted, returns ALL competitors for the authenticated user (workspace-level view).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | No | Account ID (optional — omit to list all competitors across all accounts) |

#### `add_competitor`
Start tracking a new competitor by username.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Your account ID |
| `username` | string | Yes | Competitor's username |
| `platform` | `"threads"` \| `"instagram"` | Yes | Platform |

#### `bulk_add_competitors`
Add multiple competitors in one call (up to 50).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | No | Account ID (required for Instagram) |
| `platform` | `"threads"` \| `"instagram"` | Yes | Platform |
| `usernames` | string[] | Yes | Usernames to track (max 50) |

#### `remove_competitor`
Stop tracking a competitor. Uses dryRun=true by default.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Your account ID |
| `competitorId` | string | Yes | Competitor ID |
| `dryRun` | boolean | No | Preview removal (default: true) |

#### `bulk_remove_competitors`
Remove multiple competitors in one call (max 100). Uses dryRun=true by default.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Your account ID |
| `competitorIds` | string[] | Yes | Competitor IDs to remove (max 100) |
| `dryRun` | boolean | No | Preview removal (default: true) |

#### `analyze_competitor`
AI-powered competitive analysis comparing a competitor to your account.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `competitorId` | string | Yes | Competitor ID |
| `accountId` | string | Yes | Your account ID for comparison |

**Timeout:** 30 seconds

#### `get_competitor_media`
Fetch media details for a specific Threads post (media URL, type, thumbnail).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `threadsPostId` | string | Yes | Threads post ID |

#### `get_competitor_schedule_pattern`
Analyze when competitors post and what format performs. Returns day/hour heatmap and format breakdown.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Your account ID |
| `competitorId` | string | No | Specific competitor (omit for all) |
| `days` | number | No | Days to analyze (default 30) |

#### `list_competitor_top_posts`
Get highest-engagement posts from a tracked competitor, sorted by engagement score.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `competitorId` | string | Yes | Competitor ID |
| `days` | number | No | Lookback days (default 7, max 30) |
| `limit` | number | No | Max posts (default 10, max 50) |

#### `get_inspiration_ideas`
Read AI-adapted content ideas generated from competitor posts by the daily inspiration scan.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | Yes | Workspace ID |
| `status` | `"pending"` \| `"used"` \| `"archived"` | No | Filter by status (default: pending) |
| `competitorId` | string | No | Filter to ideas from a specific competitor |
| `limit` | number | No | Max ideas (default 20, max 100) |

#### `use_inspiration_idea`
Mark an inspiration idea as 'used' for conversion rate tracking.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `ideaId` | string | Yes | Inspiration idea ID |

---

### Quick Wins & Recommendations

#### `get_quick_wins`
AI-powered recommendations for improving performance.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Account ID |
| `platform` | `"threads"` \| `"instagram"` | Yes | Platform |

**Timeout:** 30 seconds

#### `dismiss_recommendation`
Dismiss a recommendation with a reason.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `recId` | string | Yes | Recommendation ID |
| `accountId` | string | Yes | Account ID |
| `reason` | `"already_doing"` \| `"not_relevant"` \| `"will_try_later"` | Yes | Reason |
| `category` | string | No | Category |
| `platform` | `"threads"` \| `"instagram"` | No | Platform |

#### `bulk_apply_quick_wins`
Apply multiple recommendations at once.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `recommendations` | `{ id, action }[]` | Yes | Recommendations to apply |
| `accountId` | string | Yes | Account ID |

---

### Post Templates

#### `manage_templates`
Reusable content templates.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | `"list"` \| `"create"` \| `"delete"` | Yes | Action |
| `name` | string | For create | Template name |
| `content` | string | For create | Template content |
| `tags` | string[] | For create | Tags |
| `templateId` | string | For delete | Template ID |

---

### Auto-Poster (Empire Tier)

#### `auto_post_health_check`
Check auto-poster health across all accounts (token validity, queue status). Includes diagnostics: warns if master switch is OFF, AI queue fill is disabled, or group mode is off.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | No | Workspace ID (uses default if omitted) |

**Response includes:** `threads`, `instagram` health objects + `diagnostics` array (warnings like "Master switch is OFF", "AI queue fill is disabled — queue will drain and not replenish", "Group mode disabled — using legacy mode").

#### `get_workspace_config`
Get workspace-level auto-poster configuration flags (AI fill, performance, timing). Use to diagnose why the autoposter isn't generating content. Returns all workspace-level settings from `auto_post_config`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | Yes | Workspace ID |

**Response:** Full `auto_post_config` row including: `is_enabled`, `enable_ai_queue_fill`, `group_mode_enabled`, `ai_queue_min_threshold`, `ai_posts_per_fill`, `ai_daily_generation_limit`, `ai_generations_today`, `ai_last_generation_date`, `competitor_copy_ratio`, `competitor_copy_max_words`, `pause_on_low_performance`, `performance_threshold`, `use_smart_timing`, `boost_on_viral`, `content_filter_max_length`, `content_filter_min_length`, `content_filter_max_emojis`, `discord_webhook_url` (masked: "configured" or "not set").

#### `get_auto_post_configs`
Get auto-poster configurations for all account groups.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | Yes | Workspace ID |

#### `upsert_auto_post_config`
Create or update auto-poster configuration for an account group. Supports partial updates.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | Yes | Workspace ID |
| `groupId` | string | Yes | Account group ID |
| `enabled` | boolean | No | Enable/disable auto-posting |
| `contentSources` | string[] | No | Content source types |
| `postsPerAccountPerDay` | number | No | Max posts per account per day (1-50) |
| `minIntervalMinutes` | number | No | Minimum minutes between posts (1-1440) |
| `activeHoursStart` | number | No | UTC hour to start posting (0-23) |
| `activeHoursEnd` | number | No | UTC hour to stop posting (0-23) |
| `timezone` | string | No | Timezone for daily resets (e.g. 'America/New_York') |
| `postOnWeekends` | boolean | No | Whether to post on Saturday/Sunday |
| `enableHumanNoise` | boolean | No | Enable human noise injection on AI-generated content (default: true) |
| `enableAutoReply` | boolean | No | Enable auto-reply on auto-posted content |
| `autoReplyDailyLimit` | number | No | Max auto-replies per group per day (1-50, default 5) |
| `autoReplyRatio` | number | No | Fraction of comments to reply to (0-1, default 0.5) |
| `autoReplyTriggerCount` | number | No | Min comments on a post before harvesting (1-100, default 1) |
| `autoReplyWindowHours` | number | No | Hours after posting to harvest comments (1-168, default 24) |

#### `delete_auto_post_config`
Delete the auto-poster configuration for an account group. Uses dryRun=true by default.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | Yes | Workspace ID |
| `groupId` | string | Yes | Account group ID |
| `dryRun` | boolean | No | Preview deletion (default: true) |

#### `toggle_auto_post`
Enable or disable auto-posting for an account group.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | Yes | Workspace ID |
| `groupId` | string | No | Account group ID (omit for workspace-wide legacy toggle) |
| `enabled` | boolean | Yes | true to enable, false to disable |

#### `upsert_workspace_config`
Update workspace-level auto-poster settings (AI queue fill, performance monitoring, velocity, smart timing, competitor copy). These live on `auto_post_config`, NOT per-group. Only provided fields are updated. Empire tier required.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | Yes | Workspace ID |
| `enableAiQueueFill` | boolean | No | Auto-generate posts when queue runs low |
| `aiQueueMinThreshold` | number | No | Trigger AI fill when queue drops below this count |
| `aiPostsPerFill` | number | No | How many posts to generate per fill |
| `aiDailyGenerationLimit` | number | No | Max AI-generated posts per day |
| `aiStyleGuidelines` | string | No | User-provided rules/guidelines for AI content generation |
| `groupModeEnabled` | boolean | No | Enable group-based posting mode |
| `pauseOnLowPerformance` | boolean | No | Auto-pause if engagement drops below threshold |
| `performanceThreshold` | number | No | Minimum engagement rate percent before pausing |
| `enableVelocityMonitoring` | boolean | No | Track engagement acceleration/decline over time |
| `boostOnViral` | boolean | No | Reduce posting interval when a post goes viral |
| `viralIntervalReductionPct` | number | No | How much to reduce interval on viral post (percent) |
| `useSmartTiming` | boolean | No | Use AI-analyzed best posting times |
| `competitorCopyRatio` | number | No | Fraction of AI queue fill that should be direct competitor copies (0-1, default 0.2) |
| `competitorCopyMaxWords` | number | No | Max word count for eligible competitor copy posts (default 10) |

#### `get_auto_post_queue`
Inspect the auto-post queue. If `groupId` is provided, returns items for that group. If omitted, returns items across ALL groups in the workspace. Each item includes `source_type`: `"ai"`, `"competitor_copy"`, `"media"`, or `"trending"`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | Yes | Workspace ID |
| `groupId` | string | No | Account group ID (optional — omit for workspace-level view) |
| `status` | string | No | Filter: `"pending"` (default), `"published"`, `"cancelled"`, `"dead_letter"`, `"failed"`, `"all"` |
| `limit` | number | No | Max items (default 20, max 100) |

#### `get_queue_counts`
Lightweight queue count across all groups in a workspace. Returns total pending items and per-group breakdown (name + count). No content returned — just counts. Use this FIRST for a quick overview.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | Yes | Workspace ID |

**Response:** `{ totalPending, groupCount, byGroup: [{ groupId, name, pending }] }`

#### `bulk_clear_queue`
Cancel ALL pending items in the auto-post queue for a single group. For clearing ALL groups at once, use `bulk_clear_all_queues`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `groupId` | string | Yes | Account group ID |
| `workspaceId` | string | Yes | Workspace ID |
| `dryRun` | boolean | No | Preview (default: true) |

#### `bulk_clear_all_queues`
Cancel ALL pending items across EVERY group in a workspace. One call clears the entire workspace queue. Returns per-group breakdown.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | Yes | Workspace ID |
| `dryRun` | boolean | No | Preview (default: true) |

#### `delete_queue_item`
Cancel a single item from the auto-post queue by ID. Only works on pending/queued items.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `queueItemId` | string | Yes | Queue item UUID |
| `dryRun` | boolean | No | Preview (default: true) |

#### `fetch_auto_post_engagement`
Fetch engagement metrics for a specific auto-posted item.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `postId` | string | Yes | Post ID |

#### `sync_auto_post_engagement`
Trigger engagement sync for all auto-posted content in a workspace.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | Yes | Workspace ID |

#### `get_auto_reply_queue`
View the auto-reply queue for a workspace. Shows harvested comments and their reply status.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | Yes | Workspace ID |
| `status` | string | No | Filter by status: pending, processing, posted, failed, skipped |
| `limit` | number | No | Max items to return (default 20, max 100) |

#### `toggle_auto_reply`
Enable or disable auto-reply for an account group. When enabled, the autoposter harvests comments on auto-posted content and generates contextual AI replies using the account's voice profile.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | Yes | Workspace ID |
| `groupId` | string | Yes | Account group ID |
| `enabled` | boolean | Yes | true to enable auto-reply, false to disable |
| `dailyLimit` | number | No | Max auto-replies per group per day (1-50, default 5) |
| `ratio` | number | No | Fraction of comments to reply to (0-1, default 0.5) |
| `triggerCount` | number | No | Min comments on a post before harvesting (1-100, default 1) |
| `windowHours` | number | No | Hours after posting to harvest comments (1-168, default 24) |

#### `get_account_overrides`
Get per-account config overrides within a group. Returns overrides that take priority over group-level settings.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | Yes | Workspace ID |
| `groupId` | string | No | Filter to a specific group |
| `accountId` | string | No | Filter to a specific account |

#### `upsert_account_override`
Set per-account config overrides within a group. Any setting not specified falls back to the group default. Supports all group-level settings (postsPerAccountPerDay, minIntervalMinutes, activeHoursStart/End, timezone, postOnWeekends, enableHumanNoise, enableAutoReply, etc.).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | Yes | Workspace ID |
| `groupId` | string | Yes | Account group ID |
| `accountId` | string | Yes | Account ID to override settings for |
| `postsPerAccountPerDay` | number | No | Override: max posts per day |
| `minIntervalMinutes` | number | No | Override: min minutes between posts |
| `activeHoursStart` | number | No | Override: hour to start posting (0-23) |
| `activeHoursEnd` | number | No | Override: hour to stop posting (0-23) |
| `timezone` | string | No | Override: timezone for this account |
| `postOnWeekends` | boolean | No | Override: post on weekends |
| `enabled` | boolean | No | Override: enable/disable this account |
| `enableHumanNoise` | boolean | No | Override: enable human noise injection |
| `enableAutoReply` | boolean | No | Override: enable auto-reply |
| `autoReplyDailyLimit` | number | No | Override: max auto-replies per day |
| `autoReplyRatio` | number | No | Override: fraction of comments to reply to |
| `autoReplyTriggerCount` | number | No | Override: min comments before harvesting |
| `autoReplyWindowHours` | number | No | Override: hours after posting to harvest |

#### `delete_account_override`
Remove per-account config overrides — account falls back to group defaults. Use dryRun=true (default) to preview.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | Yes | Workspace ID |
| `groupId` | string | Yes | Account group ID |
| `accountId` | string | Yes | Account ID to remove overrides for |
| `dryRun` | boolean | No | Preview deletion (default: true) |

---

### Social Listening

#### `manage_listening_alerts`
Keyword monitoring alerts with spike/threshold detection.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | `"list"` \| `"create"` \| `"update"` \| `"delete"` | Yes | Action |
| `alertId` | string | For update/delete | Alert ID |
| `keyword` | string | For create | Keyword to monitor |
| `alertType` | `"spike"` \| `"threshold"` | For create | Alert type |
| `thresholdValue` | number | For create | Threshold (1-10000) |
| `isActive` | boolean | For update | Active state |

---

### Reports

#### `generate_report`
Generate a branded performance report with optional AI recommendations. Returns PDF.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Account ID |
| `reportType` | `"weekly"` \| `"monthly"` \| `"custom"` | Yes | Report type |
| `startDate` | string | Yes | Start date (ISO 8601) |
| `endDate` | string | Yes | End date (ISO 8601) |
| `platform` | `"threads"` \| `"instagram"` | No | Platform filter |
| `includeRecommendations` | boolean | No | Include AI recommendations |
| `clientName` | string | No | Client name in header |

**Timeout:** 30 seconds

---

### Link in Bio

#### `manage_link_page`
Create and manage Link in Bio pages.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | `"create-page"` \| `"update-page"` \| `"list-pages"` \| `"delete-page"` \| `"analytics"` | Yes | Action |
| `slug` | string | For create | URL slug (e.g. `mypage`) |
| `title` | string | For create/update | Page title |
| `bio` | string | For create/update | Bio text |
| `backgroundColor` | string | For create/update | Background hex color |
| `brandColor` | string | For create/update | Brand hex color |
| `pageId` | string | For update/delete/analytics | Page ID |
| `days` | number | For analytics | Period in days (default: 30) |

#### `manage_bio_links`
Manage individual links on a Link in Bio page.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | `"add-link"` \| `"update-link"` \| `"reorder"` \| `"delete-link"` | Yes | Action |
| `pageId` | string | Yes | Page ID |
| `title` | string | For add/update | Link title |
| `url` | string | For add/update | Link URL |
| `icon` | string | For add/update | Icon name |
| `isPrimary` | boolean | For add/update | Primary link styling |
| `linkId` | string | For update/delete | Link ID |
| `linkIds` | string[] | For reorder | Ordered link IDs |

---

### Team Management

#### `send_team_invite`
Send a team invitation email (Pro tier+).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceName` | string | Yes | Workspace name |
| `inviteCode` | string | Yes | Invite code |
| `recipientEmail` | string | Yes | Email to invite |
| `role` | string | No | Role (default: member) |

#### `get_team_stats`
Team member performance stats.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspaceId` | string | Yes | Workspace ID |
| `days` | number | No | Period (7, 30, or 0 for all time) |
| `platform` | `"threads"` \| `"instagram"` | No | Platform filter |

---

### Subscription

#### `check_subscription`
Check current tier, trial status, and billing info.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| — | — | — | No parameters |

---

### Instagram-Specific

#### `ig_hashtag_search`
Search hashtags and get top/recent media.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | `"search"` \| `"top-media"` \| `"recent-media"` | Yes | Action |
| `accountId` | string | Yes | Instagram account ID |
| `hashtagName` | string | For search | Hashtag (without #) |
| `hashtagId` | string | For top/recent-media | Hashtag ID |
| `limit` | number | No | Results (max 50) |

#### `ig_publishing_limit`
Check Instagram publishing rate limit.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Instagram account ID |

---

### Threads-Specific

#### `threads_lookup_profile`
Look up a Threads user profile.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Your Threads account ID |
| `username` | string | Yes | Username to look up |

#### `threads_get_user_posts`
Get posts from a Threads user.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Your Threads account ID |
| `username` | string | Yes | Username to fetch |
| `limit` | number | No | Number of posts (default: 25) |

#### `threads_quota`
Check Threads API publishing quota (posts, replies, deletes remaining).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `accountId` | string | Yes | Threads account ID |

---

### Discovery & Trends

#### `search_discover`
Search for content, users, or hashtags.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search query |
| `platform` | `"threads"` \| `"instagram"` | No | Platform filter |

#### `get_trends`
Trending topics and hashtags.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `platform` | `"threads"` \| `"instagram"` | No | Platform filter |
| `limit` | number | No | Number of trends |

#### `get_inspiration`
Content inspiration with AI analysis.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | No | Topic or keyword |
| `accountId` | string | No | Account for personalization |

---

### Growth Journal

#### `growth_journal`
Track which recommendations you acted on and their outcomes.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | `"list"` \| `"create"` | Yes | Action |
| `accountId` | string | Yes | Account ID |
| `platform` | `"threads"` \| `"instagram"` | No | Platform |
| `category` | string | No | Category filter (list) |
| `recommendationText` | string | For create | What you did |
| `icon` | string | For create | Icon |

---

### URL Shortener

#### `shorten_url`
Create a shortened/tracked URL.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | URL to shorten |

---

### System & Admin

#### `check_health`
Full system health dashboard: cron jobs, Redis, Meta API, DLQ, rate limits.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| — | — | — | No parameters |

#### `get_dead_letters`
View and manage the dead letter queue (failed background jobs).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | `"list"` \| `"retry"` \| `"purge"` | No | Action (default: list) |
| `source` | string | No | Filter by source |
| `itemId` | string | No | Item ID (for retry) |

---

## Example Workflows

### Post with an image

```
1. "Upload this image: https://example.com/photo.jpg as photo.jpg"
   → upload_media returns { media: { id: "media_abc123" } }

2. "Post 'Check out this sunset!' to my Threads account with that image"
   → publish_post with mediaIds: ["media_abc123"]
```

### Generate and schedule content

```
1. "Generate 3 caption variants about productivity for my Threads account"
   → ai_generate returns 3 options

2. "Schedule variant 2 for tomorrow at 9am EST"
   → schedule_post with scheduledFor: "2026-03-07T14:00:00Z"
```

### Full analytics review

```
1. "Show me my analytics for the last 30 days"
   → get_analytics

2. "Why did engagement drop last week?"
   → ai_analytics_advisor

3. "What quick wins can I implement?"
   → get_quick_wins

4. "Generate a monthly report for my client"
   → generate_report
```

### Inbox management

```
1. "Show me my unread mentions"
   → get_inbox with filter: "mentions"

2. "Reply to the first one saying 'Thanks for the mention!'"
   → reply_to_message

3. "Set up an auto-reply rule for messages containing 'pricing'"
   → manage_inbox_rules with action: "create"
```

### Competitor research

```
1. "Add @competitor as a tracked competitor on Threads"
   → manage_competitor with action: "add"

2. "Run an AI analysis comparing them to me"
   → analyze_competitor

3. "Look up their recent posts"
   → threads_get_user_posts
```

---

## Architecture

```
mcp-server/
  src/
    index.ts          # Server entry + tool registration
    helpers.ts        # API client, response helpers, Zod coercions
    tools/
      accounts.ts     # Account management (list, sync, groups)
      posts.ts        # Publishing, scheduling, drafts, evergreen
      media.ts        # Upload, random media, folder sharing
      ai.ts           # AI generation, copilot, vision, autopsy
      analytics.ts    # Metrics, insights, demographics, recaps
      inbox.ts        # Unified inbox, replies, comment management
      competitors.ts  # Competitor tracking, analysis, inspiration
      autoposter.ts   # Auto-poster config, queue, overrides
      listening.ts    # Social listening alerts
      reports.ts      # PDF report generation
      links.ts        # Link in Bio, smart links, URL shortener
      admin.ts        # Health checks, dead letters, agent notes
      teams.ts        # Team management, invites
  dist/               # Compiled JS (after npm run build)
  package.json
  tsconfig.json
```

The server runs as a stdio process launched by Claude Code. Each tool maps to one or more API calls to the Vercel backend at `juno33.com/api`. All requests include the Supabase JWT for authentication.

### Timeouts

- Standard API calls: 15 seconds
- AI-powered tools (generate, copilot, vision, autopsy, reports): 30 seconds

### Error Handling

All API errors are surfaced as MCP tool errors with the HTTP status code and response body. The server never crashes on API errors — it reports them back to Claude for handling.

---

## Tier Requirements

Some tools require specific subscription tiers:

| Tier | Features |
|------|----------|
| **Free** | Basic posts, analytics, inbox, templates, trends |
| **Pro** | Reports, evergreen, growth journal, team, Link in Bio, copilot |
| **Empire** | Auto-poster, group configs, advanced health checks |

If you call a tool that requires a higher tier, the API will return an error indicating the required tier.

---

## Troubleshooting

### Server not showing in `/mcp`
- Restart Claude Code after editing `.mcp.json`
- Verify the `dist/index.js` path is correct
- Run `node mcp-server/dist/index.js` manually — it should print an error about missing `TD_AUTH_TOKEN`

### "401 Unauthorized" errors
- Your JWT has expired. Get a fresh one from the browser
- Ensure `TD_AUTH_TOKEN` is set in your env or `.mcp.json`

### Timeouts on AI tools
- AI endpoints can take 10-30 seconds. The 30s timeout should cover most cases
- If consistently timing out, check system health with `check_health`

### "Rate limited" errors
- Most endpoints have per-user rate limits (30-60 requests/minute)
- Wait a moment and retry, or reduce request frequency

### Build errors
```bash
cd mcp-server
rm -rf dist node_modules
npm install
npm run build
```
