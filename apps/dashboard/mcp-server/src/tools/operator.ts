import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, dryRunResponse, respond, zBool } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "get_operator_manifest",
    "List operator control-plane actions, risk levels, and approval requirements.",
    {},
    async () => respond(await api("/operator?action=manifest")),
  );

  server.tool(
    "get_operator_snapshot",
    "Get the current operator queue: tasks, approvals, failed posts, decisions, and next actions.",
    {},
    async () => respond(await api("/operator?action=snapshot")),
  );

  server.tool(
    "update_operator_task",
    "Update an operator task status. Defaults to dry-run and requires explicit dryRun=false to execute.",
    {
      id: z.string().uuid().describe("Operator task ID"),
      status: z.enum(["open", "assigned", "in_progress", "snoozed", "resolved", "ignored"]),
      resolutionReason: z.string().optional().nullable(),
      snoozedUntil: z.string().optional().nullable(),
      dryRun: zBool.default(true),
    },
    async ({ id, status, resolutionReason, snoozedUntil, dryRun }) => {
      const payload = {
        id,
        status,
        resolution_reason: resolutionReason,
        snoozed_until: snoozedUntil,
      };
      if (dryRun !== false) return dryRunResponse("Update operator task", payload);
      return respond(await api("/operator?action=tasks", "PATCH", payload));
    },
  );

  server.tool(
    "dry_run_operator_action",
    "Create an operator dry-run intent for a risky action before requesting human approval.",
    {
      actionName: z.string().min(1).max(120),
      payload: z.record(z.string(), z.unknown()).default({}),
      accountId: z.string().optional().nullable(),
      groupId: z.string().optional().nullable(),
      workspaceId: z.string().optional().nullable(),
      riskLevel: z.enum(["low", "medium", "high", "critical"]).default("medium"),
      expiresInHours: z.number().int().min(1).max(168).default(24),
    },
    async ({ actionName, payload, accountId, groupId, workspaceId, riskLevel, expiresInHours }) =>
      respond(await api("/operator?action=dry-run", "POST", {
        action_name: actionName,
        payload,
        account_id: accountId,
        group_id: groupId,
        workspace_id: workspaceId,
        risk_level: riskLevel,
        expires_in_hours: expiresInHours,
      })),
  );

  server.tool(
    "request_operator_approval",
    "Create a human approval request bound to an exact dry-run operator intent.",
    {
      intentId: z.string().uuid(),
      context: z.string().min(1).max(2000).optional(),
      urgency: z.enum(["low", "medium", "high"]).optional(),
      expiresInHours: z.number().int().min(1).max(168).optional(),
    },
    async ({ intentId, context, urgency, expiresInHours }) =>
      respond(await api("/operator?action=request-approval", "POST", {
        intent_id: intentId,
        context,
        urgency,
        expires_in_hours: expiresInHours,
      })),
  );

  server.tool(
    "execute_operator_action",
    "Execute an approved operator action. Requires an existing approval ID.",
    {
      intentId: z.string().uuid(),
      approvalId: z.string().uuid(),
    },
    async ({ intentId, approvalId }) =>
      respond(await api("/operator?action=execute", "POST", {
        intent_id: intentId,
        approval_id: approvalId,
      })),
  );
};
