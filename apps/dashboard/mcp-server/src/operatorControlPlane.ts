import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import {
  api,
  deriveAgentActionReason,
  dryRunResponse,
  error,
  logAgentAction,
  zBool,
} from "./helpers.js";
import { checkRateLimit, recordSuccess } from "./rateLimiter.js";

export const WRITE_TOOLS = new Set([
  "sync_threads_account",
  "sync_instagram_account",
  "bulk_sync_accounts",
  "bulk_cap_status",
  "ai_generate",
  "ai_copilot",
  "ai_generate_image",
  "ai_generate_single",
  "ai_vision_score",
  "ai_post_autopsy",
  "ai_growth_simulator",
  "ai_feedback",
  "upsert_ai_config",
  "growth_journal_create",
  "log_revenue_snapshot",
  "upsert_auto_post_config",
  "upsert_workspace_config",
  "delete_auto_post_config",
  "toggle_auto_post",
  "sync_auto_post_engagement",
  "toggle_auto_reply",
  "bulk_clear_queue",
  "bulk_clear_all_queues",
  "delete_queue_item",
  "upsert_account_override",
  "delete_account_override",
  "bulk_update_group_configs",
  "bulk_set_content_strategy",
  "retry_queue_item",
  "trigger_queue_fill",
  "override_account_state",
  "promote_auto_post_variant",
  "update_agency_branding",
  "add_competitor",
  "bulk_add_competitors",
  "remove_competitor",
  "bulk_remove_competitors",
  "assign_competitors_to_group",
  "analyze_competitor",
  "use_inspiration_idea",
  "create_account_group",
  "update_account_group",
  "delete_account_group",
  "assign_accounts_to_group",
  "bulk_assign_accounts_to_group",
  "reply_to_message",
  "mark_inbox_message_read",
  "assign_inbox_message",
  "unassign_inbox_message",
  "update_inbox_ai_suggestion",
  "reply_to_ig_comment",
  "hide_ig_comment",
  "private_reply_ig_comment",
  "create_inbox_rule",
  "toggle_inbox_rule",
  "delete_inbox_rule",
  "create_collab",
  "update_collab",
  "delete_collab",
  "send_ig_message",
  "send_ig_media_message",
  "send_ig_quick_replies",
  "send_ig_generic_template",
  "send_ig_message_reaction",
  "send_ig_typing_indicator",
  "create_ig_auto_responder",
  "update_ig_auto_responder",
  "toggle_ig_auto_responder",
  "delete_ig_auto_responder",
  "create_ig_dm_template",
  "update_ig_dm_template",
  "delete_ig_dm_template",
  "set_ig_persistent_menu",
  "delete_ig_persistent_menu",
  "set_ig_ice_breakers",
  "delete_ig_ice_breakers",
  "set_ig_welcome_message",
  "delete_ig_welcome_message",
  "accept_ig_collaboration",
  "decline_ig_collaboration",
  "delete_ig_media",
  "like_ig_media_or_comment",
  "unlike_ig_media_or_comment",
  "toggle_ig_comments",
  "delete_ig_comment",
  "bulk_delete_posts",
  "bulk_hide_ig_comments",
  "bulk_delete_ig_comments",
  "bulk_reply_ig_comments",
  "bulk_toggle_evergreen",
  "bulk_delete_queue_items",
  "bulk_reschedule_posts",
  "bulk_toggle_ig_comments",
  "bulk_reply_to_messages",
  "bulk_delete_ig_media",
  "create_link_page",
  "update_link_page",
  "delete_link_page",
  "add_bio_link",
  "update_bio_link",
  "reorder_bio_links",
  "delete_bio_link",
  "shorten_url",
  "create_listening_alert",
  "update_listening_alert",
  "delete_listening_alert",
  "upload_media",
  "bulk_register_media",
  "share_media_folder",
  "refresh_media_urls",
  "publish_threads_post",
  "schedule_threads_post",
  "publish_instagram_post",
  "schedule_instagram_post",
  "save_draft",
  "update_draft",
  "delete_post",
  "reschedule_post",
  "import_posts",
  "approve_post",
  "reject_post",
  "repost_threads_post",
  "refresh_threads_post_metrics",
  "toggle_evergreen",
  "update_evergreen_settings",
  "bulk_schedule",
  "bulk_schedule_groups",
  "bulk_cancel_scheduled",
  "create_draft_folder",
  "update_draft_folder",
  "delete_draft_folder",
  "move_drafts_to_folder",
  "create_template",
  "delete_template",
  "promote_variant",
  "dismiss_recommendation",
  "bulk_apply_quick_wins",
  "generate_report",
  "generate_saved_report",
  "update_saved_report",
  "send_saved_report",
  "create_smart_link",
  "update_smart_link",
  "enhance_smart_link",
  "delete_smart_link",
  "set_content_strategy",
  "retry_dead_letter",
  "purge_dead_letters",
  "request_human_approval",
  "set_agent_paused",
  "save_agent_note",
  "delete_agent_note",
  "send_team_invite",
  "set_trending_config",
  "generate_composer_variants",
  "promote_composer_variant",
  "create_composer_diff",
  "resolve_composer_diff",
  "update_voice_context_file",
  "log_composer_ai_action",
  "create_saved_view",
  "delete_saved_view",
  "create_tag",
  "delete_tag",
  "assign_tag_to_posts",
  "unassign_tag_from_posts",
  "create_user_webhook",
  "test_user_webhook",
  "delete_user_webhook",
  "set_data_contribution_preference",
  "request_user_data_export",
  "claim_beta_spot",
  "submit_beta_feedback",
  "create_developer_api_key",
  "update_developer_api_key",
  "delete_developer_api_key",
  "run_onboarding_instant_analysis",
  "subscribe_push_notifications",
  "unsubscribe_push_notifications",
  "set_business_goals",
  "set_agent_policy",
  "request_typed_approval",
  "lock_high_risk_actions",
  "update_operator_task",
  "request_operator_approval",
  "execute_operator_action",
]);

