import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const ROOT = path.resolve(__dirname, "../..");

function read(relativePath: string) {
  return fs.readFileSync(path.join(ROOT, relativePath), "utf8");
}

describe("MCP operator control plane", () => {
  it("uses one canonical tool module manifest for local and hosted MCP", () => {
    const toolModules = read("mcp-server/src/toolModules.ts");
    const localIndex = read("mcp-server/src/index.ts");
    const hostedApi = read("api/mcp.ts");

    expect(toolModules).toContain("TOOL_MODULE_NAMES");
    expect(toolModules).toContain("LOCAL_TOOL_MODULES");
    expect(toolModules).toContain("HOSTED_TOOL_MODULE_PATHS");
    expect(localIndex).toContain("LOCAL_TOOL_MODULES");
    expect(hostedApi).toContain("HOSTED_TOOL_MODULE_PATHS");
  });

  it("uses the shared operator control-plane wrapper in both transports", () => {
    const localIndex = read("mcp-server/src/index.ts");
    const hostedApi = read("api/mcp.ts");
    const controlPlane = read("mcp-server/src/operatorControlPlane.ts");

    expect(controlPlane).toContain("installOperatorControlPlane");
    expect(controlPlane).toContain("dryRun !== false");
    expect(controlPlane).toContain("approvalBindingRequired");
    expect(controlPlane).toContain("highRiskActionsLocked");
    expect(localIndex).toContain("installOperatorControlPlane(server)");
    expect(hostedApi).toContain("installOperatorControlPlane(server)");
  });

  it("does not allow hosted MCP to fall back to logging-only wrapping", () => {
    const hostedApi = read("api/mcp.ts");
    expect(hostedApi).not.toContain("installAgentActionLogging");
    expect(hostedApi).not.toContain("logAgentAction(");
  });

  it("exposes the exact intent approval flow through the operator API and MCP tools", () => {
    const operatorApi = read("api/operator.ts");
    const operatorTools = read("mcp-server/src/tools/operator.ts");
    const apiReference = read("docs/API_REFERENCE.md");
    const operatorManifestDoc = read("docs/OPERATOR_ACTION_MANIFEST.md");
    const openApi = read("api/_lib/openapi.ts");

    expect(operatorApi).toContain('action === "request-approval"');
    expect(operatorApi).toContain("buildExactProposedAction");
    expect(operatorApi).toContain("approvalMatchesIntent");
    expect(operatorApi).toContain("compensationDescription");
    expect(operatorApi).toContain("compensationRequiresApproval");
    expect(operatorTools).toContain("request_operator_approval");
    expect(operatorTools).toContain("/operator?action=request-approval");
    expect(apiReference).toContain("### operator");
    expect(apiReference).toContain("rollback/compensation metadata");
    expect(operatorManifestDoc).toContain("compensationActionName");
    expect(operatorManifestDoc).toContain("Rollback Classes");
    expect(openApi).toContain('tags: ["Operator"]');
    expect(openApi).toContain("compensationDescription");
  });

  it("enforces hierarchical kill switches before operator execution approval", () => {
    const operatorApi = read("api/operator.ts");
    const helper = read("api/_lib/operatorKillSwitches.ts");
    const migration = read("supabase/migrations/20260522130000_operator_kill_switches.sql");

    expect(operatorApi).toContain("checkOperatorKillSwitch");
    expect(operatorApi).toContain("OPERATOR_KILL_SWITCH_BLOCKED");
    expect(helper).toContain("global");
    expect(helper).toContain("workspace");
    expect(helper).toContain("group");
    expect(helper).toContain("account");
    expect(helper).toContain("session");
    expect(helper).toContain("api_key");
    expect(migration).toContain("operator_kill_switches");
  });

  it("materializes daily operator tasks from approval and failed publish sources", () => {
    const operatorApi = read("api/operator.ts");

    expect(operatorApi).toContain("materializeOperatorTasks");
    expect(operatorApi).toContain('"approval"');
    expect(operatorApi).toContain('"failed_publish"');
    expect(operatorApi).toContain('"recover_failed_post"');
    expect(operatorApi).toContain('"review_approval"');
  });

  it("materializes health and workflow task sources into the operator queue", () => {
    const operatorApi = read("api/operator.ts");
    const queueTile = read("src/components/dashboard-v2/tiles/OperatorTaskQueueTile.tsx");

    expect(operatorApi).toContain('"token_reauth"');
    expect(operatorApi).toContain('"token_expiring"');
    expect(operatorApi).toContain('"sync_failed"');
    expect(operatorApi).toContain('"sync_stale"');
    expect(operatorApi).toContain('"webhook_delivery"');
    expect(operatorApi).toContain('"report_overdue"');
    expect(operatorApi).toContain('"inbox_attention"');
    expect(operatorApi).toContain('"listening_signal"');
    expect(operatorApi).toContain('"cron_failed"');
    expect(operatorApi).toContain('"cron_stale"');
    expect(queueTile).toContain("reconnect_account");
    expect(queueTile).toContain("run_overdue_report");
    expect(queueTile).toContain("review_inbox_item");
    expect(queueTile).toContain("review_listening_signal");
  });

  it("supports durable operator task transitions by source identity", () => {
    const operatorApi = read("api/operator.ts");
    const snapshotHook = read("src/hooks/useOperatorSnapshot.ts");

    expect(operatorApi).toContain("Task id or source/source_id is required");
    expect(operatorApi).toContain("updateOperatorTaskRecord");
    expect(operatorApi).toContain('.eq("source", input.source)');
    expect(operatorApi).toContain('.eq("source_id", input.source_id)');
    expect(operatorApi).toContain('"resolved"');
    expect(operatorApi).toContain('"ignored"');
    expect(operatorApi).toContain('"snoozed"');
    expect(snapshotHook).toContain("sourceId");
    expect(snapshotHook).toContain("source_id: input.sourceId");
  });

  it("persists listening and anomaly workflow state through operator tasks", () => {
    const operatorApi = read("api/operator.ts");
    const listeningPage = read("src/pages/Listening.tsx");
    const anomalyTile = read("src/components/dashboard-v2/tiles/AnomalyFeedTile.tsx");

    expect(operatorApi).toContain('action === "source-workflow"');
    expect(operatorApi).toContain('"competitor_signal"');
    expect(operatorApi).toContain('"trend_signal"');
    expect(operatorApi).toContain('"listening_signal"');
    expect(operatorApi).toContain('"anomaly_alert"');
    expect(operatorApi).toContain(".from(\"anomaly_alerts\")");
    expect(operatorApi).toContain("dismissed_at");
    expect(operatorApi).toContain('"review_anomaly_alert"');
    expect(listeningPage).toContain("/api/operator?action=source-workflow");
    expect(listeningPage).toContain("fetchDurableListeningWorkflowIds");
    expect(listeningPage).toContain('status: "ignored"');
    expect(listeningPage).toContain('status: "snoozed"');
    expect(anomalyTile).toContain("/api/operator?action=source-workflow");
    expect(anomalyTile).toContain("Anomaly marked handled");
  });
});
