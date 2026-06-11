import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, error, zNum } from "../helpers.js";

const PeakWindowSchema = z.object({
  day: z.enum(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])
    .describe("Day of week"),
  hour: z.number().int().min(0).max(23).describe("Hour (0-23 UTC)"),
});

export const register: ToolRegistrar = (server) => {
  server.tool(
    "get_content_strategy",
    "Read the content strategy for an account group (or all groups). Returns pillars, weekly post target, tone notes, topics to avoid, CTA rotation, and preferred posting windows. Call this at the start of every autonomous session before generating content.",
    {
      accountGroupId: z.string().optional().describe("Account group ID — omit to get all groups"),
    },
    async ({ accountGroupId }) => {
      const params = new URLSearchParams();
      if (accountGroupId) params.set("accountGroupId", accountGroupId);
      return respond(await api(`/agent/content-strategy?${params}`));
    }
  );

  server.tool(
    "set_content_strategy",
    "Save or update the content strategy for an account group. This persists across sessions — Claude reads it at the start of every autonomous run. At minimum set pillars and weekly_target.",
    {
      accountGroupId: z.string().describe("Account group ID to save strategy for"),
      pillars: z.array(z.string()).optional().describe("3-5 content themes (e.g. ['growth tips', 'behind the scenes', 'social proof'])"),
      weeklyTarget: zNum.optional().describe("Target posts per week for this group (1-50)"),
      toneNotes: z.string().optional().describe("Tone overrides / additions beyond voice_profile (e.g. 'Always end with a question. No corporate speak.')"),
      topicsToAvoid: z.array(z.string()).optional().describe("Topics/keywords to never post about"),
      ctaRotation: z.array(z.string()).optional().describe("CTAs to cycle through across posts"),
      peakWindows: z.array(PeakWindowSchema).optional().describe("Preferred posting times (day + UTC hour)"),
      competitorIds: z.array(z.string()).optional().describe("Competitor IDs to use for this group's content. Restricts competitor copy and style examples to only these competitors. Use list_competitors to find IDs. Omit to use all competitors."),
    },
    async ({ accountGroupId, pillars, weeklyTarget, toneNotes, topicsToAvoid, ctaRotation, peakWindows, competitorIds }) => {
      // Merge non-undefined fields into strategy object
      const strategy: Record<string, unknown> = {};
      if (pillars !== undefined) strategy.pillars = pillars;
      if (weeklyTarget !== undefined) strategy.weekly_target = weeklyTarget;
      if (toneNotes !== undefined) strategy.tone_notes = toneNotes;
      if (topicsToAvoid !== undefined) strategy.topics_to_avoid = topicsToAvoid;
      if (ctaRotation !== undefined) strategy.cta_rotation = ctaRotation;
      if (peakWindows !== undefined) strategy.peak_windows = peakWindows;
      if (competitorIds !== undefined) strategy.competitor_ids = competitorIds;

      if (Object.keys(strategy).length === 0) {
        return error({ code: "invalid_input", message: "No strategy fields provided", status: 400 });
      }

      return respond(await api("/agent/content-strategy", "PATCH", { accountGroupId, strategy }));
    }
  );
};
