# Threads API Reference — v1.0

> Verified reference for the Threads Graph API. All endpoints use **v1.0**.
> Base URLs: `graph.threads.net` or `graph.threads.com` (both valid since Jun 2025).

---

## Table of Contents

1. [Overview & Base URLs](#1-overview--base-urls)
2. [Authentication & Access Tokens](#2-authentication--access-tokens)
3. [Permissions](#3-permissions)
4. [Rate Limits](#4-rate-limits)
5. [Media Specifications](#5-media-specifications)
6. [Publishing](#6-publishing)
7. [Media Retrieval](#7-media-retrieval)
8. [Keyword & Topic Tag Search](#8-keyword--topic-tag-search)
9. [Mentions](#9-mentions)
10. [Reply Management](#10-reply-management)
11. [Delete Posts](#11-delete-posts)
12. [User Profiles](#12-user-profiles)
13. [Insights](#13-insights)
14. [Webhooks](#14-webhooks)
15. [oEmbed](#15-oembed)
16. [Web Intents](#16-web-intents)
17. [Debug Token](#17-debug-token)
18. [Troubleshooting](#18-troubleshooting)
19. [API Endpoint Reference](#19-api-endpoint-reference)
20. [Changelog](#20-changelog)

---

## §1 Overview & Base URLs

The Threads API enables apps to create/publish content, retrieve posts, manage replies, view insights, and embed posts on behalf of Threads users.

**Base URLs** (both valid):
- `https://graph.threads.net`
- `https://graph.threads.com`

All endpoints use API version **v1.0** (unlike Instagram which uses v25.0).

**Key differences from Instagram API:**
- Separate OAuth flow (threads.net, not facebook.com)
- Separate app ID and app secret (Threads-specific, not Meta/FB)
- Token grant types use `th_exchange_token` / `th_refresh_token` (not `ig_exchange_token`)
- No batch API
- All tokens are app-scoped (not page-scoped)

---

## §2 Authentication & Access Tokens

### Authorization Window

Present users with the Threads authorization window to get permissions and authorization codes:

```
https://threads.net/oauth/authorize
  ?client_id=<THREADS_APP_ID>
  &redirect_uri=<REDIRECT_URI>
  &scope=<SCOPE>
  &response_type=code
  &state=<STATE>              // Optional, for CSRF protection
```

| Parameter | Required | Description |
|-----------|----------|-------------|
| `client_id` | Yes | Threads App ID (App Dashboard > App settings > Basic > Threads App ID) |
| `redirect_uri` | Yes | Must exactly match an OAuth URI in app settings |
| `response_type` | Yes | Always `code` |
| `scope` | Yes | Comma or URL-encoded space-separated list. `threads_basic` required. |
| `state` | No | Passed back on redirect for CSRF protection |

> On Android, open the URL in native webview/browser, NOT the native app.

**Successful redirect:**
```
https://your-app.com/auth/?code=AQBx-hBsH3...#_
```
> Strip `#_` from the end — it is not part of the code.

**Canceled redirect:**
```
https://your-app.com/auth/?error=access_denied&error_reason=user_denied&error_description=The+user+denied+your+request
```

### Step 1 — Exchange Code for Short-Lived Token

Authorization codes are valid for **1 hour** and single-use.

```
POST https://graph.threads.net/oauth/access_token

Body (form data):
  client_id=<THREADS_APP_ID>
  client_secret=<THREADS_APP_SECRET>
  grant_type=authorization_code
  redirect_uri=<REDIRECT_URI>
  code=<AUTHORIZATION_CODE>
```

**Response:**
```json
{
  "access_token": "THQVJ...",
  "user_id": 17841405793187218
}
```

### Step 2 — Exchange for Long-Lived Token

Short-lived tokens expire in **1 hour**. Exchange for a long-lived token (60 days).

```
GET https://graph.threads.net/access_token
  ?grant_type=th_exchange_token
  &client_secret=<THREADS_APP_SECRET>
  &access_token=<SHORT_LIVED_TOKEN>
```

**Response:**
```json
{
  "access_token": "<LONG_LIVED_USER_ACCESS_TOKEN>",
  "token_type": "bearer",
  "expires_in": 5183944
}
```

> **Server-side only** — never expose `client_secret` in frontend code.
> Expired short-lived tokens CANNOT be exchanged.

### Refresh Long-Lived Token

```
GET https://graph.threads.net/refresh_access_token
  ?grant_type=th_refresh_token
  &access_token=<LONG_LIVED_TOKEN>
```

Token must be **at least 24 hours old** but **not expired**. Refreshed tokens are valid for **60 days**. Tokens not refreshed in 60 days expire permanently.

> Long-lived tokens for **private profiles** can now be refreshed. Permissions for private profile users are valid for **90 days**.

> Permission grants for **public profiles** are valid for **90 days**. Refreshing the token extends the permission grant for another 90 days.

### App Access Tokens

Used for app-level requests (e.g., oEmbed API). No user authentication required.

```
GET https://graph.threads.net/oauth/access_token
  ?client_id=<APP_ID>
  &client_secret=<APP_SECRET>
  &grant_type=client_credentials
```

**Response:**
```json
{
  "access_token": "TH|<APP_ID>|<ACCESS_TOKEN>",
  "token_type": "bearer"
}
```

**Alternate method** (inline secret):
```
?access_token=TH|<APP_ID>|<APP_SECRET>
```

> Must be server-side only. Since Mar 2026, oEmbed can be called without any access token.

---

## §3 Permissions

All Threads API calls require `threads_basic`. Additional permissions:

| Permission | Required For |
|-----------|-------------|
| `threads_basic` | All endpoints |
| `threads_content_publish` | Publishing posts |
| `threads_manage_replies` | POST to reply endpoints |
| `threads_read_replies` | GET on reply endpoints |
| `threads_manage_insights` | GET on insights endpoints |
| `threads_manage_mentions` | GET on mentions endpoint |
| `threads_keyword_search` | GET on keyword_search endpoint |
| `threads_delete` | DELETE posts |
| `threads_location_tagging` | Location search + tagging |
| `threads_profile_discovery` | Profile lookup + public profile posts |
| `threads_share_to_instagram` | Cross-sharing Threads posts to IG Stories |

> Without Advanced Access approval, most operations are limited to tester accounts only.

---

## §4 Rate Limits

### API Call Rate

```
Calls within 24 hours = 4800 × Number of Impressions
```

Where `Number of Impressions` = times any content from the user's account entered someone's screen in 24h (minimum 10).

CPU time limits:
- `total_cputime`: 720,000 × impressions
- `total_time`: 2,880,000 × impressions

### Publishing Quotas

| Action | Quota | Period | Required Permissions |
|--------|-------|--------|---------------------|
| Posts | 250 | 24h rolling | `threads_basic`, `threads_content_publish` |
| Replies | 1,000 | 24h rolling | `threads_basic`, `threads_content_publish`, `threads_manage_replies` |
| Deletions | 100 | 24h rolling | `threads_basic`, `threads_delete` |
| Location searches | 500 | 24h rolling | `threads_basic`, `threads_location_tagging` |
| Keyword search queries | 2,200 | 24h rolling (per user, across apps) |
| Profile discovery | 1,000 | 24h rolling |
| oEmbed | 1,000 | per hour |

> Carousel posts count as **1 post** against the publishing limit.

### Check Quota Usage

```
GET /{threads-user-id}/threads_publishing_limit
  ?fields=quota_usage,config,reply_quota_usage,reply_config,delete_quota_usage,delete_config,location_search_quota_usage,location_search_config
  &access_token=<TOKEN>
```

**Response:**
```json
{
  "data": [{
    "quota_usage": 4,
    "config": { "quota_total": 250, "quota_duration": 86400 },
    "reply_quota_usage": 1,
    "reply_config": { "quota_total": 1000, "quota_duration": 86400 },
    "delete_quota_usage": 0,
    "delete_config": { "quota_total": 100, "quota_duration": 86400 },
    "location_search_quota_usage": 0,
    "location_search_config": { "quota_total": 500, "quota_duration": 86400 }
  }]
}
```

---

## §5 Media Specifications

### Image

| Property | Spec |
|----------|------|
| Format | JPEG, PNG |
| Max file size | 8 MB |
| Aspect ratio | up to 10:1 |
| Min width | 320 (scaled up if needed) |
| Max width | 1440 (scaled down if needed) |
| Color space | sRGB (auto-converted) |

### Video

| Property | Spec |
|----------|------|
| Container | MOV or MP4 (MPEG-4 Part 14), no edit lists, moov atom at front |
| Audio codec | AAC, 48kHz max, mono or stereo |
| Video codec | HEVC or H264, progressive scan, closed GOP, 4:2:0 |
| Frame rate | 23–60 FPS |
| Max width | 1920 pixels |
| Aspect ratio | 0.01:1 to 10:1 (recommended 9:16) |
| Video bitrate | VBR, 100 Mbps max |
| Audio bitrate | 128 kbps |
| Duration | >0 to 300 seconds (5 min) |
| Max file size | 1 GB |

### Other Limits

| Limit | Value |
|-------|-------|
| Text post length | 500 characters (emojis = UTF-8 byte count) |
| Carousel children | 2–20 |
| Text attachment length | 10,000 characters |
| Link limit per post | 5 unique URLs max |
| Alt text length | 1,000 characters max |
| Topic tag length | 1–50 characters |
| Poll options | 2–4, each 1–25 characters |

---

## §6 Publishing

### 6.1 Single Posts (Two-Step)

**Step 1 — Create container:**
```
POST /{threads-user-id}/threads

  media_type=TEXT|IMAGE|VIDEO
  text=<TEXT>                    // Required for TEXT
  image_url=<URL>               // Required for IMAGE
  video_url=<URL>               // Required for VIDEO
  access_token=<TOKEN>
```

**Step 2 — Publish:**
```
POST /{threads-user-id}/threads_publish

  creation_id=<CONTAINER_ID>
  access_token=<TOKEN>
```

> Wait ~30 seconds between create and publish for video processing.

**Response:** `{ "id": "<THREADS_MEDIA_ID>" }`

### 6.2 Auto-Publish (Text Only)

For text-only posts, skip the publish step with `auto_publish_text=true`:
```
POST /{threads-user-id}/threads
  media_type=TEXT
  text=<TEXT>
  auto_publish_text=true
  access_token=<TOKEN>
```

### 6.3 Carousel Posts (Three-Step)

1. Create individual containers with `is_carousel_item=true` (IMAGE or VIDEO only)
2. Create carousel container with `media_type=CAROUSEL` and `children=<ID1>,<ID2>,...`
3. Publish the carousel container

### 6.4 Container Status

Check processing status before publishing:
```
GET /{threads-container-id}?fields=status,error_message&access_token=<TOKEN>
```

| Status | Meaning |
|--------|---------|
| `IN_PROGRESS` | Still processing |
| `FINISHED` | Ready to publish |
| `PUBLISHED` | Already published |
| `ERROR` | Failed (check `error_message`) |
| `EXPIRED` | Not published within 24h |

Error messages: `FAILED_DOWNLOADING_VIDEO`, `FAILED_PROCESSING_AUDIO`, `FAILED_PROCESSING_VIDEO`, `INVALID_ASPEC_RATIO`, `INVALID_BIT_RATE`, `INVALID_DURATION`, `INVALID_FRAME_RATE`, `INVALID_AUDIO_CHANNELS`, `INVALID_AUDIO_CHANNEL_LAYOUT`, `UNKNOWN`

> Poll once per minute, max 5 minutes.

### 6.5 Topic Tags

**Via parameter (preferred):**
```
POST /{threads-user-id}/threads
  topic_tag=<TAG>
```

**Via in-text (legacy):** First `#tag` in text becomes the topic. Only 1 topic per post.

Topic tag rules:
- 1–50 characters
- No periods (`.`), ampersands (`&`)
- `#1` (hash + whole number) is NOT converted to a tag
- In-text tags also break on: spaces, tabs, newlines, `@`, `!`, `?`, `,`, `;`, `:`

### 6.6 Links

```
POST /{threads-user-id}/threads
  media_type=TEXT
  text=<TEXT>
  link_attachment=<URL>
```

- **Text-only posts only** (no image/video/carousel)
- Max **5 unique links** per post (across `text` + `link_attachment`)
- If no `link_attachment`, first URL in text becomes the preview card
- Error `THREADS_API__LINK_LIMIT_EXCEEDED` if >5 links (since Dec 22, 2025)

**Retrieve link:**
```
GET /{threads-media-id}?fields=id,link_attachment_url
```

### 6.7 GIFs

```
POST /{threads-user-id}/threads
  media_type=TEXT
  text=<TEXT>
  gif_attachment={"gif_id":"<GIF_ID>","provider":"TENOR"|"GIPHY"}
```

- Text-only posts only
- Tenor and GIPHY supported
- **Tenor API sunset: March 31, 2026** — migrate to GIPHY

**Retrieve:**
```
GET /{threads-media-id}?fields=id,gif_url
```

### 6.8 Polls

```
POST /{threads-user-id}/threads
  media_type=TEXT
  text=<TEXT>
  poll_attachment={"option_a":"...", "option_b":"...", "option_c":"...", "option_d":"..."}
```

- Text-only posts only
- 2–4 options, each 1–25 characters

**Retrieve:**
```
GET /{threads-media-id}?fields=id,poll_attachment{option_a,option_b,option_c,option_d,option_a_votes_percentage,option_b_votes_percentage,option_c_votes_percentage,option_d_votes_percentage,total_votes,expiration_timestamp}
```

### 6.9 Spoilers

**Text spoiler** — `text_entities` parameter:
```json
[
  { "entity_type": "SPOILER", "offset": 0, "length": 10 },
  { "entity_type": "SPOILER", "offset": 15, "length": 5 }
]
```

**Media spoiler** — `is_spoiler_media=true` (hides image/video behind spoiler overlay)

- Max 10 text spoiler entities per post
- Media spoilers: IMAGE, VIDEO, or CAROUSEL only
- For carousels, `is_spoiler_media=true` on the carousel container hides ALL children

### 6.10 Text Attachments

Long-form writing (up to 10,000 characters) attached to a text post:

```
POST /{threads-user-id}/threads
  media_type=TEXT
  text=<TEXT>
  text_attachment={
    "plaintext": "Long text...",
    "link_attachment_url": "<URL>",
    "text_with_styling_info": [
      { "offset": 0, "length": 7, "styling_info": ["bold", "italic"] },
      { "offset": 7, "length": 10, "styling_info": ["highlight"] }
    ]
  }
```

Available styles: `bold`, `italic`, `highlight`, `underline`, `strikethrough`

Limitations:
- Text-only posts only
- Cannot combine with `poll_attachment`
- If main post has `link_attachment`, text attachment cannot also have one
- Same 5-link limit applies

### 6.11 Ghost Posts

Ephemeral text posts that expire after 24 hours:

```
POST /{threads-user-id}/threads
  media_type=TEXT
  text=<TEXT>
  is_ghost_post=true
```

Limitations:
- Text-only
- Cannot reply with ghost posts
- Only text spoilers supported (no media)

Retrieve: `GET /{threads-user-id}/ghost_posts`

Fields: `ghost_post_status` (ACTIVE/ARCHIVED), `ghost_post_expiration_timestamp`

### 6.12 Quote Posts

```
POST /{threads-user-id}/threads
  media_type=<TYPE>
  quote_post_id=<POST_ID>
  text=<TEXT>
```

Retrieve: `GET /{threads-media-id}?fields=is_quote_post,quoted_post`

### 6.13 Reposts

```
POST /{threads-media-id}/repost?access_token=<TOKEN>
```

Response: `{ "id": "<REPOST_ID>" }`

Retrieve: `GET /{threads-media-id}?fields=media_type,reposted_post` — `media_type` = `REPOST_FACADE`

### 6.14 Location Tagging

**Permission:** `threads_location_tagging`

**Search:**
```
GET /location_search
  ?q=<QUERY>                     // Search by name
  &latitude=<LAT>&longitude=<LON> // Or by coordinates
  &access_token=<TOKEN>
```

Response returns array of `{ id, name, address, city, country, latitude, longitude, postal_code }`.

**Tag a post:**
```
POST /{threads-user-id}/threads
  location_id=<LOCATION_ID>
```

**Retrieve tagged location:**
```
GET /{threads-media-id}?fields=location_id,location{id,address,city,country,name,latitude,longitude,postal_code}
```

**Retrieve location by ID:**
```
GET /{location-id}?fields=id,name,address,city,country,latitude,longitude,postal_code
```

### 6.15 Geo-Gated Content

Restrict post visibility to specific countries:

```
POST /{threads-user-id}/threads
  allowlisted_country_codes=US,CA
```

- Uses ISO 3166-1 alpha-2 codes
- Creator always sees their own content regardless
- Check eligibility: `GET /me?fields=is_eligible_for_geo_gating`
- Only users with this feature on threads.net can use it via API

Errors: `THREADS_API__FEATURE_NOT_AVAILABLE`, `THREADS_API__GEO_GATING_INVALID_COUNTRY_CODES`

### 6.16 Accessibility (Alt Text)

```
POST /{threads-user-id}/threads
  media_type=IMAGE
  image_url=<URL>
  alt_text="Description of the image"
```

- IMAGE and VIDEO only (not text-only)
- Max 1,000 characters
- Retrieve: `GET /{threads-media-id}?fields=alt_text`

### 6.17 Reply Control

Control who can reply when creating a post:

```
POST /{threads-user-id}/threads
  reply_control=everyone|accounts_you_follow|mentioned_only|parent_post_author_only|followers_only
```

### 6.18 Reply Approvals

Create posts where replies must be approved before being visible:

```
POST /{threads-user-id}/threads
  enable_reply_approvals=true
```

- Cannot be used with ghost posts
- See §10.5 for managing pending replies

### 6.19 Fediverse

Posts by users who enabled fediverse sharing will be shared to the fediverse (since Aug 28, 2024).

### 6.20 Cross-Share to Instagram Stories

Share a Threads post as an Instagram Story on the user's linked IG account. The Story expires after 24 hours per standard IG behavior. Requires `threads_share_to_instagram` permission.

```
POST /{threads-user-id}/threads
  crossreshare_to_ig=true          // normal mode
  crossreshare_to_ig_dark_mode=true // dark mode (mutually exclusive)
```

- Parameters are set on the **container creation** step (not publish)
- Only one of `crossreshare_to_ig` or `crossreshare_to_ig_dark_mode` should be set
- The publish response includes `crossreshare_to_ig_status`: `SUCCESS` or `FAILED`
- The Threads post publishes even if the cross-share fails — check the status field
- User must have a linked Instagram account; if none, cross-share fails silently
- Works with all media types: text, image, video, carousel

**Response fields (on publish):**
```json
{
  "id": "<MEDIA_ID>",
  "crossreshare_to_ig_status": "SUCCESS"
}
```

---

## §7 Media Retrieval

### 7.1 User's Own Posts

```
GET /{threads-user-id}/threads
  ?fields=<FIELDS>
  &since=<UNIX_TS>&until=<UNIX_TS>
  &limit=<N>                    // default 25, max 100
  &before=<CURSOR>&after=<CURSOR>
  &access_token=<TOKEN>
```

**Permission:** `threads_basic`

### 7.2 Public Profile's Posts

```
GET /profile_posts
  ?username=<EXACT_USERNAME>
  &fields=<FIELDS>
  &since=<UNIX_TS>&until=<UNIX_TS>
  &limit=<N>
  &access_token=<TOKEN>
```

**Permission:** `threads_basic` + `threads_profile_discovery`

Limitations:
- Public profiles only, 18+ age, 100+ followers
- 1,000 requests/24h per user
- Standard access: only official Meta accounts (@meta, @threads, @instagram, @facebook)
- `owner` field not available

### 7.3 Single Media Object

```
GET /{threads-media-id}
  ?fields=<FIELDS>
  &access_token=<TOKEN>
```

### 7.4 Ghost Posts

```
GET /{threads-user-id}/ghost_posts
  ?fields=<FIELDS>
  &since=<UNIX_TS>&until=<UNIX_TS>
  &access_token=<TOKEN>
```

### 7.5 Available Media Fields

| Field | Description |
|-------|-------------|
| `id` | Media ID (default) |
| `media_product_type` | Always `THREADS` |
| `media_type` | `TEXT_POST`, `IMAGE`, `VIDEO`, `CAROUSEL_ALBUM`, `AUDIO`, `REPOST_FACADE` |
| `media_url` | Post media URL |
| `permalink` | Permanent link (omitted if copyright flagged) |
| `owner` | Creator user ID (own posts only) |
| `username` | Creator username |
| `text` | Post text |
| `timestamp` | ISO 8601 publish date |
| `shortcode` | Media shortcode |
| `thumbnail_url` | Video thumbnail |
| `children` | Carousel child list |
| `is_quote_post` | Boolean |
| `quoted_post` | Quoted media ID |
| `reposted_post` | Reposted media ID |
| `alt_text` | Accessibility label |
| `link_attachment_url` | Attached link URL |
| `gif_url` | GIF URL |
| `poll_attachment` | Poll data |
| `topic_tag` | Topic tag |
| `is_spoiler_media` | Boolean |
| `text_entities` | Spoiler entities |
| `text_attachment` | Text attachment data |
| `ghost_post_status` | `ACTIVE` or `ARCHIVED` |
| `ghost_post_expiration_timestamp` | ISO 8601 |
| `is_verified` | Author verified status |
| `profile_picture_url` | Author profile picture |
| `has_replies` | Boolean |
| `is_reply` | Boolean |
| `reply_audience` | `EVERYONE`, `ACCOUNTS_YOU_FOLLOW`, `MENTIONED_ONLY`, `PARENT_POST_AUTHOR_ONLY`, `FOLLOWERS_ONLY` |

### 7.6 Pagination

Cursor-based. Response includes `paging.cursors.before` and `paging.cursors.after`. Unlike standard pagination, no `previous`/`next` URLs — construct manually with `?before=` or `?after=`.

---

## §8 Keyword & Topic Tag Search

```
GET /keyword_search
  ?q=<KEYWORD>
  &search_type=TOP|RECENT           // default TOP
  &search_mode=KEYWORD|TAG          // default KEYWORD
  &media_type=TEXT|IMAGE|VIDEO      // optional filter
  &author_username=<USERNAME>       // optional filter (exact match, no @)
  &fields=<FIELDS>
  &since=<UNIX_TS>&until=<UNIX_TS>
  &limit=<N>                        // default 25, max 100
  &access_token=<TOKEN>
```

**Permission:** `threads_basic` + `threads_keyword_search`

Limitations:
- 2,200 queries per user per 24h (across all apps)
- Queries with no results don't count
- Sensitive/offensive keywords return empty array
- Without approval: only user's own posts searchable
- `owner` field not returned

### Recently Searched Keywords

```
GET /me?fields=recently_searched_keywords&access_token=<TOKEN>
```

Response:
```json
{
  "id": "1234567890",
  "recently_searched_keywords": [
    { "query": "some keyword", "timestamp": 1735707600000 }
  ]
}
```

### Interacting with Search Results

After searching, you can reply to, quote, or repost public posts found in results.

---

## §9 Mentions

```
GET /{threads-user-id}/mentions
  ?fields=<FIELDS>
  &since=<UNIX_TS>&until=<UNIX_TS>
  &limit=<N>
  &access_token=<TOKEN>
```

**Permission:** `threads_basic` + `threads_manage_mentions`

Limitations:
- Media by private users not returned
- `since` must be ≥ 1688540400
- Without Advanced Access: only tester mentions returned

---

## §10 Reply Management

### 10.1 Create Replies

**Permission:** Reply permission requires one of:
- You are the owner of the root thread post
- You have either `threads_keyword_search` or `threads_manage_mentions`

**Step 1 — Create reply container:**
```
POST /me/threads
  media_type=<MEDIA_TYPE>
  text=<TEXT>
  reply_to_id=<THREADS_ID>
  access_token=<TOKEN>
```

**Step 2 — Publish:**
```
POST /{threads-user-id}/threads_publish
  creation_id=<CONTAINER_ID>
  access_token=<TOKEN>
```

### 10.2 Retrieve User Replies

```
GET /{threads-user-id}/replies
  ?fields=<FIELDS>
  &since=<UNIX_TS>&until=<UNIX_TS>
  &limit=<N>
  &access_token=<TOKEN>
```

**Permission:** `threads_basic` + `threads_read_replies`

Additional reply fields (beyond standard media fields):

| Field | Description |
|-------|-------------|
| `has_replies` | Has nested replies |
| `root_post` | Top-level post ID |
| `replied_to` | Direct parent ID |
| `is_reply` | Boolean |
| `is_reply_owned_by_me` | Boolean |
| `reply_audience` | Who can reply |
| `hide_status` | `NOT_HUSHED`, `UNHUSHED`, `HIDDEN`, `COVERED`, `BLOCKED`, `RESTRICTED` |

### 10.3 Retrieve Media Replies (Top-Level Only)

```
GET /{media-id}/replies
  ?fields=<FIELDS>
  &reverse=true|false            // default true (reverse chronological)
  &access_token=<TOKEN>
```

Returns only top-level replies. Use `has_replies` to determine if deeper replies exist.

### 10.4 Retrieve Conversations (All Depths)

```
GET /{media-id}/conversation
  ?fields=<FIELDS>
  &reverse=true|false
  &access_token=<TOKEN>
```

Returns flattened list of all replies at all depths. Only for root-level threads.

### 10.5 Hide/Unhide Replies

```
POST /{threads-reply-id}/manage_reply
  hide=true|false
  access_token=<TOKEN>
```

- Only top-level replies can be targeted
- Hiding auto-hides all nested replies

### 10.6 Pending Replies (Reply Approvals)

**Retrieve pending:**
```
GET /{threads-media-id}/pending_replies
  ?fields=<FIELDS>,reply_approval_status
  &approval_status=pending|ignored    // optional filter
  &reverse=true|false
  &access_token=<TOKEN>
```

`reply_approval_status`: `pending` or `ignored`

**Approve/Ignore:**
```
POST /{threads-reply-id}/manage_pending_reply
  approve=true|false
  access_token=<TOKEN>
```

> Ignored replies can still be approved later.

---

## §11 Delete Posts

```
DELETE /{threads-media-id}?access_token=<TOKEN>
```

**Permission:** `threads_basic` + `threads_delete`

**Response:**
```json
{
  "success": true,
  "deleted_id": "1234567"
}
```

Rate limit: 100 deletions per 24h per account.

---

## §12 User Profiles

### 12.1 App-Scoped User Profile

```
GET /{threads-user-id}
  ?fields=id,username,name,threads_profile_picture_url,threads_biography,is_verified
  &access_token=<TOKEN>
```

**Permission:** `threads_basic`

Can only fetch your own (app-scoped) profile.

| Field | Description |
|-------|-------------|
| `id` | Threads user ID (default) |
| `username` | Handle |
| `name` | Display name |
| `threads_profile_picture_url` | Profile picture URL |
| `threads_biography` | Bio text |
| `is_verified` | Boolean |
| `is_eligible_for_geo_gating` | Boolean |
| `recently_searched_keywords` | Array of recent searches |

### 12.2 Public Profile Lookup

```
GET /profile_lookup
  ?username=<EXACT_USERNAME>
  &access_token=<TOKEN>
```

**Permission:** `threads_basic` + `threads_profile_discovery`

| Field | Description |
|-------|-------------|
| `username` | Handle |
| `name` | Display name |
| `profile_picture_url` | Profile picture URL |
| `biography` | Bio text |
| `follower_count` | Total followers |
| `likes_count` | Likes in past 7 days |
| `quotes_count` | Quotes in past 7 days |
| `replies_count` | Replies in past 7 days |
| `reposts_count` | Reposts in past 7 days |
| `views_count` | Views in past 7 days |
| `is_verified` | Boolean |

Limitations:
- Public profiles only, 18+ age, 100+ followers (reduced from 1,000 in Nov 2025)
- 1,000 requests/24h
- Standard access: only official Meta accounts

> Note field name differences: App-scoped uses `threads_profile_picture_url` / `threads_biography`. Public lookup uses `profile_picture_url` / `biography`.

---

## §13 Insights

**Permission:** `threads_basic` + `threads_manage_insights`

### 13.1 Media Insights

```
GET /{threads-media-id}/insights
  ?metric=views,likes,replies,reposts,quotes,shares
  &access_token=<TOKEN>
```

| Metric | Description |
|--------|-------------|
| `views` | Times post was played/displayed (in development) |
| `likes` | Like count |
| `replies` | Reply count (root post = total; reply = direct only) |
| `reposts` | Repost count |
| `quotes` | Quote count |
| `shares` | Share count (in development) |

- Does not capture nested replies' metrics
- Returns empty array for `REPOST_FACADE` posts
- Response format: `{ data: [{ name, period: "lifetime", values: [{ value: N }] }] }`

### 13.2 User Insights

```
GET /{threads-user-id}/threads_insights
  ?metric=<METRICS>
  &since=<UNIX_TS>&until=<UNIX_TS>
  &access_token=<TOKEN>
```

- `since`/`until` default to 2-day range (yesterday through today)
- Earliest valid timestamp: `1712991600` (April 13, 2024)
- User insights not guaranteed before June 1, 2024

| Metric | Response Type | Description |
|--------|--------------|-------------|
| `views` | Time Series | Profile views |
| `likes` | Total Value | Likes on posts |
| `replies` | Total Value | Top-level replies only |
| `reposts` | Total Value | Repost count |
| `quotes` | Total Value | Quote count |
| `clicks` | Link Total Values | URL click count (per-link breakdown) |
| `followers_count` | Total Value | Total followers (no since/until) |
| `follower_demographics` | Total Value | Demographics breakdown (no since/until) |

**`follower_demographics` requirements:**
- 100+ followers
- Must include `breakdown` param: `country`, `city`, `age`, or `gender` (exactly one)
- No `since`/`until` support

> Since Sep 2025: Profiles without linked Instagram can use all API features except `followers_count` and `follower_demographics`.
> Since Jan 2026: These profiles CAN now access `followers_count` and `follower_demographics`.

**Response formats:**

Time Series:
```json
{ "data": [{ "name": "views", "period": "day", "values": [{ "value": 10, "end_time": "..." }] }] }
```

Total Value:
```json
{ "data": [{ "name": "likes", "period": "day", "total_value": { "value": 100 } }] }
```

Link Total Values:
```json
{ "data": [{ "name": "clicks", "period": "day", "link_total_values": [{ "value": 11, "link_url": "https://..." }] }] }
```

---

## §14 Webhooks

### Setup Requirements

1. Add "Threads webhooks" sub-use case in App Dashboard
2. Configure callback URL and verification token
3. App must be in Live Mode (non-tech providers) or have Advanced Access
4. Business must be verified
5. Users must grant appropriate permissions

### Webhook Topics & Fields

**Moderate topic:**

| Field | Description | Required Permissions |
|-------|-------------|---------------------|
| `replies` | Reply on owned media | `threads_basic`, `threads_read_replies` |
| `delete` | Post deleted by authenticated user | `threads_basic`, `threads_delete` |

**Interaction topic:**

| Field | Description | Required Permissions |
|-------|-------------|---------------------|
| `mentions` | @mention in public media | `threads_basic`, `threads_manage_mentions` |
| `publish` | Post published (including replies) | `threads_basic` |

> For mentions: `threads_read_replies` optional — required for `has_replies`, `is_reply`, `replied_to`, `root_post` fields.

### Webhook Payload Format

All payloads include: `app_id`, `topic`, `target_id`, `time`, `subscription_id`, `values.field`, `values.value`

**Reply payload extras:** `id`, `username`, `text`, `media_type`, `permalink`, `replied_to`, `root_post` (with `owner_id`, `username`), `shortcode`, `timestamp`, `is_verified`, `profile_picture_url`

**Mention payload extras:** `id`, `alt_text`, `gif_url`, `has_replies`, `is_quote_post`, `is_reply`, `media_product_type`, `media_type`, `permalink`, `shortcode`, `text`, `timestamp`, `username`, `is_verified`, `profile_picture_url`. Optional: `media_url`, `poll_attachment`, `quoted_post`, `replied_to`, `reposted_post`, `root_post`, `thumbnail_url`

**Delete payload extras:** `id`, `owner.owner_id`, `deleted_at`, `timestamp`, `username`

**Publish payload extras:** `id`, `media_type`, `permalink`, `timestamp`, `username`

### Limitations

- No webhooks for media created by private accounts
- Must complete App Review (Advanced Access) for all webhook fields
- Real-time reply/mention: media owner must not be private
- Real-time delete/publish: owner must be public OR private but authenticated to the app

---

## §15 oEmbed

Embed public Threads posts in websites.

```
GET /oembed?url=<POST_URL>
```

> Since March 3, 2026: No access token required.

**Accepted URL formats:**
- `https://www.threads.com/@{username}/post/{shortcode}/`
- `https://www.threads.com/t/{shortcode}/`

| Parameter | Description |
|-----------|-------------|
| `url` | Required. Post permalink |
| `maxwidth` | Optional. 320–658 pixels |

**Response:**
```json
{
  "type": "rich",
  "version": "1.0",
  "html": "<blockquote class=\"text-post-media\" ...",
  "provider_name": "Threads",
  "provider_url": "https://www.threads.com/",
  "width": 658
}
```

Embed JS: `<script async src="https://www.threads.com/embed.js"></script>`

Limitations:
- Private, inactive, age-restricted accounts not supported
- Geo-gated posts not supported
- 1,000 requests/hour
- Not for analytics extraction — embedding only

---

## §16 Web Intents

### Post Intent

```
https://www.threads.com/intent/post
  ?text=<URL_ENCODED_TEXT>
  &url=<URL_ENCODED_LINK>
  &tag=<TOPIC_TAG>
  &reply_control=everyone|accounts_you_follow|mentioned_only|followers_only
```

All parameters optional. Opens Threads app on mobile if installed.

### Follow Intent

```
https://www.threads.com/intent/follow?username=<USERNAME>
```

---

## §17 Debug Token

Inspect access token metadata:

```
GET /debug_token
  ?access_token=<TESTER_TOKEN>
  &input_token=<TOKEN_TO_INSPECT>
```

Both tokens must be from the same app (can be different users).

**Response:**
```json
{
  "data": {
    "type": "USER",
    "application": "App Name",
    "data_access_expires_at": 1754846089,
    "expires_at": 1752254132,
    "is_valid": true,
    "issued_at": 1747070132,
    "scopes": ["threads_basic", "threads_content_publish", "..."],
    "user_id": "1234567890123456"
  }
}
```

---

## §18 Troubleshooting

### Container Status Polling

If `threads_publish` doesn't return a media ID, check container status:
```
GET /{threads-container-id}?fields=status,error_message&access_token=<TOKEN>
```
See §6.4 for status values and error messages.

### Quota Limits

See §4 for the comprehensive quota check endpoint.

---

## §19 API Endpoint Reference

### Publishing

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/{threads-user-id}/threads` | Create media container |
| POST | `/{threads-user-id}/threads_publish` | Publish container |
| GET | `/{threads-container-id}?fields=status` | Check container status |
| POST | `/{threads-media-id}/repost` | Repost a post |
| DELETE | `/{threads-media-id}` | Delete a post |

### Media Retrieval

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/{threads-media-id}` | Single media object |
| GET | `/{threads-user-id}/threads` | User's posts (paginated) |
| GET | `/{threads-user-id}/ghost_posts` | User's ghost posts |
| GET | `/profile_posts?username=...` | Public profile's posts |
| GET | `/keyword_search?q=...` | Search posts by keyword/tag |

### Reply Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/{threads-user-id}/replies` | User's replies |
| GET | `/{media-id}/replies` | Top-level replies on a post |
| GET | `/{media-id}/conversation` | All replies (flattened) |
| POST | `/{reply-id}/manage_reply` | Hide/unhide reply |
| GET | `/{media-id}/pending_replies` | Pending approval replies |
| POST | `/{reply-id}/manage_pending_reply` | Approve/ignore pending reply |

### User

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/{threads-user-id}?fields=...` | App-scoped profile |
| GET | `/profile_lookup?username=...` | Public profile lookup |
| GET | `/profile_posts?username=...` | Public profile posts |
| GET | `/{threads-user-id}/threads_publishing_limit` | Quota usage |
| GET | `/{threads-user-id}/mentions` | Mentions |

### Location

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/location_search` | Search locations |
| GET | `/{location-id}` | Get location by ID |

### Insights

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/{threads-media-id}/insights` | Media insights |
| GET | `/{threads-user-id}/threads_insights` | User insights |

### Other

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/oembed?url=...` | Embed HTML |
| GET | `/debug_token` | Token inspection |
| GET | `/access_token` | Exchange short→long token |
| GET | `/refresh_access_token` | Refresh long-lived token |

---

## §20 Changelog

### 2026

| Date | Change |
|------|--------|
| Mar 3 | oEmbed API callable without access token |
| Feb 27 | GIPHY support added for GIFs; Tenor sunset Mar 31, 2026 |
| Feb 17 | App ads available for Threads |
| Feb 13 | Reply approvals + pending reply management |
| Jan 30 | `followers_count`/`follower_demographics` for profiles without linked IG |
| Jan 26 | `is_verified`/`profile_picture_url` in reply/mention webhooks |
| Jan 22 | `tag`/`reply_control` params added to Web Intents |
| Jan 20 | `author_username` filter for keyword/tag search |

### 2025

| Date | Change |
|------|--------|
| Dec 22 | >5 links error: `THREADS_API__LINK_LIMIT_EXCEEDED` |
| Dec 16 | `is_verified`/`profile_picture_url` on replies/mentions |
| Dec 15 | Ghost posts |
| Nov 20 | Profile discovery follower min: 1,000 → 100 |
| Oct 28 | Advantage+ catalog ads for Threads |
| Oct 17 | GIF support (Tenor) |
| Oct 6 | Spoilers (text + media) |
| Oct 3 | Text attachments |
| Sep 23 | API available to profiles without linked Instagram |
| Sep 9 | `media_type` filter on keyword search |
| Aug 15 | Video ads; publish webhooks |
| Aug 12 | `total_votes` on polls |
| Aug 1 | Delete webhooks |
| Jul 21 | `topic_tag` field on media retrieval |
| Jul 15 | Mention webhooks |
| Jul 14 | Profile discovery; `topic_tag` parameter; topic tag search; deletion/location quotas |
| Jul 7 | `is_verified` on profile; `parent_post_author_only`/`followers_only` reply audiences |
| Jul 2 | `clicks` metric (user insights) |
| Jun 25 | Keyword search query limit change |
| Jun 6 | `graph.threads.com` as alternate base URL |
| Jun 4 | Debug token endpoint; `auto_publish_text` |
| May 27 | Location search + tagging |
| Apr 14 | Polls |
| Mar 6 | Delete posts |
| Feb 13 | `gif_url` field |

### 2024

| Date | Change |
|------|--------|
| Dec 9 | Keyword search; mentions; oEmbed; Postman collection |
| Oct 28 | `shares` metric |
| Oct 11 | Tag character rules update |
| Oct 9 | Quote posts; reposts |
| Oct 8 | Additional webhook fields |
| Sep 19 | Carousel max: 10 → 20 |
| Sep 12 | Link attachment parameter |
| Aug 28 | Fediverse sharing |
| Aug 21 | Alt text |
| Aug 15 | Webhooks launch (reply/mention) |
| Aug 13 | Real-time webhook notifications |
| Aug 5 | `name` field on profile; `/me/replies` endpoint |
| Jul 23 | Geo-gated content |
| Jul 12 | Web intents |
| Jun 25 | Empty array for repost insights |
| Jun 18 | API open to all developers |
| Jun 17 | threads.net domain; tester flow |
| Jun 12 | `reply_audience` field |
| Jun 7 | graph.threads.net domain; v1.0 |
| May 21 | User insights date limit (≥ Apr 13, 2024); `follower_demographics` 100+ followers |
| May 15 | `REPOST_FACADE` removed from reply `media_type` |
| May 2 | Deprecated status code on media builder |
| May 1 | `is_reply_owned_by_me` field |
| Apr 26 | User-level insights launch |
| Apr 18 | `permalink`/`username` on public replies |
| Apr 8 | API documentation public launch |
