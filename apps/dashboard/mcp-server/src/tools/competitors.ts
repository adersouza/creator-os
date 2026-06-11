import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, dryRunResponse, zBool, zNum, AI_TIMEOUT } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "list_competitors",
    "List all tracked competitors and their latest metrics. If accountId is omitted, returns ALL competitors for the authenticated user (workspace-level view). Competitors are user-scoped, not workspace-scoped.",
    {
      accountId: z.string().optional().describe("Account ID (optional — omit to list all competitors across all accounts)"),
    },
    async ({ accountId }) => {
      const params = new URLSearchParams({ action: "list" });
      if (accountId) params.set("accountId", accountId);
      return respond(await api(`/competitors?${params}`));
    }
  );

  server.tool(
    "add_competitor",
    "Start tracking a new competitor by username",
    {
      accountId: z.string().describe("Your account ID"),
      username: z.string().describe("Competitor's username to track"),
      platform: z.enum(["threads", "instagram"]).describe("Platform"),
    },
    async ({ accountId, username, platform }) => {
      return respond(await api("/competitors?action=add", "POST", {
        accountId, username, platform,
      }));
    }
  );

  server.tool(
    "bulk_add_competitors",
    "Add multiple competitors in one call (up to 50). Avoids circuit-breaker trips from sequential add_competitor calls. Returns per-username success/failure breakdown.",
    {
      accountId: z.string().optional().describe("Account ID (required for Instagram)"),
      platform: z.enum(["threads", "instagram"]).describe("Platform"),
      usernames: z.array(z.string()).describe("Usernames to track (max 50)"),
    },
    async ({ accountId, platform, usernames }) => {
      return respond(await api("/competitors?action=bulk-add", "POST", {
        accountId, platform, usernames,
      }, 120_000)); // 2min timeout for large batches
    }
  );

  server.tool(
    "remove_competitor",
    "Stop tracking a competitor. Use dryRun=true (default) to preview.",
    {
      accountId: z.string().describe("Your account ID"),
      competitorId: z.string().describe("Competitor ID to remove"),
      dryRun: zBool.default(true).describe("Preview removal (default: true). Must be explicitly set to false to execute."),
    },
    async ({ accountId, competitorId, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse("Remove competitor from tracking", { competitorId, accountId });
      }
      return respond(await api("/competitors?action=remove", "POST", {
        accountId, competitorId,
      }));
    }
  );

  server.tool(
    "bulk_remove_competitors",
    "[SAFETY] Remove multiple competitors in one call. dryRun=true (default) previews what would be removed. " +
    "Validates all competitorIds belong to accountId before deleting. Partial success — removes what it can, reports failures. " +
    "Cap: 100 competitorIds per request. Circuit breaker counts this as 1 call.",
    {
      accountId: z.string().describe("Your account ID"),
      competitorIds: z.array(z.string()).min(1).max(100).describe("Competitor IDs to remove"),
      dryRun: zBool.default(true).describe("Preview removal (default: true). Must be explicitly set to false to execute."),
    },
    async ({ accountId, competitorIds, dryRun }) => {
      return respond(await api("/competitors?action=bulk-remove", "POST", {
        accountId, competitorIds, dryRun: dryRun !== false,
      }));
    }
  );

  server.tool(
    "assign_competitors_to_group",
    "Assign specific competitors to an account group. That group's content pipeline (competitor copy + style examples) will ONLY use these competitors. " +
    "Use list_competitors to find IDs, then assign gym/thirst competitors to Lola groups and GFE competitors to Larissa groups. " +
    "Pass an empty array to clear the assignment (reverts to using all competitors).",
    {
      accountGroupId: z.string().describe("Account group ID to assign competitors to"),
      competitorIds: z.array(z.string()).describe("Competitor IDs to use for this group. Empty array = use all competitors."),
    },
    async ({ accountGroupId, competitorIds }) => {
      return respond(await api("/agent/content-strategy", "PATCH", {
        accountGroupId,
        strategy: { competitor_ids: competitorIds },
      }));
    }
  );

  server.tool(
    "analyze_competitor",
    "Run AI-powered competitive analysis comparing a competitor to your account",
    {
      competitorId: z.string().describe("Competitor ID"),
      accountId: z.string().describe("Your account ID for comparison"),
    },
    async ({ competitorId, accountId }) => {
      return respond(await api("/competitors/analyze", "POST", { competitorId, accountId }, AI_TIMEOUT));
    }
  );

  server.tool(
    "get_competitor_media",
    "Fetch media details for a specific Threads post (media URL, type, thumbnail)",
    {
      threadsPostId: z.string().describe("Threads post ID to fetch media for"),
    },
    async ({ threadsPostId }) => {
      return respond(await api(`/competitors?action=media&threadsPostId=${encodeURIComponent(threadsPostId)}`));
    }
  );

  server.tool(
    "get_competitor_schedule_pattern",
    "[STRATEGY] Analyze when competitors post and what format performs for them. Returns a day/hour heatmap of their posting activity plus format breakdown. Use for scheduling decisions.",
    {
      accountId: z.string().describe("Your account ID"),
      competitorId: z.string().optional().describe("Specific competitor (omit for all tracked competitors)"),
      days: zNum.optional().describe("Days to analyze (default 30)"),
    },
    async ({ accountId, competitorId, days }) => {
      const params = new URLSearchParams({ accountId });
      if (competitorId) params.set("competitorId", competitorId);
      if (days) params.set("days", String(days));
      return respond(await api(`/analytics/competitor-patterns?${params}`));
    }
  );

  server.tool(
    "list_competitor_top_posts",
    "[RESEARCH] Get the highest-engagement posts from a tracked competitor, sorted by engagement score. Use to find viral content to adapt via get_inspiration_ideas.",
    {
      competitorId: z.string().describe("Competitor ID"),
      days: zNum.optional().describe("Lookback window in days (default: 7, max: 30)"),
      limit: zNum.optional().describe("Max posts to return (default: 10, max: 50)"),
    },
    async ({ competitorId, days, limit }) => {
      const params = new URLSearchParams({ action: "top-posts", competitorId });
      if (days) params.set("days", String(days));
      if (limit) params.set("limit", String(limit));
      return respond(await api(`/competitors?${params}`));
    }
  );

  server.tool(
    "get_inspiration_ideas",
    "[CONTENT] Read AI-adapted content ideas generated from competitor posts by the daily inspiration scan. Returns ideas ready to use, edit, or publish. Filter by status='pending' to see unused ideas. Call at the start of a content session to queue up your best angles.",
    {
      workspaceId: z.string().describe("Workspace ID"),
      status: z.enum(["pending", "used", "archived"]).optional().describe("Filter by idea status (default: pending)"),
      competitorId: z.string().optional().describe("Filter to ideas from a specific competitor"),
      limit: zNum.optional().describe("Max ideas to return (default: 20, max: 100)"),
    },
    async ({ workspaceId, status, competitorId, limit }) => {
      const params = new URLSearchParams({ workspaceId });
      if (status) params.set("status", status);
      if (competitorId) params.set("competitorId", competitorId);
      if (limit) params.set("limit", String(limit));
      return respond(await api(`/inspiration?${params}`));
    }
  );

  server.tool(
    "use_inspiration_idea",
    "[CONTENT] Mark an inspiration idea as 'used' and optionally pre-fill the post composer with its adapted content. Call this before publishing the content so the system tracks conversion rates from competitor posts.",
    {
      ideaId: z.string().describe("Inspiration idea ID to mark as used"),
    },
    async ({ ideaId }) => {
      return respond(await api("/inspiration", "POST", { action: "use", ideaId }));
    }
  );
};