export const HIGH_RISK_LOCK_EXEMPT_TOOLS = new Set([
  "set_business_goals",
  "set_agent_policy",
  "request_typed_approval",
  "request_operator_approval",
  "lock_high_risk_actions",
  "set_agent_paused",
  "save_agent_note",
  "delete_agent_note",
]);

export interface OperatorActionManifestEntry {
  toolName: string;
  riskLevel: "low" | "medium" | "high" | "critical";
  sideEffectType: "none" | "ai_generation" | "content_write" | "external_publish" | "settings_write" | "destructive";
  requiresApproval: boolean;
  requiresIdempotencyKey: boolean;
  supportsDryRun: boolean;
  hostedAvailable: boolean;
  rollbackSupport: "none" | "compensating_action" | "delete_or_revert";
  compensationActionName?: string;
  compensationDescription: string;
  compensationRequiresApproval: boolean;
  rollbackWindowHours?: number;
}

export function getOperatorActionManifest(): OperatorActionManifestEntry[] {
  return [...WRITE_TOOLS].sort().map((toolName) => ({
    toolName,
    ...classifyWriteTool(toolName),
    supportsDryRun: true,
    hostedAvailable: true,
  }));
}

export function installOperatorControlPlane(target: McpServer) {
  const originalTool = target.tool.bind(target) as (...args: unknown[]) => unknown;
  const toolHost = target as unknown as { tool: (...args: unknown[]) => unknown };

  toolHost.tool = (...args: unknown[]) => {
    const handlerIndex = findHandlerIndex(args);
    if (handlerIndex === -1) return originalTool(...args);

    const toolName = String(args[0]);
    const handler = args[handlerIndex] as (...handlerArgs: unknown[]) => Promise<unknown>;
    const isWriteTool = WRITE_TOOLS.has(toolName);
    if (isWriteTool) addControlPlaneParams(args);

    if ((handler as { __agentLoggingInstalled?: boolean }).__agentLoggingInstalled) {
      return originalTool(...args);
    }

    const wrappedHandler = async (...handlerArgs: unknown[]) => {
      const rateCheck = checkRateLimit();
      if (rateCheck) {
        return error({
          code: "rate_limit",
          message: rateCheck.reason,
          status: 429,
          retryAfterMs: rateCheck.waitMs,
        });
      }

      const start = Date.now();
      const params = handlerParams(handlerArgs[0]);

      try {
        if (isWriteTool && params.dryRun !== false) {
          const response = dryRunResponse(`Would execute ${toolName}`, omitControlParams(params));
          logAgentAction(
            toolName,
            params,
            response,
            Date.now() - start,
            deriveAgentActionReason(toolName, params, response),
          );
          return response;
        }

        if (
          isWriteTool &&
          !HIGH_RISK_LOCK_EXEMPT_TOOLS.has(toolName) &&
          await highRiskActionsLocked()
        ) {
          return error({
            code: "forbidden",
            message: "High-risk MCP writes are locked by business_policy. Keep the call in dryRun mode or unlock with an approved policy change.",
            status: 403,
          });
        }

        if (
          isWriteTool &&
          !HIGH_RISK_LOCK_EXEMPT_TOOLS.has(toolName) &&
          (typeof params.approvalId === "string" || await approvalBindingRequired())
        ) {
          if (typeof params.approvalId !== "string" || !params.approvalId) {
            return error({
              code: "forbidden",
              message: "approvalId is required by business_policy.enforceApprovalBinding for this write.",
              status: 403,
            });
          }
          const approval = await verifyBoundApproval(params.approvalId, toolName, omitControlParams(params));
          if (!approval.ok) return error(approval.error);
        }

        const response = await handler(...handlerArgs);
        if (!isToolErrorResponse(response)) recordSuccess();
        logAgentAction(
          toolName,
          params,
          response as Parameters<typeof logAgentAction>[2],
          Date.now() - start,
          deriveAgentActionReason(toolName, params, response as Parameters<typeof deriveAgentActionReason>[2]),
        );
        return response;
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        const response = {
          ok: false as const,
          error: { code: "server_error" as const, message, status: 500 },
        };
        logAgentAction(
          toolName,
          params,
          response,
          Date.now() - start,
          deriveAgentActionReason(toolName, params, response),
        );
        return error(response.error);
      }
    };

    (wrappedHandler as { __agentLoggingInstalled?: boolean }).__agentLoggingInstalled = true;
    args[handlerIndex] = wrappedHandler;
    return originalTool(...args);
  };
}

