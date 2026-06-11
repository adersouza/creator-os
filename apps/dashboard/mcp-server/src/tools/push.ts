import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, dryRunResponse, zBool } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "get_push_vapid_key",
    "Get the public VAPID key used for browser push subscriptions",
    {
      bustCache: zBool.optional().describe("Bypass cache for key rotation checks"),
    },
    async ({ bustCache }) => {
      const params = new URLSearchParams({ action: "vapid-key" });
      if (bustCache) params.set("bust", "1");
      return respond(await api(`/push?${params}`));
    }
  );

  server.tool(
    "subscribe_push_notifications",
    "Register a browser push subscription for the current user",
    {
      subscription: z.any().describe("Browser PushSubscription JSON with endpoint and keys"),
      dryRun: zBool.default(true).describe("Preview subscription (default: true). Must be explicitly set to false to execute."),
    },
    async ({ subscription, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Subscribe push notifications", { subscription });
      return respond(await api("/push?action=subscribe", "POST", { subscription }));
    }
  );

  server.tool(
    "unsubscribe_push_notifications",
    "Remove a browser push subscription for the current user",
    {
      endpoint: z.string().describe("Push subscription endpoint"),
      dryRun: zBool.default(true).describe("Preview unsubscribe (default: true). Must be explicitly set to false to execute."),
    },
    async ({ endpoint, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Unsubscribe push notifications", { endpoint });
      return respond(await api("/push?action=subscribe", "DELETE", { endpoint }));
    }
  );
};
