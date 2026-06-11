import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, success, dryRunResponse, zBool, zNum, SESSION_ID } from "../helpers.js";

const GOALS_KEY = "business_goals";
const POLICY_KEY = "business_policy";
const RUNBOOK_KEY = "business_runbook_state";

const approvalType = z.enum([
  "publish_batch",
  "spend_money",
  "change_automation",
  "delete_content",
  "message_users",
  "alter_branding",
  "invite_team",
  "revoke_keys",
  "data_export",
  "other",
]);

async function saveNote(key: string, value: unknown) {
  return api("/agent/notes", "POST", {
    action: "upsert",
    key,
    value: typeof value === "string" ? value : JSON.stringify(value, null, 2),
  });
}

async function getNotes() {
  const result = await api<{ notes?: Array<{ key?: string; value?: string; updated_at?: string }> }>("/agent/notes");
  if (!result.ok) return result;
  return {
    ok: true as const,
    data: {
      notes: result.data.notes ?? [],
      byKey: Object.fromEntries((result.data.notes ?? []).map((note) => [note.key, note])),
    },
  };
}

function parseNote(note: { value?: string; updated_at?: string } | undefined, fallback: unknown) {
  if (!note?.value) return fallback;
  try {
    return JSON.parse(note.value);
  } catch {
    return note.value;
  }
}

async function collectBrief(days: number, accountGroupId?: string) {
  const revenueParams = new URLSearchParams();
  revenueParams.set("days", String(days));
  if (accountGroupId) revenueParams.set("accountGroupId", accountGroupId);

  const [
    accounts,
    subscription,
    health,
    weeklyState,
    agentSettings,
    circuitBreaker,
    approvals,
    notes,
    accountHealth,
    crossInsights,
    revenueHistory,
    revenueTrend,
    monthlyKpis,
    calendar,
  ] = await Promise.all([
    api("/accounts"),
    api("/subscription?action=check-trial", "POST", {}),
    api("/admin/health"),
    api("/agent/weekly-state"),
    api("/agent/settings"),
    api("/agent/circuit-breaker"),
    api("/agent/approvals?status=all&limit=10"),
    getNotes(),
    api("/analytics?action=account-health"),
    api(`/analytics/cross-insights?days=${Math.min(90, Math.max(1, days))}`),
    api(`/analytics/revenue?${revenueParams}`),
    api("/smart-links", "POST", { action: "revenue-trend" }),
    api("/admin/monthly-kpi"),
    api("/calendar?action=portfolio"),
  ]);

  const notesData = notes.ok ? notes.data : { byKey: {}, notes: [] };
  const goals = parseNote(notesData.byKey[GOALS_KEY], {});
  const policy = parseNote(notesData.byKey[POLICY_KEY], defaultPolicy());
  const runbook = parseNote(notesData.byKey[RUNBOOK_KEY], {});

  return {
    generatedAt: new Date().toISOString(),
    windowDays: days,
    goals,
    policy,
    runbook,
    accounts: summarize("accounts", accounts),
    subscription: summarize("subscription", subscription),
    health: summarize("health", health),
    weeklyState: summarize("weeklyState", weeklyState),
    agentSettings: summarize("agentSettings", agentSettings),
    circuitBreaker: summarize("circuitBreaker", circuitBreaker),
    approvals: summarize("approvals", approvals),
    accountHealth: summarize("accountHealth", accountHealth),
    crossInsights: summarize("crossInsights", crossInsights),
    revenueHistory: summarize("revenueHistory", revenueHistory),
    revenueTrend: summarize("revenueTrend", revenueTrend),
    monthlyKpis: summarize("monthlyKpis", monthlyKpis),
    calendar: summarize("calendar", calendar),
    residualRisks: [
      "MCP can block direct dryRun=false writes when highRiskActionsLocked is enabled, but external UI/API actions are outside this MCP lock.",
      "Runbook tools return plans and approval requests; they do not autonomously publish, spend, delete, or message users.",
    ],
  };
}

function summarize(name: string, result: Awaited<ReturnType<typeof api>>) {
  if (result.ok) return { ok: true, data: result.data };
  return { ok: false, source: name, error: result.error };
}

function defaultPolicy() {
  return {
    highRiskActionsLocked: false,
    requireApprovalFor: [
      "publish_batch",
      "spend_money",
      "change_automation",
      "delete_content",
      "message_users",
      "alter_branding",
      "invite_team",
      "revoke_keys",
      "data_export",
    ],
    budgetLimits: {
      dailyAiSpendUsd: null,
      monthlyAdSpendUsd: 0,
      maxPostsPerAccountPerDay: null,
    },
    escalationRules: [
      "Ask for approval before any externally visible write.",
      "Pause and report if circuit breaker is tripped, health check fails, or publish caps are exhausted.",
    ],
    contentBoundaries: [],
    brandRules: [],
  };
}