function classifyWriteTool(toolName: string): Omit<OperatorActionManifestEntry, "toolName" | "supportsDryRun" | "hostedAvailable"> {
  const compensation = classifyCompensation(toolName);
  if (/publish|schedule|reply|send_|message|like_|unlike_|repost/.test(toolName)) {
    return {
      riskLevel: "critical",
      sideEffectType: "external_publish",
      requiresApproval: true,
      requiresIdempotencyKey: true,
      ...compensation,
    };
  }
  if (/delete|purge|remove|clear/.test(toolName)) {
    return {
      riskLevel: "high",
      sideEffectType: "destructive",
      requiresApproval: true,
      requiresIdempotencyKey: true,
      ...compensation,
    };
  }
  if (/config|policy|pause|lock|key|webhook|group|tag|override|template|view/.test(toolName)) {
    return {
      riskLevel: "high",
      sideEffectType: "settings_write",
      requiresApproval: true,
      requiresIdempotencyKey: true,
      ...compensation,
    };
  }
  if (/ai_|generate|vision|autopsy/.test(toolName)) {
    return {
      riskLevel: "medium",
      sideEffectType: "ai_generation",
      requiresApproval: false,
      requiresIdempotencyKey: false,
      ...compensation,
    };
  }
  return {
    riskLevel: "medium",
    sideEffectType: "content_write",
    requiresApproval: false,
    requiresIdempotencyKey: true,
    ...compensation,
  };
}

