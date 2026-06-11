import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "run_onboarding_instant_analysis",
    "Analyze recent posts for onboarding insights: best post, CES baseline, timing, and top quick win",
    {
      accountId: z.string().describe("Account ID"),
      platform: z.enum(["threads", "instagram"]).describe("Platform"),
    },
    async ({ accountId, platform }) => {
      return respond(await api("/onboarding?action=instant-analysis", "POST", { accountId, platform }, 30_000));
    }
  );
};
