import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, dryRunResponse, zBool } from "../helpers.js";

const webhookEvent = z.enum([
  "post_published",
  "post_failed",
  "account_reconnect_needed",
  "report_sent",
]);

export const register: ToolRegistrar = (server) => {
  server.tool(
    "list_user_webhooks",
    "List configured outbound user webhooks",
    {},
    async () => respond(await api("/settings?action=user-webhooks"))
  );

  server.tool(
    "create_user_webhook",
    "Create an outbound webhook subscription. Returns the signing secret once.",
    {
      url: z.string().describe("Webhook destination URL"),
      events: z.array(webhookEvent).describe("Events to send"),
      dryRun: zBool.default(true).describe("Preview creation (default: true). Must be explicitly set to false to execute."),
    },
    async ({ url, events, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Create user webhook", { url, events });
      return respond(await api("/settings?action=user-webhooks", "POST", { url, events }));
    }
  );

  server.tool(
    "test_user_webhook",
    "Send a test event to a configured outbound webhook",
    {
      id: z.string().describe("Webhook ID"),
      dryRun: zBool.default(true).describe("Preview test send (default: true). Must be explicitly set to false to execute."),
    },
    async ({ id, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Send test webhook event", { id });
      return respond(await api("/settings?action=user-webhooks", "POST", { mode: "test", id }));
    }
  );

  server.tool(
    "delete_user_webhook",
    "Delete an outbound webhook subscription",
    {
      id: z.string().describe("Webhook ID"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ id, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Delete user webhook", { id });
      return respond(await api("/settings?action=user-webhooks", "DELETE", { id }));
    }
  );
};
