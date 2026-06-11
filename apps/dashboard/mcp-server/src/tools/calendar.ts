import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, zNum } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "get_calendar_portfolio",
    "Get the 7-day portfolio scheduling matrix with account health and scheduled post density",
    {},
    async () => respond(await api("/calendar?action=portfolio"))
  );

  server.tool(
    "parse_calendar_command",
    "Parse a natural-language calendar scheduling command into structured scheduling intent",
    {
      text: z.string().describe("Natural-language scheduling instruction"),
      context: z.any().optional().describe("Optional context object from the current calendar view"),
    },
    async ({ text, context }) => {
      return respond(await api("/calendar?action=parse-command", "POST", { text, context }, 30_000));
    }
  );

  server.tool(
    "get_calendar_window",
    "List scheduled posts for an account or account group over a calendar window",
    {
      accountId: z.string().optional().describe("Filter to one account ID"),
      accountGroupId: z.string().optional().describe("Filter to one account group ID"),
      start: z.string().optional().describe("Window start ISO datetime"),
      end: z.string().optional().describe("Window end ISO datetime"),
      limit: zNum.optional().describe("Max posts to return (default API behavior if omitted)"),
    },
    async ({ accountId, accountGroupId, start, end, limit }) => {
      const params = new URLSearchParams();
      if (accountId) params.set("accountId", accountId);
      if (accountGroupId) params.set("accountGroupId", accountGroupId);
      if (start) params.set("start", start);
      if (end) params.set("end", end);
      if (limit) params.set("limit", String(limit));
      return respond(await api(`/posts?status=scheduled&${params}`));
    }
  );
};
