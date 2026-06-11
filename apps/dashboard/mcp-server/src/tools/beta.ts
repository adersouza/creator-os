import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, dryRunResponse, zBool } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "get_beta_status",
    "Get beta availability and the current user's beta status when authenticated",
    {},
    async () => respond(await api("/beta?action=status"))
  );

  server.tool(
    "claim_beta_spot",
    "Claim an available beta spot for the current user",
    {
      dryRun: zBool.default(true).describe("Preview beta claim (default: true). Must be explicitly set to false to execute."),
    },
    async ({ dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Claim beta spot", {});
      return respond(await api("/beta?action=claim", "POST", {}));
    }
  );

  server.tool(
    "submit_beta_feedback",
    "Submit feedback as a beta user",
    {
      feedback: z.string().describe("Feedback text"),
      category: z.string().optional().describe("Feedback category (default: general)"),
      dryRun: zBool.default(true).describe("Preview feedback submission (default: true). Must be explicitly set to false to execute."),
    },
    async ({ feedback, category, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Submit beta feedback", { feedback, category });
      return respond(await api("/beta?action=feedback", "POST", { feedback, category }));
    }
  );
};
