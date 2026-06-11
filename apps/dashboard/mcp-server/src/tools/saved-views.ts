import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, dryRunResponse, zBool } from "../helpers.js";

const savedViewScope = z.enum(["analytics"]);

export const register: ToolRegistrar = (server) => {
  server.tool(
    "list_saved_views",
    "List saved analytics filter views for the current user",
    {
      scope: savedViewScope.optional().describe("Saved view scope (default: analytics)"),
    },
    async ({ scope }) => {
      const params = new URLSearchParams();
      if (scope) params.set("scope", scope);
      return respond(await api(`/saved-views?${params}`));
    }
  );

  server.tool(
    "create_saved_view",
    "Create a saved analytics filter view",
    {
      name: z.string().describe("Saved view name"),
      filters: z.any().describe("Analytics filters JSON object"),
      scope: savedViewScope.optional().describe("Saved view scope (default: analytics)"),
      dryRun: zBool.default(true).describe("Preview creation (default: true). Must be explicitly set to false to execute."),
    },
    async ({ name, filters, scope, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Create saved analytics view", { name, filters, scope });
      return respond(await api("/saved-views", "POST", { name, filters, scope }));
    }
  );

  server.tool(
    "delete_saved_view",
    "Delete a saved analytics filter view",
    {
      id: z.string().describe("Saved view ID"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ id, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Delete saved analytics view", { id });
      const params = new URLSearchParams({ id });
      return respond(await api(`/saved-views?${params}`, "DELETE"));
    }
  );
};
