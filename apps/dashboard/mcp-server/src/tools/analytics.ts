import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, error, zBool, zNum } from "../helpers.js";

const ADVANCED_ANALYTICS_ACTIONS = [
  "daily-activity",
  "feature-usage",
  "forecasts",
  "reach-anomalies",
  "self-compare",
  "while-away",
  "network",
  "health-snapshots",
  "demographics-db",
  "benchmarks",
  "annotations",
  "hashtag-performance",
  "top-engagers",
  "team-performance",
  "engager-retention",
  "audience-overlap",
  "follower-attribution",
  "content-type-trend",
  "competitor-benchmark",
  "overnight-brief",
  "sends-per-reach-leaders",
  "skip-rate-alerts",
  "quote-reply-ratio",
  "link-click-leaders",
  "watch-time-leaders",
  "topic-tag-lift",
  "save-rate-leaders",
  "non-follower-reach-breakdown",
  "audience-online-now",
  "story-profile-activity",
  "anomaly-feed",
  "reply-depth-leaders",
  "pending-replies-queue",
  "competitor-surprises",
  "cross-account-patterns",
  "fleet-health-accounts",
  "views-by-source",
  "severity-score",
  "cohort-benchmarks",
  "quality-by-pillar",
  "bio-link-funnel",
  "hook-class-lift",
  "stories-funnel",
  "strikes-count",
  "originality-risk",
  "audience-twin-map",
] as const;

function appendParams(params: URLSearchParams, input: Record<string, unknown> | undefined) {
  if (!input) return;
  for (const [key, value] of Object.entries(input)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      params.set(key, value.join(","));
    } else if (typeof value === "object") {
      params.set(key, JSON.stringify(value));
    } else {
      params.set(key, String(value));
    }
  }
}