function classifyCompensation(toolName: string): Pick<
  OperatorActionManifestEntry,
  "rollbackSupport" | "compensationActionName" | "compensationDescription" | "compensationRequiresApproval" | "rollbackWindowHours"
> {
  if (/^publish_|^schedule_|bulk_schedule|import_posts/.test(toolName)) {
    return {
      rollbackSupport: "compensating_action",
      compensationActionName: "delete_post",
      compensationDescription: "Use an approved delete/cancel action for the created or scheduled post. Published external content may remain visible until the platform accepts deletion.",
      compensationRequiresApproval: true,
      rollbackWindowHours: 24,
    };
  }

  if (/reschedule/.test(toolName)) {
    return {
      rollbackSupport: "compensating_action",
      compensationActionName: "reschedule_post",
      compensationDescription: "Create a new approved reschedule intent using the previous scheduled timestamp from the audit log.",
      compensationRequiresApproval: true,
      rollbackWindowHours: 24 * 7,
    };
  }

  if (/reply|send_ig_message|send_ig_media_message|send_ig_quick_replies|send_ig_generic_template/.test(toolName)) {
    return {
      rollbackSupport: "compensating_action",
      compensationDescription: "Replies and messages cannot be reliably unsent through the API; create a reviewed follow-up correction or mark the conversation for human handling.",
      compensationRequiresApproval: true,
      rollbackWindowHours: 24,
    };
  }

  if (/like_|unlike_|repost/.test(toolName)) {
    return {
      rollbackSupport: "compensating_action",
      compensationActionName: toolName.startsWith("like_") ? toolName.replace(/^like_/, "unlike_") : undefined,
      compensationDescription: "Use the opposite engagement action where the official API supports it; otherwise route to manual review.",
      compensationRequiresApproval: true,
      rollbackWindowHours: 24,
    };
  }

  if (/delete|purge|remove|clear/.test(toolName)) {
    return {
      rollbackSupport: "none",
      compensationDescription: "Destructive removals are not automatically reversible; recovery depends on backups, audit payloads, or recreating the entity through a new approved action.",
      compensationRequiresApproval: true,
    };
  }

  if (/config|policy|pause|lock|key|webhook|group|tag|override|template|view/.test(toolName)) {
    return {
      rollbackSupport: "delete_or_revert",
      compensationDescription: "Revert by submitting a new approved settings intent with the previous values recorded in the audit log.",
      compensationRequiresApproval: true,
      rollbackWindowHours: 24 * 7,
    };
  }

  if (/ai_|generate|vision|autopsy/.test(toolName)) {
    return {
      rollbackSupport: "none",
      compensationDescription: "Generation-only actions have no external side effect; discard the output or mark it rejected.",
      compensationRequiresApproval: false,
    };
  }

  return {
    rollbackSupport: "delete_or_revert",
    compensationDescription: "Revert by creating a new approved intent using the previous values from the audit trail.",
    compensationRequiresApproval: false,
    rollbackWindowHours: 24 * 7,
  };
}

function findHandlerIndex(args: unknown[]): number {
  for (let i = args.length - 1; i >= 0; i--) {
    if (typeof args[i] === "function") return i;
  }
  return -1;
}

function addControlPlaneParams(args: unknown[]) {
  const schema = args[2];
  if (!schema || typeof schema !== "object" || Array.isArray(schema)) return;
  const shape = schema as Record<string, unknown>;
  if (!("dryRun" in shape)) {
    shape.dryRun = zBool.default(true).describe(
      "Preview without executing (default: true). Must be explicitly set to false to execute."
    );
  }
  if (!("approvalId" in shape)) {
    shape.approvalId = z.string().optional().describe(
      "Approved agent_approvals ID for executing high-risk writes. Required when business_policy.enforceApprovalBinding is true."
    );
  }
}

