import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, dryRunResponse, zBool, zNum } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "auto_post_health_check",
    "Check auto-poster health across all accounts (token validity, queue status). Now includes diagnostics: warns if master switch is OFF, AI queue fill is disabled, or group mode is off. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
    },
    async ({ workspaceId }) => respond(await api("/auto-post?action=health-check", "POST", { workspaceId }))
  );

  server.tool(
    "get_workspace_config",
    "Get workspace-level auto-poster settings: AI fill (provider, limits, style), content filters, velocity monitoring, source-mix policy, and Discord alerts. Group-level posting settings (intervals, hours, media) live on per-group configs — use get_auto_post_configs for those. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
    },
    async ({ workspaceId }) => respond(await api("/auto-post?action=get-workspace-config", "POST", { workspaceId }))
  );

  server.tool(
    "get_auto_post_configs",
    "Get auto-poster configurations for all account groups. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
    },
    async ({ workspaceId }) => respond(await api("/auto-post?action=get-group-configs", "POST", { workspaceId }))
  );

  server.tool(
    "upsert_auto_post_config",
    "Create or update auto-poster configuration for an account group. Only group-level settings — for workspace-level AI/performance settings, use upsert_workspace_config. On UPDATE, only provided fields are changed (no default overwrite). Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      groupId: z.string().describe("Account group ID"),
      // Core posting controls
      enabled: zBool.optional().describe("Enable/disable auto-posting for this group"),
      contentSources: z.array(z.string()).optional().describe("Content source types"),
      postsPerAccountPerDay: zNum.optional().describe("Max posts per account per day"),
      minIntervalMinutes: zNum.optional().describe("Minimum minutes between posts"),
      maxIntervalMinutes: zNum.optional().describe("Maximum minutes between posts"),
      activeHoursStart: zNum.optional().describe("Hour to start posting (0-23, in group timezone)"),
      activeHoursEnd: zNum.optional().describe("Hour to stop posting (0-23, in group timezone)"),
      timezone: z.string().optional().describe("Timezone for daily resets (e.g. 'America/New_York')"),
      postOnWeekends: zBool.optional().describe("Whether to post on Saturday/Sunday"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Platform to post to"),
      roundRobinEnabled: zBool.optional().describe("Cycle through accounts in group"),
      // Media controls
      mediaAttachmentChance: zNum.optional().describe("Percent chance to attach media (0-100)"),
      mediaSource: z.string().optional().describe("Where to pull media: 'global', 'group-specific', or 'mixed'"),
      // Approval gate
      requireApproval: zBool.optional().describe("Require human approval before each auto-post"),
      // Cross-share to IG Stories
      crossreshareToIg: zBool.optional().describe("Auto cross-share Threads posts to linked Instagram account as a Story (requires threads_share_to_instagram permission)"),
      crossreshareToIgDarkMode: zBool.optional().describe("Use dark mode styling for IG Story cross-share (overrides crossreshareToIg)"),
      // Delayed CTA replies (replaces old self-reply threads)
      ctaReplyEnabled: zBool.optional().describe("Enable delayed CTA replies — posts a Snap/DM CTA as a reply to yesterday's best-performing post (12-24h delay)"),
      ctaReplyMinLikes: zNum.optional().describe("Minimum likes before a post gets a CTA reply (default 5)"),
      ctaReplyDelayHours: zNum.optional().describe("Hours to wait before posting CTA reply (default 16)"),
      ctaTemplates: z.array(z.string()).optional().describe("CTA reply templates — use {handle} as placeholder for account username. E.g. 'Write me on Snap: {handle}'"),
      // Human randomness — variable daily posts + rest days
      minPostsPerAccountPerDay: zNum.optional().describe("Min posts per account per day. Daily count randomized between this and postsPerAccountPerDay. NULL = fixed (no randomization)."),
      restDaysPerWeek: zNum.optional().describe("Random rest days per week per account (0-6). Each account gets different rest days, re-rolled weekly."),
      // Auto-reply (also configurable via toggle_auto_reply)
      enableAutoReply: zBool.optional().describe("Enable auto-reply on auto-posted content"),
      autoReplyDailyLimit: zNum.optional().describe("Max auto-replies per group per day (1-50, default 5)"),
      autoReplyRatio: zNum.optional().describe("Fraction of comments to reply to (0-1, default 0.5)"),
      autoReplyTriggerCount: zNum.optional().describe("Min comments on a post before harvesting (1-100, default 1)"),
      autoReplyWindowHours: zNum.optional().describe("Hours after posting to harvest comments (1-168, default 24)"),
    },
    async (params) => {
      const { workspaceId, groupId, ...rest } = params;
      const config: Record<string, unknown> = {};
      const mapping: Record<string, string> = {
        enabled: "enabled",
        contentSources: "content_sources",
        postsPerAccountPerDay: "posts_per_account_per_day",
        minIntervalMinutes: "min_interval_minutes",
        maxIntervalMinutes: "max_interval_minutes",
        activeHoursStart: "active_hours_start",
        activeHoursEnd: "active_hours_end",
        timezone: "timezone",
        postOnWeekends: "post_on_weekends",
        platform: "platform",
        roundRobinEnabled: "round_robin_enabled",
        mediaAttachmentChance: "media_attachment_chance",
        mediaSource: "media_source",
        requireApproval: "require_approval",
        crossreshareToIg: "crossreshare_to_ig",
        crossreshareToIgDarkMode: "crossreshare_to_ig_dark_mode",
        minPostsPerAccountPerDay: "min_posts_per_account_per_day",
        restDaysPerWeek: "rest_days_per_week",
        ctaReplyEnabled: "cta_reply_enabled",
        ctaReplyMinLikes: "cta_reply_min_likes",
        ctaReplyDelayHours: "cta_reply_delay_hours",
        ctaTemplates: "cta_templates",
        enableAutoReply: "enable_auto_reply",
        autoReplyDailyLimit: "auto_reply_daily_limit",
        autoReplyRatio: "auto_reply_ratio",
        autoReplyTriggerCount: "auto_reply_trigger_count",
        autoReplyWindowHours: "auto_reply_window_hours",
      };
      for (const [camel, snake] of Object.entries(mapping)) {
        if ((rest as Record<string, unknown>)[camel] !== undefined) {
          config[snake] = (rest as Record<string, unknown>)[camel];
        }
      }
      return respond(await api("/auto-post?action=upsert-group-config", "POST", {
        workspaceId, groupId, config,
      }));
    }
  );

  server.tool(
    "upsert_workspace_config",
    "Update workspace-level auto-poster settings (AI queue fill, performance monitoring, velocity, smart timing). These live on auto_post_config, NOT per-group. Only provided fields are updated. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      enableAiQueueFill: zBool.optional().describe("Auto-generate posts when queue runs low"),
      aiQueueMinThreshold: zNum.optional().describe("Trigger AI fill when queue drops below this count"),
      aiPostsPerFill: zNum.optional().describe("How many posts to generate per fill"),
      aiDailyGenerationLimit: zNum.optional().describe("Max AI-generated posts per day"),
      aiStyleGuidelines: z.string().optional().describe("User-provided rules/guidelines for AI content generation"),
      groupModeEnabled: zBool.optional().describe("Enable group-based posting mode"),
      pauseOnLowPerformance: zBool.optional().describe("Auto-pause if engagement drops below threshold"),
      performanceThreshold: zNum.optional().describe("Minimum engagement rate percent before pausing"),
      enableVelocityMonitoring: zBool.optional().describe("Track engagement acceleration/decline over time"),
      boostOnViral: zBool.optional().describe("Reduce posting interval when a post goes viral"),
      viralIntervalReductionPct: zNum.optional().describe("How much to reduce interval on viral post (percent)"),
      useSmartTiming: zBool.optional().describe("Use AI-analyzed best posting times"),
      competitorCopyRatio: zNum.optional().describe("Deprecated legacy setting. The live queue-fill mix now follows the built-in source policy instead of this ratio."),
      competitorCopyMaxWords: zNum.optional().describe("Deprecated legacy setting retained for backward compatibility."),
      contentFilterPatterns: z.array(z.object({
        pattern: z.string().describe("Regex pattern (case-insensitive)"),
        label: z.string().describe("Human-readable label for this rule"),
      })).optional().describe("Banned content patterns — posts matching any pattern are rejected before queue insertion. Replaces defaults when set."),
      contentFilterMinLength: zNum.optional().describe("Min character length for auto-posted content (default 20). Posts shorter than this are rejected. Catches fragments like 'snap?' or 'bro rn'."),
      contentFilterMaxLength: zNum.optional().describe("Max character length for auto-posted content (default 200). Posts exceeding this are rejected."),
      contentFilterMaxEmojis: zNum.optional().describe("Max emoji count allowed (default 2). Posts with more are rejected."),
      discordWebhookUrl: z.string().optional().describe("Per-workspace Discord webhook URL for watchdog alerts. Falls back to DISCORD_ALERT_WEBHOOK_URL env var."),
      aiProvider: z.string().optional().describe("AI provider for content generation: 'gemini' (default), 'xai' (Grok — minimal content filtering, best for edgy/thirst content). Set to 'xai' to use Grok via XAI_API_KEY env var."),
    },
    async (params) => {
      const { workspaceId, ...rest } = params;
      const body: Record<string, unknown> = { workspaceId };
      const mapping: Record<string, string> = {
        enableAiQueueFill: "enable_ai_queue_fill",
        aiQueueMinThreshold: "ai_queue_min_threshold",
        aiPostsPerFill: "ai_posts_per_fill",
        aiDailyGenerationLimit: "ai_daily_generation_limit",
        aiStyleGuidelines: "ai_style_guidelines",
        groupModeEnabled: "group_mode_enabled",
        pauseOnLowPerformance: "pause_on_low_performance",
        performanceThreshold: "performance_threshold",
        enableVelocityMonitoring: "enable_velocity_monitoring",
        boostOnViral: "boost_on_viral",
        viralIntervalReductionPct: "viral_interval_reduction_pct",
        useSmartTiming: "use_smart_timing",
        competitorCopyRatio: "competitor_copy_ratio",
        competitorCopyMaxWords: "competitor_copy_max_words",
        contentFilterPatterns: "content_filter_patterns",
        contentFilterMinLength: "content_filter_min_length",
        contentFilterMaxLength: "content_filter_max_length",
        contentFilterMaxEmojis: "content_filter_max_emojis",
        discordWebhookUrl: "discord_webhook_url",
        aiProvider: "ai_provider",
      };
      for (const [camel, snake] of Object.entries(mapping)) {
        if ((rest as Record<string, unknown>)[camel] !== undefined) {
          body[snake] = (rest as Record<string, unknown>)[camel];
        }
      }
      return respond(await api("/auto-post?action=upsert-workspace-config", "POST", body));
    }
  );

  server.tool(
    "delete_auto_post_config",
    "Delete the auto-poster configuration for an account group. Use dryRun=true (default) to preview. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      groupId: z.string().describe("Account group ID whose config to delete"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ workspaceId, groupId, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse("Delete auto-post config for group", { workspaceId, groupId });
      }
      return respond(await api("/auto-post?action=delete-group-config", "POST", { workspaceId, groupId }));
    }
  );

  server.tool(
    "toggle_auto_post",
    "[SAFETY] Enable or disable auto-posting. When ENABLING, the server checks for overdue queue items (scheduled_for < NOW). " +
    "If any exist, returns 409 error — you must flush the queue first with bulk_clear_all_queues.\n\n" +
    "Behavior depends on params:\n" +
    "- groupIds (array) → enables/disables multiple specific groups (phased activation)\n" +
    "- groupId (single) → toggles that specific group's enabled flag\n" +
    "- scope='master' (default) → toggles auto_post_config.is_enabled (the master on/off switch the cron gates on)\n" +
    "- scope='group_mode' → toggles auto_post_config.group_mode_enabled (whether group-based posting is active)\n" +
    "Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      groupId: z.string().optional().describe("Account group ID — if provided, toggles this group only"),
      groupIds: z.array(z.string()).optional().describe("Array of group IDs for phased activation — enable/disable specific groups instead of all-or-nothing"),
      enabled: zBool.describe("true to enable, false to disable"),
      scope: z.enum(["master", "group_mode"]).optional().describe("'master' (default) = is_enabled master switch, 'group_mode' = group_mode_enabled flag. Ignored when groupId/groupIds is set."),
    },
    async ({ workspaceId, groupId, groupIds, enabled, scope }) => {
      return respond(await api("/auto-post?action=toggle-group-mode", "POST", { workspaceId, groupId, groupIds, enabled, scope }));
    }
  );

  server.tool(
    "verify_autoposter_state",
    "[SAFETY] Pre-flight check before toggling the autoposter. Returns: master switch status, queue counts by status, " +
    "overdue items (scheduled_for < NOW that would burst-publish), last 5 published posts with per-account time gaps, " +
    "burst alerts (any account that posted twice within 45min today), failed/stuck item counts. " +
    "ALWAYS call this before toggle_auto_post(enabled=true). Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
    },
    async ({ workspaceId }) => {
      return respond(await api("/auto-post?action=verify-autoposter-state", "POST", { workspaceId }));
    }
  );

  server.tool(
    "get_publish_log",
    "[SAFETY] Last N published posts showing account_username, published_at, seconds_since_previous_on_same_account, " +
    "content_preview, group_name. Sorted by published_at desc. Use to immediately spot burst patterns — " +
    "any entry with seconds_since_previous < 1800 (30min) is a burst violation. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      limit: zNum.optional().describe("Max posts to return (default 30, max 100)"),
    },
    async ({ workspaceId, limit }) => {
      return respond(await api("/auto-post?action=get-publish-log", "POST", { workspaceId, limit }));
    }
  );

  server.tool(
    "get_auto_post_queue",
    "Inspect the auto-post queue. If groupId is provided, returns items for that group. If omitted, returns items across ALL groups in the workspace (workspace-level view). Use to audit AI-generated content BEFORE it publishes, or review recently published items. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      groupId: z.string().optional().describe("Account group ID (optional — omit for workspace-level view across all groups)"),
      status: z.enum(["pending", "published", "cancelled", "dead_letter", "failed", "all"]).optional().describe("Filter by status (default: pending)"),
      limit: zNum.optional().describe("Max items to return (default 20, max 100)"),
    },
    async ({ workspaceId, groupId, status, limit }) => {
      return respond(await api("/auto-post?action=get-group-queue", "POST", { groupId, workspaceId, status, limit }));
    }
  );

  server.tool(
    "fetch_auto_post_engagement",
    "Fetch engagement metrics for a specific auto-posted item",
    {
      postId: z.string().describe("Post ID"),
    },
    async ({ postId }) => {
      return respond(await api("/auto-post?action=fetch-engagement", "POST", { postId }));
    }
  );

  server.tool(
    "sync_auto_post_engagement",
    "Trigger engagement sync for all auto-posted content in a workspace",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
    },
    async ({ workspaceId }) => {
      return respond(await api("/auto-post?action=sync-engagement", "POST", { workspaceId }));
    }
  );

  server.tool(
    "get_auto_reply_queue",
    "View the auto-reply queue for a workspace. Shows harvested comments and their reply status. Use status='needs_review' to see flagged negative comments awaiting human review. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      status: z.enum(["pending", "processing", "posted", "failed", "skipped", "needs_review"]).optional().describe("Filter by status. 'needs_review' shows negative comments flagged for human review."),
      limit: zNum.optional().describe("Max items to return (default 20, max 100)"),
    },
    async ({ workspaceId, status, limit }) => {
      return respond(await api("/auto-post?action=get-auto-reply-queue", "POST", { workspaceId, status, limit }));
    }
  );

  server.tool(
    "toggle_auto_reply",
    "Enable or disable auto-reply for an account group. When enabled, the autoposter will harvest comments on auto-posted content and generate contextual AI replies using the account's voice profile. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      groupId: z.string().describe("Account group ID"),
      enabled: zBool.describe("true to enable auto-reply, false to disable"),
      dailyLimit: zNum.optional().describe("Max auto-replies per group per day (1-50, default 5)"),
      ratio: zNum.optional().describe("Fraction of comments to reply to (0-1, default 0.5)"),
      triggerCount: zNum.optional().describe("Min comments on a post before harvesting (1-100, default 1)"),
      windowHours: zNum.optional().describe("Hours after posting to harvest comments (1-168, default 24)"),
    },
    async ({ workspaceId, groupId, enabled, dailyLimit, ratio, triggerCount, windowHours }) => {
      const config: Record<string, unknown> = {};
      if (enabled !== undefined) config.enable_auto_reply = enabled;
      if (dailyLimit !== undefined) config.auto_reply_daily_limit = dailyLimit;
      if (ratio !== undefined) config.auto_reply_ratio = ratio;
      if (triggerCount !== undefined) config.auto_reply_trigger_count = triggerCount;
      if (windowHours !== undefined) config.auto_reply_window_hours = windowHours;
      return respond(await api("/auto-post?action=toggle-auto-reply", "POST", {
        workspaceId, groupId, config,
      }));
    }
  );

  // Queue management
  server.tool(
    "bulk_clear_queue",
    "[SAFETY] Cancel ALL pending items in the auto-post queue for a single group. Use when content strategy changes and old queue items no longer match guidelines. For clearing ALL groups at once, use bulk_clear_all_queues instead. dryRun=true (default) previews the count before executing. Empire tier required.",
    {
      groupId: z.string().describe("Account group ID whose queue should be cleared"),
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      dryRun: zBool.default(true).describe("Preview cancellation (default: true). Must be explicitly set to false to execute."),
    },
    async ({ groupId, workspaceId, dryRun }) => {
      return respond(await api("/auto-post?action=bulk-clear-queue", "POST", { groupId, workspaceId, dryRun }));
    }
  );

  server.tool(
    "bulk_clear_all_queues",
    "[SAFETY] Cancel ALL pending items across EVERY group in a workspace. One call clears the entire workspace queue — no need to call bulk_clear_queue per group. Returns per-group breakdown of cancelled items. dryRun=true (default) previews counts before executing. Empire tier required.",
    {
      workspaceId: z.string().describe("Workspace ID — all groups in this workspace will be cleared"),
      dryRun: zBool.default(true).describe("Preview cancellation (default: true). Must be explicitly set to false to execute."),
    },
    async ({ workspaceId, dryRun }) => {
      return respond(await api("/auto-post?action=bulk-clear-all-queues", "POST", { workspaceId, dryRun }));
    }
  );

  server.tool(
    "get_queue_counts",
    "Lightweight queue count across all groups in a workspace. Returns total pending items and per-group breakdown (name + count). No content returned — just counts. Use this FIRST to get a quick overview before diving into specific groups with get_auto_post_queue. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
    },
    async ({ workspaceId }) => {
      return respond(await api("/auto-post?action=get-queue-counts", "POST", { workspaceId }));
    }
  );

  server.tool(
    "delete_queue_item",
    "[SAFETY] Cancel a single item from the auto-post queue by ID. Only works on pending/queued items. dryRun=true (default) previews the item before cancelling. Empire tier required.",
    {
      queueItemId: z.string().describe("UUID of the queue item to cancel"),
      dryRun: zBool.default(true).describe("Preview cancellation (default: true). Must be explicitly set to false to execute."),
    },
    async ({ queueItemId, dryRun }) => {
      return respond(await api("/auto-post?action=delete-queue-item", "POST", { queueItemId, dryRun }));
    }
  );

  // Per-account config overrides
  server.tool(
    "get_account_overrides",
    "Get per-account config overrides within a group. Returns overrides that take priority over group-level settings. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      groupId: z.string().optional().describe("Filter to a specific group"),
      accountId: z.string().optional().describe("Filter to a specific account"),
    },
    async ({ workspaceId, groupId, accountId }) => {
      return respond(await api("/auto-post?action=get-account-overrides", "POST", { workspaceId, groupId, accountId }));
    }
  );

  server.tool(
    "upsert_account_override",
    "Set per-account config overrides within a group. Any setting not specified falls back to the group default. Supports all group-level settings: postsPerAccountPerDay, minIntervalMinutes, activeHoursStart/End, timezone, postOnWeekends, enableAutoReply, autoReplyDailyLimit, autoReplyRatio, autoReplyTriggerCount, autoReplyWindowHours. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      groupId: z.string().describe("Account group ID"),
      accountId: z.string().describe("Account ID to override settings for"),
      // Same fields as group config — all optional since these are overrides
      postsPerAccountPerDay: zNum.optional().describe("Override: max posts per day for this account"),
      minIntervalMinutes: zNum.optional().describe("Override: min minutes between posts"),
      maxIntervalMinutes: zNum.optional().describe("Override: max minutes between posts"),
      activeHoursStart: zNum.optional().describe("Override: UTC hour to start posting (0-23)"),
      activeHoursEnd: zNum.optional().describe("Override: UTC hour to stop posting (0-23)"),
      timezone: z.string().optional().describe("Override: timezone for this account"),
      postOnWeekends: zBool.optional().describe("Override: post on weekends"),
      enabled: zBool.optional().describe("Override: enable/disable this account"),
      enableAutoReply: zBool.optional().describe("Override: enable auto-reply"),
      autoReplyDailyLimit: zNum.optional().describe("Override: max auto-replies per day (1-50)"),
      autoReplyRatio: zNum.optional().describe("Override: fraction of comments to reply to (0-1)"),
      autoReplyTriggerCount: zNum.optional().describe("Override: min comments before harvesting (1-100)"),
      autoReplyWindowHours: zNum.optional().describe("Override: hours after posting to harvest (1-168)"),
      crossreshareToIg: zBool.optional().describe("Override: cross-share Threads posts to IG Story"),
      crossreshareToIgDarkMode: zBool.optional().describe("Override: use dark mode for IG Story cross-share"),
    },
    async (params) => {
      const { workspaceId, groupId, accountId, ...rest } = params;
      const overrides: Record<string, unknown> = {};
      const mapping: Record<string, string> = {
        postsPerAccountPerDay: "posts_per_account_per_day",
        minIntervalMinutes: "min_interval_minutes",
        maxIntervalMinutes: "max_interval_minutes",
        activeHoursStart: "active_hours_start",
        activeHoursEnd: "active_hours_end",
        timezone: "timezone",
        postOnWeekends: "post_on_weekends",
        enabled: "enabled",
        crossreshareToIg: "crossreshare_to_ig",
        crossreshareToIgDarkMode: "crossreshare_to_ig_dark_mode",
        enableAutoReply: "enable_auto_reply",
        autoReplyDailyLimit: "auto_reply_daily_limit",
        autoReplyRatio: "auto_reply_ratio",
        autoReplyTriggerCount: "auto_reply_trigger_count",
        autoReplyWindowHours: "auto_reply_window_hours",
      };
      for (const [camel, snake] of Object.entries(mapping)) {
        if ((rest as Record<string, unknown>)[camel] !== undefined) {
          overrides[snake] = (rest as Record<string, unknown>)[camel];
        }
      }
      return respond(await api("/auto-post?action=upsert-account-override", "POST", {
        workspaceId, groupId, accountId, overrides,
      }));
    }
  );

  server.tool(
    "delete_account_override",
    "Remove per-account config overrides — account falls back to group defaults. Use dryRun=true (default) to preview. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      groupId: z.string().describe("Account group ID"),
      accountId: z.string().describe("Account ID to remove overrides for"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ workspaceId, groupId, accountId, dryRun }) => {
      return respond(await api("/auto-post?action=delete-account-override", "POST", {
        workspaceId, groupId, accountId, dryRun,
      }));
    }
  );

  // ============================================================================
  // Reply Chain & Health Tools
  // ============================================================================

  server.tool(
    "get_reply_chain_stats",
    "[ANALYTICS] Get self-reply and cross-reply chain metrics plus account health tier summary. " +
    "Returns published/pending/failed counts for both reply types, account health tier distribution, " +
    "and top 10 accounts by health score. Use to monitor reply chain engine performance.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      days: zNum.optional().describe("Lookback window in days (default: 7)"),
    },
    async ({ workspaceId, days }) => {
      return respond(await api("/auto-post?action=get-reply-chain-stats", "POST", {
        workspaceId, days,
      }));
    }
  );

  // ── New batch tools ───────────────────────────────────────────────────────

  server.tool(
    "get_queue_content_audit",
    "Returns last N published posts with source_type, source_competitor, char count, views, likes, replies merged from queue + posts tables. One call for full content quality + performance audit. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      groupId: z.string().optional().describe("Filter to a specific group (optional)"),
      limit: zNum.optional().describe("Max items (default 20, max 50)"),
    },
    async ({ workspaceId, groupId, limit }) => {
      return respond(await api("/auto-post?action=queue-content-audit", "POST", {
        workspaceId, groupId, limit,
      }));
    }
  );

  server.tool(
    "bulk_update_group_configs",
    "Update auto-poster config for multiple groups in one call. Pass an array of {groupId, ...settings}. Supports: enabled, postsPerAccountPerDay, minIntervalMinutes, maxIntervalMinutes, activeHoursStart, activeHoursEnd, platform, useSmartTiming. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      updates: z.array(z.object({
        groupId: z.string().describe("Account group ID"),
        enabled: zBool.optional(),
        postsPerAccountPerDay: zNum.optional(),
        minIntervalMinutes: zNum.optional(),
        maxIntervalMinutes: zNum.optional(),
        activeHoursStart: zNum.optional(),
        activeHoursEnd: zNum.optional(),
        platform: z.string().optional(),
        useSmartTiming: zBool.optional(),
        crossreshareToIg: zBool.optional().describe("Cross-share Threads posts to IG Story"),
        crossreshareToIgDarkMode: zBool.optional().describe("Dark mode for IG Story cross-share"),
      })).describe("Array of group config updates"),
    },
    async ({ workspaceId, updates }) => {
      return respond(await api("/auto-post?action=bulk-update-group-configs", "POST", {
        workspaceId, updates,
      }));
    }
  );

  server.tool(
    "get_account_bios",
    "Returns all account usernames with their current bio text, follower count, group assignment, and status. Use for bio audits across all accounts without hitting the Threads API.",
    {},
    async () => {
      return respond(await api("/auto-post?action=get-account-bios", "POST", {}));
    }
  );

  server.tool(
    "bulk_set_content_strategy",
    "Update content strategy (toneNotes, pillars, weeklyTarget, topicsToAvoid, ctaRotation) for multiple groups in one call. Merges with existing strategy — only provided fields are changed.",
    {
      strategies: z.array(z.object({
        groupId: z.string().describe("Account group ID"),
        toneNotes: z.string().optional().describe("Tone/voice notes for the group"),
        pillars: z.array(z.string()).optional().describe("Content pillar themes"),
        weeklyTarget: zNum.optional().describe("Target posts per week"),
        topicsToAvoid: z.array(z.string()).optional().describe("Topics to never post about"),
        ctaRotation: z.array(z.string()).optional().describe("CTAs to rotate"),
        competitorIds: z.array(z.string()).optional().describe("Competitor IDs to restrict content sourcing to (from list_competitors)"),
      })).describe("Array of strategy updates per group"),
    },
    async ({ strategies }) => {
      return respond(await api("/auto-post?action=bulk-set-content-strategy", "POST", {
        strategies,
      }));
    }
  );

  server.tool(
    "get_competitor_posts_sample",
    "Pull random posts from ALL tracked competitors in one call. Returns N posts each from M random human-verified competitors. Use for pattern analysis and content audits without calling list_competitor_top_posts per competitor.",
    {
      competitorCount: zNum.optional().describe("Number of random competitors to sample (default 10, max 30)"),
      postsPerCompetitor: zNum.optional().describe("Posts per competitor (default 5, max 20)"),
    },
    async ({ competitorCount, postsPerCompetitor }) => {
      return respond(await api("/auto-post?action=competitor-posts-sample", "POST", {
        competitorCount, postsPerCompetitor,
      }));
    }
  );

  // ============================================================================
  // Operator Control Tools
  // ============================================================================

  server.tool(
    "get_account_token_health",
    "[DIAGNOSTICS] View token/credential health for all accounts in a workspace. Returns: account_id, username, platform, is_active, needs_reauth, is_retired, is_shadowbanned, last_sync_at. Use to identify accounts with dead tokens before enabling the autoposter. (Different from get_account_health in analytics which scores engagement health.)",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
    },
    async ({ workspaceId }) => {
      return respond(await api("/auto-post?action=get-account-health", "POST", { workspaceId }));
    }
  );

  server.tool(
    "retry_queue_item",
    "[SAFETY] Move a failed auto_post_queue item back to pending status for retry. Resets retry_count to 0 and sets scheduled_for to NOW + 5 minutes. Use to recover items that failed due to transient errors. dryRun=true (default) previews the item.",
    {
      queueItemId: z.string().describe("Queue item ID to retry"),
      dryRun: zBool.default(true).describe("Preview before executing (default: true)"),
    },
    async ({ queueItemId, dryRun }) => {
      return respond(await api("/auto-post?action=retry-dead-letter", "POST", { queueItemId, dryRun }));
    }
  );

  server.tool(
    "trigger_queue_fill",
    "[CONTENT] Manually trigger AI queue fill for a specific group. Dispatches a background job to generate posts using the group's voice profile and content strategy. Same as what the cron does automatically, but on demand. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      groupId: z.string().describe("Account group ID to fill"),
    },
    async ({ workspaceId, groupId }) => {
      return respond(await api("/auto-post?action=trigger-queue-fill", "POST", { workspaceId, groupId }));
    }
  );

  server.tool(
    "get_filter_rejections",
    "[DIAGNOSTICS] View recent posts rejected by the content filter. Shows rejection reason, matched text, content preview, and source type. Use to tune content filter patterns and understand why posts are being blocked. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      groupId: z.string().optional().describe("Filter to a specific group"),
      limit: zNum.optional().describe("Max items (default 20, max 100)"),
    },
    async ({ workspaceId, groupId, limit }) => {
      return respond(await api("/auto-post?action=get-filter-rejections", "POST", { workspaceId, groupId, limit }));
    }
  );

  // ============================================================================
  // Account State Visibility (Phase 5 — Simplification Plan)
  // ============================================================================

  server.tool(
    "get_account_states",
    "[DIAGNOSTICS] Why aren't my accounts posting? Shows every account's autoposter status (active, suppressed, view_cooldown, viral_suppress, flop_delay, warming, shadowban_throttle, inactive), reason, blocked_until countdown, and performance metrics (14d avg views, 30d median/max, % under 5 views). Filter by group or see entire workspace. Updated every 15 min by state evaluator cron. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      groupId: z.string().optional().describe("Filter to a specific group (optional — omit for all groups)"),
    },
    async ({ workspaceId, groupId }) => {
      return respond(await api("/auto-post?action=get-account-states", "POST", { workspaceId, groupId }));
    }
  );

  server.tool(
    "get_queue_fill_explain",
    "[DIAGNOSTICS] Why did the last fill produce 0 posts? Shows last N queue fill results with: posts inserted/generated/rejected, rejection breakdown (duplicate, content_filter, embedding_dedup), per-account skip reasons (suppressed, view_cooldown, eligibility), and early exit reason if the fill never reached generation (daily_limit_reached, pending_above_threshold, etc.). Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      groupId: z.string().optional().describe("Filter to a specific group (optional)"),
      limit: zNum.optional().describe("Number of recent fills to return (default 10, max 50)"),
    },
    async ({ workspaceId, groupId, limit }) => {
      return respond(await api("/auto-post?action=get-queue-fill-explain", "POST", { workspaceId, groupId, limit }));
    }
  );

  server.tool(
    "override_account_state",
    "[OPERATOR] Force-change an account's autoposter state. Actions: 'resume' (set to active, clear all blocks + Redis keys), 'pause' (set to inactive for 30 days), 'clear_cooldown' (remove view_cooldown/viral_suppress and resume). The state evaluator cron re-evaluates every 15 min — if the underlying condition persists, the account will be re-blocked. Empire tier required.",
    {
      accountId: z.string().describe("Account ID to override"),
      groupId: z.string().describe("Account's group ID"),
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
      action: z.enum(["resume", "pause", "clear_cooldown"]).describe("'resume' = set active, 'pause' = set inactive 30d, 'clear_cooldown' = remove cooldown + resume"),
      reason: z.string().optional().describe("Human-readable reason for the override (logged)"),
    },
    async ({ accountId, groupId, workspaceId, action, reason }) => {
      return respond(await api("/auto-post?action=override-account-state", "POST", { accountId, groupId, workspaceId, action, reason }));
    }
  );

  server.tool(
    "get_autoposter_snapshot",
    "[CONTEXT] Full autoposter system snapshot in one call. Returns: master switch status, all account states with per-account active hours and performance metrics, all group configs with media mapping and caps, queue counts, last 2 fills per group with rejection breakdown, and all posts published today. Call this FIRST at the start of every session to understand the full system state. Empire tier required.",
    {
      workspaceId: z.string().optional().describe("Workspace ID (uses default if omitted)"),
    },
    async ({ workspaceId }) => {
      return respond(await api("/auto-post?action=get-autoposter-snapshot", "POST", { workspaceId }));
    }
  );

  server.tool(
    "get_auto_post_variants",
    "[AUTOPOSTER] Fetch A/B variants generated for an auto-post queue item.",
    {
      postId: z.string().describe("Original auto_post_queue item ID"),
    },
    async ({ postId }) => respond(await api(`/auto-post?action=variants&postId=${encodeURIComponent(postId)}`, "GET"))
  );

  server.tool(
    "promote_auto_post_variant",
    "[AUTOPOSTER] Promote a draft AI variant into the auto-post queue for publishing.",
    {
      variantId: z.string().describe("Draft AI variant queue item ID"),
      scheduledFor: z.string().optional().describe("Optional ISO datetime; defaults to about 30 minutes from now"),
    },
    async ({ variantId, scheduledFor }) => respond(await api("/auto-post?action=promote-variant", "POST", { variantId, scheduledFor }))
  );
};
