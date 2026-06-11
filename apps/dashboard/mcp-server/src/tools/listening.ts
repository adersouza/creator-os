import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, dryRunResponse, zBool, zNum } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "list_listening_alerts",
    "List all social listening keyword alerts",
    {},
    async () => respond(await api("/listening/alerts"))
  );

  server.tool(
    "create_listening_alert",
    "Create a keyword monitoring alert. Triggers when the keyword is mentioned in comments/mentions.",
    {
      keyword: z.string().describe("Keyword or phrase to monitor (1-200 chars)"),
      alertType: z.enum(["spike", "threshold"]).optional().describe("Alert type (default: spike)"),
      thresholdValue: zNum.optional().describe("Threshold count to trigger (1-10000, default: 10)"),
      workspaceId: z.string().optional().describe("Workspace ID to scope the alert"),
    },
    async ({ keyword, alertType, thresholdValue, workspaceId }) => {
      return respond(await api("/listening/alerts", "POST", {
        keyword, alert_type: alertType, threshold_value: thresholdValue, workspace_id: workspaceId,
      }));
    }
  );

  server.tool(
    "update_listening_alert",
    "Update a listening alert's keyword, threshold, or active state",
    {
      alertId: z.string().describe("Alert ID"),
      keyword: z.string().optional().describe("New keyword"),
      thresholdValue: zNum.optional().describe("New threshold (1-10000)"),
      isActive: zBool.optional().describe("Enable or disable"),
    },
    async ({ alertId, keyword, thresholdValue, isActive }) => {
      return respond(await api(`/listening/alerts?id=${alertId}`, "PUT", {
        keyword, threshold_value: thresholdValue, is_active: isActive,
      } as Record<string, unknown>));
    }
  );

  server.tool(
    "delete_listening_alert",
    "Delete a social listening alert. Use dryRun=true (default) to preview.",
    {
      alertId: z.string().describe("Alert ID"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ alertId, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse("Delete social listening alert", { alertId });
      }
      return respond(await api(`/listening/alerts?id=${alertId}`, "DELETE"));
    }
  );
};