function handlerParams(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function omitControlParams(params: Record<string, unknown>): Record<string, unknown> {
  const { dryRun: _dryRun, approvalId: _approvalId, ...rest } = params;
  return rest;
}

function isToolErrorResponse(value: unknown): boolean {
  return !!(
    value &&
    typeof value === "object" &&
    "isError" in value &&
    (value as { isError?: unknown }).isError === true
  );
}

async function highRiskActionsLocked(): Promise<boolean> {
  const policy = await getBusinessPolicy();
  return policy.highRiskActionsLocked === true;
}

async function approvalBindingRequired(): Promise<boolean> {
  const policy = await getBusinessPolicy();
  return policy.enforceApprovalBinding === true;
}

async function getBusinessPolicy(): Promise<Record<string, unknown>> {
  const result = await api<{ notes?: Array<{ key?: string; value?: string }> }>("/agent/notes");
  if (!result.ok) return {};
  const note = result.data.notes?.find((entry) => entry.key === "business_policy");
  if (!note?.value) return {};
  try {
    return JSON.parse(note.value) as Record<string, unknown>;
  } catch {
    return {};
  }
}

async function verifyBoundApproval(
  approvalId: string,
  toolName: string,
  params: Record<string, unknown>,
): Promise<{ ok: true } | { ok: false; error: { code: "forbidden" | "not_found" | "invalid_input"; message: string; status: number } }> {
  const result = await api<{
    approvals?: Array<{
      id?: string;
      status?: string;
      expires_at?: string;
      proposed_actions?: unknown;
    }>;
  }>("/agent/approvals?status=all&limit=100");
  if (!result.ok) {
    return {
      ok: false,
      error: { code: "forbidden", message: "Could not verify approval before executing write.", status: 403 },
    };
  }

  const approval = result.data.approvals?.find((entry) => entry.id === approvalId);
  if (!approval) {
    return { ok: false, error: { code: "not_found", message: `Approval ${approvalId} was not found.`, status: 404 } };
  }
  if (approval.status !== "approved") {
    return {
      ok: false,
      error: { code: "forbidden", message: `Approval ${approvalId} is ${approval.status ?? "not approved"}.`, status: 403 },
    };
  }
  if (approval.expires_at && new Date(approval.expires_at).getTime() < Date.now()) {
    return { ok: false, error: { code: "forbidden", message: `Approval ${approvalId} has expired.`, status: 403 } };
  }

  const actions = Array.isArray(approval.proposed_actions) ? approval.proposed_actions : [];
  const normalizedParams = stableStringify(normalizeApprovalParams(params));
  const matched = actions.some((action) => {
    if (!action || typeof action !== "object") return false;
    const candidate = action as Record<string, unknown>;
    if (candidate.tool !== toolName && candidate.toolName !== toolName) return false;
    const rawParams = candidate.params ?? candidate.params_json ?? candidate.arguments;
    if (!rawParams || typeof rawParams !== "object" || Array.isArray(rawParams)) return false;
    return stableStringify(normalizeApprovalParams(rawParams as Record<string, unknown>)) === normalizedParams;
  });

  if (!matched) {
    return {
      ok: false,
      error: {
        code: "forbidden",
        message: `Approval ${approvalId} does not exactly match ${toolName} parameters.`,
        status: 403,
      },
    };
  }

  return { ok: true };
}

function normalizeApprovalParams(params: Record<string, unknown>): Record<string, unknown> {
  const normalized: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(params).sort(([a], [b]) => a.localeCompare(b))) {
    if (key === "dryRun" || key === "approvalId") continue;
    if (value === undefined) continue;
    normalized[key] = value;
  }
  return normalized;
}

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== undefined)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => `${JSON.stringify(k)}:${stableStringify(v)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}
