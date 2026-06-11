import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, success, error, dryRunResponse, zBool, zNum, SESSION_ID } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "check_health",
    "Full system health dashboard: cron jobs, Redis connectivity, Meta API status, dead letter queue, rate limits, crisis detection",
    {},
    async () => respond(await api("/admin/health"))
  );

  server.tool(
    "list_dead_letters",
    "View the dead letter queue — failed background jobs awaiting retry or purge",
    {
      source: z.string().optional().describe("Filter by source (e.g. 'webhook-processor', 'analytics-pipeline')"),
    },
    async ({ source }) => {
      const params = new URLSearchParams();
      if (source) params.set("source", source);
      return respond(await api(`/admin/dead-letters?${params}`));
    }
  );

  server.tool(
    "retry_dead_letter",
    "Retry a specific failed job from the dead letter queue",
    {
      itemId: z.string().describe("Dead letter item ID"),
      source: z.string().describe("Source of the failed job"),
    },
    async ({ itemId, source }) => {
      return respond(await api("/admin/dead-letters", "POST", { action: "retry", itemId, source }));
    }
  );

  server.tool(
    "purge_dead_letters",
    "Purge all dead letters for a source. Use dryRun=true (default) to preview count.",
    {
      source: z.string().optional().describe("Source to purge (omit for all)"),
      dryRun: zBool.default(true).describe("Preview purge (default: true). Must be explicitly set to false to execute."),
    },
    async ({ source, dryRun }) => {
      if (dryRun !== false) {
        const result = await api(`/admin/dead-letters${source ? `?source=${source}` : ""}`);
        if (!result.ok) return error(result.error);
        const data = result.data as { items?: { source?: string }[] } | undefined;
        const items = Array.isArray(data?.items) ? data.items : [];
        const filtered = source ? items.filter((i) => i.source === source) : items;
        return dryRunResponse(`Purge ${filtered.length} dead letter(s) from ${source ?? "all sources"}`, {
          wouldPurge: filtered.length,
          source: source ?? "all",
        });
      }
      return respond(await api("/admin/dead-letters", "POST", {
        action: "purge-all", source,
      }));
    }
  );

  server.tool(
    "get_admin_kpis",
    "Get monthly KPI metrics from the admin dashboard",
    {},
    async () => respond(await api("/admin/monthly-kpi"))
  );

  server.tool(
    "health_ping",
    "Quick health check ping — verifies the API is responsive",
    {},
    async () => respond(await api("/health/ping"))
  );

  server.tool(
    "get_agent_log",
    "Read this agent's tool call history. Use to resume autonomous cycles, detect loops, or audit what was done. Returns entries newest-first.",
    {
      since: z.string().optional().describe("ISO timestamp — only entries after this (e.g. '2026-03-07T00:00:00Z')"),
      limit: zNum.optional().describe("Max entries to return (default 50, max 200)"),
      toolName: z.string().optional().describe("Filter to a specific tool name"),
      sessionId: z.string().optional().describe("Filter to a specific session (omit for all sessions)"),
      currentSession: zBool.optional().describe("If true, only return entries from this session"),
    },
    async ({ since, limit, toolName, sessionId, currentSession }) => {
      const params = new URLSearchParams();
      if (since) params.set("since", since);
      if (limit) params.set("limit", String(limit));
      if (toolName) params.set("tool_name", toolName);
      if (currentSession) params.set("session_id", SESSION_ID);
      else if (sessionId) params.set("session_id", sessionId);
      return respond(await api(`/agent/log?${params}`));
    }
  );

  server.tool(
    "request_human_approval",
    "Pause and request human approval before proceeding with significant actions. Sends a push/email notification. Returns an approvalId — call check_approval_status to poll. Use for: scheduling batches, publishing content, making account changes, or any action with real-world impact.",
    {
      context: z.string().describe("What you want to do and why — shown in the notification (max 2000 chars)"),
      proposedActions: z.array(z.object({
        tool: z.string().describe("Tool name to call"),
        summary: z.string().describe("Human-readable summary of what this call does"),
      })).optional().describe("List of specific tool calls awaiting approval"),
      urgency: z.enum(["low", "medium", "high"]).optional().describe("Notification urgency (default: medium)"),
      expiresInHours: zNum.optional().describe("Hours until auto-expire (default 24, max 168)"),
    },
    async ({ context, proposedActions, urgency, expiresInHours }) => {
      return respond(await api("/agent/approvals", "POST", {
        session_id: SESSION_ID,
        context,
        proposed_actions: proposedActions ?? [],
        urgency: urgency ?? "medium",
        expires_in_hours: expiresInHours ?? 24,
      }));
    }
  );

  server.tool(
    "check_approval_status",
    "Check whether a previously requested human approval has been approved, rejected, or is still pending. Poll this after request_human_approval.",
    {
      approvalId: z.string().describe("The approvalId returned by request_human_approval"),
    },
    async ({ approvalId }) => {
      const params = new URLSearchParams({ status: "all", limit: "50" });
      const result = await api(`/agent/approvals?${params}`);
      if (!result.ok) return respond(result);
      const approvals = (result.data as { approvals?: { id: string; status: string; urgency: string; decided_at?: string; decision_note?: string; expires_at: string }[] })?.approvals ?? [];
      const match = approvals.find((a) => a.id === approvalId);
      if (!match) return success({ status: "not_found", approvalId });
      return success({
        approvalId: match.id,
        status: match.status,
        urgency: match.urgency,
        decidedAt: match.decided_at,
        decisionNote: match.decision_note,
        expiresAt: match.expires_at,
      });
    }
  );

  server.tool(
    "get_publish_cap_status",
    "Check remaining daily publish budget for an account BEFORE calling publish_post or schedule_post. Returns used/remaining/limit. Call this at the start of any publishing phase to avoid wasting a cycle on a 429.",
    {
      accountId: z.string().describe("Account ID to check"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Platform (default: threads)"),
    },
    async ({ accountId, platform }) => {
      const params = new URLSearchParams({ accountId });
      if (platform) params.set("platform", platform);
      return respond(await api(`/agent/cap-status?${params}`));
    }
  );

  server.tool(
    "get_weekly_cycle_state",
    "Get the full agent state for this week: posts published/scheduled, pending approvals, agent activity summary (last 24h), and kill switch status. Call at the start of every autonomous session to resume intelligently.",
    {},
    async () => respond(await api("/agent/weekly-state"))
  );

  server.tool(
    "get_agent_settings",
    "Read agent settings including the kill switch (agent_paused). When agent_paused=true, all agent writes are blocked.",
    {},
    async () => respond(await api("/agent/settings"))
  );

  server.tool(
    "set_agent_paused",
    "Pause or resume the agent. When paused=true, all agent write operations return 503. Unpausing also resets the circuit breaker counters.",
    {
      paused: zBool.describe("true to pause the agent, false to resume"),
    },
    async ({ paused }) => {
      const result = await api("/agent/settings", "PATCH", { agent_paused: paused });
      // Reset circuit breaker counters when unpausing
      if (!paused) {
        await api("/agent/circuit-breaker", "POST").catch(() => {});
      }
      return respond(result);
    }
  );

  server.tool(
    "get_circuit_breaker_status",
    "[SAFETY] Check the automatic circuit breaker that protects against runaway agent behavior. Shows: hourly call count (limit 100), consecutive publish failures (limit 3), and whether the breaker has tripped. If tripped, the agent is auto-paused and you must investigate before unpausing.",
    {},
    async () => respond(await api("/agent/circuit-breaker"))
  );

  server.tool(
    "save_agent_note",
    "[MEMORY] Save a key-value note that persists across sessions. Use to remember patterns, learnings, and insights about accounts (e.g. 'larissa_best_time' → 'Tuesday 7pm outdoor posts 3x engagement'). Notes are scoped globally or per account group.",
    {
      key: z.string().describe("Note key (e.g. 'larissa_best_time', 'hashtag_winners', 'content_pattern_gym')"),
      value: z.string().describe("Note value — what you learned (max 5000 chars)"),
      accountGroupId: z.string().optional().describe("Scope to an account group (omit for global notes)"),
    },
    async ({ key, value, accountGroupId }) => {
      return respond(await api("/agent/notes", "POST", { action: "upsert", key, value, accountGroupId }));
    }
  );

  server.tool(
    "get_agent_notes",
    "[MEMORY] Retrieve saved notes from previous sessions. Call at session start to remember what you learned. Returns all notes sorted by last update.",
    {
      accountGroupId: z.string().optional().describe("Filter to a specific account group (omit for all notes)"),
    },
    async ({ accountGroupId }) => {
      const params = new URLSearchParams();
      if (accountGroupId) params.set("accountGroupId", accountGroupId);
      return respond(await api(`/agent/notes?${params}`));
    }
  );

  server.tool(
    "delete_agent_note",
    "[MEMORY] Delete a saved note by key. Use when a learning is outdated or wrong.",
    {
      key: z.string().describe("Note key to delete"),
      accountGroupId: z.string().optional().describe("Account group scope (omit for global)"),
    },
    async ({ key, accountGroupId }) => {
      return respond(await api("/agent/notes", "POST", { action: "delete", key, accountGroupId }));
    }
  );
};
