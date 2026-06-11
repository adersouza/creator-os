import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, dryRunResponse, zBool, zNum } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "get_annual_recap",
    "Generate or retrieve the user's annual growth recap",
    {
      year: zNum.optional().describe("Recap year, default current year"),
    },
    async ({ year }) => {
      const params = new URLSearchParams({ action: "annual-recap" });
      if (year) params.set("year", String(year));
      return respond(await api(`/user?${params}`, "GET", undefined, 30_000));
    }
  );

  server.tool(
    "get_data_contribution_preference",
    "Read the user's anonymized cohort data contribution preference",
    {},
    async () => respond(await api("/user?action=data-contribution"))
  );

  server.tool(
    "set_data_contribution_preference",
    "Update anonymized cohort data contribution preference and optional niche",
    {
      optedIn: zBool.describe("Whether to opt into anonymized cohort contribution"),
      niche: z.string().optional().describe("Canonical niche; required by API when opting in"),
      dryRun: zBool.default(true).describe("Preview update (default: true). Must be explicitly set to false to execute."),
    },
    async ({ optedIn, niche, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Update data contribution preference", { optedIn, niche });
      return respond(await api("/user?action=data-contribution", "POST", { opted_in: optedIn, niche }));
    }
  );

  server.tool(
    "request_user_data_export",
    "Start a GDPR user data export job",
    {
      dryRun: zBool.default(true).describe("Preview export request (default: true). Must be explicitly set to false to execute."),
    },
    async ({ dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Start user data export job", {});
      return respond(await api("/user?action=export", "GET", undefined, 30_000));
    }
  );

  server.tool(
    "get_user_data_export_status",
    "Check status for a GDPR user data export job",
    {
      jobId: z.string().describe("Export job ID"),
      includeDownloadUrl: zBool.optional().describe("If true, request a signed download URL when complete"),
    },
    async ({ jobId, includeDownloadUrl }) => {
      const params = new URLSearchParams({ action: "export-status", jobId });
      if (includeDownloadUrl) params.set("download", "false");
      return respond(await api(`/user?${params}`));
    }
  );

  server.tool(
    "get_recommendation_profile",
    "Get recommendation success rates by category for the current user",
    {},
    async () => respond(await api("/user?action=rec-profile"))
  );
};
