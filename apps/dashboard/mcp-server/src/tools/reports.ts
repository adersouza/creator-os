import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, zBool } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "generate_report",
    "Generate a branded performance report (weekly/monthly/custom) with optional AI recommendations. Returns PDF data.",
    {
      accountId: z.string().describe("Account ID"),
      reportType: z.enum(["weekly", "monthly", "custom"]).describe("Report type"),
      startDate: z.string().describe("Start date (ISO 8601, e.g. '2026-03-01')"),
      endDate: z.string().describe("End date (ISO 8601, e.g. '2026-03-07')"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Platform filter"),
      includeRecommendations: zBool.optional().describe("Include AI recommendations section"),
      clientName: z.string().optional().describe("Client name for report header"),
    },
    async ({ accountId, reportType, startDate, endDate, platform, includeRecommendations, clientName }) => {
      return respond(await api("/reports?action=generate", "POST", {
        accountId, reportType,
        dateRange: { start: startDate, end: endDate },
        platform, includeRecommendations, clientName,
      }, 30_000));
    }
  );

  server.tool(
    "generate_saved_report",
    "Generate/download a saved report by report ID and update its last-run timestamp.",
    {
      reportId: z.string().describe("Saved report ID"),
    },
    async ({ reportId }) => respond(await api("/reports?action=generateFromReport", "POST", { reportId }, 30_000))
  );

  server.tool(
    "update_saved_report",
    "Update a saved/scheduled report definition, recipients, cadence, status, or config.",
    {
      reportId: z.string().describe("Saved report ID"),
      name: z.string().optional().describe("Report name"),
      type: z.enum(["scheduled", "one-off"]).optional().describe("Report type"),
      cadence: z.enum(["weekly", "monthly", "quarterly", "one-off"]).optional().describe("Cadence"),
      status: z.enum(["active", "paused", "generated", "draft"]).optional().describe("Report status"),
      network: z.string().nullable().optional().describe("Network/group ID filter, or null to clear"),
      recipients: z.array(z.object({ email: z.string(), name: z.string().optional() })).optional().describe("Email recipients"),
      nextRunAt: z.string().nullable().optional().describe("Next scheduled run ISO datetime, or null"),
      config: z.object({}).passthrough().optional().describe("Advanced report config JSON"),
    },
    async ({ reportId, name, type, cadence, status, network, recipients, nextRunAt, config }) => {
      return respond(await api("/reports?action=update", "PUT", {
        reportId, name, type, cadence, status, network, recipients, nextRunAt, config,
      }));
    }
  );

  server.tool(
    "send_saved_report",
    "Generate and email a saved report to its configured recipients.",
    {
      reportId: z.string().describe("Saved report ID"),
    },
    async ({ reportId }) => respond(await api("/reports?action=send", "POST", { reportId }, 45_000))
  );
};
