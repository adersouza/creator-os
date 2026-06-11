import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const ROOT = path.resolve(__dirname, "../..");

function read(relativePath: string) {
	return fs.readFileSync(path.join(ROOT, relativePath), "utf8");
}

describe("operator approval API hardening", () => {
	it("creates exact action intents from dry-runs with hashes, scope, expiry, and idempotency keys", () => {
		const operatorApi = read("api/operator.ts");

		expect(operatorApi).toContain('action === "dry-run"');
		expect(operatorApi).toContain("normalized_payload: payload");
		expect(operatorApi).toContain("payload_hash: payloadHash");
		expect(operatorApi).toContain("content_hash: contentHash");
		expect(operatorApi).toContain("idempotency_key:");
		expect(operatorApi).toContain("expires_at: expiresAt");
		expect(operatorApi).toContain("workspace_id: parsed.data.workspace_id");
		expect(operatorApi).toContain("group_id: parsed.data.group_id");
		expect(operatorApi).toContain("account_id: parsed.data.account_id");
	});

	it("binds approval requests to exact intents and creates review tasks", () => {
		const operatorApi = read("api/operator.ts");

		expect(operatorApi).toContain('action === "request-approval"');
		expect(operatorApi).toContain(".eq(\"status\", \"pending\")");
		expect(operatorApi).toContain("buildExactProposedAction(intent)");
		expect(operatorApi).toContain("approval_id: approval.id");
		expect(operatorApi).toContain("status: \"needs_review\"");
		expect(operatorApi).toContain("source: \"approval\"");
		expect(operatorApi).toContain("type: \"review_approval\"");
	});

	it("supports edit-and-resubmit by creating a new exact intent and closing the old request", () => {
		const operatorApi = read("api/operator.ts");

		expect(operatorApi).toContain('action === "revise-approval"');
		expect(operatorApi).toContain("ReviseApprovalSchema");
		expect(operatorApi).toContain("previousIntentId");
		expect(operatorApi).toContain("previousApprovalId");
		expect(operatorApi).toContain("previousPayloadHash");
		expect(operatorApi).toContain("revisedPayloadHash");
		expect(operatorApi).toContain("Created revised approval request");
		expect(operatorApi).toContain('source: "approval"');
		expect(operatorApi).toContain("Superseded by revised approval request");
	});

	it("rejects execution without matching unexpired approved approval and active audit trail", () => {
		const operatorApi = read("api/operator.ts");

		expect(operatorApi).toContain('action === "execute"');
		expect(operatorApi).toContain(".eq(\"status\", \"approved\")");
		expect(operatorApi).toContain("Matching approved approval is required");
		expect(operatorApi).toContain("Approval has expired");
		expect(operatorApi).toContain("Approval does not match this exact action intent");
		expect(operatorApi).toContain("checkOperatorKillSwitch");
		expect(operatorApi).toContain("OPERATOR_KILL_SWITCH_BLOCKED");
		expect(operatorApi).toContain("await auditExecuteAttempt");
		expect(operatorApi).toContain("claimIntentForDispatch");
		expect(operatorApi).toContain("dispatchApprovedOperatorIntent");
		expect(operatorApi).toContain("Execution audit persistence is required for high-risk actions");
		expect(operatorApi).toContain('status: dispatch.supported ? "consumed" : "approved"');
		expect(operatorApi).toContain('status: "dispatching"');
		expect(operatorApi).toContain('status: "failed"');
	});

	it("dispatches approved internal operator actions exactly through typed executors", () => {
		const operatorApi = read("api/operator.ts");

		expect(operatorApi).toContain("function dispatchApprovedOperatorIntent");
		expect(operatorApi).toContain('actionName === "update_operator_task"');
		expect(operatorApi).toContain("updateOperatorTaskRecord");
		expect(operatorApi).toContain('actionName === "mark_inbox_message_read"');
		expect(operatorApi).toContain("markInboxMessageReadForOperator");
		expect(operatorApi).toContain('status: dispatch.supported ? "consumed" : "approved"');
		expect(operatorApi).toContain('status: dispatch.supported ? "executed" : "approved_for_execution"');
		expect(operatorApi).toContain("approved_pending_manual_dispatch");
	});

	it("routes approved high-risk social actions through existing production handlers", () => {
		const operatorApi = read("api/operator.ts");
		const runner = read("api/_lib/operatorHandlerRunner.ts");

		expect(operatorApi).toContain("runOperatorHandlerAction");
		expect(operatorApi).toContain('actionName === "publish_post"');
		expect(operatorApi).toContain('actionName === "publish_threads_post"');
		expect(operatorApi).toContain('actionName === "publish_instagram_post"');
		expect(operatorApi).toContain("handler: handlePublish");
		expect(operatorApi).toContain('actionName === "schedule_post"');
		expect(operatorApi).toContain("handler: handleSchedule");
		expect(operatorApi).toContain('actionName === "reschedule_post"');
		expect(operatorApi).toContain("handler: handleReschedule");
		expect(operatorApi).toContain('actionName === "send_reply"');
		expect(operatorApi).toContain("handler: handleSendReply");
		expect(operatorApi).toContain('actionName === "retry_queue_item"');
		expect(operatorApi).toContain("handler: handleRetryDeadLetter");
		expect(operatorApi).toContain('actionName === "trigger_queue_fill"');
		expect(operatorApi).toContain("handler: handleTriggerQueueFill");
		expect(operatorApi).toContain('actionName === "override_account_state"');
		expect(operatorApi).toContain("handleOverrideAccountState");
		expect(operatorApi).toContain("OPERATOR_UNPAUSE_ACTION_ONLY");
		expect(runner).toContain("withIdempotency");
		expect(runner).toContain('"idempotency-key": idempotencyKey');
		expect(runner).toContain("requireKey: true");
		expect(runner).toContain("failClosed: true");
	});

	it("keeps one canonical approval matcher tied to hashes and tool names", () => {
		const operatorApi = read("api/operator.ts");

		expect(operatorApi).toContain("function approvalMatchesIntent");
		expect(operatorApi).toContain("candidate.actionHash === intent.payload_hash");
		expect(operatorApi).toContain("candidate.toolName === intent.action_name");
		expect(operatorApi).toContain("candidate.action_hash === intent.payload_hash");
		expect(operatorApi).toContain("candidate.tool_name === intent.action_name");
	});
});
