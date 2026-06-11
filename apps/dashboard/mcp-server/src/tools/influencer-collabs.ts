import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, dryRunResponse, zBool, zNum } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "list_collabs",
    "[COLLABS] List all influencer collaborations with status, spend, and metrics. Pro+ tier required.",
    {},
    async () => respond(await api("/influencer-collabs?action=list"))
  );

  server.tool(
    "create_collab",
    "[COLLABS] Create a new influencer collaboration. Tracks partner, platform, campaign, budget, and status through the collab lifecycle.",
    {
      partnerHandle: z.string().describe("Partner's social handle"),
      partnerPlatform: z.enum(["instagram", "threads"]).optional().describe("Platform (default: instagram)"),
      campaignName: z.string().optional().describe("Campaign name"),
      status: z.enum(["outreach", "negotiation", "confirmed", "active", "completed", "cancelled"]).optional().describe("Status (default: outreach)"),
      budget: zNum.optional().describe("Budget in dollars"),
      currency: z.string().optional().describe("Currency code (default: USD)"),
      deliverables: z.string().optional().describe("Expected deliverables description"),
      notes: z.string().optional().describe("Internal notes"),
      outreachTemplate: z.string().optional().describe("Outreach message template"),
      startDate: z.string().optional().describe("Campaign start date (ISO 8601)"),
      endDate: z.string().optional().describe("Campaign end date (ISO 8601)"),
    },
    async ({ partnerHandle, partnerPlatform, campaignName, status, budget, currency, deliverables, notes, outreachTemplate, startDate, endDate }) => {
      return respond(await api("/influencer-collabs?action=create", "POST", {
        partner_handle: partnerHandle,
        partner_platform: partnerPlatform,
        campaign_name: campaignName,
        status, budget, currency, deliverables, notes,
        outreach_template: outreachTemplate,
        start_date: startDate,
        end_date: endDate,
      }));
    }
  );

  server.tool(
    "update_collab",
    "[COLLABS] Update an influencer collaboration — change status, adjust budget, add notes, or link posts.",
    {
      collabId: z.string().describe("Collaboration ID"),
      status: z.enum(["outreach", "negotiation", "confirmed", "active", "completed", "cancelled"]).optional().describe("New status"),
      budget: zNum.optional().describe("Updated budget"),
      deliverables: z.string().optional().describe("Updated deliverables"),
      notes: z.string().optional().describe("Updated notes"),
      startDate: z.string().optional().describe("New start date"),
      endDate: z.string().optional().describe("New end date"),
    },
    async ({ collabId, status, budget, deliverables, notes, startDate, endDate }) => {
      return respond(await api("/influencer-collabs?action=update", "POST", {
        collab_id: collabId,
        status, budget, deliverables, notes,
        start_date: startDate,
        end_date: endDate,
      }));
    }
  );

  server.tool(
    "delete_collab",
    "[COLLABS] Delete an influencer collaboration. Use dryRun=true (default) to preview.",
    {
      collabId: z.string().describe("Collaboration ID"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ collabId, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse("Delete influencer collaboration", { collabId });
      }
      return respond(await api("/influencer-collabs?action=delete", "POST", { collab_id: collabId }));
    }
  );

  server.tool(
    "get_collab_roi",
    "[COLLABS] Get ROI analysis for a collaboration — total reach, engagement, cost per engagement, and linked post performance.",
    {
      collabId: z.string().describe("Collaboration ID"),
    },
    async ({ collabId }) => {
      return respond(await api(`/influencer-collabs?action=roi&collabId=${collabId}`));
    }
  );
};