export const register: ToolRegistrar = (server) => {
  server.tool(
    "get_analytics",
    "Get SINGLE account analytics (followers, engagement, reach) with period-over-period deltas. For workspace-wide totals across ALL accounts, use get_cross_account_insights instead.",
    {
      accountId: z.string().describe("Account ID (single account only — use get_cross_account_insights for workspace-wide)"),
      period: z.enum(["7d", "14d", "30d", "90d"]).optional().describe("Time period (default: 30d)"),
      includeHistory: zBool.optional().describe("Include daily breakdown of followers/views/likes/replies"),
    },
    async ({ accountId, period, includeHistory }) => {
      const params = new URLSearchParams({ account_id: accountId });
      if (period) params.set("period", period);
      if (includeHistory) params.set("include_history", "true");
      return respond(await api(`/v1/analytics?${params}`));
    }
  );

  server.tool(
    "get_ig_account_insights",
    "Get Instagram-specific account insights (reach, impressions, saves, profile views, follower growth)",
    {
      accountId: z.string().describe("Instagram account ID"),
      period: z.enum(["day", "week", "days_28"]).optional().describe("Period (default: days_28)"),
    },
    async ({ accountId, period }) => {
      return respond(await api("/instagram/insights?action=account-insights", "POST", { accountId, period }));
    }
  );

  server.tool(
    "get_ig_post_insights",
    "Get detailed insights for a specific Instagram post (impressions, reach, saves, likes, comments, shares)",
    {
      accountId: z.string().describe("Instagram account ID"),
      mediaId: z.string().describe("Instagram media ID"),
    },
    async ({ accountId, mediaId }) => {
      return respond(await api("/instagram/insights?action=post-insights", "POST", { accountId, mediaId }));
    }
  );

  server.tool(
    "get_demographics",
    "Get audience demographics breakdown (age, gender, location) for an account",
    {
      accountId: z.string().describe("Account ID"),
    },
    async ({ accountId }) => respond(await api(`/analytics?action=demographics&accountId=${encodeURIComponent(accountId)}`))
  );

  server.tool(
    "get_recap",
    "Generate a growth recap summary with top post, best posting times, engagement score, streak",
    {
      accountId: z.string().describe("Account ID"),
      period: z.enum(["7d", "30d", "all"]).optional().describe("Period (default: 7d)"),
    },
    async ({ accountId, period }) => {
      const params = new URLSearchParams({ account_id: accountId });
      if (period) params.set("period", period);
      return respond(await api(`/recap/generate?${params}`));
    }
  );

  server.tool(
    "get_ig_publishing_limit",
    "Check Instagram publishing rate limit quota (how many posts remaining)",
    {
      accountId: z.string().describe("Instagram account ID"),
    },
    async ({ accountId }) => {
      return respond(await api("/instagram/insights?action=publishing-limit", "POST", { accountId }));
    }
  );

  server.tool(
    "get_threads_quota",
    "Check Threads API publishing quota (posts, replies, deletes remaining)",
    {
      accountId: z.string().describe("Threads account ID"),
    },
    async ({ accountId }) => respond(await api(`/threads/quota?accountId=${accountId}`))
  );

  server.tool(
    "growth_journal_list",
    "View growth journal entries — tracks which recommendations you acted on and their outcomes",
    {
      accountId: z.string().describe("Account ID"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Platform filter"),
      category: z.string().optional().describe("Category filter"),
    },
    async ({ accountId, platform, category }) => {
      const params = new URLSearchParams({ accountId });
      if (platform) params.set("platform", platform);
      if (category) params.set("category", category);
      return respond(await api(`/user?action=growth-journal&${params}`));
    }
  );

  server.tool(
    "get_mentioned_media",
    "Get Instagram posts where this account has been @mentioned or tagged by other users. " +
    "Use type='tagged' (default) to list all posts the account appears in. " +
    "Use type='mentioned' with a specific mediaId to look up a post where the account was @mentioned in a caption (requires mediaId from a webhook event).",
    {
      accountId: z.string().describe("Instagram account ID"),
      type: z.enum(["tagged", "mentioned"]).optional().describe("'tagged' = posts you appear in (list), 'mentioned' = specific @mention lookup (requires mediaId)"),
      mediaId: z.string().optional().describe("Required when type='mentioned': the specific media ID from a webhook"),
    },
    async ({ accountId, type, mediaId }) => {
      if (type === "mentioned") {
        if (!mediaId) {
          return error({ code: "invalid_input", message: "mediaId is required for type='mentioned'", status: 400 });
        }
        return respond(await api("/instagram/insights?action=mentioned-media", "POST", { accountId, mediaId }));
      }
      return respond(await api("/instagram/insights?action=tagged-posts", "POST", { accountId }));
    }
  );

  server.tool(
    "growth_journal_create",
    "Log a growth journal entry — record an action you took and track its impact over time",
    {
      accountId: z.string().describe("Account ID"),
      recommendationText: z.string().describe("What action you took"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Platform"),
      category: z.string().optional().describe("Category"),
      icon: z.string().optional().describe("Icon"),
    },
    async ({ accountId, recommendationText, platform, category, icon }) => {
      return respond(await api("/user?action=growth-journal", "POST", {
        accountId, recommendationText, platform, category, icon,
      }));
    }
  );

  server.tool(
    "get_account_health",
    "Account health scoring — detects stagnant, shadowbanned, and breakout accounts across all workspace accounts. Uses 14-day history from account_metrics_history. Returns per-account status (healthy/stagnant/possible_shadowban/breakout) with details.",
    {
      platform: z.enum(["threads", "instagram"]).optional().describe("Filter by platform (default: both)"),
    },
    async ({ platform }) => {
      const qs = platform ? `&platform=${platform}` : "";
      return respond(await api(`/analytics?action=account-health${qs}`));
    }
  );

  server.tool(
    "detect_reach_anomaly",
    "[SAFETY] Shadowban / reach anomaly detector. Compares last 3 days' reach vs 7-14 day baseline. Flags >40% drops as potential shadowban. Run this periodically to catch suppression early.",
    {
      accountId: z.string().describe("Account ID to check"),
    },
    async ({ accountId }) => {
      return respond(await api(`/analytics/reach-anomaly?accountId=${accountId}`));
    }
  );

  server.tool(
    "log_revenue_snapshot",
    "[REVENUE] Log a revenue/subscriber data point for an account group. Use to correlate social output with actual money over time. Upserts by date — call daily or weekly.",
    {
      accountGroupId: z.string().describe("Account group ID"),
      subscribers: zNum.optional().describe("Current subscriber count"),
      revenue: zNum.optional().describe("Current revenue (e.g. monthly revenue in dollars)"),
      notes: z.string().optional().describe("Optional notes (e.g. 'launched new tier', 'ran promo')"),
      recordedAt: z.string().optional().describe("Date to record for (YYYY-MM-DD, default: today)"),
    },
    async ({ accountGroupId, subscribers, revenue, notes, recordedAt }) => {
      return respond(await api("/analytics/revenue", "POST", {
        action: "log", accountGroupId, subscribers, revenue, notes, recordedAt,
      }));
    }
  );

  server.tool(
    "get_revenue_history",
    "[REVENUE] View revenue/subscriber history for correlation with social performance. Shows trends over time.",
    {
      accountGroupId: z.string().optional().describe("Filter to account group (omit for all)"),
      days: zNum.optional().describe("Days of history (default 30, max 365)"),
    },
    async ({ accountGroupId, days }) => {
      const params = new URLSearchParams();
      if (accountGroupId) params.set("accountGroupId", accountGroupId);
      if (days) params.set("days", String(days));
      return respond(await api(`/analytics/revenue?${params}`));
    }
  );

  server.tool(
    "get_cross_account_insights",
    "[STRATEGY] Workspace-level dashboard — aggregated followers, views, likes, replies, engagement rate, top post, best hours/days, per-account rankings, and per-platform breakdown. Uses account_analytics period deltas (latest - earliest) for accurate metrics matching the dashboard. Falls back to post-level sums for accounts without analytics data. Filter by platform.",
    {
      days: zNum.optional().describe("Analysis period in days (default 14, max 90)"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Filter to one platform (default: both platforms combined)"),
    },
    async ({ days, platform }) => {
      const params = new URLSearchParams();
      if (days) params.set("days", String(days));
      if (platform) params.set("platform", platform);
      return respond(await api(`/analytics/cross-insights?${params}`));
    }
  );

  server.tool(
    "get_group_analytics",
    "Aggregate metrics across all accounts in an account group. Shows total followers, views, likes, posts, engagement rate, per-account breakdown, and top posts.",
    {
      groupId: z.string().describe("Account group ID"),
      days: zNum.optional().describe("Analysis period in days (default 30, max 90)"),
    },
    async ({ groupId, days }) => {
      const params = new URLSearchParams({ groupId });
      if (days) params.set("days", String(days));
      return respond(await api(`/analytics/group-analytics?${params}`));
    }
  );

  server.tool(
    "get_model_comparison",
    "[STRATEGY] Compare performance across all account groups. Shows which group has best engagement, most views, fastest growth. Useful for multi-brand or multi-persona comparison.",
    {
      days: zNum.optional().describe("Analysis period in days (default 14, max 90)"),
    },
    async ({ days }) => {
      const params = new URLSearchParams();
      if (days) params.set("days", String(days));
      return respond(await api(`/analytics/model-comparison?${params}`));
    }
  );

  server.tool(
    "get_post_metrics_history",
    "Get time-series metric snapshots for posts from post_metric_history table. Returns views/likes/replies/reposts over time with computed deltas and velocity. Use granularity='daily' to collapse to one snapshot per day.",
    {
      postId: z.string().optional().describe("Single post ID (optional if accountId provided)"),
      accountId: z.string().optional().describe("Account ID — returns history for all posts in account"),
      startDate: z.string().optional().describe("Start date filter (ISO string)"),
      endDate: z.string().optional().describe("End date filter (ISO string)"),
      granularity: z.enum(["raw", "daily"]).optional().describe("'raw' = every snapshot, 'daily' = latest per day (default: raw)"),
      limit: zNum.optional().describe("Max rows (default 100, max 500)"),
    },
    async ({ postId, accountId, startDate, endDate, granularity, limit }) => {
      const params = new URLSearchParams();
      if (postId) params.set("postId", postId);
      if (accountId) params.set("accountId", accountId);
      if (startDate) params.set("startDate", startDate);
      if (endDate) params.set("endDate", endDate);
      if (granularity) params.set("granularity", granularity);
      if (limit) params.set("limit", String(limit));
      return respond(await api(`/analytics/post-metrics-history?${params}`));
    }
  );

  server.tool(
    "get_top_performing_elements",
    "[STRATEGY] Analyze which content elements drive the most engagement — top hashtags, CTAs (link in bio, questions, follow), caption lengths, and media types. Use to refine content strategy with data.",
    {
      accountId: z.string().describe("Account ID to analyze"),
      days: zNum.optional().describe("Analysis period in days (default 30, max 90)"),
    },
    async ({ accountId, days }) => {
      const params = new URLSearchParams({ accountId });
      if (days) params.set("days", String(days));
      return respond(await api(`/analytics/top-elements?${params}`));
    }
  );

  server.tool(
    "get_competitor_trends",
    "View competitor performance trends over time — engagement rate, follower growth, posting frequency changes. Requires competitor_metrics_history data.",
    {
      competitorId: z.string().describe("Competitor ID"),
      days: zNum.optional().describe("Analysis period (default 30, max 90)"),
    },
    async ({ competitorId, days }) => {
      const params = new URLSearchParams({ competitorId });
      if (days) params.set("days", String(days));
      return respond(await api(`/analytics/competitor-trends?${params}`));
    }
  );

  server.tool(
    "get_funnel_correlation",
    "[STRATEGY] Correlates daily post views with follower changes to estimate view-to-follower conversion rates. Shows daily breakdown, Pearson correlation, and top converter posts.",
    {
      accountId: z.string().describe("Account ID to analyze"),
      days: zNum.optional().describe("Analysis period in days (default 30, max 90)"),
    },
    async ({ accountId, days }) => {
      const params = new URLSearchParams({ accountId });
      if (days) params.set("days", String(days));
      return respond(await api(`/analytics/funnel-correlation?${params}`));
    }
  );

  server.tool(
    "get_advanced_analytics",
    "[ANALYTICS] Access advanced read-only analytics surfaces not covered by narrower tools. Use for dashboard tiles like audience overlap, story funnels, hook lift, save-rate leaders, anomaly feed, cohort benchmarks, and originality risk.",
    {
      action: z.enum(ADVANCED_ANALYTICS_ACTIONS).describe("Analytics action/surface to fetch"),
      params: z.object({}).passthrough().optional().describe("Query parameters for that analytics surface, e.g. {accountId, days, platform, groupId, limit}"),
    },
    async ({ action, params }) => {
      const qs = new URLSearchParams({ action });
      appendParams(qs, params as Record<string, unknown> | undefined);
      return respond(await api(`/analytics?${qs}`));
    }
  );
};
