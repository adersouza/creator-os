import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "list_accounts",
    "List all connected social accounts (Threads + Instagram) for the authenticated user",
    {},
    async () => respond(await api("/accounts"))
  );

  server.tool(
    "sync_threads_account",
    "Trigger a manual sync for a Threads account (refreshes metrics, posts, profile from Meta API)",
    {
      accountId: z.string().describe("Threads account ID"),
    },
    async ({ accountId }) => respond(await api("/sync/threads-account", "POST", { accountId }))
  );

  server.tool(
    "sync_instagram_account",
    "Trigger a manual sync for an Instagram account (refreshes metrics, posts, profile from Meta API)",
    {
      accountId: z.string().describe("Instagram account ID"),
    },
    async ({ accountId }) => respond(await api("/sync/ig-account", "POST", { accountId }))
  );

  server.tool(
    "bulk_sync_accounts",
    "Sync multiple accounts in one call via QStash fan-out. Accepts either a groupId (syncs all accounts in that group) or explicit accountIds/igAccountIds arrays. " +
    "Returns a jobId for async progress tracking — syncs run in background via QStash, not blocking. " +
    "Cap: 200 accounts per request. Circuit breaker counts this as 1 call regardless of account count.",
    {
      groupId: z.string().optional().describe("Sync all accounts in this group (alternative to accountIds)"),
      accountIds: z.array(z.string()).optional().describe("Specific Threads account IDs to sync"),
      igAccountIds: z.array(z.string()).optional().describe("Specific Instagram account IDs to sync"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Filter to one platform (default: both)"),
    },
    async ({ groupId, accountIds, igAccountIds, platform }) => {
      return respond(await api("/analytics?action=bulk-sync", "POST", {
        groupId, accountIds, igAccountIds, platform,
      }, 30_000));
    }
  );

  server.tool(
    "bulk_cap_status",
    "Check daily publish cap status for multiple accounts in one call. Returns per-account used/remaining/limit and a groupSummary " +
    "with totalRemaining, accountsAtLimit, accountsWithCapacity. Use BEFORE scheduling to know which accounts have capacity. " +
    "Accepts groupId (checks all accounts in group) or explicit accountIds + platform. Cap: 200 accounts per request.",
    {
      groupId: z.string().optional().describe("Check all accounts in this group"),
      accountIds: z.array(z.string()).optional().describe("Specific account IDs to check"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Platform (required when using accountIds, optional with groupId)"),
    },
    async ({ groupId, accountIds, platform }) => {
      return respond(await api("/accounts/bulk-cap-status", "POST", {
        groupId, accountIds, platform,
      }));
    }
  );

  server.tool(
    "check_subscription",
    "Check current subscription tier, trial status, and billing info",
    {},
    async () => respond(await api("/subscription?action=check-trial", "POST", {}))
  );

  server.tool(
    "audit_bios",
    "Audit account bios across the network. Reports which accounts have missing bios, missing CTAs (snap for Threads, link.me for IG), or wrong CTAs. " +
    "Per-group bio templates can be set via bio_template JSONB on account_groups (required_patterns array of regex strings). " +
    "Returns summary counts + per-account detail with status: ok, missing, no_cta, wrong_cta.",
    {
      groupId: z.string().optional().describe("Filter to a specific account group"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Filter to one platform (default: both)"),
    },
    async ({ groupId, platform }) => {
      const params = new URLSearchParams();
      params.set("action", "bio-audit");
      if (groupId) params.set("groupId", groupId);
      if (platform) params.set("platform", platform);
      return respond(await api(`/accounts?${params.toString()}`));
    }
  );
};
