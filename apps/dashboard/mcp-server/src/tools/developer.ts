import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, dryRunResponse, zBool } from "../helpers.js";

const apiScope = z.enum(["read", "write", "admin"]);

export const register: ToolRegistrar = (server) => {
  server.tool(
    "list_developer_api_keys",
    "List developer API keys for the current user",
    {},
    async () => respond(await api("/developer?action=keys"))
  );

  server.tool(
    "create_developer_api_key",
    "Create a developer API key. Requires step-up auth in the web API and returns the raw key once.",
    {
      name: z.string().describe("Key name"),
      scopes: z.array(apiScope).optional().describe("Scopes (default: read)"),
      expiresAt: z.string().optional().describe("Optional expiry ISO timestamp"),
      dryRun: zBool.default(true).describe("Preview key creation (default: true). Must be explicitly set to false to execute."),
    },
    async ({ name, scopes, expiresAt, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Create developer API key", { name, scopes, expiresAt });
      return respond(await api("/developer?action=keys", "POST", {
        name,
        scopes,
        expires_at: expiresAt,
      }));
    }
  );

  server.tool(
    "update_developer_api_key",
    "Update a developer API key. Requires step-up auth in the web API.",
    {
      id: z.string().describe("API key ID"),
      name: z.string().optional().describe("New key name"),
      scopes: z.array(apiScope).optional().describe("Replacement scopes"),
      isActive: zBool.optional().describe("Whether the key is active"),
      dryRun: zBool.default(true).describe("Preview key update (default: true). Must be explicitly set to false to execute."),
    },
    async ({ id, name, scopes, isActive, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Update developer API key", { id, name, scopes, isActive });
      const params = new URLSearchParams({ action: "keys", id });
      return respond(await api(`/developer?${params}`, "PUT", {
        name,
        scopes,
        is_active: isActive,
      }));
    }
  );

  server.tool(
    "delete_developer_api_key",
    "Delete a developer API key. Requires step-up auth in the web API.",
    {
      id: z.string().describe("API key ID"),
      dryRun: zBool.default(true).describe("Preview key deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ id, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Delete developer API key", { id });
      const params = new URLSearchParams({ action: "keys", id });
      return respond(await api(`/developer?${params}`, "DELETE"));
    }
  );

  server.tool(
    "get_openapi_spec",
    "Get the public OpenAPI specification for API-key integrations",
    {},
    async () => respond(await api("/developer?action=openapi"))
  );
};