function runbookPlan(kind: string, brief: Record<string, unknown>) {
  const common = [
    "Check kill switch, circuit breaker, and pending approvals.",
    "Inspect account health, publish caps, queue health, and calendar density.",
    "Identify blocked accounts and risks before proposing writes.",
  ];

  const byKind: Record<string, string[]> = {
    daily_ops: [
      ...common,
      "Review revenue, subscription, health, dead letters, and pending inbox work.",
      "Prepare an approval request for any publish, automation, messaging, or deletion action.",
    ],
    content_planning: [
      ...common,
      "Find under-scheduled accounts, strong recent content patterns, and safe posting windows.",
      "Draft a scheduling plan and request approval before queueing or scheduling content.",
    ],
    inbox_triage: [
      ...common,
      "Prioritize unread, negative, buyer-intent, and collaboration messages.",
      "Draft replies for approval before sending any message.",
    ],
    growth_review: [
      ...common,
      "Compare cross-account insights, account health, quick wins, competitor signals, and revenue changes.",
      "Create a short list of experiments with success metrics.",
    ],
    weekly_report: [
      ...common,
      "Summarize wins, losses, risks, revenue movement, content output, and next-week bets.",
      "Highlight decisions that need human approval.",
    ],
  };

  return {
    runbook: kind,
    generatedAt: new Date().toISOString(),
    steps: byKind[kind] ?? common,
    brief,
    proposedActions: [],
    nextApproval: {
      requiredBeforeWrites: true,
      suggestedTool: "request_typed_approval",
    },
  };
}

