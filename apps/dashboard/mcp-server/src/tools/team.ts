import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, zNum } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "send_team_invite",
    "Send a team invitation email to a new workspace member. Pro tier required.",
    {
      workspaceName: z.string().describe("Workspace name"),
      inviteCode: z.string().describe("Invite code"),
      recipientEmail: z.string().describe("Email address to invite"),
      role: z.string().optional().describe("Role (default: member)"),
    },
    async ({ workspaceName, inviteCode, recipientEmail, role }) => {
      return respond(await api("/team?action=send-invite-email", "POST", {
        workspaceName, inviteCode, recipientEmail, role,
      }));
    }
  );

  server.tool(
    "get_team_stats",
    "Get team member performance stats (posts created, engagement, etc.)",
    {
      workspaceId: z.string().describe("Workspace ID"),
      days: zNum.optional().describe("Period: 7, 30, or 0 for all time (default: 30)"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Platform filter"),
    },
    async ({ workspaceId, days, platform }) => {
      const params = new URLSearchParams({ workspace_id: workspaceId });
      if (days !== undefined) params.set("days", String(days));
      if (platform) params.set("platform", platform);
      return respond(await api(`/team?action=team-stats&${params}`));
    }
  );
};
