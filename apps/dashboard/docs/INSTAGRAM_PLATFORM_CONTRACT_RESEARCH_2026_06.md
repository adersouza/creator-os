# Instagram Platform Contract Research - June 2026

Purpose: lock down the external Instagram API contract that affects Reel Factory, ContentForge, Campaign Factory, and Juno scheduling/analytics. This is platform research, not a creative prompt guide.

## Executive Findings

- The Content Publishing API supports feed images, reels, carousels, and stories through the same container -> status polling -> `media_publish` flow.
- API Stories are plain media plus optional `user_tags`. Story stickers such as link, poll, location, question, quiz, countdown, GIF, and music stickers are not supported through publishing payloads.
- Trial Reels are API-addressable through `trial_params`, but eligibility appears account-dependent. Treat failures as account capability failures, not generic bugs.
- Native Instagram Audio API support exists for discovering audio IDs and replacement audio, but publishing support must stay guarded: Campaign should keep audio metadata, and the MP4 should remain the authoritative audio unless an account/API path proves `audio_id` attachment works.
- Metrics must be surface-aware. `views` replaces older impressions/plays-style metrics in current versions, and Story metrics have short availability windows.
- Duplicate/spam risk is now account-level and recommendation-surface oriented. Cosmetic variants are not enough; variants should be materially different in hook, edit, caption, audio, cover, timing, and concept spacing.
- For 200-account scheduling, the bottleneck is less a single global publish limit and more per-account publish windows, container creation limits, app/user call rate, token health, webhook reliability, and anti-spam/recommendation risk.

## Publishing Surface Matrix

| Surface | Container fields | Caption | Media constraints | Publish flow | Notes |
|---|---|---|---|---|---|
| Feed image | `image_url`; optional `caption`, `alt_text`, `location_id`, `user_tags`, `collaborators`, `product_tags` | Supported | JPEG, max 8 MB, 4:5 to 1.91:1, 320-1440 px wide | Create container, publish with `creation_id` | `alt_text` applies to image posts, not reels or stories. |
| Reel | `media_type=REELS`, `video_url` or resumable upload; optional `caption`, `share_to_feed`, `cover_url`, `audio_name`, `thumb_offset`, `user_tags`, `collaborators`, `location_id`, `trial_params` | Supported | MOV/MP4, AAC, HEVC/H.264, 23-60 fps, recommended 9:16, 3 sec to 15 min | Create container, poll `status_code`, publish | Published media can return `media_type=VIDEO`; use `media_product_type` to identify Reels. |
| Trial Reel | Reel payload plus `trial_params` | Supported | Same as Reel | Same as Reel | Validated locally as `{ graduation_strategy: "MANUAL" | "SS_PERFORMANCE" }`; account eligibility can vary. |
| Story | `media_type=STORIES`, `image_url` or `video_url`; optional `user_tags` | Not supported | Image: JPEG max 8 MB. Video: MOV/MP4, AAC, HEVC/H.264, 23-60 fps, 3-60 sec, max 100 MB | Create container, poll status, publish | Stickers are not supported. Mentions via `user_tags` are supported. Stories expire after 24h. |
| Carousel | Child item containers with `is_carousel_item=true`, then parent `media_type=CAROUSEL`, `children`, optional `caption`, `collaborators`, `location_id`, `product_tags` | Supported on parent | 2-10 children; images/videos allowed; Reels cannot be children | Create children, create parent, publish parent | Ordered `children` defines carousel order. Carousel counts as one published post. |

## Metrics by Surface

Use surface-specific queries. Avoid one "everything" request because Meta returns incompatible metric errors for unsupported media/metric combinations.

