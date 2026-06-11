# Instagram Graph API — Complete Reference

> Source: Meta Developers — Instagram Platform
> API version used in this project: **v25.0** (see `api/_lib/metaApiConfig.ts`)
> Facebook Login base URL: `https://graph.facebook.com/v25.0/`
> Instagram Login base URL: `https://graph.instagram.com/v25.0/`
> Login type determines which base URL to use — see Section 1.

---

## Table of Contents

1. [Overview & Account Types](#1-overview--account-types)
2. [Authentication & Access Tokens](#2-authentication--access-tokens)
3. [Permissions](#3-permissions)
4. [Rate Limits](#4-rate-limits)
5. [Account / User Endpoints](#5-account--user-endpoints)
6. [Content Publishing](#6-content-publishing)
   - 6.1 [Photo](#61-photo)
   - 6.2 [Video / Reel](#62-video--reel)
   - 6.3 [Carousel](#63-carousel)
   - 6.4 [Story](#64-story)
   - 6.5 [Resumable Uploads](#65-resumable-uploads)
   - 6.6 [Publishing Limits](#66-publishing-limits)
   - 6.7 [Copyright Detection](#67-copyright-detection)
7. [Media Objects](#7-media-objects)
8. [Comments & Replies](#8-comments--replies)
9. [Mentions](#9-mentions)
10. [Insights (Analytics)](#10-insights-analytics)
    - 10.1 [Account-Level Insights](#101-account-level-insights)
    - 10.2 [Media-Level Insights](#102-media-level-insights)
    - 10.3 [Story Insights](#103-story-insights)
    - 10.4 [Online Followers](#104-online-followers)
    - 10.5 [Audience Demographics](#105-audience-demographics)
    - 10.6 [Deprecated Metrics Reference](#106-deprecated-metrics-reference)
11. [Hashtag Search](#11-hashtag-search)
12. [Business Discovery](#12-business-discovery)
13. [Messaging (DMs)](#13-messaging-dms)
14. [Batch API](#14-batch-api)
15. [Collaborators](#15-collaborators)
16. [Saved Media](#16-saved-media)
17. [Instagram oEmbed](#17-instagram-oembed)
18. [Webhooks](#18-webhooks)
19. [Error Codes](#19-error-codes)
20. [Project-Specific Notes](#20-project-specific-notes)

---

## 1. Overview & Account Types

The **Instagram Graph API** is the official Meta API for interacting with Instagram **Business** and **Creator** accounts. Personal accounts are not supported.

| Account type | Supported? | Notes |
|---|---|---|
| Business | Yes | Full API access |
| Creator | Yes | Most endpoints; some insights differ |
| Personal | No | Must upgrade in Instagram settings |

Two login flows exist:

| Flow | Token type | Notes |
|---|---|---|
| Business Login for Instagram | Instagram User Access Token | Users log in with Instagram credentials. No Facebook Page required. **Cannot access ads or tagging.** |
| Facebook Login for Business | Facebook User Access Token | Users log in with Facebook credentials. Required for Batch API, Hashtag Search, media deletion |

> **Scope migration (completed Jan 27, 2025):** Old scope values (`business_basic`, `business_content_publish`, etc.) were deprecated. Use new `instagram_business_*` prefixed values instead.

---

## 2. Authentication & Access Tokens

### OAuth Authorization Flow

```
1. Redirect user → GET https://api.instagram.com/oauth/authorize
2. User grants permissions → Meta returns authorization_code (valid 1 hour)
3. Exchange code → POST https://api.instagram.com/oauth/access_token
   → short-lived access token (valid 1 hour)
4. Exchange short-lived → GET https://graph.instagram.com/access_token
   → long-lived access token (valid 60 days, refreshable)
```

### Step 1 — Authorization Window

```
GET https://api.instagram.com/oauth/authorize
```

| Parameter | Required | Description |
|---|---|---|
| `client_id` | Yes | Instagram App ID from Meta App Dashboard |
| `redirect_uri` | Yes | Must exactly match registered OAuth redirect URI (including trailing slash) |
| `response_type` | Yes | Always `code` |
| `scope` | Yes | Comma or URL-encoded space-separated permissions. `instagram_business_basic` is required |
| `state` | No | CSRF protection token — returned in redirect |
| `enable_fb_login` | No | `true` (default) shows Facebook Login option on IG login page. `false` hides it. Was deprecated Jun 2025, **re-introduced Feb 2026** |
| `force_reauth` | No | `true` forces re-authentication even if already logged into Instagram. Replaces deprecated `force_authentication` (Jun 2025) |

**Success redirect:**
```
https://your-app.com/auth?code=AQBx-hBsH3...#_
```

> Codes are valid for **1 hour** and can only be used **once**. Note: `#_` is appended to the redirect URI but is NOT part of the code — strip it before exchanging.

**Denied redirect:**
```
https://your-app.com/auth?error=access_denied&error_reason=user_denied&error_description=The+user+denied+your+request
```

### Step 2 — Exchange Code for Short-Lived Token

```
POST https://api.instagram.com/oauth/access_token
Content-Type: application/x-www-form-urlencoded
```

| Parameter | Required | Description |
|---|---|---|
| `client_id` | Yes | App ID |
| `client_secret` | Yes | App Secret |
| `grant_type` | Yes | `authorization_code` |
| `redirect_uri` | Yes | Same URI used in Step 1 |
| `code` | Yes | The code from Step 1 |

**Response:**
```json
{
  "data": [{
    "access_token": "EAACEdEose0...",
    "user_id": "1020...",
    "permissions": "instagram_business_basic,instagram_business_manage_messages,instagram_business_manage_comments,instagram_business_content_publish"
  }]
}
```

**Error response:**
```json
{ "error_type": "OAuthException", "code": 400, "error_message": "Matching code was not found or was already used" }
```

### Step 3 — Exchange for Long-Lived Token

```
GET https://graph.instagram.com/access_token
  ?grant_type=ig_exchange_token
  &client_secret=<APP_SECRET>
  &access_token=<SHORT_LIVED_TOKEN>
```

**Response:**
```json
{
  "access_token": "lZAfb2dhVW...",
  "token_type": "bearer",
  "expires_in": 5184000
}
```

> `expires_in` is in seconds — 5,184,000 = 60 days.
> **Server-side only** — never expose `client_secret` in frontend code.

### Refresh Long-Lived Token

```
GET https://graph.instagram.com/refresh_access_token
  ?grant_type=ig_refresh_token
  &access_token=<LONG_LIVED_TOKEN>
```

Token must be **at least 24 hours old** but **not expired**. Refreshed tokens are valid for **60 days**. Cannot refresh an expired token.

**Response:**
```json
{ "access_token": "c3oxd...", "token_type": "bearer", "expires_in": 5183944 }
```

---

## 3. Permissions

### Instagram Login Permissions

| Permission | Description |
|---|---|
| `instagram_business_basic` | Read profile + media. **Required.** |
| `instagram_business_content_publish` | Create/publish posts, stories, reels |
| `instagram_business_manage_comments` | Read, reply, hide, delete comments |
| `instagram_business_manage_messages` | Send/receive DMs |
| `instagram_business_manage_insights` | Read account and media analytics. Required for all `/insights` endpoints |

### Facebook Login Permissions

| Permission | Description |
|---|---|
| `instagram_basic` | Read profile + media |
| `instagram_content_publish` | Create/publish posts |
| `instagram_manage_comments` | Manage comments |
| `instagram_manage_insights` | Read account/post analytics |
| `instagram_manage_messages` | Send/receive DMs |
| `pages_show_list` | List Facebook Pages |
| `pages_read_engagement` | Read Page engagement data |

### Optional / Feature Permissions

| Permission | Use |
|---|---|
| `ads_management` | Required for product tagging via Business Manager |
| `ads_read` | Alternative for product tagging |
| `catalog_management` | Tag products from catalog |
| `instagram_shopping_tag_products` | Shopping product tags on media |
| `instagram_manage_saved_media` | Access saved media collection |
| Instagram Public Content Access | Hashtag Search endpoints |
| Human Agent | Allow human agent replies within 7 days of user message |

---

## 4. Rate Limits

### Instagram Business Use Case Rate Limits

Applies to all endpoints **except** Business Discovery and Hashtag Search.

```
Calls within 24 hours = 4800 × Number of Impressions
```

Where *Number of Impressions* = number of times any content from the account appeared on a screen in the last 24 hours.

- Counted per app+user pair
- Rolling 24-hour window

### Platform Rate Limits

Applies to **Business Discovery** and **Hashtag Search** endpoints.

### Messaging Rate Limits

| API | Limit |
|---|---|
| Conversations API | 2 calls/second per Instagram professional account |

### Publishing Limits

| Limit | Value |
|---|---|
| Containers created | 400 per 24 hours per account |
| Posts published (Instagram Login) | **100** per rolling 24 hours per account |
| Posts published (Facebook Login) | **50** per rolling 24 hours per account |
| Container expiry | 24 hours after creation |
| Carousel items | Max 10 images/videos per carousel (counts as 1 post) |

> The `content_publishing_limit` endpoint returns `quota_total: 50` for Facebook Login accounts. Instagram Login accounts have a higher 100-post limit enforced at the `media_publish` endpoint.
>
> **Project note:** Our codebase enforces 100/day via `ig_check_and_increment_rate_limit` DB function (defense-in-depth, accounting for container creation overhead).

---

## 5. Account / User Endpoints

Represents an Instagram Business Account or Creator Account. "Instagram User" and "Instagram Account" are used interchangeably throughout Meta docs.

### GET /me (Token Introspection)

Shortcut that resolves the user ID from the access token and queries the User endpoint. Only works with `graph.instagram.com`.

```
GET https://graph.instagram.com/v25.0/me
  ?fields=id,username,name,biography,followers_count
  &access_token={token}
```

Equivalent to `GET /{ig-user-id}` — same fields, edges, and permissions apply.

### GET User Profile

```
GET https://{host}/v25.0/{ig-user-id}
  ?fields=id,username,name,biography,followers_count,follows_count,media_count,profile_picture_url,website
  &access_token={token}
```

**Fields:**

| Field | Public | Description |
|---|---|---|
| `id` | ✅ | App-scoped User ID. Available for Page-backed accounts |
| `username` | ✅ | Instagram profile username |
| `name` | — | Instagram profile name |
| `biography` | ✅ | Profile bio text |
| `followers_count` | ✅ | Total followers |
| `follows_count` | — | Total following |
| `media_count` | ✅ | Total published media |
| `profile_picture_url` | — | Profile picture URL |
| `website` | ✅ | Website URL |
| `alt_text` | ✅ | Descriptive text for images (accessibility) |
| `has_profile_pic` | — | Whether account has a profile picture |
| `is_published` | — | Whether account is published. Page-backed accounts |
| `shopping_product_tag_eligibility` | — | `true` if Instagram Shop set up and eligible for product tagging |
| `account_type` | — | `Business` or `Media_Creator` |
| `user_id` | — | IG professional account ID (Instagram Login only, used in webhook `id` field) |
| `legacy_instagram_user_id` | — | Legacy ID for Marketing API endpoints (v21.0 and older). Page-backed accounts |

> Public fields can be returned via field expansion (e.g. through Business Discovery).

**Product tagging permissions:** If requesting `shopping_product_tag_eligibility`, also need `catalog_management` + `instagram_shopping_tag_products`, and app user must have admin role on the Business Manager owning the IG Shop.

**Edges:**

| Edge | Description |
|---|---|
| `media` | Collection of IG Media on the account |
| `stories` | Collection of story IG Media |
| `live_media` | Collection of live video IG Media |
| `insights` | Social interaction metrics (account-level) |
| `business_discovery` | Data about other Business/Creator accounts |
| `content_publishing_limit` | Current publishing usage |
| `media_publish` | Publish an IG Container |
| `mentions` | Reply to @mentions in comments or captions |
| `mentioned_comment` | Data on a comment where user was @mentioned |
| `mentioned_media` | Data on media where user was @mentioned in caption |
| `tags` | Media in which user has been tagged by others |
| `recently_searched_hashtags` | Hashtags searched in the last 7 days |
| `collaboration_invites` | Pending collaboration invitations (media_id, caption, media_url, owner username) |
| `connected_threads_user` | Threads account connected to this Instagram account |
| `instagram_backed_threads_user` | Threads account backed by this Instagram account |
| `agencies` | Businesses that can advertise for this account |
| `authorized_adaccounts` | Ad accounts that can advertise for this account |
| `upcoming_events` | Events this account is hosting |

**Example response:**
```json
{
  "biography": "Dino data crunching app",
  "id": "17841405822304914",
  "username": "metricsaurus",
  "website": "http://www.metricsaurus.com/"
}
```

### GET User Media List

```
GET https://{host}/v25.0/{ig-user-id}/media
  ?fields=id,caption,media_type,media_url,thumbnail_url,timestamp,like_count,comments_count,permalink
  &limit=25
  &since={unix_timestamp}
  &until={unix_timestamp}
  &access_token={token}
```

Supports cursor-based pagination via `after` / `before` cursors in the `paging.cursors` response object. Also supports **time-based pagination** via `since` / `until` (Unix timestamps or `strtotime` values).

**Limitations:**
- Returns a maximum of **10,000** of the most recently created media
- **Stories not included** — use `GET /{ig-user-id}/stories` instead

### GET User Stories

```
GET https://{host}/v25.0/{ig-user-id}/stories
  &access_token={token}
```

Returns a list of story IG Media objects. Use field expansion to get story fields (e.g. `?fields=id,media_type,media_url,timestamp`).

**Limitations:**
- **Live Video** stories are not included
- Stories are only available for **24 hours**
- **Reshared stories** (when a user reshares another story) are not returned
- Only **one caption** returned per story, even if multiple captions exist

**Permissions:** `instagram_basic`, `pages_read_engagement`. Business Manager: `ads_management` or `ads_read`.

---

## 6. Content Publishing

Publishing is a three-step process:
1. **Create a media container** — returns a container ID
2. **Upload media** (if resumable) and **poll container status** until `FINISHED`
3. **Publish the container** — makes it live

**General container limitations:**
- Containers expire after **24 hours**
- Max **400 containers** per account per rolling 24-hour period
- If the connected Page requires **Page Publishing Authorization (PPA)**, PPA must be completed or the request fails
- If the connected Page requires **two-factor authentication**, the Facebook User must also have completed 2FA
- App user must be able to perform **MANAGE** or **CREATE_CONTENT** tasks on the connected Page
- URLs should use **HTTP IETF standard character set** (US ASCII characters) — non-ASCII URLs may cause failures
- Reels **cannot appear in carousels**
- Reel privacy settings are respected on publish (e.g. "Allow remixing" enabled → remixing active on publish)
- Music tagging only available for **original audio**

### 6.1 Photo

**Step 1 — Create container:**
```
POST https://graph.facebook.com/v25.0/{ig-user-id}/media
  ?image_url=https://example.com/photo.jpg
  &caption=My%20caption
  &alt_text=Descriptive%20text%20for%20accessibility
  &location_id={fb-page-id}
  &user_tags=[{"username":"user1","x":0.5,"y":0.5}]
  &access_token={token}
```

| Parameter | Required | Description |
|---|---|---|
| `image_url` | Yes | Publicly accessible JPEG URL |
| `caption` | No | Up to 2200 characters |
| `alt_text` | No | Alt text for accessibility, up to 1000 characters. Single images and carousel image items only (not reels or stories) |
| `location_id` | No | Facebook Page ID for location tag |
| `user_tags` | No | Array of `{username, x, y}` objects |
| `collaborators` | No | Comma-separated collaborator usernames |
| `product_tags` | No | Array of product tag objects |

**Image specs:**
- Format: JPEG only
- Max file size: 8 MB
- Aspect ratio: 4:5 to 1.91:1
- Min width: 320px, Max width: 1440px
- Color space: sRGB

**Step 2 — Publish:**
```
POST https://graph.facebook.com/v25.0/{ig-user-id}/media_publish
  ?creation_id={container-id}
  &access_token={token}
```

**Response:**
```json
{ "id": "17896129349180431" }
```

### 6.2 Video / Reel

**Step 1 — Create container (standard URL upload):**
```
POST https://graph.facebook.com/v25.0/{ig-user-id}/media
  ?media_type=REELS
  &video_url=https://example.com/reel.mp4
  &caption=My%20reel
  &share_to_feed=true
  &cover_url=https://example.com/cover.jpg
  &audio_name=Original%20Audio
  &thumb_offset=5.5
  &collaborators=["user1","user2"]
  &user_tags=["<user-id>"]
  &location_id={fb-page-id}
  &access_token={token}
```

| Parameter | Required | Description |
|---|---|---|
| `media_type` | Yes | `REELS` |
| `video_url` | Yes | Publicly accessible video URL |
| `caption` | No | Up to 2200 characters |
| `share_to_feed` | No | `true` to share to feed (default: false) |
| `cover_url` | No | Cover image URL |
| `audio_name` | No | Audio track name (original audio only) |
| `thumb_offset` | No | Thumbnail time offset in **milliseconds** |
| `collaborators` | No | Array of collaborator usernames |
| `user_tags` | No | Array of user IDs to tag |
| `location_id` | No | Facebook Page ID for location |
| `trial_params` | No | Trial reel params: `{ graduation_strategy: "MANUAL" | "SS_PERFORMANCE" }`. `MANUAL` = graduate via app. `SS_PERFORMANCE` = auto-graduate if reel performs well |

**Reel video specs:**
- Container: MOV or MP4 (MPEG-4 Part 14)
- No edit lists, moov atom at the front
- Audio codec: AAC, max 48kHz, 1–2 channels, 128kbps
- Video codec: HEVC or H264, progressive, closed GOP, 4:2:0 chroma
- Frame rate: 23–60 FPS
- Max width: 1920px
- Recommended aspect ratio: 9:16
- Acceptable ratio range: 0.01:1 to 10:1
- Video bitrate: VBR, max 25Mbps
- Duration: 3 seconds minimum, 15 minutes maximum
- Max file size: 300 MB

**Reel cover photo specs:**
- Format: JPEG
- Max file size: 8 MB
- Color space: sRGB
- Recommended ratio: 9:16 (cropped to 1:1 for feed)

**Step 2 — Check container status (poll until FINISHED):**
```
GET https://graph.facebook.com/v25.0/{container-id}
  ?fields=status_code,status,copyright_check_status
  &access_token={token}
```

| Field | Description |
|---|---|
| `id` | Container ID |
| `status_code` | Publishing status (see below) |
| `status` | If `status_code` is `ERROR`, contains the error subcode |
| `copyright_check_status` | Video copyright detection: `matches_found` (`true`/`false`) + `status` (`completed`, `error`, `in_progress`, `not_started`) |

| `status_code` | Meaning |
|---|---|
| `EXPIRED` | Container expired (>24h) |
| `ERROR` | Failed — do not publish |
| `FINISHED` | Ready to publish |
| `IN_PROGRESS` | Processing |
| `PUBLISHED` | Already published |

**Step 3 — Publish:**
```
POST https://graph.facebook.com/v25.0/{ig-user-id}/media_publish
  ?creation_id={container-id}
  &access_token={token}
```

### 6.3 Carousel

**Step 1 — Create individual item containers** (one per image/video):
```
POST https://graph.facebook.com/v25.0/{ig-user-id}/media
  ?image_url=https://example.com/item1.jpg
  &is_carousel_item=true
  &access_token={token}
```

Repeat for each item (max 10 items, mix of images and videos allowed).

**Step 2 — Create carousel container:**
```
POST https://graph.facebook.com/v25.0/{ig-user-id}/media
  ?media_type=CAROUSEL
  &caption=Carousel%20caption
  &children=[<item-id-1>,<item-id-2>,...]
  &collaborators=user1,user2
  &location_id={fb-page-id}
  &product_tags={...}
  &access_token={token}
```

| Parameter | Required | Description |
|---|---|---|
| `media_type` | Yes | `CAROUSEL` |
| `children` | Yes | Array of up to 10 item container IDs |
| `caption` | No | Carousel caption |
| `collaborators` | No | Collaborator usernames |
| `location_id` | No | Facebook Page ID for location |
| `product_tags` | No | Product tags |

**Step 3 — Publish:**
```
POST https://graph.facebook.com/v25.0/{ig-user-id}/media_publish
  ?creation_id={carousel-container-id}
  &access_token={token}
```

### 6.4 Story

**Image story:**
```
POST https://{host}/v25.0/{ig-user-id}/media
  ?media_type=STORIES
  &image_url=https://example.com/story.jpg
  &user_tags=[{"username":"user1","x":0.5,"y":0.5}]
  &access_token={token}
```

**Video story:**
```
POST https://{host}/v25.0/{ig-user-id}/media
  ?media_type=STORIES
  &video_url=https://example.com/story.mp4
  &user_tags=[{"username":"user1"}]
  &access_token={token}
```

**Story `user_tags`** (added July 9, 2025): Mention users in stories with optional `x`, `y` coordinates to tag at a specific position.

**Story image specs:**
- Format: JPEG, max 8 MB
- Recommended aspect ratio: 9:16
- Color space: sRGB

**Story video specs:**
- Container: MOV or MP4 (MPEG-4 Part 14), no edit lists, moov atom at front
- Audio: AAC, max 48kHz, 1–2 channels, 128kbps
- Video: HEVC or H264, progressive, closed GOP, 4:2:0 chroma
- Frame rate: 23–60 FPS, max width: 1920px
- Aspect ratio: 0.1:1 to 10:1 (recommended 9:16)
- Video bitrate: VBR, max 25Mbps
- Duration: **3 seconds – 60 seconds**
- Max file size: **100 MB**

**Story limitations:**
- Stories expire after 24 hours
- Supports `video_url` OR `reels_url`, not both
- Publishing stickers (link, poll, location) is **not supported** via API
- User @mentions without stickers are supported

### 6.5 Resumable Uploads

For large videos. Works with `REELS`, `STORIES`, and `VIDEO` media types. Available with Facebook Login for Business; also supported for Instagram Login.

**Step 1 — Create resumable container:**
```
POST https://graph.facebook.com/v25.0/{ig-user-id}/media
  ?media_type=REELS
  &upload_type=resumable
  &caption=...
  &access_token={token}
```

**Response:**
```json
{
  "id": "<IG_CONTAINER_ID>",
  "uri": "https://rupload.facebook.com/ig-api-upload/v25.0/<IG_CONTAINER_ID>"
}
```

**Step 2a — Upload video from local file:**
```
POST https://rupload.facebook.com/ig-api-upload/v25.0/{container-id}
Authorization: OAuth {access_token}
offset: 0
file_size: {total_bytes}
Content-Type: application/octet-stream

[binary video data]
```

**Step 2b — Or upload from a hosted URL:**
```
POST https://rupload.facebook.com/ig-api-upload/v25.0/{container-id}
Authorization: OAuth {access_token}
file_url: https://example.com/video.mp4
```

**Upload response:**
```json
{ "success": true, "message": "Upload successful. ..." }
```

**Step 3 — Poll status, then publish** (same as standard flow).

### 6.6 Publishing Limits

```
GET https://<HOST_URL>/v25.0/{ig-user-id}/content_publishing_limit
  ?fields=config,quota_usage
  &since={unix_timestamp}
  &access_token={token}
```

> Use `graph.instagram.com` for Instagram Login, `graph.facebook.com` for Facebook Login.
> `since` is optional (Unix timestamp, max 24h old). Omit to get usage for the last 24 hours.

**Response:**
```json
{
  "data": [{
    "config": {
      "quota_total": 50,
      "quota_duration": 86400
    },
    "quota_usage": 3
  }]
}
```

### 6.7 Copyright Detection

Check if an uploaded video violates copyright **before publishing**:

```
GET https://graph.facebook.com/v25.0/{container-id}
  ?fields=copyright_check_status
  &access_token={token}
```

**Response (no violation):**
```json
{
  "copyright_check_status": {
    "status": "completed",
    "matches_found": false
  }
}
```

**Response (violation found):**
```json
{
  "copyright_check_status": {
    "status": "completed",
    "matches_found": true
  }
}
```

| `status` value | Meaning |
|---|---|
| `completed` | Check finished — read `matches_found` |
| `in_progress` | Still checking — poll again |
| `error` | Check failed |
| `not_started` | Check hasn't begun |

> **Not yet implemented in our codebase.** When added, check this AFTER container reaches `FINISHED` but BEFORE calling `media_publish`.

---

## 7. Media Objects

### GET Single Media Object

```
GET https://{host}/v25.0/{ig-media-id}
  ?fields=id,caption,media_type,media_url,thumbnail_url,timestamp,like_count,comments_count,permalink,shortcode,username,children,owner,media_product_type,is_comment_enabled,is_shared_to_feed,alt_text,copyright_check_information
  &access_token={token}
```

| Field | Description |
|---|---|
| `id` | Media ID |
| `caption` | Caption text. Excludes album children. `@` symbol excluded unless app user can perform admin tasks on connected FB Page. **FB Login only** |
| `media_type` | `IMAGE`, `VIDEO`, `CAROUSEL_ALBUM` |
| `media_url` | URL to media. **Omitted** if media contains copyrighted material or has a copyright violation (e.g. audio on reels) |
| `thumbnail_url` | Thumbnail for videos only |
| `timestamp` | ISO 8601 creation time (UTC) |
| `like_count` | Like count (includes replies on comments). Excludes album children and promoted posts. **Omitted** via field expansion if owner hides like counts |
| `comments_count` | Comment count. Excludes album children and captions. Includes replies |
| `media_product_type` | `AD`, `FEED`, `STORY`, `REELS`. **FB Login only** |
| `permalink` | Permanent URL. Cannot be used on photos within albums (children) |
| `shortcode` | Short code from URL |
| `username` | Owner username |
| `owner` | Object `{ id }` of owning account. Only returned if app user created the media |
| `alt_text` | Descriptive text for images (accessibility) |
| `is_comment_enabled` | Whether comments are enabled. Excludes album children |
| `is_shared_to_feed` | Reels only — `true` if reel can appear in both Feed and Reels tabs |
| `view_count` | View count for reels (paid + organic). **Business Discovery API only** |
| `copyright_check_information` | Copyright detection status + matches (see below) |
| `boost_ads_list` | Active ad info for organic media. **FB Login only** |
| `boost_eligibility_info` | Whether media is eligible to boost as ad. **FB Login only** |
| `legacy_instagram_media_id` | Legacy ID for Marketing API endpoints (v21.0 and older) |

**Copyright check information** (`copyright_check_information.status`):

| Sub-field | Description |
|---|---|
| `status` | `completed`, `error`, `in_progress`, `not_started` |
| `matches_found` | `true` if violating, `false` if not |
| `copyright_matches` | Array of `{ author, content_title, matched_segments[], owner_copyright_policy }` — only present when `matches_found: true` |

**Edges:**

| Edge | Description |
|---|---|
| `children` | Album/carousel child media |
| `collaborators` | Collaborator users. **FB Login only** |
| `comments` | Comments on the media |
| `insights` | Social interaction metrics |

**Limitations:**
- Aggregated fields (like_count, comments_count) don't include ads-driven data
- Live video media can only be read during broadcast
- Only returns data for professional accounts — not personal accounts

### GET Media Children (Carousel)

```
GET https://{host}/v25.0/{carousel-media-id}/children
  ?fields=id,media_type,media_url
  &access_token={token}
```

### POST Enable / Disable Comments

```
POST https://{host}/v25.0/{ig-media-id}
  ?comment_enabled=true
  &access_token={token}
```

Set `comment_enabled=false` to disable. Not supported on live video.

**Permissions:** `instagram_business_manage_comments` (IG Login) or `instagram_manage_comments` + `pages_read_engagement` (FB Login)

### DELETE Media

```
DELETE https://graph.facebook.com/v25.0/{ig-media-id}
  ?access_token={token}
```

**Facebook Login only.** Permission: `instagram_manage_contents`.

**Limitations:**
- Supports non-ad posts, stories, reels, and entire carousel albums
- Cannot delete individual items within a carousel — must delete the entire carousel by its container media ID

**Success response:**
```json
{ "success": true, "deleted_id": "17918920912340654" }
```

**Failure response (unsupported media type):**
```json
{
  "error": {
    "code": -1,
    "error_subcode": 2207073,
    "error_user_title": "Media Type Not Supported",
    "error_user_msg": "The media type is not supported for this endpoint"
  }
}
```

---

## 8. Comments & Replies

### IG Comment Fields

| Field | Description |
|---|---|
| `id` | Comment ID |
| `text` | Comment text |
| `timestamp` | ISO 8601 creation time (e.g. `2017-05-19T23:27:28+0000`) |
| `username` | Username of commenter. **Since Aug 27, 2024:** requires `instagram_business_manage_comments` (IG Login) or `instagram_manage_comments` (FB Login) |
| `from` | Object: `{ id, username }` of the commenter (IGSID) |
| `user` | ID of commenter — only returned if the app user created the comment; otherwise `username` is returned |
| `like_count` | Number of likes on the comment |
| `hidden` | `true` if comment is hidden, `false` otherwise |
| `media` | Object: `{ id, media_product_type }` of the media the comment was made on |
| `parent_id` | ID of parent comment (if this is a reply) |
| `replies` | Edge — list of reply comments |
| `legacy_instagram_comment_id` | Legacy ID for Marketing API endpoints (v21.0 and older) |

### POST Comment on Media

```
POST https://{host}/v25.0/{ig-media-id}/comments
  ?message=This%20is%20awesome!
  &access_token={token}
```

**Response:**
```json
{ "id": "17870913679156914" }
```

**Limitations:** Comments on live video media are not supported.

> **Non-organic comments:** Comments on ads containing IG Media are a different type and not returned by these endpoints. Use the Marketing API with `effective_instagram_media_id` to get ad comments.

### GET Comments on Media

```
GET https://{host}/v25.0/{ig-media-id}/comments
  ?fields=id,text,username,timestamp,like_count,from,hidden,replies
  &access_token={token}
```

**Limitations:**
- Returns **top-level comments only** — use `replies` field expansion to get replies
- Max **50 comments** per query
- Results returned in **reverse chronological** order (v3.2+)
- Cannot filter by timestamp

### GET Single Comment

```
GET https://graph.facebook.com/v25.0/{ig-comment-id}
  ?fields=id,text,username,timestamp,like_count,hidden,from,media,parent_id
  &access_token={token}
```

**Example response:**
```json
{
  "hidden": false,
  "media": { "id": "17856134461174448" },
  "timestamp": "2017-05-19T23:27:28+0000",
  "id": "17881770991003328"
}
```

### GET Replies on a Comment

```
GET https://graph.facebook.com/v25.0/{ig-comment-id}/replies
  ?fields=id,text,username,timestamp,like_count
  &access_token={token}
```

**Example response:**
```json
{
  "data": [
    { "timestamp": "2017-08-31T16:53:49+0000", "text": "This is a great comment", "id": "17871618799146774" },
    { "timestamp": "2017-08-30T04:24:45+0000", "text": "It's me. Trust me.", "id": "17887288333072596" }
  ]
}
```

**Limitations:**
- Cannot get replies on a deleted comment

### POST Reply to Comment

```
POST https://graph.facebook.com/v25.0/{ig-comment-id}/replies
  ?message=Your%20reply%20text
  &access_token={token}
```

**Response:**
```json
{ "id": "17873440459141021" }
```

**Limitations:**
- Can only reply to **top-level comments** — replies to a reply are added to the top-level comment
- Cannot reply to **hidden** comments
- Cannot reply to comments on **live video** — use Private Replies (Messaging API) instead

> To comment on a media object directly (not a reply), use `POST /{ig-media-id}/comments` instead.

### POST Hide / Unhide Comment

```
POST https://graph.facebook.com/v25.0/{ig-comment-id}
  ?hide=true
  &access_token={token}
```

`hide=false` to unhide.

**Limitations:**
- Comments made by media owners on their own media are always displayed, even if `hide=true`
- Not supported on live video media

**Response:**
```json
{ "success": true }
```

### POST Disable / Enable Comments on Media

```
POST https://graph.facebook.com/v25.0/{ig-media-id}
  ?comment_enabled=false
  &access_token={token}
```

Set `comment_enabled=true` to re-enable.

### DELETE Comment

```
DELETE https://graph.facebook.com/v25.0/{ig-comment-id}
  ?access_token={token}
```

**Limitations:**
- Only the **media owner** can delete a comment — not the comment author
- Not supported on live video media

**Response:**
```json
{ "success": true }
```

**Required permissions:** `instagram_business_manage_comments` (Instagram Login) or `instagram_manage_comments` + `pages_read_engagement` (Facebook Login). If app user has a Business Manager Page role, also needs `ads_management` or `ads_read`.

**Reading limitations:**
- Cannot read comments discovered through Mentions API unless requested by the comment owner (use Mentioned Comment node instead)
- Comments on age-gated media are not returned
- Comments from restricted users are hidden until unrestricted and approved
- Comments on live video can only be read during the broadcast

> **Project note:** `list_ig_comments` MCP tool queries local DB (`ig_comments` table). `hide_ig_comment` and `reply_to_ig_comment` call the Graph API directly. `private_reply_ig_comment` uses the Messaging API (see Section 13).

---

## 9. Mentions

Triggered when another user @mentions your Business/Creator account in a comment or caption. Use the `media_id` and `comment_id` from the webhook notification payload.

**Permissions (Instagram Login):** `instagram_business_basic`, `instagram_business_manage_comments`

### Reply to a Caption Mention

```
POST https://{host}/v25.0/{ig-user-id}/mentions
  ?media_id={media-id}
  &message=Thanks%20for%20the%20mention!
  &access_token={token}
```

| Parameter | Required | Description |
|---|---|---|
| `media_id` | Yes | Media ID from the webhook notification payload |
| `message` | Yes | Text to include in the comment |

### Reply to a Mention in a Comment

```
POST https://{host}/v25.0/{ig-user-id}/mentions
  ?comment_id={comment-id}
  &media_id={media-id}
  &message=Thanks%20for%20the%20mention!
  &access_token={token}
```

| Parameter | Required | Description |
|---|---|---|
| `comment_id` | Yes | Comment ID from the webhook notification payload |
| `media_id` | Yes | Media ID from the webhook notification payload |
| `message` | Yes | Text to include in the comment |

**Response:**
```json
{ "id": "17846319838228163" }
```

**Permissions (Facebook Login):** `instagram_basic`, `instagram_manage_comments`, `pages_read_engagement`. Comment replies also need `pages_show_list`. Business Manager Page roles also need `ads_management` or `ads_read`.

**Limitations:**
- Does not support replies to **Story mentions**
- Cannot comment on photos where you were merely **tagged** (must be @mentioned in text)
- Webhooks will not be sent if the media was created by a **private account**

### GET Mentioned Comment

Read data about a comment where your user was @mentioned. Use the `comment_id` from the webhook notification payload.

```
GET https://{host}/v25.0/{ig-user-id}
  ?fields=mentioned_comment.comment_id({comment-id}){id,text,timestamp,like_count,media{id,media_url}}
  &access_token={token}
```

| Field | Description |
|---|---|
| `id` | Comment ID (default) |
| `text` | Comment text (default) |
| `timestamp` | ISO 8601 creation time (default) |
| `like_count` | Number of likes |
| `media` | ID of the media. Supports field expansion: `media{id,media_url,media_type}` |

**Response:**
```json
{
  "mentioned_comment": {
    "timestamp": "2017-05-03T16:09:08+0000",
    "like_count": 185,
    "text": "Shout out to @metricsaurus",
    "id": "17873440459141021",
    "media": { "id": "17895695668004550", "media_url": "https://scont..." }
  },
  "id": "17841405309211844"
}
```

**Limitations:**
- Returns an error if comments have been **disabled** on the media where you were @mentioned
- `like_count` on expanded IG Media is **omitted** if the media owner has hidden like counts (v11.0+)

**Permissions:** `instagram_basic`, `instagram_manage_comments`, `pages_read_engagement`. Business Manager: `ads_management` or `ads_read`. Tasks: MANAGE, CREATE_CONTENT, or MODERATE.

### GET Mentioned Media

Read data about a media object where your user was @mentioned in the caption.

```
GET https://{host}/v25.0/{ig-user-id}
  ?fields=mentioned_media.media_id({media-id}){id,caption,media_type,media_url,timestamp,like_count,comments_count,comments,owner,username}
  &access_token={token}
```

| Field | Description |
|---|---|
| `id` | Media ID (default) |
| `caption` | Caption text. **`@` symbol stripped** unless the app user created the media |
| `media_type` | `CAROUSEL_ALBUM`, `IMAGE`, `STORY`, or `VIDEO` |
| `media_url` | URL of the published media |
| `timestamp` | ISO 8601 creation time |
| `like_count` | Like count (excludes album children and promoted posts). **Omitted** if owner hides likes (v11.0+) |
| `comments_count` | Comment count |
| `comments` | List of comments. `@` in comment text also stripped unless app user created the media |
| `owner` | Creator ID — only returned if app user created the media |
| `username` | Creator username — returned when `owner` is not |

**Response:**
```json
{
  "mentioned_media": {
    "caption": "metricsaurus headquarters!",
    "media_type": "IMAGE",
    "id": "17873440459141021"
  },
  "id": "17841405309211844"
}
```

> Note: The `@` symbol was stripped from the original caption (`@metricsaurus headquarters!`) because the app user did not create it.

**Permissions:** `instagram_basic`, `instagram_manage_comments`, `pages_read_engagement`. Business Manager: `ads_management` or `ads_read`. Tasks: MANAGE, CREATE_CONTENT, or MODERATE.

### GET Tagged Media

Returns media objects where your user has been tagged by another Instagram user.

```
GET https://{host}/v25.0/{ig-user-id}/tags
  ?fields=id,username,media_type,media_url,timestamp,caption
  &access_token={token}
```

**Response:**
```json
{
  "data": [
    { "id": "18038...", "username": "keldo..." },
    { "id": "17930...", "username": "ashla..." }
  ]
}
```

Supports cursor-based pagination (manual — use `before`/`after` cursors, no `previous`/`next` URLs).

**Limitations:** Private media is not returned.

**Permissions:** `instagram_basic`, `instagram_manage_comments`, `pages_read_engagement`. Business Manager: `ads_management` or `ads_read`.

### Collaboration Invites (Dec 2025)

Query and accept/decline collaboration invitations on the app user's Instagram account.

**GET pending invitations:**
```
GET https://graph.instagram.com/v25.0/{ig-user-id}/collaboration_invites
  ?access_token={token}
```

Returns media objects where the app user has been invited to collaborate (media_id, caption, media_url, owner username).

**POST accept/decline:**
```
POST https://graph.instagram.com/v25.0/{ig-user-id}/collaboration_invites
  ?media_id={media-id}
  &action=accept   // or "decline"
  &access_token={token}
```

**Permissions (Facebook Login):** `instagram_basic`

---

## 10. Insights (Analytics)

> **Critical v18+ change:** All account-level insights require the `metric_type` parameter (`time_series` or `total_value`). Without it, the API silently drops metrics. Different metrics require different `metric_type` values — you must make **two separate calls**.

### 10.1 Account-Level Insights

Account insights require **two API calls** because some metrics only work with `time_series` and others only with `total_value`.

**Permissions:** `instagram_business_manage_insights` (IG Login) or `instagram_manage_insights` + `pages_read_engagement` (FB Login). Business Manager Page roles also need `ads_management` or `ads_read`.

**Full request syntax:**
```
GET https://{host}/v25.0/{ig-user-id}/insights
  ?metric={metrics}
  &period={period}
  &metric_type={time_series|total_value}
  &breakdown={breakdown}
  &since={unix_timestamp}
  &until={unix_timestamp}
  &timeframe={timeframe}
  &access_token={token}
```

**Call 1 — time_series metrics:**
```
GET https://{host}/v25.0/{ig-user-id}/insights
  ?metric=reach,follower_count
  &period=day
  &metric_type=time_series
  &since={unix_timestamp}
  &until={unix_timestamp}
  &access_token={token}
```

> `follower_count` is **day-only** and not returned for accounts with <100 followers. For `week` or `days_28` periods, request only `reach`.

**Call 2 — total_value metrics:**
```
GET https://{host}/v25.0/{ig-user-id}/insights
  ?metric=accounts_engaged,total_interactions,profile_links_taps,views,likes,comments,shares,saves,reposts,follows_and_unfollows
  &period=day
  &metric_type=total_value
  &breakdown=media_product_type
  &access_token={token}
```

> `profile_links_taps` is **Instagram Login only** (not available for Facebook Login accounts).

**General limitations:**
- `follower_count` and `online_followers` not available for accounts with **<100 followers**
- `online_followers` data only available for the **last 30 days**
- If requested data doesn't exist or is unavailable, returns **empty data set** (not `0`)
- Demographic metrics only return the **top 45** performers
- Only viewers with demographic data are used — summing values may be less than actual totals
- Data used to calculate metrics can be **delayed up to 48 hours**
- Breakdowns only work with `metric_type=total_value` — ignored for `time_series`
- Requesting a metric that doesn't support a breakdown returns an error (`"An unknown error has occurred."`)

**Periods:**

| `period` | Description |
|---|---|
| `day` | Per day |
| `week` | 7-day rolling (not all metrics) |
| `days_28` | 28-day rolling (not all metrics) |
| `lifetime` | Demographics only |

**Range (`since`/`until`):** UNIX timestamps defining an inclusive range. If omitted, the API looks back **24 hours**. For demographic metrics, `timeframe` overrides these values.

**Timeframe (demographics only):**

| Value | Description |
|---|---|
| `this_month` | Last 30 days |
| `this_week` | Last 7 days |
| `last_14_days` | Last 14 days (**deprecated v20.0+**) |
| `last_30_days` | Last 30 days (**deprecated v20.0+**) |
| `last_90_days` | Last 90 days (**deprecated v20.0+**) |
| `prev_month` | Previous month (**deprecated v20.0+**) |

**Available account metrics (v25.0):**

| Metric | `metric_type` | Period | Breakdowns | Description |
|---|---|---|---|---|
| `reach` | `time_series` or `total_value` | day | `media_product_type`, `follow_type` | Unique accounts that saw content (estimated) |
| `follower_count` | `time_series` | day only | — | Current follower count (<100 returns empty) |
| `accounts_engaged` | `total_value` | day | — | Accounts that interacted with content (estimated) |
| `total_interactions` | `total_value` | day | `media_product_type` | Total interactions across all content including boosted |
| `profile_links_taps` | `total_value` | day | `contact_button_type` | Taps on business address/call/email/text buttons (IG Login only) |
| `views` | `total_value` | day | `follower_type`, `media_product_type` | Times content was played/displayed. Replaces deprecated `impressions`. **In development** |
| `likes` | `total_value` | day | `media_product_type` | Total likes on posts, reels, videos |
| `comments` | `total_value` | day | `media_product_type` | Total comments. **In development** |
| `shares` | `total_value` | day | `media_product_type` | Total shares |
| `saves` | `total_value` | day | `media_product_type` | Total saves |
| `reposts` | `total_value` | day | — | Total reposts |
| `replies` | `total_value` | day | — | Story replies (text + quick reactions) |
| `follows_and_unfollows` | `total_value` | day | `follow_type` | Daily follow/unfollow counts (<100 followers returns empty) |
| `impressions` | `total_value` or `time_series` | day | — | Times content was on screen. **Deprecated v22.0+, all versions April 21, 2025** |
| `online_followers` | — | lifetime | — | Hourly audience activity (see 10.4) |
| `follower_demographics` | `total_value` | lifetime | `age`, `city`, `country`, `gender` | Follower demographics. Requires `timeframe`. <100 followers returns empty (see 10.5) |
| `engaged_audience_demographics` | `total_value` | lifetime | `age`, `city`, `country`, `gender` | Engaged audience demographics. Requires `timeframe`. <100 engagements returns empty (see 10.5) |

**Breakdown values:**

| Breakdown | Possible values |
|---|---|
| `media_product_type` | `AD`, `FEED`, `REELS`, `STORY` |
| `follow_type` / `follower_type` | `FOLLOWER`, `NON_FOLLOWER`, `UNKNOWN` |
| `contact_button_type` | `BOOK_NOW`, `CALL`, `DIRECTION`, `EMAIL`, `INSTANT_EXPERIENCE`, `TEXT`, `UNDEFINED` |

**time_series response:**
```json
{
  "data": [{
    "name": "reach",
    "period": "day",
    "values": [
      { "value": 12050, "end_time": "2024-01-01T08:00:00+0000" },
      { "value": 14200, "end_time": "2024-01-02T08:00:00+0000" }
    ],
    "id": "17841405822304914/insights/reach/day"
  }]
}
```

**total_value response (with breakdown):**
```json
{
  "data": [{
    "name": "reach",
    "period": "day",
    "title": "Accounts reached",
    "total_value": {
      "value": 224,
      "breakdowns": [{
        "dimension_keys": ["media_product_type"],
        "results": [
          { "dimension_values": ["FEED"], "value": 124 },
          { "dimension_values": ["REELS"], "value": 100 }
        ]
      }]
    },
    "id": "17841405309211844/insights/reach/day"
  }]
}
```

> **Project implementation:** See `api/_lib/metaApiConfig.ts` — `ACCOUNT_INSIGHTS.timeSeries` and `ACCOUNT_INSIGHTS.totalValue` define the exact metric sets per login type.

### 10.2 Media-Level Insights

```
GET https://{host}/v25.0/{ig-media-id}/insights
  ?metric=views,reach,likes,comments,shares,saved
  &breakdown={breakdown}
  &access_token={token}
```

**Permissions:** `instagram_business_manage_insights` (IG Login) or `instagram_manage_insights` + `pages_read_engagement` (FB Login). Business Manager Page roles also need `ads_management` or `ads_read`.

**General limitations:**
- If requested data doesn't exist or is unavailable, returns **empty data set** (not `0`)
- Data used to calculate metrics can be **delayed up to 48 hours**
- Metrics data stored for **up to 2 years**
- Only reports **organic** interactions — ad interactions not counted
- **Album children:** insights not available for individual media within an album
- Period is automatically set to `lifetime` and cannot be changed

**Available media metrics (v25.0):**

| Metric | Feed | Reels | Story | Description |
|---|---|---|---|---|
| `views` | ✅ | ✅ | ✅ | Total times the media has been seen. **Metric in development** |
| `reach` | ✅ | ✅ | ✅ | Unique accounts that saw it. Estimated |
| `likes` | ✅ | ✅ | — | Like count |
| `comments` | ✅ | ✅ | — | Comment count |
| `shares` | ✅ | ✅ | ✅ | Share count |
| `saved` | ✅ | ✅ | — | Save count |
| `total_interactions` | ✅ | ✅ | ✅ | Likes + saves + comments + shares minus unlikes/unsaves/deleted comments. **Metric in development** |
| `follows` | ✅ | — | ✅ | Users who followed after seeing this media |
| `profile_activity` | ✅ | — | ✅ | Profile actions taken after engaging with content. Supports `action_type` breakdown |
| `profile_visits` | ✅ | — | ✅ | Profile visits after seeing this media |
| `ig_reels_avg_watch_time` | — | ✅ | — | Average time spent playing the reel |
| `ig_reels_video_view_total_time` | — | ✅ | — | Total playback time including replays. **Metric in development** |
| `reels_skip_rate` | — | ✅ | — | Percentage of reel views that were skipped (Dec 2025) |
| `reposts` | ✅ | ✅ | — | Number of reposts (Dec 2025) |
| `crossposted_views` | — | ✅ | — | Total views for reels crossposted to Facebook (Instagram + Facebook combined). Does NOT affect Business Discovery `view_count` (Dec 2025) |
| `facebook_views` | — | ✅ | — | Views specifically from Facebook for crossposted reels (Dec 2025) |

**Breakdowns:**

| Breakdown | Compatible Metric | Values |
|---|---|---|
| `action_type` | `profile_activity` | `BIO_LINK_CLICKED`, `CALL`, `DIRECTION`, `EMAIL`, `OTHER`, `TEXT` |
| `story_navigation_action_type` | `navigation` (stories) | `TAP_FORWARD` (Forward), `TAP_BACK` (Back), `TAP_EXIT` (Exit), `SWIPE_FORWARD` (Next Story) |

> **Warning:** Requesting a metric that doesn't support breakdowns alongside the `breakdown` parameter returns an error (`"An unknown error has occurred."`). Don't mix breakdown-compatible and non-compatible metrics in a single query.

**Carousel metrics:** Aggregate across all children. Use `GET /{carousel-id}/children` then `GET /{child-id}/insights` for per-item breakdown.

**Response:**
```json
{
  "data": [
    {
      "name": "profile_activity",
      "period": "lifetime",
      "values": [{ "value": 4 }],
      "title": "Profile activity",
      "description": "...",
      "total_value": {
        "value": 4,
        "breakdowns": [{
          "dimension_keys": ["action_type"],
          "results": [
            { "dimension_values": ["email"], "value": 1 },
            { "dimension_values": ["bio_link_clicked"], "value": 1 },
            { "dimension_values": ["direction"], "value": 1 },
            { "dimension_values": ["text"], "value": 1 }
          ]
        }]
      },
      "id": "17932174733377207/insights/profile_activity/lifetime"
    }
  ]
}
```

> **Fallback:** If the primary metric set is rejected (error code 100), our codebase falls back to `likes,comments` — the minimum always-available set.

**Deprecated metrics (removed v22.0, all versions April 21, 2025):**

| Metric | Was | Replacement |
|---|---|---|
| `impressions` | Total times media seen (FEED/STORY) | `views`. Still available for media created before July 2, 2024 on v21.0 and older |
| `plays` | Reel play count excluding replays (REELS) | `views` |
| `clips_replays_count` | Reel replay count (REELS) | `views` |
| `ig_reels_aggregated_all_plays_count` | Reel plays + replays including XAR (REELS) | `views` |
| `video_views` | — | `views` |
| `engagement` | Likes + comments (v18.0, deprecated Dec 2023) | `total_interactions` |
| `CAROUSEL_ALBUM_IMPRESSIONS` | Carousel-specific impressions (deprecated Dec 2023) | Use standard `views` on parent media |
| `CAROUSEL_ALBUM_REACH` | Carousel-specific reach (deprecated Dec 2023) | Use standard `reach` on parent media |
| `CAROUSEL_ALBUM_ENGAGEMENT` | Carousel-specific engagement (deprecated Dec 2023) | Use `total_interactions` |
| `CAROUSEL_ALBUM_SAVED` | Carousel-specific saves (deprecated Dec 2023) | Use standard `saved` |
| `CAROUSEL_ALBUM_VIDEO_VIEWS` | Carousel video views (deprecated Dec 2023) | Use standard `views` |
| `TAPS_FORWARD` | Story taps forward (deprecated Dec 2023) | Use `navigation` with `story_navigation_action_type` breakdown |
| `TAPS_BACK` | Story taps back (deprecated Dec 2023) | Use `navigation` with breakdown |
| `EXITS` | Story exits (deprecated Dec 2023) | Use `navigation` with breakdown |

### 10.3 Story Insights

Stories have different metrics and unique limitations:

```
GET https://{host}/v25.0/{ig-story-media-id}/insights
  ?metric=views,reach,replies,navigation
  &breakdown=story_navigation_action_type
  &access_token={token}
```

| Metric | Description |
|---|---|
| `views` | Times the story was displayed (replaces `impressions`) |
| `reach` | Unique accounts that saw the story |
| `replies` | Text replies + quick reactions |
| `navigation` | Total navigation actions. Use `story_navigation_action_type` breakdown for detail |
| `follows` | Users who followed after seeing this story |
| `profile_activity` | Profile actions after engaging. Use `action_type` breakdown |
| `profile_visits` | Profile visits from this story |
| `shares` | Share count |
| `total_interactions` | Net interactions (likes + saves + comments + shares minus removals) |

**Story-specific limitations:**
- Story metrics are **only available for 24 hours** after the story expires
- Subscribe to `story_insights` webhook to capture insights before expiry. May receive data after expiry if story is added to a highlight
- Stories with **fewer than 5 viewers** return error code 10: *"Not enough viewers for the media to show insights"*
- **Europe & Japan:** `replies` returns `0` for stories created by users in these regions. Replies from users in these regions are excluded from all story reply calculations
- **Insights webhook** for Instagram API with Instagram Login is **not supported**

**Navigation breakdown response:**
```json
{
  "data": [{
    "name": "navigation",
    "period": "lifetime",
    "values": [{ "value": 25 }],
    "total_value": {
      "value": 25,
      "breakdowns": [{
        "dimension_keys": ["story_navigation_action_type"],
        "results": [
          { "dimension_values": ["tap_forward"], "value": 19 },
          { "dimension_values": ["tap_back"], "value": 4 },
          { "dimension_values": ["tap_exit"], "value": 1 },
          { "dimension_values": ["swipe_forward"], "value": 1 }
        ]
      }]
    },
    "id": "17969782069736348/insights/navigation/lifetime"
  }]
}
```

> **Project implementation:** See `STORY_INSIGHT_METRICS` in `api/_lib/metaApiConfig.ts`.

### 10.4 Online Followers

Returns hourly audience activity data (hours 0-23 UTC) for the last 30 days. Requires 100+ followers.

```
GET https://graph.facebook.com/v25.0/{ig-user-id}/insights
  ?metric=online_followers
  &period=lifetime
  &access_token={token}
```

> **Project endpoint:** `GET /api/instagram/online-followers?accountId={uuid}` (6-hour Redis cache).

### 10.5 Audience Demographics

Three demographic metrics are available, each with different data:

**Follower demographics** (who follows you):
```
GET https://graph.facebook.com/v25.0/{ig-user-id}/insights
  ?metric=follower_demographics
  &period=lifetime
  &timeframe=this_month
  &breakdown=country
  &metric_type=total_value
  &access_token={token}
```

**Engaged audience demographics** (who engages with your content):
```
GET https://graph.facebook.com/v25.0/{ig-user-id}/insights
  ?metric=engaged_audience_demographics
  &period=lifetime
  &timeframe=this_month
  &breakdown=country
  &metric_type=total_value
  &access_token={token}
```

**Supported breakdowns:** `country`, `city`, `gender`, `age`

**Supported timeframes:**
- `this_month` — last 30 days
- `this_week` — last 7 days

> **Deprecated timeframes (removed in v20.0):** `last_14_days`, `last_30_days`, `last_90_days`, `prev_month`

**Limitations:**
- Not returned if account has <100 followers (follower) or <100 engagements (engaged)
- Only top 45 values returned per breakdown
- Only viewers with demographic data are included — totals may be less than actual counts

**Deprecated demographic metrics (removed v18.0):**
`AUDIENCE_GENDER_AGE`, `AUDIENCE_LOCALE`, `AUDIENCE_COUNTRY`, `AUDIENCE_CITY`

**Response:**
```json
{
  "data": [{
    "name": "follower_demographics",
    "period": "lifetime",
    "total_value": {
      "breakdowns": [{
        "dimension_keys": ["timeframe", "country"],
        "results": [
          { "dimension_values": ["THIS_MONTH", "US"], "value": 5000 },
          { "dimension_values": ["THIS_MONTH", "CA"], "value": 800 }
        ]
      }]
    }
  }]
}
```

### 10.6 Deprecated Metrics Reference

These metrics are **no longer available** on v22.0+ (enforced for all versions April 21, 2025):

| Deprecated metric | Replacement | Level |
|---|---|---|
| `impressions` (account) | `views` | Account |
| `impressions` (media) | `views` | Media |
| `profile_views` | — (removed, no replacement) | Account |
| `website_clicks` | `profile_links_taps` | Account |
| `email_contacts` | — (removed) | Account |
| `get_directions_clicks` | — (removed) | Account |
| `phone_call_clicks` | — (removed) | Account |
| `text_message_clicks` | — (removed) | Account |
| `plays` | `views` | Media |
| `video_views` | `views` | Media |
| `clips_replays_count` | — (removed) | Media |
| `ig_reels_aggregated_all_plays_count` | `views` | Media |
| `taps_forward` / `taps_back` / `exits` | `navigation` | Story |

---

## 11. Hashtag Search

**Step 1 — Get hashtag ID:**
```
GET https://graph.facebook.com/v25.0/ig_hashtag_search
  ?user_id={ig-user-id}
  &q=bluebottle
  &access_token={token}
```

**Response:**
```json
{ "data": [{ "id": "17873440459141021" }] }
```

**Step 2 — Get top/recent media for hashtag:**
```
GET https://graph.facebook.com/v25.0/{hashtag-id}/top_media
  ?user_id={ig-user-id}
  &fields=id,caption,media_type,media_url,permalink,timestamp
  &access_token={token}
```

```
GET https://graph.facebook.com/v25.0/{hashtag-id}/recent_media
  ?user_id={ig-user-id}
  &fields=id,caption,media_type,permalink,timestamp
  &access_token={token}
```

**Step 3 (optional) — Read hashtag node fields:**
```
GET https://graph.facebook.com/v25.0/{hashtag-id}
  ?fields=id,name
  &access_token={token}
```

| Field | Description |
|---|---|
| `id` | Hashtag ID (static and global — same hashtag = same ID everywhere) |
| `name` | Hashtag name without the leading `#` |

**Edges:** `recent_media`, `top_media` (shown above)

**Hashtag Search limitations:**
- **Facebook Login only** — not available with Instagram Business Login
- Max 30 unique hashtag queries per 7 days per user
- Hashtag IDs are static (same hashtag = same ID across API versions)
- Sensitive or offensive hashtags are blocked
- Requires **Instagram Public Content Access** feature approval
- Subject to Platform Rate Limits (not Business Use Case limits)

### GET Recently Searched Hashtags

Returns hashtags the user has queried via the Hashtag Search endpoint within the last 7 days.

```
GET https://graph.facebook.com/v25.0/{ig-user-id}/recently_searched_hashtags
  ?limit=30
  &access_token={token}
```

**Response:**
```json
{
  "data": [
    { "id": "17841562906103814" },
    { "id": "17841563587120501" }
  ]
}
```

**Notes:**
- A queried hashtag counts against the 30/7-day limit on first query only — subsequent queries of the same hashtag don't count
- Default 25 results per page, max **30** via `limit=30`
- Emojis in hashtag queries are **not supported**
- Requires **Instagram Public Content Access** feature

---

## 12. Business Discovery

Look up any public Instagram Business or Creator account by username. The request is made **on your own account ID** with the target specified via `.username()` syntax.

```
GET https://graph.facebook.com/v25.0/{your-ig-user-id}
  ?fields=business_discovery.username(bluebottle){followers_count,media_count,biography,profile_picture_url,website,media{id,caption,media_url,timestamp,like_count,comments_count}}
  &access_token={token}
```

> Note the syntax: `business_discovery.username(<TARGET>){<FIELDS>}` — the target username goes in parentheses, requested fields in braces.

**Response:**
```json
{
  "business_discovery": {
    "followers_count": 267788,
    "media_count": 1205,
    "id": "17841401441775531"
  },
  "id": "17841405309211844"
}
```

**Required permissions (Facebook Login):** `instagram_basic`, `instagram_manage_insights`, `pages_read_engagement`

**Limitations:**
- Only works for public Business and Creator accounts
- Cannot look up personal accounts
- Age-gated accounts will not return data
- Subject to Platform Rate Limits

---

## 13. Messaging (DMs)

**Required permissions:** `instagram_business_basic`, `instagram_business_manage_messages`

**Webhook subscriptions:** `messages`, `messaging_optins`, `messaging_postbacks`, `messaging_reactions`, `messaging_referrals`, `messaging_seen`

**24-hour window:** Your app has 24 hours to respond to any message sent from an Instagram user. Use `human_agent` tag to extend to 7 days.

### Inbox Folder Behavior

| Folder | Behavior |
|---|---|
| **Primary** | New conversations from followers appear here |
| **Requests** | New conversations from non-followers appear here |
| **General** | Conversation moves here only after your app user replies via your app |

**Inbox Limitations:**
- Inbox folders are **not supported** via the API — messages don't include folder information
- Webhook notifications and API-delivered messages are **not marked as Read** in the Instagram app — only after a reply is sent
- Messages in Requests folder inactive for **30 days** are not returned in API calls
- Group messaging is not supported — one customer per conversation only

### Media Types & Size Limits

| Type | Supported Formats | Max Size |
|---|---|---|
| Audio | aac, m4a, wav, mp4 | 25MB |
| Image | png, jpeg | 8MB |
| Video | mp4, ogg, avi, mov, webm | 25MB |
| File | pdf | 25MB |

### GET Conversations List

```
GET https://graph.instagram.com/v25.0/me/conversations
  ?platform=instagram
  &access_token={token}
```

Returns `id` and `updated_time` for each conversation.

**Find conversation with a specific person:**
```
GET https://graph.instagram.com/v25.0/me/conversations
  ?user_id={ig-scoped-id}
  &access_token={token}
```

### GET Messages in Conversation

```
GET https://graph.instagram.com/v25.0/{conversation-id}
  ?fields=messages
  &access_token={token}
```

Returns message IDs and `created_time` for each message.

### GET Message Details

```
GET https://graph.instagram.com/v25.0/{message-id}
  ?fields=id,created_time,from,to,message
  &access_token={token}
```

Default fields: `id`, `created_time`.

> **Limitation:** You can only get details about the **20 most recent messages** in a conversation. Older messages return a "deleted" error.

### POST Send Message

```
POST https://graph.instagram.com/v25.0/{ig-user-id}/messages
Content-Type: application/json

{
  "recipient": { "id": "{recipient-ig-scoped-id}" },
  "message": { "text": "Hello!" }
}
```

Message text must be **UTF-8** and **1000 bytes or less**. Links must be valid formatted URLs.

**Response:**
```json
{ "recipient_id": "IGSID", "message_id": "MESSAGE-ID" }
```

### POST Send Attachment (Image/Audio/Video/File)

```
POST https://graph.instagram.com/v25.0/{ig-user-id}/messages
Content-Type: application/json

{
  "recipient": { "id": "{ig-scoped-id}" },
  "message": {
    "attachment": {
      "type": "image",
      "payload": { "url": "<IMAGE_URL>" }
    }
  }
}
```

Attachment `type` values: `image`, `audio`, `video`, `file`

**Multi-image send** (beta, Nov 2025): Use `attachments` (array) instead of `attachment` — up to 10 images per message. Some accounts may get error subcode `2534068` during rollout.

### POST Send Sticker (Heart)

```json
{
  "recipient": { "id": "{ig-scoped-id}" },
  "message": {
    "attachment": { "type": "like_heart" }
  }
}
```

### POST React/Unreact to Message

```json
{
  "recipient": { "id": "{ig-scoped-id}" },
  "sender_action": "react",
  "payload": {
    "message_id": "<MESSAGE_ID>",
    "reaction": "😊"
  }
}
```

- To edit a reaction: repeat with new emoji
- To remove: set `sender_action` to `unreact`, omit `reaction`

### POST Send Published Post (Media Share)

```json
{
  "recipient": { "id": "{ig-scoped-id}" },
  "message": {
    "attachment": {
      "type": "MEDIA_SHARE",
      "payload": { "id": "<POST_ID>" }
    }
  }
}
```

App user must own the post.

**For Human Agent replies** (within 7-day window):
```json
{
  "recipient": { "id": "{ig-scoped-id}" },
  "message": { "text": "Let me help you with that." },
  "messaging_type": "RESPONSE",
  "tag": "human_agent"
}
```

### POST Send Generic Template (Carousel Cards)

```
POST https://graph.instagram.com/v25.0/{ig-user-id}/messages
Content-Type: application/json

{
  "recipient": { "id": "{ig-scoped-id}" },
  "message": {
    "attachment": {
      "type": "template",
      "payload": {
        "template_type": "generic",
        "elements": [
          {
            "title": "Product Name",
            "subtitle": "Description here",
            "image_url": "https://example.com/image.jpg",
            "default_action": { "type": "web_url", "url": "https://example.com" },
            "buttons": [
              { "type": "web_url", "url": "https://example.com", "title": "View" },
              { "type": "postback", "title": "Buy", "payload": "BUY_PRODUCT_1" }
            ]
          }
        ]
      }
    }
  }
}
```

- Max 10 elements per template (horizontally scrollable carousel)
- Max 3 buttons per element
- Button types: `web_url` and `postback` only
- Title/subtitle: 80 character limit each

### POST Send Quick Replies

```json
{
  "recipient": { "id": "{ig-scoped-id}" },
  "messaging_type": "RESPONSE",
  "message": {
    "text": "What is your favorite color?",
    "quick_replies": [
      { "content_type": "text", "title": "Red", "payload": "RED_PAYLOAD" },
      { "content_type": "text", "title": "Blue", "payload": "BLUE_PAYLOAD" }
    ]
  }
}
```

- Max **13** quick replies per message
- Quick reply title: max 20 characters (truncated if longer)
- Only supports plain text (`content_type: "text"`)
- **Not available on desktop** — mobile only
- When tapped: buttons dismiss, title posted as message, webhook fires with `quick_reply.payload`

### Ice Breakers

Pre-set questions shown when a user opens a conversation with your account for the first time.

**Create:**
```
POST https://graph.instagram.com/v25.0/{ig-user-id}/messenger_profile
Content-Type: application/json

{
  "platform": "instagram",
  "ice_breakers": [{
    "call_to_actions": [
      { "question": "What are your hours?", "payload": "HOURS_PAYLOAD" },
      { "question": "Where are you located?", "payload": "LOCATION_PAYLOAD" }
    ]
  }]
}
```

**Delete:**
```
DELETE https://graph.instagram.com/v25.0/me/messenger_profile
Content-Type: application/json

{ "fields": ["ice_breakers"] }
```

When a user taps an ice breaker, your app receives a `messaging_postbacks` webhook.

### Persistent Menu

A menu always visible in the conversation thread.

```
POST https://graph.instagram.com/v25.0/{ig-user-id}/messenger_profile
Content-Type: application/json

{
  "platform": "instagram",
  "persistent_menu": [{
    "locale": "default",
    "composer_input_disabled": false,
    "call_to_actions": [
      { "type": "postback", "title": "Help", "payload": "HELP_PAYLOAD" },
      { "type": "web_url", "title": "Visit Website", "url": "https://example.com", "webview_height_ratio": "full" }
    ]
  }]
}
```

Supports locale-specific menus. Button types: `postback` and `web_url`.

### POST Sender Actions (Typing Indicator / Mark Seen)

```
POST https://graph.instagram.com/v25.0/me/messages
Content-Type: application/json

{
  "recipient": { "id": "{ig-scoped-id}" },
  "sender_action": "typing_on"
}
```

| Action | Description |
|---|---|
| `typing_on` | Show typing indicator |
| `typing_off` | Hide typing indicator |
| `mark_seen` | Mark most recent message as seen |

**Limitations:**
- Request must contain **only** `sender_action` + `recipient` — no `text`, `attachment`, or `template` in the same request
- Recipient must be signed in for sender actions to display

### GET Messaging User Profile

```
GET https://graph.instagram.com/v25.0/{ig-scoped-user-id}
  ?fields=name,username,profile_pic,follower_count,is_user_follow_business,is_business_follow_user
  &access_token={token}
```

> `profile_pic` URL is temporary and expires. `is_user_follow_business` / `is_business_follow_user` indicate follow relationship.

**User consent required:** The Instagram user must have sent a message to your app user, or clicked an icebreaker/persistent menu. Commenting alone is NOT sufficient — your app will receive error "User consent is required to access user profile."

**Limitations:**
- If the Instagram user has blocked your app user, profile information is not available
- `profile_pic` URL is temporary and expires

**Rate limit:** 2 calls/second per Instagram professional account (Conversations API).

**Required permissions:** `instagram_business_basic`, `instagram_business_manage_messages`

### Private Replies to Comments

Send a private DM to someone who commented on your app user's post, reel, story, Live, or ad.

**Flow:**
1. User comments on your app user's content
2. Webhook fires (`comments` or `live_comments` field) with comment ID, commenter's IG-scoped ID, and media ID
3. Your app sends a private reply using the comment ID → appears in commenter's Inbox (if they follow) or Requests folder (if not)
4. Reply includes a link back to the commented post

**Request:**

```
POST https://{host}/v25.0/{app-user-ig-id}/messages
Content-Type: application/json
Authorization: Bearer {token}

{
  "recipient": { "comment_id": "{comment-id}" },
  "message": { "text": "Thanks for your comment!" }
}
```

**Response:**

```json
{
  "recipient_id": "526...",
  "message_id": "aWdfZ..."
}
```

**Limitations:**
- Only **one** private reply per comment
- Must be sent within **7 days** of the comment (posts/reels/stories)
- **Live:** replies only allowed during the broadcast — not after it ends
- Follow-up messages only if the recipient responds, within **24 hours** of their response

**Permissions:**

| Login Type | Permissions |
|---|---|
| Instagram Login | `instagram_business_basic`, `instagram_business_manage_comments` |
| Facebook Login | `instagram_basic`, `instagram_manage_comments`, `pages_read_engagement` |

If the app user was granted a Page role via Business Manager, also requires `ads_management` + `ads_read`.

**Webhook fields:** `comments`, `live_comments`

> **Project note:** `private_reply_ig_comment` MCP tool wraps this endpoint. Backend: `POST /{ig-id}/messages` with `recipient.comment_id`.

---

## 14. Batch API

Send up to 50 Graph API requests in a single HTTP call.

```
POST https://graph.facebook.com/v25.0/
Content-Type: application/x-www-form-urlencoded

access_token={token}&batch=[{"method":"GET","relative_url":"..."},{"method":"GET","relative_url":"..."}]
```

| Parameter | Required | Description |
|---|---|---|
| `access_token` | Yes | Goes in body, **not** Authorization header |
| `batch` | Yes | JSON array of request objects (max 50 items) |

**Each batch item:**
```json
{
  "method": "GET",
  "relative_url": "{ig-media-id}/insights?metric=views,reach,likes,comments,shares,saved"
}
```

**Response:** Array of response objects (one per batch item):
```json
[
  { "code": 200, "body": "{\"data\":[...]}" },
  { "code": 200, "body": "{\"data\":[...]}" }
]
```

**Limitations:**
- **Facebook Login only** — Instagram Business Login tokens are NOT compatible (returns empty 200)
- Max 50 items per batch request
- Body is form-encoded (`application/x-www-form-urlencoded`)
- Each batch item's `body` is also form-encoded (for POST items)
- Base URL must be `graph.facebook.com` (not `graph.instagram.com`)
- Rate limits: each item in the batch counts as a separate API call

> **Project implementation:** Used in `api/_lib/instagramApi.ts` for bulk post insights fetching. Config: `api/_lib/metaApiConfig.ts` — `BATCH_API` object (`maxBatchSize: 50`, `supportedLoginTypes: ["facebook"]`).

---

## 15. Collaborators

Read the list of users added as collaborators on an IG Media object and their invitation status.

Available for Instagram API with **Facebook Login** only.

### GET Collaborators on Media

```
GET https://graph.facebook.com/v25.0/{ig-media-id}/collaborators
  &access_token={token}
```

**Required permissions:** `instagram_basic`, `pages_read_engagement`. If Page role was granted via Business Manager, also need `ads_management` or `ads_read`.

**Access token:** User token — user must have created the media object.

**Response:**
```json
{
  "data": [
    {
      "id": "90010775360791",
      "username": "realtest1",
      "invite_status": "Accepted"
    },
    {
      "id": "17841449208283139",
      "username": "realtest2",
      "invite_status": "Pending"
    }
  ]
}
```

| Field | Description |
|---|---|
| `id` | App-scoped ID for the collaborator's Instagram account |
| `username` | Instagram username |
| `invite_status` | `Accepted` or `Pending` |

**Limitations:**
- Max 5 collaborators per media
- Only users who have enabled collaborator tagging are returned
- Supports Feed image, Reels, and Carousel — **not Stories**
- Create/Update/Delete not supported via API (set at publish time via `collaborators` param in Section 6)

---

## 16. Saved Media

Retrieve media saved by the authenticated user.

```
GET https://graph.facebook.com/v25.0/{ig-user-id}/saved_media
  ?fields=id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,username,like_count,comments_count
  &access_token={token}
```

**Required permission:** `instagram_manage_saved_media`

> **Project endpoint:** `POST /api/instagram/saved-media?action=list`

---

## 17. Instagram oEmbed

Retrieve embed HTML and metadata for public Instagram posts.

```
GET https://graph.facebook.com/v25.0/instagram_oembed
  ?url=https://www.instagram.com/p/ABC123/
  &access_token={token}
```

| Parameter | Required | Description |
|---|---|---|
| `url` | Yes | Full URL of public IG post (photo, video, Reel, Feed) |
| `access_token` | Yes | App access token (backend) or User access token |
| `maxwidth` | No | Max embed width in pixels (min 320) |
| `fields` | No | Comma-separated fields to return (e.g. `thumbnail_url,author_name,provider_name,provider_url`) |
| `hidecaption` | No | `true` to hide caption in embed |

**Response:**
```json
{
  "version": "1.0",
  "author_name": "username",
  "provider_name": "Instagram",
  "provider_url": "https://www.instagram.com",
  "type": "rich",
  "width": 658,
  "html": "<blockquote class=\"instagram-media\" ...>...</blockquote><script async src=\"//www.instagram.com/embed.js\"></script>",
  "thumbnail_url": "https://...",
  "thumbnail_width": 640,
  "thumbnail_height": 640
}
```

**Requirements:**
- **"Meta oEmbed Read"** feature required (App Review). Replaces old "oEmbed Read" (deprecated November 3, 2025).
- Works with App access tokens (preferred for server-side) or User access tokens.
- Only public posts are supported.

> **Not yet implemented in our codebase.** We have Threads oEmbed but not Instagram.

---

## 18. Webhooks

### Setup Overview

1. Create HTTPS endpoint on your server that handles `GET` (verification) and `POST` (events)
2. Subscribe app to webhook fields in Meta App Dashboard
3. Enable per-account webhook subscription via API
4. Test by sending a message/comment

### Webhook Verification (GET)

Meta sends a GET request to verify your endpoint:
```
GET https://your-server.com/webhook
  ?hub.mode=subscribe
  &hub.verify_token=YOUR_VERIFY_TOKEN
  &hub.challenge=CHALLENGE_STRING
```

Respond with `200` and echo `hub.challenge` in the body.

### Webhook Events (POST)

All events share this envelope:
```json
{
  "object": "instagram",
  "entry": [{
    "id": "{ig-user-id}",
    "time": 1678886400,
    "changes": [{
      "field": "{event-field}",
      "value": { ... }
    }]
  }]
}
```

### Available Webhook Fields

| Field | Description |
|---|---|
| `comments` | New comment on your media |
| `mentions` | Your account @mentioned in a comment or caption |
| `messages` | New DM received |
| `message_reactions` | Reaction to a DM |
| `messaging_handover` | Handover protocol events between apps |
| `messaging_optins` | User opted in via send-to-Messenger plugin or checkbox |
| `messaging_policy_enforcement` | Policy enforcement actions (e.g., block) |
| `messaging_postbacks` | Postback button tapped (ice breaker, CTA, persistent menu) |
| `messaging_referral` | User arrived via referral (ad, ig.me link, etc.) |
| `messaging_seen` | Message read receipt |
| `message_edit` | Message edited by sender (Sep 2025). Supports both IG Login and FB Login |
| `message_echoes` | Echo of messages sent by your app (included in `messages` subscription) |
| `response_feedback` | Feedback on automated responses |
| `standby` | Messages in standby channel (handover protocol) |
| `story_insights` | Story expired with final insights |
| `live_comments` | Comments on a live broadcast |

### Comments Event Payload

```json
{
  "field": "comments",
  "value": {
    "from": { "id": "<scoped-user-id>", "username": "example_user" },
    "comment_id": "<comment-id>",
    "parent_id": null,
    "text": "Great post!",
    "media": { "id": "<media-id>" }
  }
}
```

### Mentions Event Payload

```json
{
  "field": "mentions",
  "value": {
    "comment_id": "17894227972186120",
    "media_id": "17918195224117851"
  }
}
```

### Messages Event Payload

```json
{
  "field": "messages",
  "value": {
    "sender": { "id": "<sender-ig-scoped-id>" },
    "recipient": { "id": "<your-ig-user-id>" },
    "timestamp": 1678886400000,
    "message": { "mid": "<message-id>", "text": "Hello!" }
  }
}
```

**Story reply webhooks** include `link_sticker_url` field in `reply_to.story` object when the user replied to a story with a link sticker (Dec 2025). Can be used to trigger different messaging automations based on the story's link sticker URL.

### Subscribe Account to Webhooks (API)

```
POST https://graph.facebook.com/v25.0/{ig-user-id}/subscribed_apps
  ?subscribed_fields=comments,mentions,messages
  &access_token={token}
```

**Subscription limitations:**
- App must be set to **Live** in App Dashboard to receive notifications
- **Advanced Access** required for `comments` and `live_comments`
- IG professional account must be **public** to receive comment/mention notifications
- `live_comments` only sent **during** the broadcast
- Account-level customization not supported — subscribing to any field means receiving **all** subscribed fields
- Album IDs not included in notifications — use Comment ID to look up album
- `story_insights` only shows metrics for the first 24 hours (even for highlights)
- Failed deliveries retry with decreasing frequency over **36 hours**, then dropped. Handle deduplication.
- Batches up to **1,000 updates** per notification (not guaranteed)

### Post Share Attachment Migration (Nov 2025 → Feb 2026)

**Starting November 3, 2025:** Webhook payloads for Instagram post shares include TWO attachments — the existing `share` type and a new `ig_post` type. Both contain the same data: `ig_post_media_id`, `title` (caption), and `url`.

**February 1, 2026:** The `share` attachment type for IG posts will be **removed**. Migrate to `ig_post` before this date.

```json
{
  "type": "ig_post",
  "payload": {
    "ig_post_media_id": "18139494541428835",
    "title": "Caption text...",
    "url": "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=18139494541428835={SIGNATURE}"
  }
}
```

> **Project action needed:** Check if our webhook processor (`api/instagram/webhook.ts`) handles `type: "ig_post"` attachments. If it only checks for `type: "share"`, update before Feb 1, 2026.

### Webhook Security — HMAC Verification

All incoming webhook POST requests include an `X-Hub-Signature-256` header:
```
X-Hub-Signature-256: sha256=<hmac>
```

Verify:
```typescript
import * as crypto from "crypto";
const signature = crypto
  .createHmac("sha256", process.env.META_APP_SECRET!)
  .update(rawBody)
  .digest("hex");
const isValid = `sha256=${signature}` === req.headers["x-hub-signature-256"];
```

---

## 19. Error Codes

Error responses follow this structure:

```json
{
  "error": {
    "message": "The image size is too large.",
    "type": "OAuthException",
    "code": 36000,
    "error_subcode": 2207004,
    "is_transient": false,
    "error_user_title": "Image size too large",
    "error_user_msg": "The image is too large to download. It should be less than 8 MiB.",
    "fbtrace_id": "A6LJylpZRKw2xKLFsAP-cJh"
  }
}
```

### Content Publishing Errors

| HTTP | Code | Subcode | User Message | Solution |
|---|---|---|---|---|
| 400 | -2 | 2207003 | It takes too long to download the media | Timeout downloading media. Retry. |
| 400 | -2 | 2207020 | The media you are trying to access has expired | Generate a new container ID and retry. |
| 400 | -1 | 2207001 | Instagram server error | Transient. Retry. |
| 400 | -1 | 2207032 | Create media fail, please try to re-create media | Failed to create container. Retry. |
| 400 | -1 | 2207053 | Unknown upload error | Generate new container and retry (video uploads). |
| 400 | 1 | 2207057 | Thumbnail offset must be ≥ 0 and < video duration | Fix `thumb_offset` to be within video length (ms). |
| 400 | 4 | 2207051 | We restrict certain activity to protect our community | Publishing action suspected as spam. |
| 400 | 9 | 2207042 | Maximum number of posts reached | Daily publishing limit hit. Retry next day. |
| 400 | 24 | 2207006 | The media with {media-id} cannot be found | Possible permission error or expired token. Regenerate container. |
| 400 | 24 | 2207008 | The media builder does not exist or has expired | Transient. Retry 1–2× in 30s–2min, then regenerate container. |
| 400 | 25 | 2207050 | The Instagram account is restricted | Account inactive/checkpointed. User must fix in Instagram app. |
| 400 | 100 | 2207023 | The media type is unknown | Invalid `media_type`. Use IMAGE, VIDEO, CAROUSEL, REELS, or STORIES. |
| 400 | 100 | 2207028 | Carousels need 2–10 photos/videos | Fix carousel item count. |
| 400 | 100 | 2207035 | Product tag positions should not be specified for video | Videos don't support X/Y tag coordinates. |
| 400 | 100 | 2207036 | Product tag positions are required for photo media | Images require X/Y coordinates for product tags. |
| 400 | 100 | 2207037 | Couldn't add all product tags | Product ID invalid, deleted, or no permission. Re-fetch catalogs. |
| 400 | 100 | 2207040 | Cannot use more than {max} tags per media | Max 20 @ tags per post. |
| 400 | 352 | 2207026 | Video format not supported | Use MOV or MP4 (MPEG-4 Part 14). |
| 400 | 9004 | 2207052 | Media could not be fetched from this URI | URI invalid or not publicly accessible. |
| 400 | 9007 | 2207027 | Media not ready for publishing | Poll container status; publish when `FINISHED`. |
| 400 | 36000 | 2207004 | Image too large (< 8 MiB) | Reduce image file size below 8 MiB. |
| 400 | 36001 | 2207005 | Image format not supported | Use JPEG or PNG. |
| 400 | 36003 | 2207009 | Invalid aspect ratio | Must be between 4:5 and 1.91:1. |
| 400 | 36004 | 2207010 | Caption too long | Max 2,200 characters, 30 hashtags, 20 @ tags. |

### General Graph API Errors

| Code | Name | Description |
|---|---|---|
| 100 | Invalid parameter | Missing or malformed parameter |
| 102 | Session key invalid | Access token expired or revoked |
| 190 | Invalid OAuth 2.0 Access Token | Bad token |
| 200-299 | Permission denied | Missing permission for the requested operation |
| 400 | API Session | User needs to re-authenticate |
| 368 | Temporarily blocked | Account temporarily blocked from API |
| 4 | Application request limit | App-level rate limit hit |
| 17 | User request limit | Per-user rate limit hit |
| 32 | Page-level throttling | Page/account rate limit hit |
| 613 | Calls to this API have exceeded the rate limit | Business Use Case rate limit |

**Retryable errors (transient):**
- `2` — Service temporarily unavailable
- `4` — Rate limit (back off and retry)
- `17` — Rate limit
- `341` — Feed action request limit

> **Project note:** `isRetryableMetaError()` in `api/_lib/retryUtils.ts` matches codes 2, 4, 17, and 341 for automatic retry via `withRetry()`.

---

## 20. Project-Specific Notes

### API Version

This project uses **v25.0** for all Instagram/Facebook Graph API calls. Configured in:
- `api/_lib/metaApiConfig.ts` — `META_API_VERSION = "v25.0"`

### Token Handling

Tokens are encrypted at rest with AES-256-GCM. Decryption happens **only** in API routes, never on the frontend:

```typescript
import * as crypto from "crypto";  // Use * as for Vercel compatibility
// NEVER decrypt on frontend
```

### IG Insights — Permission-Missing Accounts

Some accounts may not have insights permissions (e.g., personal accounts converted without proper setup). The project caches these with Redis:

```
ig-no-insights:{accountId}  →  TTL: 24 hours
```

Flush via: `POST /api/instagram/flush-insights-cache?accountId=X`

### Partial Metrics Handling

`instagramApi.ts` returns `partial + missingMetrics` when Meta doesn't return all requested metrics. Both `analyticsSync.ts` and `instagramRefresh.ts` only write DB columns whose metric was actually returned — never overwrite with `null`.

### Column Name Gotcha

| Table | Followers field |
|---|---|
| `accounts` | `followers_count` (plural) |
| `instagram_accounts` | `follower_count` (singular) |

### Retry Utility

```typescript
import { withRetry, isRetryableMetaError } from './_lib/retryUtils';
const data = await withRetry(
  () => fetchFromMeta(url),
  { isRetryable: isRetryableMetaError }
);
```

### Publishing Limit Check

Always check publishing cap before posting:
```typescript
GET /api/instagram/publishing-limit?accountId={id}
```

Returns `{ used, limit, resetAt }`. Block publishing when `used >= limit`.

### Container ID Expiry

Containers expire **24 hours** after creation. The project polls container status before publishing and handles `EXPIRED` / `ERROR` status codes.

### IG Publishing Pipeline — Full Parameter Support

All IG publishing parameters are wired end-to-end across all 5 publish paths (immediate handler, schedule handler, QStash, cron, container-publisher):

| Parameter | Type | Description | Storage |
|---|---|---|---|
| `mediaType` / `igMediaType` | string | IMAGE, VIDEO, REELS, STORIES, CAROUSEL | `ig_media_type` column |
| `altText` | string | Image accessibility description | `alt_text` column |
| `locationId` | string | Facebook Places location ID | `location_id` column |
| `collaborators` | string[] | Up to 3 IG usernames for collab posts | `metadata` JSONB |
| `coverUrl` | string | Reel cover image URL | `metadata` JSONB |
| `shareToFeed` | boolean | Show Reel in Feed tab (REELS only) | `metadata` JSONB |
| `userTags` | {username, x, y}[] | Tag users in images (0-1 coordinates) | `metadata` JSONB |
| `trialReels` / `isTrialReel` | boolean | Publish as Trial Reel | `metadata` JSONB |

Both `mediaType`/`igMediaType` and `trialReels`/`isTrialReel` aliases are accepted (MCP sends one form, frontend sends the other).

### Auto-Attach Media from Group Library

When scheduling posts via `bulk_schedule_groups` without explicit `mediaIds`, the handler auto-selects random media from the group's media library:

- **Instagram**: always attaches media (required by API). Fails if no media in group.
- **Threads**: attaches media ~30% of the time (configurable per group via `media_attachment_chance` on `auto_post_group_config`).
- Uses `getRandomMediaWithContext()` from auto-poster publisher — validates URL reachability via HEAD request with Redis caching.
- `autoAttachMedia: false` disables auto-attachment.
- Explicit `mediaIds` (even empty `[]`) always takes precedence over auto-attach.

### Engagement Sync After Publish

All publish paths schedule account-level engagement syncs at 1h, 6h, and 24h via QStash using the shared `schedulePostPublishSyncs()` helper in `qstashSchedule.ts`. Dedup IDs are namespaced by platform + source (e.g., `instagram-immediate-{postId}-3600`).

### QStash Fan-Out for Large Batches

When syncing more than 20 IG accounts simultaneously, the `sync-orchestrator` cron uses QStash fan-out to avoid Vercel function timeout limits:
- Batches >20 accounts → QStash queue per account
- Each QStash message triggers `periodic-sync` for that single account

### Webhook Architecture

- Endpoint: `juno33.com/api/instagram/webhook`
- 8 subscribed fields
- Per-account config in Meta App Dashboard
- Dedup: `UNIQUE (event_type, user_id, payload_id)` on `webhook_events` table
- HMAC: uses `META_APP_SECRET` env var
- Async-first: returns `200` immediately after DB insert, QStash nudge (5s delay) triggers `webhook-processor` cron

### Cron Jobs Related to Instagram

| Cron | Schedule | Function |
|---|---|---|
| `sync-orchestrator` | Every 15 min | Dispatches IG analytics sync |
| `analytics-pipeline` | 2 AM daily | Full IG refresh + aggregations |
| `ig-container-publisher` | Via publish-worker | Polls and publishes IG containers |
| `daily-orchestrator` | 1 AM daily | Token refresh phase |

---

## 21. Changelog Summary (Key Changes 2024–2026)

Condensed from Meta's official Instagram Platform changelog. Only items relevant to our app.

| Date | Change | Section |
|---|---|---|
| Feb 6, 2026 | `enable_fb_login` re-introduced for OAuth | §2 |
| Dec 19, 2025 | PDF attachment support in DMs | §13 |
| Dec 12, 2025 | `link_sticker_url` in story reply webhooks | §18 |
| Dec 3, 2025 | Collaboration Invites API (`GET/POST /<IG_USER_ID>/collaboration_invites`) | §9 |
| Dec 3, 2025 | New metrics: `reels_skip_rate`, `reposts`, `crossposted_views`, `facebook_views` | §10.2 |
| Dec 3, 2025 | Trial Reels (`trial_params`) in Content Publishing API | §6 |
| Dec 3, 2025 | DELETE `/{ig_media_id}` — delete posts/carousels/reels/stories | §7 |
| Nov 3, 2025 | Multi-image DM sending (beta) | §13 |
| Oct 27, 2025 | Post share attachment type migration (`share` → `ig_post`) in messaging webhooks | §18 |
| Sep 23, 2025 | Sender Actions: `typing_on`, `typing_off`, `mark_seen` | §13 |
| Sep 10, 2025 | `message_edit` webhook subscription | §18 |
| Jun 16, 2025 | `view_count` field on IG Media (Business Discovery, Reels only) | §7 |
| Jun 14, 2025 | `force_reauth` param introduced; `enable_fb_login` + `force_authentication` deprecated | §2 |
| Mar 24, 2025 | `alt_text` field for image posts on publishing endpoint | §6, §7 |
| Jan 21, 2025 | Insights available for IG Login apps. `views` metric. Deprecations: `impressions`, `plays`, `clips_replays_count`, `ig_reels_aggregated_all_plays_count` | §10 |
| Sep 17, 2024 | New scope values: `instagram_business_*` (old `business_*` deprecated Jan 27, 2025) | §2 |
| Jul 23, 2024 | Launch of Instagram API with Instagram Login (no Page required, `graph.instagram.com` host) | §1 |

**Deprecated & removed:**
- **Instagram Basic Display API** — deprecated Dec 4, 2024, all requests return errors
- **v1.0 endpoints** — deprecated v22.0+, all versions May 20, 2025
- **User insight metrics** (v21.0+): `email_contacts`, `get_direction_clicks`, `profile_views`, `text_message_clicks`, `website_clicks`, `phone_call_clicks`
- **Media insight metrics** (v22.0+): `impressions`, `plays`, `clips_replays_count`, `ig_reels_aggregated_all_plays_count`, `video_views`
- **Timeframes** (v20.0+): `last_14_days`, `last_30_days`, `last_90_days`, `prev_month` for demographic metrics
- **oEmbed fields** (Nov 3, 2025): `author_name`, `author_url`, `thumbnail_url`, `thumbnail_width`, `thumbnail_height`
- **`VIDEO` media_type** (Nov 9, 2023): No longer supported for publishing — use `REELS` instead
- **Carousel/story legacy metrics** (Dec 2023): `CAROUSEL_ALBUM_*`, `TAPS_FORWARD`, `TAPS_BACK`, `EXITS`, `engagement`
- **User insight legacy metrics** (Dec 2023): `AUDIENCE_GENDER_AGE`, `AUDIENCE_LOCALE`, `AUDIENCE_COUNTRY`, `AUDIENCE_CITY`

**Historical milestones:**
- Jul 2024: Instagram Login launched (no Page required, `graph.instagram.com` host)
- Jun 2022: Reels publishing support (`media_type=REELS`)
- Mar 2022: Carousel publishing support
- Nov 2021: Live video support (live_media edge, live_comments webhook, private replies)
- Jun 2021: `like_count` hidden behavior (v11.0+), time-based pagination (`since`/`until`) on user media
- Dec 2020: Europe story replies = 0 (ePrivacy Directive); Apr 2021: Japan story replies = 0
- Dec 2019: Account insights require 100+ followers
- Oct 2018: Hashtag Search API launched
