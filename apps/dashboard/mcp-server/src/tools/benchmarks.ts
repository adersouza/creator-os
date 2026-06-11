import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "get_benchmarks",
    "[ANALYTICS] Get anonymized tier benchmarks — avg engagement rate, posts/week, follower growth rate, and views/post grouped by follower tier (0-1K, 1K-5K, 5K-10K, 10K-50K, 50K+). See how your account compares. Only includes data from accounts that opted in.",
    {
      accountId: z.string().optional().describe("Your account ID — used to determine which tier you're in"),
    },
    async ({ accountId }) => {
      const params = new URLSearchParams();
      if (accountId) params.set("accountId", accountId);
      params.set("action", "benchmarks");
      return respond(await api(`/analytics?${params}`));
    }
  );
};