| Surface | Safer current metrics | Important caveats |
|---|---|---|
| Reels | `views`, `reach`, `saved`, `shares`, `likes`, `comments`, `total_interactions`, `ig_reels_avg_watch_time`, `ig_reels_video_view_total_time`; newer docs/tools also expose `reposts`, `reels_skip_rate` | Older `plays`, `video_views`, and related replay metrics are deprecated/replaced by `views` in current versions. |
| Stories | `views`, `reach`, `replies`, `navigation`, `shares`, `follows`, `profile_visits`, `profile_activity`, `total_interactions` | Story insights are time-sensitive; capture near expiry and subscribe to `story_insights` where supported. Stories with too few viewers can return "not enough viewers." |
| Feed image | `views`, `reach`, `saved`, `likes`, `comments`, `total_interactions`; test `shares` per account/version before relying on it | `impressions` is deprecated for current media; use `views`. |
| Carousel | Parent-level `views`, `reach`, `saved`, `likes`, `comments`, `total_interactions`; children have limited fields | Deprecated carousel-specific metrics should not be used for new collection. |

Latency: plan for delay. Meta/partner docs report insight data can lag; production collectors should run at multiple checkpoints, not only immediately after publish. For Stories, final capture should happen before/around the 24-hour expiry window.

## Trial Reels

Confirmed product contract:

- Trial Reels are Reels that are first shown to non-followers and can later graduate to followers/profile visibility.
- API publishing uses the Reels path plus `trial_params`.
- Known graduation strategies in the repo contract: `MANUAL` and `SS_PERFORMANCE`.
- API failures can be account-dependent. Do not assume every Creator/Business account has Trial Reel eligibility at the same time.
- Metrics should be treated like Reel metrics unless Meta returns a narrower set for that account. Store `is_trial`, `graduation_strategy`, and graduation status separately from the published media ID.

Open uncertainty:

- Meta's public docs are still thin on account eligibility and exact performance thresholds for `SS_PERFORMANCE`.
- "Maximum number of Trial Reels allowed by Content Publishing API" errors are reported by scheduler vendors, so Juno should classify these separately from token/media failures.

## Native Audio and Music

Current stance:

- The June 1, 2026 Instagram Audio API introduces `GET /ig_audio` for searching/retrieving music and original sounds, plus an ads replacement-audio discovery use case.
- The provided release note says the API can attach audio to Reels at creation time for apps using Facebook Login, but the exact publishing parameter and eligibility rules need to be feature-flagged until verified against Meta's endpoint reference and a live account.
- Existing Reels publishing docs support `audio_name`, which renames original audio; that is not the same as attaching a licensed Instagram music track.
- Safe production assumption: render/export MP4s with embedded cleared audio. Store Instagram audio IDs as optional metadata, not as the only source of sound.
- Commercial/business accounts may have restricted licensed music access. Meta Help distinguishes licensed music from royalty-free Sound Collection and notes commercial restrictions.

Product implication:

- Campaign Factory can recommend or record audio IDs, but the publish pipeline should keep embedded audio as fallback and surface account-level audio capability separately.

## Cover and Thumbnail Support

Reels:

- `cover_url` is supported for Reels cover images.
- `thumb_offset` is supported for selecting a frame offset when no custom cover is supplied.
- `share_to_feed` affects whether the Reel is eligible to appear in Feed as well as Reels, but Instagram ranking/eligibility still decides actual distribution.
- Feed/grid cover behavior can crop the Reel cover to square; ContentForge should produce both 9:16 and center-safe 1:1 preview-safe covers.

Stories:

- No cover/thumbnail concept for API-published Story media.

Feed images/carousels:

- Feed images are the media. Carousel preview is governed by the first child/order.

## Duplicate and Spam Risk

Official/credible evidence points to account-level recommendation eligibility:

- Instagram has expanded originality rules so accounts that primarily post unoriginal Reels, photos, or carousels may stop appearing in recommendation surfaces.
- Low-effort edits such as watermarks, speed changes, borders, or simple repost-with-credit do not appear to qualify as original.
- Material edits can qualify: new perspective, voiceover, creative graphics, humor/commentary, remixing, or substantive transformation.

Juno scheduling implication:

