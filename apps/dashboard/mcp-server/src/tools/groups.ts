import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, dryRunResponse, zBool } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "list_account_groups",
    "List all account groups with account counts (Threads + Instagram). Use before create/delete/assign to see current state.",
    {},
    async () => respond(await api("/agent/groups"))
  );

  server.tool(
    "create_account_group",
    "Create a new account group. After creating, use assign_accounts_to_group to add accounts, then set_content_strategy to configure the posting strategy.",
    {
      name: z.string().describe("Group name (e.g. 'Stacey', 'Larissa', 'Test Batch A')"),
      voiceProfile: z.string().optional().describe("Writing style/voice description for this group"),
    },
    async ({ name, voiceProfile }) => {
      return respond(await api("/agent/groups", "POST", { action: "create", name, voiceProfile }));
    }
  );

  server.tool(
    "update_account_group",
    "Update a group's name or voice profile. Use to rename or adjust the persona description.",
    {
      groupId: z.string().describe("Group ID to update"),
      name: z.string().optional().describe("New group name"),
      voiceProfile: z.string().optional().describe("New voice/persona description"),
    },
    async ({ groupId, name, voiceProfile }) => {
      return respond(await api("/agent/groups", "PATCH", { action: "update", groupId, name, voiceProfile }));
    }
  );

  server.tool(
    "delete_account_group",
    "Delete an account group. All accounts in the group are moved to ungrouped first. Use dryRun=true (default) to preview.",
    {
      groupId: z.string().describe("Group ID to delete"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ groupId, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse("Delete account group (accounts will be ungrouped)", { groupId });
      }
      return respond(await api("/agent/groups", "DELETE", { action: "delete", groupId }));
    }
  );

  server.tool(
    "assign_accounts_to_group",
    "Assign one or more accounts to a group. Pass groupId=null to unassign (move to ungrouped). Specify platform to target the correct table.",
    {
      accountIds: z.array(z.string()).min(1).describe("Account IDs to assign"),
      platform: z.enum(["threads", "instagram"]).describe("Platform the accounts belong to"),
      groupId: z.string().nullable().describe("Target group ID, or null to unassign"),
    },
    async ({ accountIds, platform, groupId }) => {
      return respond(await api("/agent/groups", "POST", { action: "assign", accountIds, platform, groupId }));
    }
  );

  server.tool(
    "bulk_assign_accounts_to_group",
    "Assign up to 200 accounts to a group in one call with per-account success/failure reporting. Use instead of assign_accounts_to_group for large batches to avoid circuit-breaker trips.",
    {
      accountIds: z.array(z.string()).min(1).describe("Account IDs to assign (max 200)"),
      platform: z.enum(["threads", "instagram"]).describe("Platform the accounts belong to"),
      groupId: z.string().nullable().describe("Target group ID, or null to unassign"),
    },
    async ({ accountIds, platform, groupId }) => {
      return respond(await api("/agent/groups", "POST", { action: "bulk-assign", accountIds, platform, groupId }, 60_000));
    }
  );
};
