import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, success, dryRunResponse, zBool, zNum } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "get_posts",
    "Get posts with engagement metrics. Omit accountId to get ALL posts across workspace. Max 100 per page — use offset to paginate. Default status=published; pass status='all' for all statuses.",
    {
      accountId: z.string().optional().describe("Account ID (omit for all workspace accounts)"),
      limit: zNum.optional().describe("Posts per page, max 100 (default: 50)."),
      offset: zNum.optional().describe("Pagination offset (default: 0). Increment by limit to fetch the next page."),
      status: z.enum(["published", "scheduled", "draft", "all"]).optional().describe("Filter by status (default: published)"),
    },
    async ({ accountId, limit, offset, status }) => {
      const params = new URLSearchParams();
      if (accountId) params.set("account_id", accountId);
      if (limit) params.set("limit", String(Math.min(100, limit)));
      if (offset) params.set("offset", String(offset));
      if (status) params.set("status", status);
      return respond(await api(`/v1/posts?${params}`));
    }
  );

  // -- Threads Publishing --

  server.tool(
    "publish_threads_post",
    "[POSTS:THREADS] Publish a text or media post to Threads immediately. Supports polls, quote posts, link cards, GIFs, long-form textAttachments, reply threading, reply controls, spoilers, ghost posts, and geo-gating.",
    {
      accountId: z.string().describe("Threads account ID"),
      content: z.string().describe("Post text content"),
      mediaIds: z.array(z.string()).optional().describe("Media IDs to attach (upload first via upload_media)"),
      pollOptions: z.array(z.string()).optional().describe("Poll choices (2–4 items)"),
      replyToThreadId: z.string().optional().describe("Thread ID to reply to"),
      replyToAccountId: z.string().optional().describe("Account ID owning that thread (required if replyToThreadId set)"),
      quotePostId: z.string().optional().describe("Post ID to quote-repost"),
      linkUrl: z.string().optional().describe("URL for link-card attachment (text posts only)"),
      locationId: z.string().optional().describe("Location ID to tag"),
      gifAttachment: z.object({ gifId: z.string(), provider: z.string() }).optional().describe("GIF to attach"),
      textAttachment: z.object({ text: z.string().describe("Long-form text body (up to 10k chars)"), link: z.string().optional().describe("Optional URL") }).optional().describe("Long-form text attachment (replaces caption)"),
      topicTag: z.string().optional().describe("Topic tag (1–50 chars, no # prefix needed). One per post."),
      whoCanReply: z.enum(["everyone", "followers", "mentioned", "author_only", "followers_only"]).optional().describe("Reply audience control (default: everyone)"),
      replyApprovalMode: z.enum(["manual_approval"]).optional().describe("Enable manual reply approval before replies are visible"),
      isSpoiler: zBool.optional().describe("Mark media as spoiler (blurred until tapped)"),
      isGhostPost: zBool.optional().describe("Publish as unlisted/ghost post"),
      textSpoilers: z.array(z.object({ offset: z.number(), length: z.number() })).optional().describe("Spoiler text ranges — array of {offset, length} marking text as hidden"),
      allowlistedCountryCodes: z.array(z.string()).max(20).optional().describe("Geo-gate: only show post in these countries (ISO 3166-1 alpha-2 codes)"),
      altText: z.string().optional().describe("Image accessibility description (for carousel items)"),
      topics: z.array(z.string()).max(20).optional().describe("Hashtag topics (appended to content as #tags)"),
      crossreshareToIg: zBool.optional().describe("Cross-share post to linked Instagram account as a Story"),
      crossreshareToIgDarkMode: zBool.optional().describe("Cross-share to IG Story in dark mode (overrides crossreshareToIg)"),
    },
    async ({ accountId, content, mediaIds, pollOptions, replyToThreadId, replyToAccountId, quotePostId, linkUrl, locationId, gifAttachment, textAttachment, topicTag, whoCanReply, replyApprovalMode, isSpoiler, isGhostPost, textSpoilers, allowlistedCountryCodes, altText, topics, crossreshareToIg, crossreshareToIgDarkMode }) => {
      const replyTo = replyToThreadId && replyToAccountId
        ? { threadId: replyToThreadId, accountId: replyToAccountId }
        : undefined;
      return respond(await api("/posts?action=publish", "POST", {
        accountId, content, platform: "threads", mediaIds,
        pollOptions, quotePostId, linkUrl, locationId, gifAttachment, textAttachment, topicTag,
        settings: whoCanReply ? { allowReplies: true, whoCanReply } : undefined,
        replyApprovalMode, isSpoiler, isGhostPost, textSpoilers, allowlistedCountryCodes, altText, topics,
        crossreshareToIg, crossreshareToIgDarkMode,
        shouldReply: !!replyTo, replyTo,
      }));
    }
  );

  server.tool(
    "schedule_threads_post",
    "[POSTS:THREADS] Schedule a Threads post for future publication. Same options as publish_threads_post plus scheduledFor datetime.",
    {
      accountId: z.string().describe("Threads account ID"),
      content: z.string().describe("Post text content"),
      scheduledFor: z.string().describe("ISO 8601 datetime (e.g. '2026-03-10T14:00:00Z')"),
      mediaIds: z.array(z.string()).optional().describe("Media IDs to attach"),
      pollOptions: z.array(z.string()).optional().describe("Poll choices (2–4 items)"),
      quotePostId: z.string().optional().describe("Post ID to quote"),
      linkUrl: z.string().optional().describe("URL for link-card attachment"),
      locationId: z.string().optional().describe("Location ID to tag"),
      gifAttachment: z.object({ gifId: z.string(), provider: z.string() }).optional().describe("GIF to attach"),
      textAttachment: z.object({ text: z.string().describe("Long-form text body"), link: z.string().optional() }).optional().describe("Long-form text attachment"),
      topicTag: z.string().optional().describe("Topic tag (1–50 chars, no # prefix needed). One per post."),
      whoCanReply: z.enum(["everyone", "followers", "mentioned", "author_only", "followers_only"]).optional().describe("Reply audience control (default: everyone)"),
      replyApprovalMode: z.enum(["manual_approval"]).optional().describe("Enable manual reply approval"),
      isSpoiler: zBool.optional().describe("Mark media as spoiler"),
      isGhostPost: zBool.optional().describe("Publish as unlisted/ghost post"),
      textSpoilers: z.array(z.object({ offset: z.number(), length: z.number() })).optional().describe("Spoiler text ranges"),
      allowlistedCountryCodes: z.array(z.string()).max(20).optional().describe("Geo-gate to specific countries"),
      altText: z.string().optional().describe("Image accessibility description"),
      topics: z.array(z.string()).max(20).optional().describe("Hashtag topics (appended to content)"),
      crossreshareToIg: zBool.optional().describe("Cross-share post to linked Instagram account as a Story"),
      crossreshareToIgDarkMode: zBool.optional().describe("Cross-share to IG Story in dark mode (overrides crossreshareToIg)"),
    },
    async ({ accountId, content, scheduledFor, mediaIds, pollOptions, quotePostId, linkUrl, locationId, gifAttachment, textAttachment, topicTag, whoCanReply, replyApprovalMode, isSpoiler, isGhostPost, textSpoilers, allowlistedCountryCodes, altText, topics, crossreshareToIg, crossreshareToIgDarkMode }) => {
      return respond(await api("/posts?action=schedule", "POST", {
        accountId, content, platform: "threads", scheduledFor, mediaIds,
        pollOptions, quotePostId, linkUrl, locationId, gifAttachment, textAttachment, topicTag,
        settings: whoCanReply ? { allowReplies: true, whoCanReply } : undefined,
        replyApprovalMode, isSpoiler, isGhostPost, textSpoilers, allowlistedCountryCodes, altText, topics,
        crossreshareToIg, crossreshareToIgDarkMode,
      }));
    }
  );

  // -- Instagram Publishing --

  server.tool(
    "publish_instagram_post",
    "[POSTS:INSTAGRAM] Publish a media post to Instagram immediately. mediaType is required (IMAGE, VIDEO, REELS, STORIES, CAROUSEL). mediaIds required for all types except STORIES with a URL.",
    {
      accountId: z.string().describe("Instagram account ID"),
      content: z.string().describe("Caption text"),
      mediaType: z.string().describe("IMAGE | VIDEO | REELS | STORIES | CAROUSEL"),
      mediaIds: z.array(z.string()).optional().describe("Media IDs to attach (upload first via upload_media)"),
      trialReels: zBool.optional().describe("Publish as Trial Reel (mediaType must be REELS)"),
      trialGraduationStrategy: z.enum(["MANUAL", "SS_PERFORMANCE"]).optional().describe("Trial Reel graduation strategy: MANUAL or SS_PERFORMANCE"),
      locationId: z.string().optional().describe("Location ID to tag"),
      altText: z.string().optional().describe("Image accessibility description"),
      collaborators: z.array(z.string()).max(3).optional().describe("Collaborator IG usernames (max 3)"),
      coverUrl: z.string().optional().describe("Reel cover image URL (REELS only)"),
      shareToFeed: zBool.optional().describe("Show Reel in Feed tab too (REELS only, default: true)"),
      userTags: z.array(z.object({ username: z.string(), x: z.number(), y: z.number() })).optional().describe("Tag users in images — {username, x: 0-1, y: 0-1} coordinates"),
      thumbOffset: z.number().optional().describe("Video/Reels: millisecond offset for cover thumbnail frame"),
      audioName: z.string().optional().describe("Reels only: name the audio track (can only be set once)"),
      productTags: z.array(z.object({ product_id: z.string(), x: z.number().optional(), y: z.number().optional() })).max(5).optional().describe("Tag products from IG Shop (max 5)"),
      commentEnabled: zBool.optional().describe("Set false to disable comments on this post"),
    },
    async ({ accountId, content, mediaType, mediaIds, trialReels, trialGraduationStrategy, locationId, altText, collaborators, coverUrl, shareToFeed, userTags, thumbOffset, audioName, productTags, commentEnabled }) => {
      return respond(await api("/posts?action=publish", "POST", {
        instagramAccountId: accountId, content, platform: "instagram",
        mediaIds, igMediaType: mediaType, isTrialReel: trialReels, graduation: trialGraduationStrategy, locationId, altText, collaborators,
        coverUrl, shareToFeed, userTags, thumbOffset, audioName, productTags, commentEnabled,
      }));
    }
  );

  server.tool(
    "schedule_instagram_post",
    "[POSTS:INSTAGRAM] Schedule an Instagram post for future publication. mediaType is required.",
    {
      accountId: z.string().describe("Instagram account ID"),
      content: z.string().describe("Caption text"),
      scheduledFor: z.string().describe("ISO 8601 datetime (e.g. '2026-03-10T14:00:00Z')"),
      mediaType: z.string().describe("IMAGE | VIDEO | REELS | STORIES | CAROUSEL"),
      mediaIds: z.array(z.string()).optional().describe("Media IDs to attach"),
      trialReels: zBool.optional().describe("Publish as Trial Reel (mediaType must be REELS)"),
      trialGraduationStrategy: z.enum(["MANUAL", "SS_PERFORMANCE"]).optional().describe("Trial Reel graduation strategy: MANUAL or SS_PERFORMANCE"),
      locationId: z.string().optional().describe("Location ID to tag"),
      altText: z.string().optional().describe("Image accessibility description"),
      collaborators: z.array(z.string()).max(3).optional().describe("Collaborator IG usernames (max 3)"),
      coverUrl: z.string().optional().describe("Reel cover image URL (REELS only)"),
      shareToFeed: zBool.optional().describe("Show Reel in Feed tab too (REELS only, default: true)"),
      userTags: z.array(z.object({ username: z.string(), x: z.number(), y: z.number() })).optional().describe("Tag users in images — {username, x: 0-1, y: 0-1} coordinates"),
      thumbOffset: z.number().optional().describe("Video/Reels: millisecond offset for cover thumbnail frame"),
      audioName: z.string().optional().describe("Reels only: name the audio track (can only be set once)"),
      productTags: z.array(z.object({ product_id: z.string(), x: z.number().optional(), y: z.number().optional() })).max(5).optional().describe("Tag products from IG Shop (max 5)"),
      commentEnabled: zBool.optional().describe("Set false to disable comments on this post"),
    },
    async ({ accountId, content, scheduledFor, mediaType, mediaIds, trialReels, trialGraduationStrategy, locationId, altText, collaborators, coverUrl, shareToFeed, userTags, thumbOffset, audioName, productTags, commentEnabled }) => {
      return respond(await api("/posts?action=schedule", "POST", {
        instagramAccountId: accountId, content, platform: "instagram",
        scheduledFor, mediaIds, mediaType, trialReels, graduation: trialGraduationStrategy, locationId, altText, collaborators,
        coverUrl, shareToFeed, userTags, thumbOffset, audioName, productTags, commentEnabled,
      }));
    }
  );

  server.tool(
    "save_draft",
    "Save a post as a draft for later editing/publishing. Supports both Threads and Instagram.",
    {
      content: z.string().describe("Draft text content"),
      accountId: z.string().optional().describe("Account to associate with"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Target platform (default: threads)"),
      mediaIds: z.array(z.string()).optional().describe("Media to attach"),
      draftFolderId: z.string().optional().describe("Folder to save in"),
      topicTag: z.string().optional().describe("Threads: topic tag (1–50 chars)"),
      pollOptions: z.array(z.string()).optional().describe("Threads: poll choices (2–4 items)"),
      linkUrl: z.string().optional().describe("Threads: link-card URL"),
      scheduledFor: z.string().optional().describe("Optional: schedule time (ISO 8601) — converts draft to scheduled"),
      mediaType: z.string().optional().describe("IG: IMAGE | VIDEO | REELS | STORIES | CAROUSEL"),
      altText: z.string().optional().describe("IG: image accessibility description"),
      locationId: z.string().optional().describe("Location ID to tag"),
      collaborators: z.array(z.string()).max(3).optional().describe("IG: collaborator usernames (max 3)"),
      trialReels: zBool.optional().describe("IG: publish as Trial Reel"),
      trialGraduationStrategy: z.enum(["MANUAL", "SS_PERFORMANCE"]).optional().describe("IG: Trial Reel graduation strategy"),
      coverUrl: z.string().optional().describe("IG: Reel cover image URL"),
      shareToFeed: zBool.optional().describe("IG: show Reel in Feed tab"),
      userTags: z.array(z.object({ username: z.string(), x: z.number(), y: z.number() })).optional().describe("IG: tag users in images"),
    },
    async ({ content, accountId, platform, mediaIds, draftFolderId, topicTag, pollOptions, linkUrl, scheduledFor, mediaType, altText, locationId, collaborators, trialReels, trialGraduationStrategy, coverUrl, shareToFeed, userTags }) => {
      const p = platform || "threads";
      const accountField = p === "instagram" ? { instagramAccountId: accountId } : { accountId };
      return respond(await api("/posts?action=schedule", "POST", {
        content, ...accountField, platform: p, mediaIds, draftFolderId,
        topicTag, pollOptions, linkUrl, scheduledFor,
        ...(p === "instagram" ? { mediaType, altText, locationId, collaborators, trialReels, graduation: trialGraduationStrategy, coverUrl, shareToFeed, userTags } : {}),
      }));
    }
  );

  server.tool(
    "update_draft",
    "Update an existing draft or scheduled post — content, media, poll options, topic tag, or reschedule time. Use after ai_feedback or ai_vision_score to refine before scheduling. Only works on status: draft or scheduled.",
    {
      postId: z.string().describe("Draft or scheduled post ID to update"),
      content: z.string().optional().describe("New post text (replaces existing)"),
      mediaIds: z.array(z.string()).optional().describe("New media IDs (replaces existing)"),
      pollOptions: z.array(z.string()).optional().describe("New poll options (Threads only)"),
      scheduledFor: z.string().nullable().optional().describe("New scheduled time (ISO 8601), or null to move to draft"),
      topicTag: z.string().nullable().optional().describe("New topic tag (Threads only), or null to remove"),
      mediaType: z.string().optional().describe("IG: IMAGE | VIDEO | REELS | STORIES | CAROUSEL"),
      altText: z.string().nullable().optional().describe("Image accessibility description, or null to remove"),
      locationId: z.string().nullable().optional().describe("Location ID, or null to remove"),
      collaborators: z.array(z.string()).max(3).nullable().optional().describe("IG: collaborator usernames, or null to remove"),
      coverUrl: z.string().nullable().optional().describe("IG: Reel cover image URL, or null to remove"),
      shareToFeed: zBool.optional().describe("IG: show Reel in Feed tab"),
      userTags: z.array(z.object({ username: z.string(), x: z.number(), y: z.number() })).nullable().optional().describe("IG: tag users, or null to remove"),
      trialReels: zBool.optional().describe("IG: publish as Trial Reel"),
      trialGraduationStrategy: z.enum(["MANUAL", "SS_PERFORMANCE"]).nullable().optional().describe("IG: Trial Reel graduation strategy, or null to remove"),
    },
    async ({ postId, content, mediaIds, pollOptions, scheduledFor, topicTag, mediaType, altText, locationId, collaborators, coverUrl, shareToFeed, userTags, trialReels, trialGraduationStrategy }) => {
      return respond(await api("/posts?action=update-draft", "POST", {
        postId, content, mediaIds, pollOptions, scheduledFor, topicTag,
        mediaType, altText, locationId, collaborators, coverUrl, shareToFeed, userTags, trialReels,
        graduation: trialGraduationStrategy,
      }));
    }
  );

  server.tool(
    "delete_post",
    "Delete a published or scheduled post. Use dryRun=true (default) to preview before deleting.",
    {
      postId: z.string().describe("Post ID to delete"),
      accountId: z.string().describe("Account the post belongs to"),
      dryRun: zBool.default(true).describe("Preview deletion without executing (default: true). Must be explicitly set to false to execute."),
    },
    async ({ postId, accountId, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse("Delete post permanently", { postId, accountId });
      }
      return respond(await api("/posts?action=delete", "POST", { postId, accountId }));
    }
  );

  server.tool(
    "preflight_post",
    "[POSTS] Validate a Threads or Instagram post before publishing/scheduling: account health, media requirements, Trial Reel rules, caption limits, and platform constraints.",
    {
      accountId: z.string().describe("Threads or Instagram account ID"),
      platform: z.enum(["threads", "instagram"]).describe("Target platform"),
      content: z.string().describe("Post text/caption"),
      mediaType: z.string().optional().describe("IG: IMAGE | VIDEO | REELS | STORIES | CAROUSEL"),
      mediaIds: z.array(z.string()).optional().describe("Media IDs to validate"),
      trialReels: zBool.optional().describe("IG: Trial Reel flag"),
      collaborators: z.array(z.string()).max(3).optional().describe("IG collaborator usernames"),
      coverUrl: z.string().optional().describe("IG Reel cover URL"),
      shareToFeed: zBool.optional().describe("IG Reel share-to-feed"),
      userTags: z.array(z.object({ username: z.string(), x: z.number(), y: z.number() })).optional().describe("IG image user tags"),
      productTags: z.array(z.object({ product_id: z.string(), x: z.number().optional(), y: z.number().optional() })).max(5).optional().describe("IG product tags"),
    },
    async ({ accountId, platform, content, mediaType, mediaIds, trialReels, collaborators, coverUrl, shareToFeed, userTags, productTags }) => {
      return respond(await api("/posts?action=preflight", "POST", {
        ...(platform === "instagram" ? { instagramAccountId: accountId } : { accountId }),
        platform, content, mediaType, igMediaType: mediaType, mediaIds, trialReels, collaborators, coverUrl, shareToFeed, userTags, productTags,
      }));
    }
  );

  server.tool(
    "lookup_threads_post",
    "[POSTS:THREADS] Look up a Threads post URL and return its Threads media/post ID for quoting or analysis.",
    {
      postUrl: z.string().describe("Threads post URL"),
    },
    async ({ postUrl }) => respond(await api("/posts?action=lookup", "POST", { postUrl }))
  );

  server.tool(
    "search_post_locations",
    "[POSTS] Search platform location IDs for location tagging.",
    {
      accountId: z.string().describe("Account ID whose token should be used"),
      platform: z.enum(["threads", "instagram"]).describe("Platform to search"),
      query: z.string().describe("Location search query"),
    },
    async ({ accountId, platform, query }) => respond(await api("/posts?action=search-locations", "POST", { accountId, platform, query }))
  );

  server.tool(
    "approve_post",
    "[POSTS] Approve a pending draft/scheduled post. Requires admin/owner approval rights.",
    {
      postId: z.string().describe("Post ID to approve"),
      notes: z.string().optional().describe("Approval notes"),
    },
    async ({ postId, notes }) => respond(await api("/posts?action=approve", "POST", { postId, notes }))
  );

  server.tool(
    "reject_post",
    "[POSTS] Reject a pending draft/scheduled post. Requires admin/owner approval rights.",
    {
      postId: z.string().describe("Post ID to reject"),
      notes: z.string().optional().describe("Rejection notes"),
    },
    async ({ postId, notes }) => respond(await api("/posts?action=reject", "POST", { postId, notes }))
  );

  server.tool(
    "repost_threads_post",
    "[POSTS:THREADS] Repost a Threads media/post ID from one connected account.",
    {
      accountId: z.string().describe("Threads account ID"),
      mediaId: z.string().describe("Threads media/post ID to repost"),
    },
    async ({ accountId, mediaId }) => respond(await api("/posts?action=repost", "POST", { accountId, mediaId }))
  );

  server.tool(
    "refresh_threads_post_metrics",
    "[POSTS:THREADS] Refresh stale or selected Threads post metrics on demand.",
    {
      accountId: z.string().optional().describe("Filter to one Threads account"),
      postIds: z.array(z.string()).max(20).optional().describe("Specific post IDs to refresh, max 20"),
    },
    async ({ accountId, postIds }) => respond(await api("/posts?action=refresh-metrics", "POST", { accountId, postIds }, 30_000))
  );

  server.tool(
    "reschedule_post",
    "Change the scheduled time for a scheduled or draft post. Pass scheduledFor to move it to a new future time, or omit it to unschedule (moves to draft). Only works on posts with status 'scheduled' or 'draft'.",
    {
      postId: z.string().describe("Post ID to reschedule"),
      scheduledFor: z.string().optional().describe("New ISO 8601 datetime (e.g. '2026-03-12T14:00:00Z'). Omit to unschedule to draft."),
    },
    async ({ postId, scheduledFor }) => respond(await api("/posts?action=reschedule", "POST", { postId, scheduledFor }))
  );

  server.tool(
    "import_posts",
    "Import posts from a URL (e.g. a Threads or Instagram profile URL)",
    {
      url: z.string().describe("URL to import from"),
    },
    async ({ url }) => respond(await api("/posts?action=import-posts", "POST", { url }))
  );

  // -- Evergreen --

  server.tool(
    "list_evergreen_posts",
    "List all posts marked as evergreen (auto-recycled content)",
    {
      accountId: z.string().optional().describe("Filter by account"),
    },
    async ({ accountId }) => {
      const params = new URLSearchParams();
      if (accountId) params.set("accountId", accountId);
      return respond(await api(`/posts/evergreen?action=list&${params}`));
    }
  );

  server.tool(
    "toggle_evergreen",
    "Mark or unmark a post as evergreen for automatic recycling",
    {
      postId: z.string().describe("Post ID"),
      isEvergreen: zBool.describe("Mark as evergreen (true) or remove (false)"),
    },
    async ({ postId, isEvergreen }) => {
      return respond(await api("/posts/evergreen", "POST", { action: "toggle", postId, isEvergreen }));
    }
  );

  server.tool(
    "update_evergreen_settings",
    "Update recycling settings for an evergreen post",
    {
      postId: z.string().describe("Post ID"),
      intervalDays: zNum.optional().describe("Days between recycles (7-180)"),
      maxRecycles: zNum.optional().describe("Max recycle count (1-50)"),
      minEngagement: zNum.optional().describe("Min engagement rate to recycle (0-1)"),
    },
    async ({ postId, intervalDays, maxRecycles, minEngagement }) => {
      return respond(await api("/posts/evergreen", "POST", {
        action: "update", postId, intervalDays, maxRecycles, minEngagement,
      }));
    }
  );

  server.tool(
    "bulk_schedule",
    "[POSTS] Schedule multiple posts in one call — the weekly planning tool. Supports both Threads and Instagram. " +
    "IG mediaType: IMAGE | VIDEO | REELS | STORIES | CAROUSEL. Threads extras: quotePostId, linkUrl, gifAttachment. " +
    "Schedules sequentially and returns a pass/fail summary. Use instead of calling schedule_threads_post/schedule_instagram_post N times.",
    {
      posts: z.array(z.object({
        accountId: z.string().describe("Account to post to"),
        content: z.string().describe("Post text"),
        platform: z.enum(["threads", "instagram"]).describe("Target platform"),
        scheduledFor: z.string().describe("ISO 8601 datetime"),
        mediaIds: z.array(z.string()).optional().describe("Media IDs to attach"),
        mediaType: z.string().optional().describe("IG: IMAGE | VIDEO | REELS | STORIES | CAROUSEL"),
        trialReels: zBool.optional().describe("IG: publish as Trial Reel"),
        trialGraduationStrategy: z.enum(["MANUAL", "SS_PERFORMANCE"]).optional().describe("IG: Trial Reel graduation strategy"),
        pollOptions: z.array(z.string()).optional().describe("Threads: poll choices (2-4)"),
        quotePostId: z.string().optional().describe("Threads: post ID to quote"),
        linkUrl: z.string().optional().describe("Threads: link-card URL"),
        locationId: z.string().optional().describe("Threads/IG: location ID"),
        gifAttachment: z.object({ gifId: z.string(), provider: z.string() }).optional().describe("Threads: GIF"),
        textAttachment: z.object({ text: z.string(), link: z.string().optional() }).optional().describe("Threads: long-form text attachment"),
        topicTag: z.string().optional().describe("Threads: topic tag (1–50 chars)"),
        whoCanReply: z.enum(["everyone", "followers", "mentioned", "author_only", "followers_only"]).optional().describe("Threads: reply audience"),
        isSpoiler: zBool.optional().describe("Threads: mark media as spoiler"),
        isGhostPost: zBool.optional().describe("Threads: unlisted/ghost post"),
        altText: z.string().optional().describe("Threads/IG: image accessibility text"),
        allowlistedCountryCodes: z.array(z.string()).max(20).optional().describe("Threads: geo-gate countries"),
        collaborators: z.array(z.string()).max(3).optional().describe("IG: collaborator usernames"),
        coverUrl: z.string().optional().describe("IG: Reel cover image URL"),
        shareToFeed: zBool.optional().describe("IG: show Reel in Feed tab"),
        userTags: z.array(z.object({ username: z.string(), x: z.number(), y: z.number() })).optional().describe("IG: tag users in images"),
        crossreshareToIg: zBool.optional().describe("Threads: cross-share to IG Story"),
        crossreshareToIgDarkMode: zBool.optional().describe("Threads: cross-share to IG Story in dark mode"),
      })).min(1).max(20).describe("Posts to schedule (max 20)"),
    },
    async ({ posts }) => {
      const results: { index: number; scheduledFor: string; ok: boolean; error?: string }[] = [];
      for (let i = 0; i < posts.length; i++) {
        const p = posts[i];
        const isThreads = p.platform === "threads";
        const igFields = !isThreads ? { instagramAccountId: p.accountId } : { accountId: p.accountId };
        const result = await api("/posts?action=schedule", "POST", {
          ...igFields,
          content: p.content,
          platform: p.platform,
          scheduledFor: p.scheduledFor,
          mediaIds: p.mediaIds,
          mediaType: p.mediaType ?? (!isThreads ? "IMAGE" : undefined),
          trialReels: p.trialReels,
          graduation: p.trialGraduationStrategy,
          pollOptions: p.pollOptions,
          quotePostId: p.quotePostId,
          linkUrl: p.linkUrl,
          locationId: p.locationId,
          gifAttachment: p.gifAttachment,
          textAttachment: p.textAttachment,
          topicTag: isThreads ? p.topicTag : undefined,
          settings: isThreads && p.whoCanReply ? { allowReplies: true, whoCanReply: p.whoCanReply } : undefined,
          isSpoiler: isThreads ? p.isSpoiler : undefined,
          isGhostPost: isThreads ? p.isGhostPost : undefined,
          allowlistedCountryCodes: isThreads ? p.allowlistedCountryCodes : undefined,
          crossreshareToIg: isThreads ? p.crossreshareToIg : undefined,
          crossreshareToIgDarkMode: isThreads ? p.crossreshareToIgDarkMode : undefined,
          altText: p.altText,
          collaborators: !isThreads ? p.collaborators : undefined,
          coverUrl: !isThreads ? p.coverUrl : undefined,
          shareToFeed: !isThreads ? p.shareToFeed : undefined,
          userTags: !isThreads ? p.userTags : undefined,
        });
        results.push({ index: i, scheduledFor: p.scheduledFor, ok: result.ok, error: result.ok ? undefined : (result as { ok: false; error: { message: string } }).error?.message });
      }
      const succeeded = results.filter(r => r.ok).length;
      return success({ scheduled: succeeded, failed: results.length - succeeded, results });
    }
  );

  server.tool(
    "bulk_schedule_groups",
    "[POSTS] Schedule up to 100 posts across multiple account groups in one call. Distributes posts across accounts within each group using round-robin. " +
    "Respects per-account daily publish cap (8/day) — skips and reports rather than failing the whole batch. " +
    "AUTO-MEDIA: When mediaIds is omitted, auto-attaches random media from the group's library. IG always gets media (required). Threads ~30% chance (configurable per group). Pass autoAttachMedia=false to disable. " +
    "Posts go to the STANDARD scheduler (posts table), NOT the auto-post queue — they publish via publish-worker cron. " +
    "View them in calendar/scheduled view, not the auto-poster queue UI. " +
    "Use for cross-group content planning where you want group-level targeting without manually picking account IDs.",
    {
      posts: z.array(z.object({
        groupId: z.string().describe("Account group ID to distribute post across"),
        platform: z.enum(["threads", "instagram"]).describe("Target platform"),
        content: z.string().describe("Post text"),
        scheduledFor: z.string().describe("ISO 8601 datetime"),
        mediaIds: z.array(z.string()).optional().describe("Media IDs to attach"),
        mediaType: z.string().optional().describe("IG: IMAGE | VIDEO | REELS | STORIES | CAROUSEL"),
        pollOptions: z.array(z.string()).optional().describe("Threads: poll choices (2-4)"),
        quotePostId: z.string().optional().describe("Threads: post ID to quote"),
        linkUrl: z.string().optional().describe("Threads: link-card URL"),
        gifAttachment: z.object({ gifId: z.string(), provider: z.string() }).optional().describe("Threads: GIF"),
        textAttachment: z.object({ text: z.string(), link: z.string().optional() }).optional().describe("Threads: long-form text attachment"),
        locationId: z.string().optional().describe("Location ID to tag"),
        topicTag: z.string().optional().describe("Threads: topic tag (1–50 chars)"),
        altText: z.string().optional().describe("IG: image accessibility text"),
        collaborators: z.array(z.string()).max(3).optional().describe("IG: collaborator usernames"),
        trialReels: zBool.optional().describe("IG: publish as Trial Reel"),
        trialGraduationStrategy: z.enum(["MANUAL", "SS_PERFORMANCE"]).optional().describe("IG: Trial Reel graduation strategy"),
        coverUrl: z.string().optional().describe("IG: Reel cover image URL"),
        shareToFeed: zBool.optional().describe("IG: show Reel in Feed tab"),
        userTags: z.array(z.object({ username: z.string(), x: z.number(), y: z.number() })).optional().describe("IG: tag users in images"),
        crossreshareToIg: zBool.optional().describe("Threads: cross-share to IG Story"),
        crossreshareToIgDarkMode: zBool.optional().describe("Threads: cross-share to IG Story in dark mode"),
        thumbOffset: z.number().optional().describe("IG: millisecond offset for video/reel cover thumbnail"),
        audioName: z.string().optional().describe("IG Reels: name the audio track"),
        productTags: z.array(z.object({ product_id: z.string(), x: z.number().optional(), y: z.number().optional() })).max(5).optional().describe("IG: tag products from Shop"),
        commentEnabled: zBool.optional().describe("IG: set false to disable comments"),
      })).min(1).max(100).describe("Posts to schedule (max 100)"),
      autoAttachMedia: zBool.optional().describe("Auto-attach random media from group library when mediaIds not provided (default: true). IG always tries. Threads uses group media_attachment_chance (default 30%)."),
    },
    async ({ posts, autoAttachMedia }) => {
      return respond(await api("/posts?action=bulk-schedule-groups", "POST", { posts, autoAttachMedia }, 120_000));
    }
  );
  server.tool(
    "check_content_uniqueness",
    "Before scheduling, check if planned content is too similar to recent posts on this account (prevents loops and repetitive content). Returns similarity score 0–1 and the closest matching post. Score < 0.7 = safe to post.",
    {
      content: z.string().describe("The content you plan to post"),
      accountId: z.string().describe("Account to check against"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Platform (default: threads)"),
      days: zNum.optional().describe("How many days back to check (default 14)"),
    },
    async ({ content, accountId, platform: _platform, days }) => {
      const limit = (days ?? 14) * 2; // rough posts-per-day estimate
      const params = new URLSearchParams({ account_id: accountId, limit: String(Math.min(limit, 100)) });
      const result = await api(`/v1/posts?${params}`);
      if (!result.ok) return respond(result);

      const posts = (result.data as { posts?: { id: string; content: string; created_at: string }[] })?.posts ?? [];

      // Token-overlap similarity (Jaccard)
      const tokenize = (s: string) => new Set(s.toLowerCase().replace(/[^\w\s]/g, "").split(/\s+/).filter(Boolean));
      const planned = tokenize(content);
      let maxSim = 0;
      let closestPost: { id: string; content: string; created_at: string; similarity: number } | null = null;

      for (const post of posts) {
        const existing = tokenize(post.content ?? "");
        const intersection = [...planned].filter(t => existing.has(t)).length;
        const union = new Set([...planned, ...existing]).size;
        const sim = union === 0 ? 0 : intersection / union;
        if (sim > maxSim) { maxSim = sim; closestPost = { ...post, similarity: sim }; }
      }

      const safe = maxSim < 0.7;
      return success({
        similarity: Math.round(maxSim * 100) / 100,
        safe,
        verdict: safe ? "✅ Unique enough to post" : "⚠️ Too similar to a recent post — rephrase or pick a different angle",
        closestMatch: closestPost ? { id: closestPost.id, preview: closestPost.content?.slice(0, 120), postedAt: closestPost.created_at, similarity: closestPost.similarity } : null,
        checkedAgainst: posts.length,
      });
    }
  );

  server.tool(
    "bulk_cancel_scheduled",
    "[SAFETY] Bulk cancel scheduled or draft posts — the emergency escape hatch. Use dryRun=true (default) to preview what would be cancelled before executing. Max 50 posts per call.",
    {
      postIds: z.array(z.string()).min(1).max(50).describe("Post IDs to cancel"),
      dryRun: zBool.default(true).describe("Preview cancellation (default: true). Must be explicitly set to false to execute."),
    },
    async ({ postIds, dryRun }) => {
      return respond(await api("/posts?action=bulk-cancel", "POST", { postIds, dryRun }));
    }
  );

  server.tool(
    "ai_sentiment_scan",
    "[ENGAGEMENT] Bulk sentiment analysis on a post's comments — see if an account is generating hype vs drama before doubling down on that content type. Returns per-comment sentiment + overall score + verdict.",
    {
      postId: z.string().describe("Post ID to scan comments for"),
      platform: z.enum(["threads", "instagram"]).describe("Platform"),
      limit: zNum.optional().describe("Max comments to analyze (default 50, max 100)"),
    },
    async ({ postId, platform, limit }) => {
      const params = new URLSearchParams({ postId, platform });
      if (limit) params.set("limit", String(limit));
      return respond(await api(`/posts?action=sentiment-scan&${params}`));
    }
  );

  // -- Draft folders --

  server.tool(
    "list_draft_folders",
    "List all draft folders",
    {},
    async () => respond(await api("/draft-folders?action=list", "POST", {}))
  );

  server.tool(
    "create_draft_folder",
    "Create a new draft folder",
    {
      name: z.string().describe("Folder name"),
      color: z.string().optional().describe("Hex color (default: #6366f1)"),
      icon: z.string().optional().describe("Icon name (default: folder)"),
    },
    async ({ name, color, icon }) => {
      return respond(await api("/draft-folders?action=create", "POST", { name, color, icon }));
    }
  );

  server.tool(
    "update_draft_folder",
    "Update a draft folder's name, color, or icon",
    {
      folderId: z.string().describe("Folder ID"),
      name: z.string().optional().describe("New name"),
      color: z.string().optional().describe("New hex color"),
      icon: z.string().optional().describe("New icon"),
    },
    async ({ folderId, name, color, icon }) => {
      return respond(await api("/draft-folders?action=update", "POST", { folderId, name, color, icon }));
    }
  );

  server.tool(
    "delete_draft_folder",
    "Delete a draft folder. Use dryRun=true (default) to preview.",
    {
      folderId: z.string().describe("Folder ID"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ folderId, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse("Delete draft folder", { folderId });
      }
      return respond(await api("/draft-folders?action=delete", "POST", { folderId }));
    }
  );

  server.tool(
    "move_drafts_to_folder",
    "Move draft posts into a folder (or unfiled)",
    {
      postIds: z.array(z.string()).describe("Post IDs to move"),
      folderId: z.string().optional().describe("Target folder ID (omit to unfiled)"),
    },
    async ({ postIds, folderId }) => {
      return respond(await api("/draft-folders?action=move-posts", "POST", {
        postIds, folderId: folderId ?? null,
      }));
    }
  );

  // -- Templates --

  server.tool(
    "list_templates",
    "List all saved post templates",
    {},
    async () => respond(await api("/post-templates?action=list", "POST", {}))
  );

  server.tool(
    "create_template",
    "Create a reusable post template",
    {
      name: z.string().describe("Template name"),
      content: z.string().describe("Template content (the post text)"),
      category: z.string().optional().describe("Category (e.g. 'engagement', 'promo')"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Platform (threads/instagram)"),
    },
    async ({ name, content, category, platform }) => {
      return respond(await api("/post-templates?action=create", "POST", {
        name, text_template: content, category, platform,
      }));
    }
  );

  server.tool(
    "delete_template",
    "Delete a post template. Use dryRun=true (default) to preview.",
    {
      templateId: z.string().describe("Template ID"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ templateId, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse("Delete post template", { templateId });
      }
      return respond(await api(`/post-templates?action=delete`, "POST", { templateId }));
    }
  );

  // ---------------------------------------------------------------------------
  // A/B Variant Management
  // ---------------------------------------------------------------------------

  server.tool(
    "list_post_variants",
    "List A/B test variants for a published post. Shows the draft variant that was stored alongside the published post, including both judge scores for comparison. Only works for hot_take/question/tribe_check content types which generate variants automatically.",
    {
      postId: z.string().describe("Queue item ID of the published post (from auto_post_queue)"),
    },
    async ({ postId }) => {
      return respond(await api(`/auto-post?action=variants&postId=${postId}`, "GET"));
    }
  );

  server.tool(
    "promote_variant",
    "Promote an A/B draft variant to scheduled status. Takes a variant queue item ID and schedules it for publishing. The variant must have status 'draft' and source_type 'ai_variant'.",
    {
      variantId: z.string().describe("Queue item ID of the draft variant to promote"),
      scheduledFor: z.string().optional().describe("ISO 8601 time to schedule (default: next available slot)"),
      dryRun: zBool.default(true).describe("Preview without promoting (default: true). Must be explicitly set to false to execute."),
    },
    async ({ variantId, scheduledFor, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse("Promote variant to scheduled", { variantId, scheduledFor });
      }
      return respond(await api("/auto-post?action=promote-variant", "POST", { variantId, scheduledFor }));
    }
  );
};