- Do not only cooldown on exact `variant_id`.
- Track cooldowns across `variant_family_id`, `parent_reel_id`, and `concept_id`.
- Treat same-day sibling variants across many accounts as risky unless materially transformed.
- Prefer spreading sibling concepts across days/accounts, changing first frame/hook, captions, audio bed, edit sequence, cover, and CTA.
- Add account-level "originality pressure" telemetry: recent repeated concept density, repeated audio density, repeated visual fingerprint density, and recent Account Status issues where available manually.

## Rate Limits and 200-Account Scaling

Known limits and rules:

- Containers expire after 24 hours.
- An Instagram account can create up to 400 containers per rolling 24 hours.
- Instagram Login publishing docs/collections state 100 API-published posts per rolling 24 hours per account; older Facebook Login paths and `content_publishing_limit` can show 50. Juno should inspect the endpoint per account/login type.
- Carousel counts as one published post.
- Polling container status and insights can consume meaningful call volume at 200 accounts; use bounded polling and webhooks where available.

Operational guidance for 200 accounts:

- Preflight media before container creation; do not burn containers on predictable validation failures.
- Create containers close to publish time, not hours early.
- Use per-account queues with jitter, not synchronized fanout.
- Check `content_publishing_limit` before scheduling dense days.
- Keep retry classes separate: transient Meta 5xx, token/auth, media validation, copyright/policy, rate limit, account eligibility, and container expiry.
- Do not escalate from 25 to 200 accounts until Story/Reel metrics capture, publish failure taxonomy, and token refresh health are observable.

## Account Health and Token Management

Token/account risks:

- Instagram Login long-lived tokens are commonly valid for about 60 days and should be refreshed before expiry.
- Facebook Login/Page-backed flows have different token behavior and permission requirements.
- Permission revocation, missing Page tasks, app review access level, Page Publishing Authorization, 2FA requirements, account type, and linked Page/Business state can all cause publish failures.

Failure classification:

- Token/auth: invalid or expired token, revoked permission, missing scope.
- Permission/account: missing Page task, account not Professional, unsupported Story publishing account type, Trial Reel not eligible.
- Media: invalid URL, non-public media, invalid codec/size/aspect/duration, unsupported caption/sticker field.
- Container: `IN_PROGRESS` timeout, `ERROR`, `EXPIRED`, duplicate publish.
- Rate limit: publish cap, container cap, app/user call throttles.
- Policy/copyright: copyright match, muted/replacement-audio path, platform originality/account-status suppression.
- Meta transient: Graph `code=1` or other retryable 5xx-style failures should not be treated as dead tokens.

## Juno Product Decisions

- Keep Story stickers as handoff-only. Juno can prepare creative and reminders; it should not promise clickable/poll/native sticker publishing.
- Keep embedded audio as the reliable publish artifact. Treat native audio IDs as optional capability behind Facebook Login and account eligibility checks.
- Keep Trial Reels behind readiness checks and classify eligibility/limit failures distinctly.
- Make analytics collectors surface-aware and version-aware. Store raw metric payloads alongside normalized columns so Meta naming changes do not destroy history.
- Add cooldown policy at concept/family/parent level before scaling Campaign Factory posting volume.
- For covers, keep ContentForge cover variants valuable for Reels but center-safe for feed/grid crops.

## Sources

- Meta IG User Media reference archive: https://archive.ph/20251231074512/https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media
- Meta Instagram Postman collection, Publish Content and Insights: https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api
- Meta Instagram Postman Reels publish request: https://www.postman.com/meta/instagram/request/23987686-f1c081c0-be35-4ffa-84bb-2c1726860c2b
- Local API reference: `docs/instagram-api.md`
- Instagram Help, licensed music access: https://www.facebook.com/help/instagram/402084904469945
- Instagram Help, Reels audio types: https://www.facebook.com/help/instagram/329208821595430
- TechCrunch coverage of Instagram originality/repost recommendation changes: https://techcrunch.com/2026/04/30/instagram-restricts-reach-of-content-aggregators-in-new-crackdown/
- Postman/Meta insights docs mirror in search result: https://www.postman.com/meta/documentation/23987686-9386f468-7714-490f-9bfc-9442db5c8f00
- June 1, 2026 Instagram Audio API release note provided in project conversation.
