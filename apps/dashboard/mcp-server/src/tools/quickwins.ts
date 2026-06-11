import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, zNum, AI_TIMEOUT } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "get_quick_wins",
    "Get AI-powered quick win recommendations for improving account performance",
    {
      accountId: z.string().describe("Account ID"),
      platform: z.enum(["threads", "instagram"]).describe("Platform"),
    },
    async ({ accountId, platform }) => {
      return respond(await api(`/ai/low-hanging-fruit?accountId=${accountId}&platform=${platform}`, "GET", undefined, AI_TIMEOUT));
    }
  );

  server.tool(
    "dismiss_recommendation",
    "Dismiss a quick win recommendation with a reason. 'not_relevant' deprioritizes for 30 days, 'will_try_later' resurfaces after 14 days.",
    {
      recId: z.string().describe("Recommendation ID"),
      accountId: z.string().describe("Account ID"),
      reason: z.enum(["already_doing", "not_relevant", "will_try_later"]).describe("Dismissal reason"),
      category: z.string().optional().describe("Recommendation category"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Platform"),
    },
    async ({ recId, accountId, reason, category, platform }) => {
      return respond(await api("/ai/dismiss-recommendation", "POST", { recId, accountId, reason, category, platform }));
    }
  );

  server.tool(
    "bulk_apply_quick_wins",
    "Apply a quick win action (apply-timing or snooze) for a recommendation category",
    {
      category: z.string().describe("Recommendation category (e.g. 'posting_time', 'content_type')"),
      action: z.enum(["apply-timing", "snooze"]).describe("Action: 'apply-timing' adjusts next 5 posts, 'snooze' hides for 30 days"),
      accountId: z.string().describe("Account ID"),
      platform: z.enum(["threads", "instagram"]).describe("Platform"),
      recommendedHours: z.array(zNum).optional().describe("Recommended posting hours (for apply-timing)"),
    },
    async ({ category, action, accountId, platform, recommendedHours }) => {
      return respond(await api("/quickwins/bulk-apply", "POST", { category, action, accountId, platform, recommendedHours }));
    }
  );
};