export const register: ToolRegistrar = (server) => {
  server.tool(
    "get_business_brief",
    "Business operating brief: goals, policy, accounts, health, approvals, revenue, calendar, and risk state",
    {
      days: zNum.optional().describe("Lookback window in days (default 14, max 90)"),
      accountGroupId: z.string().optional().describe("Optional account group ID for revenue/history focus"),
    },
    async ({ days, accountGroupId }) => {
      const windowDays = Math.min(90, Math.max(1, Number(days ?? 14)));
      const params = new URLSearchParams({ action: "brief", days: String(windowDays) });
      if (accountGroupId) params.set("accountGroupId", accountGroupId);
      return respond(await api(`/business-ops?${params}`));
    }
  );

  server.tool(
    "get_business_goals",
    "Read persisted business goals used by autonomous business runbooks",
    {},
    async () => {
      return respond(await api("/business-ops?action=goals"));
    }
  );

  server.tool(
    "set_business_goals",
    "Persist business goals for autonomous runbooks",
    {
      goals: z.any().describe("JSON object with targets, priorities, products, accounts, KPIs, and constraints"),
      dryRun: zBool.default(true).describe("Preview goal update (default: true). Must be explicitly set to false to execute."),
    },
    async ({ goals, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Update business goals", { goals });
      return respond(await api("/business-ops?action=goals", "POST", { goals }));
    }
  );

  server.tool(
    "get_agent_policy",
    "Read business-agent operating policy: approvals, budgets, content boundaries, and escalation rules",
    {},
    async () => {
      return respond(await api("/business-ops?action=policy"));
    }
  );

  server.tool(
    "set_agent_policy",
    "Persist business-agent operating policy: approvals, budgets, content boundaries, and escalation rules",
    {
      policy: z.any().describe("Policy JSON object"),
      dryRun: zBool.default(true).describe("Preview policy update (default: true). Must be explicitly set to false to execute."),
    },
    async ({ policy, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Update business agent policy", { policy });
      return respond(await api("/business-ops?action=policy", "PATCH", { policy }));
    }
  );

  server.tool(
    "request_typed_approval",
    "Request typed human approval for high-risk business actions",
    {
      type: approvalType.describe("Approval category"),
      context: z.string().describe("What should be approved and why"),
      proposedActions: z.array(z.any()).optional().describe("Concrete tool calls or business actions awaiting approval"),
      urgency: z.enum(["low", "medium", "high"]).optional().describe("Approval urgency"),
      expiresInHours: zNum.optional().describe("Expiration window in hours (default 24, max 168)"),
    },
    async ({ type, context, proposedActions, urgency, expiresInHours }) => {
      return respond(await api("/agent/approvals", "POST", {
        session_id: SESSION_ID,
        context: `[${type}] ${context}`,
        proposed_actions: proposedActions ?? [],
        urgency: urgency ?? "medium",
        expires_in_hours: expiresInHours ?? 24,
      }));
    }
  );

  server.tool(
    "get_financial_controls",
    "Read financial state and controls: subscription, revenue history/trend, monthly KPIs, policy budgets, and cost visibility gaps",
    {
      days: zNum.optional().describe("Lookback window in days (default 30, max 365)"),
      accountGroupId: z.string().optional().describe("Optional account group ID"),
    },
    async ({ days, accountGroupId }) => {
      const windowDays = Math.min(365, Math.max(1, Number(days ?? 30)));
      const params = new URLSearchParams({ days: String(windowDays) });
      params.set("action", "costs");
      if (accountGroupId) params.set("accountGroupId", accountGroupId);
      return respond(await api(`/business-ops?${params}`));
    }
  );

  server.tool(
    "get_risk_state",
    "Read agent risk state: high-risk lock, kill switch, circuit breaker, crisis status, pending approvals, and health",
    {},
    async () => {
      return respond(await api("/business-ops?action=risk"));
    }
  );

  server.tool(
    "lock_high_risk_actions",
    "Lock or unlock direct MCP dryRun=false writes. When locked, write tools are blocked at the MCP wrapper unless they are policy/approval/emergency controls.",
    {
      locked: zBool.describe("true to lock high-risk writes, false to unlock"),
      reason: z.string().optional().describe("Reason for audit memory"),
      pauseAllAgentWrites: zBool.optional().describe("Also call set_agent_paused with the same locked value"),
      dryRun: zBool.default(true).describe("Preview lock change (default: true). Must be explicitly set to false to execute."),
    },
    async ({ locked, reason, pauseAllAgentWrites, dryRun }) => {
      const notes = await getNotes();
      const existing = notes.ok ? parseNote(notes.data.byKey[POLICY_KEY], defaultPolicy()) : defaultPolicy();
      const policy = {
        ...defaultPolicy(),
        ...(typeof existing === "object" && existing ? existing : {}),
        highRiskActionsLocked: locked,
        lastRiskLockChange: {
          at: new Date().toISOString(),
          locked,
          reason: reason ?? null,
        },
      };
      if (dryRun !== false) return dryRunResponse("Change high-risk action lock", { policy, pauseAllAgentWrites });
      const saved = await api("/business-ops?action=policy", "PATCH", { policy });
      if (pauseAllAgentWrites) await api("/agent/settings", "PATCH", { agent_paused: locked }).catch(() => {});
      return respond(saved);
    }
  );

  for (const [name, kind, description] of [
    ["run_daily_ops_dry_run", "daily_ops", "Run the daily business operations checklist in dry-run mode"],
    ["run_content_planning_dry_run", "content_planning", "Run content planning in dry-run mode"],
    ["run_inbox_triage_dry_run", "inbox_triage", "Run inbox triage in dry-run mode"],
    ["run_growth_review_dry_run", "growth_review", "Run growth review in dry-run mode"],
    ["run_weekly_report_dry_run", "weekly_report", "Generate a weekly business report in dry-run mode"],
  ] as const) {
    server.tool(
      name,
      description,
      {
        days: zNum.optional().describe("Lookback window in days (default 14, max 90)"),
        accountGroupId: z.string().optional().describe("Optional account group focus"),
        saveRunbookState: zBool.optional().describe("Persist the generated runbook state to agent notes"),
      },
      async ({ days, accountGroupId, saveRunbookState }) => {
        return respond(await api("/business-ops?action=runbook", "POST", {
          kind,
          days: Math.min(90, Math.max(1, Number(days ?? 14))),
          accountGroupId,
          saveRunbookState,
        }));
      }
    );
  }

  server.tool(
    "get_action_audit",
    "Read recent MCP/agent action history for audit, replay planning, and loop detection",
    {
      since: z.string().optional().describe("Only entries after this ISO timestamp"),
      limit: zNum.optional().describe("Max entries (default 50, max 200)"),
      toolName: z.string().optional().describe("Filter to one tool"),
      currentSession: zBool.optional().describe("Only this MCP process session"),
    },
    async ({ since, limit, toolName, currentSession }) => {
      const params = new URLSearchParams();
      if (since) params.set("since", since);
      if (limit) params.set("limit", String(limit));
      if (toolName) params.set("tool_name", toolName);
      if (currentSession) params.set("session_id", SESSION_ID);
      return respond(await api(`/agent/log?${params}`));
    }
  );
};
