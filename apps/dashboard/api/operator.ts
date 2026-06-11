/**
 * Operator API — 10/10 agent manager control-plane surface.
 *
 * /api/operator?action=manifest
 * /api/operator?action=snapshot
 * /api/operator?action=tasks
 * /api/operator?action=dry-run
 * /api/operator?action=request-approval
 * /api/operator?action=execute
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { createHash } from "node:crypto";
import { apiError, apiSuccess } from "./_lib/apiResponse.js";
import { withAuth } from "./_lib/middleware.js";
import {
	OperatorAuditError,
	recordOperatorActionAudit,
	requireOperatorActionAudit,
} from "./_lib/operatorAudit.js";
import { runOperatorHandlerAction } from "./_lib/operatorHandlerRunner.js";
import { loadOperatorManagerBrain } from "./_lib/operatorManagerBrain.js";
import { checkOperatorKillSwitch } from "./_lib/operatorKillSwitches.js";
import { evaluateAIQualityGate } from "./_lib/handlers/auto-post/qualityGate.js";
import {
	AI_EVAL_DIRECT_GENERATIVE_SURFACES,
	AI_EVAL_DOCUMENTED_NON_GENERATIVE_SURFACES,
} from "./_lib/aiEvalSnapshots.js";
import { buildAIEvalReport } from "./_lib/aiEvalReporting.js";
import {
	loadReliabilitySections,
	persistReliabilitySloSnapshot,
} from "./_lib/reliability.js";
import { handlePublish } from "./_lib/handlers/posts/publish.js";
import {
	handleReschedule,
	handleSchedule,
} from "./_lib/handlers/posts/schedule.js";
import { handleSendReply } from "./_lib/handlers/replies/sendReply.js";
import {
	handleRetryDeadLetter,
	handleTriggerQueueFill,
} from "./_lib/handlers/auto-post/route/queueHandlers.js";
import { handleOverrideAccountState } from "./_lib/handlers/auto-post/stateHandlers.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "./_lib/privilegedDb.js";
import { z, zEnum, zUnknown } from "./_lib/zodCompat.js";

const TaskStatusSchema = zEnum([
	"open",
	"assigned",
	"in_progress",
	"snoozed",
	"resolved",
	"ignored",
]);

const TaskUpdateSchema = z.object({
	id: z.string().uuid().optional(),
	source: z.string().min(1).max(120).optional(),
	source_id: z.string().min(1).max(240).optional(),
	status: TaskStatusSchema,
	resolution_reason: z.string().max(1000).optional().nullable(),
	snoozed_until: z.string().datetime().optional().nullable(),
});

const SourceWorkflowUpdateSchema = z.object({
	source: zEnum([
		"listening_signal",
		"competitor_signal",
		"trend_signal",
		"anomaly_alert",
	]),
	source_id: z.string().min(1).max(240),
	status: TaskStatusSchema,
	title: z.string().min(1).max(220).optional(),
	priority: zEnum(["low", "medium", "high", "critical"]).optional(),
	workspace_id: z.string().optional().nullable(),
	group_id: z.string().optional().nullable(),
	account_id: z.string().optional().nullable(),
	resolution_reason: z.string().max(1000).optional().nullable(),
	snoozed_until: z.string().datetime().optional().nullable(),
	payload: zUnknown().optional(),
});

type SourceWorkflowUpdate = {
	source: "listening_signal" | "competitor_signal" | "trend_signal" | "anomaly_alert";
	source_id: string;
	status: "open" | "assigned" | "in_progress" | "snoozed" | "resolved" | "ignored";
	title?: string | undefined;
	priority?: "low" | "medium" | "high" | "critical" | undefined;
	workspace_id?: string | null | undefined;
	group_id?: string | null | undefined;
	account_id?: string | null | undefined;
	resolution_reason?: string | null | undefined;
	snoozed_until?: string | null | undefined;
	payload?: unknown;
};

type TaskUpdateInput = {
	id?: string | undefined;
	source?: string | undefined;
	source_id?: string | undefined;
	status: "open" | "assigned" | "in_progress" | "snoozed" | "resolved" | "ignored";
	resolution_reason?: string | null | undefined;
	snoozed_until?: string | null | undefined;
};

const DryRunSchema = z.object({
	action_name: z.string().min(1).max(120),
	payload: zUnknown().default({}),
	account_id: z.string().optional().nullable(),
	group_id: z.string().optional().nullable(),
	workspace_id: z.string().optional().nullable(),
	risk_level: zEnum(["low", "medium", "high", "critical"]).default("medium"),
	expires_in_hours: z.number().int().min(1).max(168).default(24),
});

const ExecuteSchema = z.object({
	intent_id: z.string().uuid(),
	approval_id: z.string().uuid(),
});

const RequestApprovalSchema = z.object({
	intent_id: z.string().uuid(),
	context: z.string().min(1).max(2000).optional(),
	urgency: zEnum(["low", "medium", "high"]).optional(),
	expires_in_hours: z.number().int().min(1).max(168).optional(),
});

const ReviseApprovalSchema = z.object({
	intent_id: z.string().uuid(),
	approval_id: z.string().uuid(),
	payload: zUnknown(),
	context: z.string().min(1).max(2000).optional(),
	note: z.string().max(1000).optional().nullable(),
	expires_in_hours: z.number().int().min(1).max(168).default(24),
});

type OperatorManifestEntry = {
	toolName: string;
	riskLevel: string;
	sideEffectType: string;
	requiresApproval: boolean;
	requiresIdempotencyKey: boolean;
	supportsDryRun: boolean;
	hostedAvailable: boolean;
	rollbackSupport: string;
	compensationActionName?: string;
	compensationDescription: string;
	compensationRequiresApproval: boolean;
	rollbackWindowHours?: number;
};

type OperatorActionContext = {
	req: VercelRequest;
	res: VercelResponse;
	db: ReturnType<typeof getPrivilegedSupabaseAny>;
	userId: string;
};

type OperatorActionHandler = (
	ctx: OperatorActionContext,
) => Promise<VercelResponse | undefined>;

const OPERATOR_CONTROL_ACTIONS: Record<string, OperatorActionHandler> = {
	manifest: handleManifestAction,
	snapshot: handleSnapshotAction,
	tasks: handleTasksAction,
	"source-workflow": handleSourceWorkflowAction,
};

export default withAuth(async (req: VercelRequest, res: VercelResponse, user) => {
	const action = String(req.query.action || "snapshot");
	const db = getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.operatorControlPlane,
	);

	if (action === "source-workflow") {
		return handleSourceWorkflowAction({ req, res, db, userId: user.id });
	}

	const controlHandler = OPERATOR_CONTROL_ACTIONS[action];
	if (controlHandler) {
		return controlHandler({ req, res, db, userId: user.id });
	}

	if (action === "dry-run") {
		if (req.method !== "POST") return apiError(res, 405, "Method not allowed");
		const parsed = DryRunSchema.safeParse(req.body);
		if (!parsed.success) {
			await recordOperatorActionAudit({
				db,
				req,
				userId: user.id,
				phase: "dry-run",
				actionName: "unknown",
				body: req.body,
				outcome: "failure",
				error: parsed.error.issues[0]?.message || "Invalid dry-run request",
			});
			return apiError(res, 400, parsed.error.issues[0]?.message || "Invalid dry-run request");
		}
		const payload = normalizePayload(parsed.data.payload);
		const qualityGate =
			requiresQualityGateForOperatorAction(
				parsed.data.action_name,
				parsed.data.risk_level,
				payload,
			) && typeof payload.content === "string"
				? evaluateAIQualityGate({
						content: payload.content,
						sourceType:
							typeof payload.source_type === "string"
								? payload.source_type
								: "ai",
						sourceContent:
							typeof payload.source_content === "string"
								? payload.source_content
								: null,
						sourceCompetitorId:
							typeof payload.source_competitor_id === "string"
								? payload.source_competitor_id
								: null,
						viralScore:
							typeof payload.viral_score === "number"
								? payload.viral_score
								: typeof payload.predicted_viral_score === "number"
									? payload.predicted_viral_score
									: null,
					})
				: null;
		if (qualityGate?.decision === "block") {
			await recordOperatorActionAudit({
				db,
				req,
				userId: user.id,
				phase: "dry-run",
				actionName: parsed.data.action_name,
				riskLevel: parsed.data.risk_level,
				scope: operatorScope(parsed.data),
				payload,
				body: req.body,
				outcome: "failure",
				error: `AI quality gate blocked action: ${qualityGate.reason}`,
				metadata: { quality_gate: qualityGate },
			});
			return apiError(res, 422, "AI quality gate blocked this action", {
				extra: { qualityGate },
			});
		}
		const riskLevel =
			qualityGate?.decision === "needs_review" &&
			!["high", "critical"].includes(parsed.data.risk_level)
				? "high"
				: parsed.data.risk_level;
		const payloadHash = hashJson(payload);
		const contentHash = typeof payload.content === "string" ? hashString(payload.content) : null;
		const expiresAt = new Date(Date.now() + parsed.data.expires_in_hours * 3600 * 1000).toISOString();
		const { data, error } = await db
			.from("agent_action_intents")
			.insert({
				user_id: user.id,
				workspace_id: parsed.data.workspace_id ?? null,
				group_id: parsed.data.group_id ?? null,
				account_id: parsed.data.account_id ?? null,
				action_name: parsed.data.action_name,
				risk_level: riskLevel,
				normalized_payload: payload,
				payload_hash: payloadHash,
				content_hash: contentHash,
				idempotency_key: `operator:${parsed.data.action_name}:${payloadHash.slice(0, 24)}`,
				expires_at: expiresAt,
			})
			.select("*")
			.single();
		if (error || !data) {
			await recordOperatorActionAudit({
				db,
				req,
				userId: user.id,
				phase: "dry-run",
				actionName: parsed.data.action_name,
				riskLevel: parsed.data.risk_level,
				scope: operatorScope(parsed.data),
				payload,
				payloadHash,
				body: req.body,
				contentHash,
				outcome: "failure",
				error: error?.message || "Failed to create action intent",
				metadata: { target_action_name: parsed.data.action_name, quality_gate: qualityGate },
			});
			return apiError(res, 500, "Failed to create action intent");
		}
		await recordOperatorActionAudit({
			db,
			req,
			userId: user.id,
			phase: "dry-run",
			actionName: parsed.data.action_name,
			riskLevel: parsed.data.risk_level,
			scope: operatorScope(parsed.data),
			payload,
			payloadHash,
			body: req.body,
			contentHash,
			intentId: data.id,
			idempotencyKey: data.idempotency_key,
			outcome: "success",
			message: "Created operator action intent from dry-run preview.",
			metadata: { target_action_name: parsed.data.action_name, quality_gate: qualityGate },
		});
		return apiSuccess(res, {
			intent: data,
			preview: {
				actionName: parsed.data.action_name,
				scope: {
					workspaceId: parsed.data.workspace_id ?? null,
					groupId: parsed.data.group_id ?? null,
					accountId: parsed.data.account_id ?? null,
				},
				payload,
				payloadHash,
				requiresApproval: ["high", "critical"].includes(riskLevel),
				qualityGate,
			},
		});
	}

	if (action === "request-approval") {
		if (req.method !== "POST") return apiError(res, 405, "Method not allowed");
		const parsed = RequestApprovalSchema.safeParse(req.body);
		if (!parsed.success) {
			await recordOperatorActionAudit({
				db,
				req,
				userId: user.id,
				phase: "request-approval",
				actionName: "unknown",
				body: req.body,
				outcome: "failure",
				error: parsed.error.issues[0]?.message || "Invalid approval request",
			});
			return apiError(
				res,
				400,
				parsed.error.issues[0]?.message || "Invalid approval request",
			);
		}

		const { data: intent, error: intentError } = await db
			.from("agent_action_intents")
			.select("*")
			.eq("id", parsed.data.intent_id)
			.eq("user_id", user.id)
			.eq("status", "pending")
			.maybeSingle();
		if (intentError || !intent) {
			await recordOperatorActionAudit({
				db,
				req,
				userId: user.id,
				phase: "request-approval",
				actionName: "unknown",
				body: req.body,
				intentId: parsed.data.intent_id,
				outcome: "failure",
				error: intentError?.message || "Pending action intent not found",
			});
			return apiError(res, 404, "Pending action intent not found");
		}
		if (intent.expires_at && new Date(intent.expires_at).getTime() < Date.now()) {
			await recordOperatorActionAudit({
				db,
				req,
				userId: user.id,
				phase: "request-approval",
				actionName: String(intent.action_name),
				riskLevel: stringOrNull(intent.risk_level),
				scope: scopeFromIntent(intent),
				payloadHash: stringOrNull(intent.payload_hash),
				body: req.body,
				contentHash: stringOrNull(intent.content_hash),
				intentId: intent.id,
				idempotencyKey: stringOrNull(intent.idempotency_key),
				outcome: "failure",
				error: "Action intent has expired",
			});
			return apiError(res, 403, "Action intent has expired");
		}

		const expiresInHours = parsed.data.expires_in_hours ?? 24;
		const expiresAt = new Date(Date.now() + expiresInHours * 3600 * 1000).toISOString();
		const proposedAction = buildExactProposedAction(intent);
		const urgency = parsed.data.urgency ?? urgencyForRisk(intent.risk_level);
		const context =
			parsed.data.context ??
			`Review ${intent.risk_level || "medium"} risk ${intent.action_name} action before execution.`;

		const { data: approval, error } = await db
			.from("agent_approvals")
			.insert({
				user_id: user.id,
				session_id: null,
				context,
				proposed_actions: [proposedAction],
				urgency,
				status: "pending",
				expires_at: expiresAt,
			})
			.select("id, status, expires_at, proposed_actions")
			.single();
		if (error || !approval) {
			await recordOperatorActionAudit({
				db,
				req,
				userId: user.id,
				phase: "request-approval",
				actionName: String(intent.action_name),
				riskLevel: stringOrNull(intent.risk_level),
				scope: scopeFromIntent(intent),
				payloadHash: stringOrNull(intent.payload_hash),
				body: req.body,
				contentHash: stringOrNull(intent.content_hash),
				intentId: intent.id,
				idempotencyKey: stringOrNull(intent.idempotency_key),
				outcome: "failure",
				error: error?.message || "Failed to create approval request",
			});
			return apiError(res, 500, "Failed to create approval request");
		}

		const { error: intentUpdateError } = await db
			.from("agent_action_intents")
			.update({
				status: "needs_review",
				approval_id: approval.id,
				updated_at: new Date().toISOString(),
			})
			.eq("id", intent.id)
			.eq("user_id", user.id);
		if (intentUpdateError) {
			await recordOperatorActionAudit({
				db,
				req,
				userId: user.id,
				phase: "request-approval",
				actionName: String(intent.action_name),
				riskLevel: stringOrNull(intent.risk_level),
				scope: scopeFromIntent(intent),
				payloadHash: stringOrNull(intent.payload_hash),
				body: req.body,
				contentHash: stringOrNull(intent.content_hash),
				intentId: intent.id,
				approvalId: approval.id,
				idempotencyKey: stringOrNull(intent.idempotency_key),
				outcome: "failure",
				error: intentUpdateError.message || "Failed to bind approval to action intent",
			});
			return apiError(res, 500, "Failed to bind approval to action intent");
		}

		await upsertOperatorTask(db, {
			user_id: user.id,
			source: "approval",
			source_id: approval.id,
			title: context.slice(0, 160),
			priority: urgency === "high" ? "high" : "medium",
			status: "open",
			workspace_id: intent.workspace_id ?? null,
			group_id: intent.group_id ?? null,
			account_id: intent.account_id ?? null,
			due_at: expiresAt,
			sla_at: expiresAt,
			recommended_action: {
				type: "review_approval",
				approval_id: approval.id,
				intent_id: intent.id,
			},
			linked_entity_type: "agent_approval",
			linked_entity_id: approval.id,
			payload: { proposed_action: proposedAction },
		});

		await recordOperatorActionAudit({
			db,
			req,
			userId: user.id,
			phase: "request-approval",
			actionName: String(intent.action_name),
			riskLevel: stringOrNull(intent.risk_level),
			scope: scopeFromIntent(intent),
			payloadHash: stringOrNull(intent.payload_hash),
			body: req.body,
			contentHash: stringOrNull(intent.content_hash),
			intentId: intent.id,
			approvalId: approval.id,
			idempotencyKey: stringOrNull(intent.idempotency_key),
			outcome: "success",
			message: "Created approval request for exact operator action intent.",
			metadata: { urgency, expires_at: expiresAt },
		});

		return apiSuccess(res, {
			approvalId: approval.id,
			intentId: intent.id,
			status: approval.status,
			expiresAt,
			proposedAction,
		});
	}

	if (action === "revise-approval") {
		if (req.method !== "POST") return apiError(res, 405, "Method not allowed");
		const parsed = ReviseApprovalSchema.safeParse(req.body);
		if (!parsed.success) {
			await recordOperatorActionAudit({
				db,
				req,
				userId: user.id,
				phase: "request-approval",
				actionName: "unknown",
				body: req.body,
				outcome: "failure",
				error: parsed.error.issues[0]?.message || "Invalid approval revision",
			});
			return apiError(res, 400, parsed.error.issues[0]?.message || "Invalid approval revision");
		}

		const { data: intent, error: intentError } = await db
			.from("agent_action_intents")
			.select("*")
			.eq("id", parsed.data.intent_id)
			.eq("user_id", user.id)
			.in("status", ["pending", "needs_review"])
			.maybeSingle();
		if (intentError || !intent) {
			await recordOperatorActionAudit({
				db,
				req,
				userId: user.id,
				phase: "request-approval",
				actionName: "unknown",
				body: req.body,
				intentId: parsed.data.intent_id,
				approvalId: parsed.data.approval_id,
				outcome: "failure",
				error: intentError?.message || "Pending action intent not found",
			});
			return apiError(res, 404, "Pending action intent not found");
		}

		const { data: approval, error: approvalError } = await db
			.from("agent_approvals")
			.select("id, status, context, urgency, proposed_actions, expires_at")
			.eq("id", parsed.data.approval_id)
			.eq("user_id", user.id)
			.eq("status", "pending")
			.maybeSingle();
		if (approvalError || !approval || !approvalMatchesIntent(approval.proposed_actions, intent)) {
			await recordOperatorActionAudit({
				db,
				req,
				userId: user.id,
				phase: "request-approval",
				actionName: String(intent.action_name),
				riskLevel: stringOrNull(intent.risk_level),
				scope: scopeFromIntent(intent),
				payloadHash: stringOrNull(intent.payload_hash),
				body: req.body,
				contentHash: stringOrNull(intent.content_hash),
				intentId: intent.id,
				approvalId: parsed.data.approval_id,
				idempotencyKey: stringOrNull(intent.idempotency_key),
				outcome: "failure",
				error: approvalError?.message || "Pending approval does not match this intent",
			});
			return apiError(res, 403, "Pending approval does not match this intent");
		}

		const revisedPayload = normalizePayload(parsed.data.payload);
		const payloadHash = hashJson(revisedPayload);
		const contentHash = typeof revisedPayload.content === "string" ? hashString(revisedPayload.content) : null;
		const expiresAt = new Date(Date.now() + parsed.data.expires_in_hours * 3600 * 1000).toISOString();
		const context = parsed.data.context ?? `Review revised ${intent.risk_level || "medium"} risk ${intent.action_name} action before execution.`;
		const urgency = typeof approval.urgency === "string" ? approval.urgency : urgencyForRisk(intent.risk_level);

		const { data: revisedIntent, error: revisedIntentError } = await db
			.from("agent_action_intents")
			.insert({
				user_id: user.id,
				workspace_id: intent.workspace_id ?? null,
				group_id: intent.group_id ?? null,
				account_id: intent.account_id ?? null,
				action_name: intent.action_name,
				risk_level: intent.risk_level,
				status: "pending",
				normalized_payload: revisedPayload,
				payload_hash: payloadHash,
				content_hash: contentHash,
				idempotency_key: `operator:${intent.action_name}:${payloadHash.slice(0, 24)}`,
				required_reviewer_role: intent.required_reviewer_role ?? null,
				expires_at: expiresAt,
			})
			.select("*")
			.single();
		if (revisedIntentError || !revisedIntent) {
			await recordOperatorActionAudit({
				db,
				req,
				userId: user.id,
				phase: "request-approval",
				actionName: String(intent.action_name),
				riskLevel: stringOrNull(intent.risk_level),
				scope: scopeFromIntent(intent),
				payload: revisedPayload,
				payloadHash,
				body: req.body,
				contentHash,
				intentId: intent.id,
				approvalId: approval.id,
				idempotencyKey: stringOrNull(intent.idempotency_key),
				outcome: "failure",
				error: revisedIntentError?.message || "Failed to create revised action intent",
				metadata: { previous_intent_id: intent.id },
			});
			return apiError(res, 500, "Failed to create revised action intent");
		}

		const proposedAction = {
			...buildExactProposedAction(revisedIntent),
			revision: {
				previousIntentId: intent.id,
				previousApprovalId: approval.id,
				previousPayloadHash: intent.payload_hash,
				revisedPayloadHash: payloadHash,
				note: parsed.data.note ?? null,
			},
		};

		const { data: revisedApproval, error: revisedApprovalError } = await db
			.from("agent_approvals")
			.insert({
				user_id: user.id,
				session_id: null,
				context,
				proposed_actions: [proposedAction],
				urgency,
				status: "pending",
				expires_at: expiresAt,
			})
			.select("id, status, expires_at, proposed_actions")
			.single();
		if (revisedApprovalError || !revisedApproval) {
			await db
				.from("agent_action_intents")
				.update({ status: "failed", updated_at: new Date().toISOString() })
				.eq("id", revisedIntent.id)
				.eq("user_id", user.id);
			return apiError(res, 500, "Failed to create revised approval request");
		}

		await Promise.all([
			db
				.from("agent_action_intents")
				.update({
					status: "rejected",
					updated_at: new Date().toISOString(),
				})
				.eq("id", intent.id)
				.eq("user_id", user.id),
			db
				.from("agent_action_intents")
				.update({
					status: "needs_review",
					approval_id: revisedApproval.id,
					updated_at: new Date().toISOString(),
				})
				.eq("id", revisedIntent.id)
				.eq("user_id", user.id),
			db
				.from("agent_approvals")
				.update({
					status: "rejected",
					decided_at: new Date().toISOString(),
					decision_note: parsed.data.note ?? "Superseded by revised approval request.",
				})
				.eq("id", approval.id)
				.eq("user_id", user.id),
		]);

		await upsertOperatorTask(db, {
			user_id: user.id,
			source: "approval",
			source_id: revisedApproval.id,
			title: context.slice(0, 160),
			priority: urgency === "high" ? "high" : "medium",
			status: "open",
			workspace_id: revisedIntent.workspace_id ?? null,
			group_id: revisedIntent.group_id ?? null,
			account_id: revisedIntent.account_id ?? null,
			due_at: expiresAt,
			sla_at: expiresAt,
			recommended_action: {
				type: "review_approval",
				approval_id: revisedApproval.id,
				intent_id: revisedIntent.id,
			},
			linked_entity_type: "agent_approval",
			linked_entity_id: revisedApproval.id,
			payload: { proposed_action: proposedAction, previous_approval_id: approval.id },
		});

		await updateOperatorTaskRecord(db, user.id, {
			source: "approval",
			source_id: approval.id,
			status: "resolved",
			resolution_reason: "Superseded by revised approval request",
		});

		await recordOperatorActionAudit({
			db,
			req,
			userId: user.id,
			phase: "request-approval",
			actionName: String(intent.action_name),
			riskLevel: stringOrNull(intent.risk_level),
			scope: scopeFromIntent(revisedIntent),
			payload: revisedPayload,
			payloadHash,
			body: req.body,
			contentHash,
			intentId: revisedIntent.id,
			approvalId: revisedApproval.id,
			idempotencyKey: stringOrNull(revisedIntent.idempotency_key),
			outcome: "success",
			message: "Created revised approval request from edited exact action payload.",
			metadata: {
				previous_intent_id: intent.id,
				previous_approval_id: approval.id,
				previous_payload_hash: intent.payload_hash,
			},
		});

		return apiSuccess(res, {
			approvalId: revisedApproval.id,
			intentId: revisedIntent.id,
			previousApprovalId: approval.id,
			previousIntentId: intent.id,
			status: revisedApproval.status,
			expiresAt,
			proposedAction,
		});
	}

	if (action === "execute") {
		if (req.method !== "POST") return apiError(res, 405, "Method not allowed");
		const parsed = ExecuteSchema.safeParse(req.body);
		if (!parsed.success) {
			await recordOperatorActionAudit({
				db,
				req,
				userId: user.id,
				phase: "execute",
				actionName: "unknown",
				body: req.body,
				outcome: "failure",
				error: parsed.error.issues[0]?.message || "Invalid execute request",
			});
			return apiError(res, 400, parsed.error.issues[0]?.message || "Invalid execute request");
		}
		const { data: intent, error: intentError } = await db
			.from("agent_action_intents")
			.select("*")
			.eq("id", parsed.data.intent_id)
			.eq("user_id", user.id)
			.in("status", ["pending", "needs_review"])
			.maybeSingle();
		if (intentError || !intent) {
			await recordOperatorActionAudit({
				db,
				req,
				userId: user.id,
				phase: "execute",
				actionName: "unknown",
				body: req.body,
				intentId: parsed.data.intent_id,
				approvalId: parsed.data.approval_id,
				outcome: "failure",
				error: intentError?.message || "Pending action intent not found",
			});
			return apiError(res, 404, "Pending action intent not found");
		}

		const { data: approval, error: approvalError } = await db
			.from("agent_approvals")
			.select("id, status, expires_at, proposed_actions, session_id")
			.eq("id", parsed.data.approval_id)
			.eq("user_id", user.id)
			.eq("status", "approved")
			.maybeSingle();
		if (approvalError || !approval) {
			const audited = await auditExecuteGateFailure(db, req, user.id, intent, parsed.data.approval_id, {
				body: req.body,
				error: approvalError?.message || "Matching approved approval is required",
			});
			if (!audited) {
				return apiError(res, 500, "Execution audit persistence is required for high-risk actions");
			}
			return apiError(res, 403, "Matching approved approval is required");
		}
		if (approval.expires_at && new Date(approval.expires_at).getTime() < Date.now()) {
			const audited = await auditExecuteGateFailure(db, req, user.id, intent, approval.id, {
				body: req.body,
				error: "Approval has expired",
			});
			if (!audited) {
				return apiError(res, 500, "Execution audit persistence is required for high-risk actions");
			}
			return apiError(res, 403, "Approval has expired");
		}

		const approved = approvalMatchesIntent(approval.proposed_actions, intent);
		if (!approved) {
			const audited = await auditExecuteGateFailure(db, req, user.id, intent, approval.id, {
				body: req.body,
				error: "Approval does not match this exact action intent",
			});
			if (!audited) {
				return apiError(res, 500, "Execution audit persistence is required for high-risk actions");
			}
			return apiError(res, 403, "Approval does not match this exact action intent");
		}

		const killSwitch = await checkOperatorKillSwitch(db, {
			userId: user.id,
			workspaceId: intent.workspace_id ?? null,
			groupId: intent.group_id ?? null,
			accountId: intent.account_id ?? null,
			sessionId: approval.session_id ?? null,
			actionName: intent.action_name ?? null,
			riskLevel: intent.risk_level ?? null,
		});
		if (killSwitch.blocked) {
			const audited = await auditExecuteGateFailure(db, req, user.id, intent, approval.id, {
				body: req.body,
				error: killSwitch.reason,
				message: "Operator kill switch blocked execution.",
				metadata: {
					code: "OPERATOR_KILL_SWITCH_BLOCKED",
					scope_type: killSwitch.scopeType,
					scope_id: killSwitch.scopeId,
					switch_id: killSwitch.switchId,
				},
			});
			if (!audited) {
				return apiError(res, 500, "Execution audit persistence is required for high-risk actions");
			}
			return apiError(res, 503, killSwitch.reason, {
				code: "OPERATOR_KILL_SWITCH_BLOCKED",
				extra: {
					scopeType: killSwitch.scopeType,
					scopeId: killSwitch.scopeId,
					switchId: killSwitch.switchId,
				},
			});
		}

		try {
			await auditExecuteAttempt(db, req, user.id, intent, approval.id, req.body);
		} catch (err: unknown) {
			if (err instanceof OperatorAuditError) {
				return apiError(res, 500, "Execution audit persistence is required for high-risk actions");
			}
			throw err;
		}

		const claim = await claimIntentForDispatch(db, user.id, intent);
		if (!claim.ok) {
			const audited = await auditExecuteGateFailure(db, req, user.id, intent, approval.id, {
				body: req.body,
				error: claim.message,
				message: "Approved operator action intent could not be claimed for dispatch.",
				metadata: { code: claim.code },
			});
			if (!audited) {
				return apiError(res, 500, "Execution audit persistence is required for high-risk actions");
			}
			return apiError(res, claim.status, claim.message, { code: claim.code });
		}

		const dispatch = await dispatchApprovedOperatorIntent(db, req, user.id, intent);
		if (!dispatch.ok) {
			await markIntentDispatchFailed(db, user.id, intent, approval.id);
			const recoveryTask = await createOperatorDispatchFailureTask(db, user.id, intent, dispatch);
			const audited = await auditExecuteGateFailure(db, req, user.id, intent, approval.id, {
				body: req.body,
				error: dispatch.message,
				message: "Approved operator action dispatch failed.",
				metadata: {
					code: dispatch.code,
					dispatch_supported: dispatch.supported,
					handler_status: dispatch.handlerStatus ?? null,
					recovery_task_id: recoveryTask?.id ?? null,
				},
			});
			if (!audited) {
				return apiError(res, 500, "Execution audit persistence is required for high-risk actions");
			}
			return apiError(res, dispatch.status, dispatch.message, {
				code: dispatch.code,
				extra: {
					supported: dispatch.supported,
					handlerStatus: dispatch.handlerStatus ?? null,
					recoveryTaskId: recoveryTask?.id ?? null,
				},
			});
		}

		const { error: intentUpdateError } = await db
			.from("agent_action_intents")
			.update({
				status: dispatch.supported ? "consumed" : "approved",
				approval_id: approval.id,
				consumed_at: dispatch.supported ? new Date().toISOString() : null,
				updated_at: new Date().toISOString(),
			})
			.eq("id", intent.id)
			.eq("user_id", user.id);
		if (intentUpdateError) {
			const audited = await auditExecuteGateFailure(db, req, user.id, intent, approval.id, {
				body: req.body,
				error: intentUpdateError.message || "Failed to mark action intent approved",
			});
			if (!audited) {
				return apiError(res, 500, "Execution audit persistence is required for high-risk actions");
			}
			return apiError(res, 500, "Failed to mark action intent approved");
		}

		const successAudit = {
			db,
			req,
			userId: user.id,
			phase: "execute" as const,
			actionName: String(intent.action_name),
			riskLevel: stringOrNull(intent.risk_level),
			scope: scopeFromIntent(intent),
			payloadHash: stringOrNull(intent.payload_hash),
			body: req.body,
			contentHash: stringOrNull(intent.content_hash),
			intentId: intent.id,
			approvalId: approval.id,
			idempotencyKey: stringOrNull(intent.idempotency_key),
			outcome: "success" as const,
			message: dispatch.supported
				? "Approval verified and operator action executed."
				: "Approval verified and action intent marked approved for manual dispatch.",
			metadata: {
				dispatch_supported: dispatch.supported,
				dispatch_result: dispatch.result,
			},
		};
		if (isHighRisk(intent.risk_level)) {
			try {
				await requireOperatorActionAudit(successAudit);
			} catch (err: unknown) {
				if (err instanceof OperatorAuditError) {
					return apiError(res, 500, "Execution audit persistence is required for high-risk actions");
				}
				throw err;
			}
		} else {
			await recordOperatorActionAudit(successAudit);
		}

		return apiSuccess(res, {
			status: dispatch.supported ? "executed" : "approved_for_execution",
			intentId: intent.id,
			approvalId: approval.id,
			dispatch: {
				supported: dispatch.supported,
				result: dispatch.result,
			},
			message: dispatch.supported
				? "Approved operator action executed."
				: "Intent is approved. This action is not wired to a direct executor yet.",
		});
	}

	return apiError(res, 400, `Unknown operator action: ${action}`);
});

async function handleManifestAction({
	req,
	res,
}: OperatorActionContext): Promise<VercelResponse | undefined> {
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");
	const manifest = await loadManifest();
	return apiSuccess(res, {
		version: "2026-05-22",
		actions: manifest,
		summary: summarizeManifest(manifest),
	});
}

async function handleSnapshotAction({
	req,
	res,
	db,
	userId,
}: OperatorActionContext): Promise<VercelResponse | undefined> {
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");
	await materializeOperatorTasks(db, userId);
	const [
		tasks,
		approvals,
		failedPosts,
		managerBrain,
		opsHealth,
		fleetCapacity,
		aiEvalSummary,
		reliabilitySections,
	] = await Promise.all([
		db
			.from("operator_tasks")
			.select("id, source, source_id, title, priority, status, due_at, sla_at, workspace_id, account_id, group_id, recommended_action, linked_entity_type, linked_entity_id, created_at")
			.eq("user_id", userId)
			.in("status", ["open", "assigned", "in_progress", "snoozed"])
			.order("created_at", { ascending: false })
			.limit(25),
		db
			.from("agent_approvals")
			.select("id, context, urgency, status, expires_at, created_at")
			.eq("user_id", userId)
			.eq("status", "pending")
			.order("created_at", { ascending: false })
			.limit(25),
		db
			.from("posts")
			.select("id, account_id, platform, content, status, error_message, updated_at")
			.eq("user_id", userId)
			.eq("status", "failed")
			.order("updated_at", { ascending: false })
			.limit(25),
		loadOperatorManagerBrain(db, userId),
		loadOperatorOpsHealth(db, userId),
		loadOperatorFleetCapacity(db, userId, stringOrNull(req.query.capacityStart)),
		loadOperatorAIEvalSummary(db, userId),
		loadReliabilitySections(db, userId),
	]);
	await persistReliabilitySloSnapshot(
		db,
		userId,
		reliabilitySections.reliabilitySlo,
	);

	return apiSuccess(res, {
		generatedAt: new Date().toISOString(),
		tasks: tasks.data || [],
		pendingApprovals: approvals.data || [],
		failedPosts: failedPosts.data || [],
		recentDecisions: managerBrain.recentDecisions,
		managerBrain,
		opsHealth,
		fleetCapacity,
		aiEvalSummary,
		reliabilitySlo: reliabilitySections.reliabilitySlo,
		metaApiUsage: reliabilitySections.metaApiUsage,
		webhookHealth: reliabilitySections.webhookHealth,
		tokenSlo: reliabilitySections.tokenSlo,
		recommendedNextActions: [
			...buildRecommendedActions({
				taskCount: tasks.data?.length || 0,
				approvalCount: approvals.data?.length || 0,
				failedPostCount: failedPosts.data?.length || 0,
			}),
			...managerBrain.recommendedNextActions,
		],
		warnings: [
			...managerBrain.staleEvidenceWarnings.map((warning) => warning.message),
			"Operator snapshot is conservative: high-risk writes still require exact approval before execution.",
		],
	});
}

async function handleTasksAction({
	req,
	res,
	db,
	userId,
}: OperatorActionContext): Promise<VercelResponse | undefined> {
	if (req.method === "GET") {
		const status =
			typeof req.query.status === "string" ? req.query.status : "open";
		const limit = Math.min(Number(req.query.limit || 50), 100);
		let query = db
			.from("operator_tasks")
			.select("*")
			.eq("user_id", userId)
			.order("created_at", { ascending: false })
			.limit(limit);
		if (status !== "all") query = query.eq("status", status);
		const { data, error } = await query;
		if (error) return apiError(res, 500, "Failed to load operator tasks");
		return apiSuccess(res, { tasks: data || [] });
	}

	if (req.method === "PATCH") {
		const parsed = TaskUpdateSchema.safeParse(req.body);
		if (!parsed.success) {
			return apiError(
				res,
				400,
				parsed.error.issues[0]?.message || "Invalid task update",
			);
		}
		const result = await updateOperatorTaskRecord(
			db,
			userId,
			parsed.data as TaskUpdateInput,
		);
		if (!result.ok) return apiError(res, result.status, result.message);
		return apiSuccess(res, { task: result.task });
	}

	return apiError(res, 405, "Method not allowed");
}

async function handleSourceWorkflowAction({
	req,
	res,
	db,
	userId,
}: OperatorActionContext): Promise<VercelResponse | undefined> {
	if (req.method !== "PATCH") return apiError(res, 405, "Method not allowed");
	const parsed = SourceWorkflowUpdateSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			parsed.error.issues[0]?.message || "Invalid workflow update",
		);
	}
	const result = await updateSourceWorkflowState(
		db,
		userId,
		parsed.data as SourceWorkflowUpdate,
	);
	if (!result.ok) return apiError(res, result.status, result.message);
	return apiSuccess(res, { task: result.task });
}

async function auditExecuteAttempt(
	db: ReturnType<typeof getPrivilegedSupabaseAny>,
	req: VercelRequest,
	userId: string,
	intent: Record<string, unknown>,
	approvalId: string,
	body: unknown,
) {
	const audit = {
		db,
		req,
		userId,
		phase: "execute" as const,
		actionName: String(intent.action_name),
		riskLevel: stringOrNull(intent.risk_level),
		scope: scopeFromIntent(intent),
		payloadHash: stringOrNull(intent.payload_hash),
		body,
		contentHash: stringOrNull(intent.content_hash),
		intentId: String(intent.id),
		approvalId,
		idempotencyKey: stringOrNull(intent.idempotency_key),
		outcome: "attempted" as const,
		message: "Approval verified; preparing to mark intent approved for execution.",
	};

	if (isHighRisk(intent.risk_level)) {
		await requireOperatorActionAudit(audit);
		return;
	}
	await recordOperatorActionAudit(audit);
}

async function auditExecuteGateFailure(
	db: ReturnType<typeof getPrivilegedSupabaseAny>,
	req: VercelRequest,
	userId: string,
	intent: Record<string, unknown>,
	approvalId: string | null,
	options: {
		body: unknown;
		error: string;
		message?: string;
		metadata?: Record<string, unknown>;
	},
) {
	const audit = {
		db,
		req,
		userId,
		phase: "execute" as const,
		actionName: String(intent.action_name),
		riskLevel: stringOrNull(intent.risk_level),
		scope: scopeFromIntent(intent),
		payloadHash: stringOrNull(intent.payload_hash),
		body: options.body,
		contentHash: stringOrNull(intent.content_hash),
		intentId: String(intent.id),
		approvalId,
		idempotencyKey: stringOrNull(intent.idempotency_key),
		outcome: "failure" as const,
		message: options.message ?? null,
		error: options.error,
		metadata: options.metadata ?? null,
	};

	if (isHighRisk(intent.risk_level)) {
		const result = await recordOperatorActionAudit(audit);
		return result.ok;
	}
	await recordOperatorActionAudit(audit);
	return true;
}

type OperatorDispatchResult =
	| {
			ok: true;
			supported: boolean;
			result: Record<string, unknown>;
	  }
	| {
			ok: false;
			supported: boolean;
			status: number;
			code: string;
			message: string;
			handlerStatus?: number | undefined;
	  };

async function dispatchApprovedOperatorIntent(
	db: ReturnType<typeof getPrivilegedSupabaseAny>,
	req: VercelRequest,
	userId: string,
	intent: Record<string, unknown>,
): Promise<OperatorDispatchResult> {
	const actionName = String(intent.action_name || "");
	const payload = normalizePayload(intent.normalized_payload);
	const idempotencyKey = stringOrNull(intent.idempotency_key);

	if (actionName === "update_operator_task") {
		const parsed = TaskUpdateSchema.safeParse({
			id: payload.id,
			source: payload.source,
			source_id: payload.source_id ?? payload.sourceId,
			status: payload.status,
			resolution_reason: payload.resolution_reason ?? payload.resolutionReason,
			snoozed_until: payload.snoozed_until ?? payload.snoozedUntil,
		});
		if (!parsed.success) {
			return {
				ok: false,
				supported: true,
				status: 400,
				code: "OPERATOR_DISPATCH_INVALID_PAYLOAD",
				message: parsed.error.issues[0]?.message || "Invalid operator task payload",
			};
		}
		const result = await updateOperatorTaskRecord(db, userId, parsed.data as TaskUpdateInput);
		if (!result.ok) {
			return {
				ok: false,
				supported: true,
				status: result.status,
				code: "OPERATOR_TASK_UPDATE_FAILED",
				message: result.message,
			};
		}
		return {
			ok: true,
			supported: true,
			result: {
				type: "operator_task_updated",
				task: result.task,
			},
		};
	}

	if (actionName === "mark_inbox_message_read") {
		const messageId = stringOrNull(payload.messageId ?? payload.message_id);
		if (!messageId) {
			return {
				ok: false,
				supported: true,
				status: 400,
				code: "OPERATOR_DISPATCH_INVALID_PAYLOAD",
				message: "messageId is required",
			};
		}
		const read = payload.read !== false;
		const result = await markInboxMessageReadForOperator(db, userId, messageId, read);
		if (!result.ok) {
			return {
				ok: false,
				supported: true,
				status: result.status,
				code: "OPERATOR_INBOX_MARK_READ_FAILED",
				message: result.message,
			};
		}
		return {
			ok: true,
			supported: true,
			result: {
				type: "inbox_message_read_state_updated",
				messageId,
				read,
			},
		};
	}

	const handlerDispatch = await dispatchApprovedHandlerAction(
		req,
		userId,
		actionName,
		payload,
		idempotencyKey,
	);
	if (handlerDispatch) return handlerDispatch;

	return {
		ok: true,
		supported: false,
		result: {
			type: "approved_pending_manual_dispatch",
			actionName,
			reason: "No direct operator executor is registered for this action yet.",
		},
	};
}

async function claimIntentForDispatch(
	db: ReturnType<typeof getPrivilegedSupabaseAny>,
	userId: string,
	intent: Record<string, unknown>,
): Promise<{ ok: true } | { ok: false; status: number; code: string; message: string }> {
	const idempotencyKey = stringOrNull(intent.idempotency_key);
	if (!idempotencyKey) {
		return {
			ok: false,
			status: 409,
			code: "OPERATOR_INTENT_IDEMPOTENCY_REQUIRED",
			message: "Approved operator intent is missing an idempotency key",
		};
	}
	const { data, error } = await db
		.from("agent_action_intents")
		.update({
			status: "dispatching",
			updated_at: new Date().toISOString(),
		})
		.eq("id", intent.id)
		.eq("user_id", userId)
		.in("status", ["pending", "needs_review"])
		.select("id")
		.maybeSingle();

	if (error || !data) {
		return {
			ok: false,
			status: 409,
			code: "OPERATOR_INTENT_ALREADY_DISPATCHING",
			message: error?.message || "Action intent is already dispatching or no longer executable",
		};
	}
	return { ok: true };
}

async function markIntentDispatchFailed(
	db: ReturnType<typeof getPrivilegedSupabaseAny>,
	userId: string,
	intent: Record<string, unknown>,
	approvalId: string,
) {
	await db
		.from("agent_action_intents")
		.update({
			status: "failed",
			approval_id: approvalId,
			updated_at: new Date().toISOString(),
		})
		.eq("id", intent.id)
		.eq("user_id", userId);
}

async function createOperatorDispatchFailureTask(
	db: ReturnType<typeof getPrivilegedSupabaseAny>,
	userId: string,
	intent: Record<string, unknown>,
	dispatch: Extract<OperatorDispatchResult, { ok: false }>,
): Promise<Record<string, unknown> | null> {
	const task = {
		user_id: userId,
		source: "operator_dispatch_failed",
		source_id: String(intent.id),
		title: `Recover failed operator action: ${String(intent.action_name || "unknown")}`,
		priority: isHighRisk(intent.risk_level) ? "high" : "medium",
		status: "open",
		workspace_id: stringOrNull(intent.workspace_id),
		group_id: stringOrNull(intent.group_id),
		account_id: stringOrNull(intent.account_id),
		recommended_action: {
			type: "recover_operator_dispatch",
			intent_id: intent.id,
			action_name: intent.action_name,
			error_code: dispatch.code,
		},
		linked_entity_type: "agent_action_intent",
		linked_entity_id: String(intent.id),
		payload: {
			action_name: intent.action_name,
			risk_level: intent.risk_level,
			error: dispatch.message,
			code: dispatch.code,
			handler_status: dispatch.handlerStatus ?? null,
		},
	};
	return upsertOperatorTask(db, task);
}

async function dispatchApprovedHandlerAction(
	req: VercelRequest,
	userId: string,
	actionName: string,
	payload: Record<string, unknown>,
	idempotencyKey: string | null,
): Promise<OperatorDispatchResult | null> {
	if (!idempotencyKey) {
		return {
			ok: false,
			supported: true,
			status: 409,
			code: "OPERATOR_INTENT_IDEMPOTENCY_REQUIRED",
			message: "Approved operator intent is missing an idempotency key",
		};
	}

	const action = handlerActionConfig(actionName, payload);
	if (!action) return null;
	if (!action.ok) return action.result;

	const result = await runOperatorHandlerAction({
		baseReq: req,
		userId,
		body: action.body,
		idempotencyKey,
		route: action.route,
		action: action.action,
		query: { action: action.queryAction },
		handler: action.handler,
	});

	if (result.statusCode >= 200 && result.statusCode < 300) {
		return {
			ok: true,
			supported: true,
			result: {
				type: action.resultType,
				statusCode: result.statusCode,
				body: result.body,
			},
		};
	}

	return {
		ok: false,
		supported: true,
		status: result.statusCode || 500,
		handlerStatus: result.statusCode || 500,
		code: "OPERATOR_HANDLER_DISPATCH_FAILED",
		message: errorMessageFromHandlerResult(result.body, action.failureMessage),
	};
}

type HandlerActionConfig =
	| {
			ok: true;
			route: string;
			action: string;
			queryAction: string;
			resultType: string;
			failureMessage: string;
			body: Record<string, unknown>;
			handler: (
				req: VercelRequest,
				res: VercelResponse,
				userId: string,
			) => Promise<VercelResponse | undefined>;
	  }
	| {
			ok: false;
			result: Extract<OperatorDispatchResult, { ok: false }>;
	  };

function handlerActionConfig(
	actionName: string,
	payload: Record<string, unknown>,
): HandlerActionConfig | null {
	if (
		actionName === "publish_post" ||
		actionName === "publish_threads_post" ||
		actionName === "publish_instagram_post"
	) {
		const platform =
			actionName === "publish_threads_post"
				? "threads"
				: actionName === "publish_instagram_post"
					? "instagram"
					: payload.platform;
		return {
			ok: true,
			route: "posts",
			action: "publish",
			queryAction: "publish",
			resultType: "post_published",
			failureMessage: "Approved publish action failed",
			body: { ...payload, platform },
			handler: handlePublish,
		};
	}

	if (
		actionName === "schedule_post" ||
		actionName === "schedule_threads_post" ||
		actionName === "schedule_instagram_post"
	) {
		const platform =
			actionName === "schedule_threads_post"
				? "threads"
				: actionName === "schedule_instagram_post"
					? "instagram"
					: payload.platform;
		return {
			ok: true,
			route: "posts",
			action: "schedule",
			queryAction: "schedule",
			resultType: "post_scheduled",
			failureMessage: "Approved schedule action failed",
			body: { ...payload, platform },
			handler: handleSchedule,
		};
	}

	if (actionName === "reschedule_post") {
		return {
			ok: true,
			route: "posts",
			action: "reschedule",
			queryAction: "reschedule",
			resultType: "post_rescheduled",
			failureMessage: "Approved reschedule action failed",
			body: payload,
			handler: handleReschedule,
		};
	}

	if (
		actionName === "send_reply" ||
		actionName === "reply_to_message" ||
		actionName === "reply_to_ig_comment"
	) {
		return {
			ok: true,
			route: "/api/replies",
			action: "send",
			queryAction: "send",
			resultType: "reply_sent",
			failureMessage: "Approved reply action failed",
			body: payload,
			handler: handleSendReply,
		};
	}

	if (actionName === "retry_queue_item") {
		return {
			ok: true,
			route: "/api/auto-post",
			action: "retry-dead-letter",
			queryAction: "retry-dead-letter",
			resultType: "queue_item_retry_scheduled",
			failureMessage: "Approved queue retry action failed",
			body: { ...payload, dryRun: false },
			handler: handleRetryDeadLetter,
		};
	}

	if (actionName === "trigger_queue_fill") {
		return {
			ok: true,
			route: "/api/auto-post",
			action: "trigger-queue-fill",
			queryAction: "trigger-queue-fill",
			resultType: "queue_fill_dispatched",
			failureMessage: "Approved queue-fill action failed",
			body: payload,
			handler: handleTriggerQueueFill,
		};
	}

	if (actionName === "override_account_state") {
		const overrideAction = stringOrNull(payload.action);
		if (overrideAction !== "resume" && overrideAction !== "clear_cooldown") {
			return {
				ok: false,
				result: {
					ok: false,
					supported: true,
					status: 403,
					code: "OPERATOR_UNPAUSE_ACTION_ONLY",
					message: "Operator account-state execution only supports resume or clear_cooldown",
				},
			};
		}
		return {
			ok: true,
			route: "/api/auto-post",
			action: "override-account-state",
			queryAction: "override-account-state",
			resultType: "account_state_overridden",
			failureMessage: "Approved account unpause action failed",
			body: payload,
			handler: handleOverrideAccountState,
		};
	}

	return null;
}

function errorMessageFromHandlerResult(body: unknown, fallback: string): string {
	if (body && typeof body === "object") {
		const record = body as Record<string, unknown>;
		const message = record.error ?? record.message ?? record.details;
		if (typeof message === "string" && message.trim()) return message;
	}
	return fallback;
}

async function loadManifest(): Promise<OperatorManifestEntry[]> {
	try {
		const modulePath = "../mcp-server/dist/operatorControlPlane.js";
		const { getOperatorActionManifest } = await import(modulePath);
		return getOperatorActionManifest() as OperatorManifestEntry[];
	} catch {
		return [];
	}
}

async function materializeOperatorTasks(db: ReturnType<typeof getPrivilegedSupabaseAny>, userId: string) {
	const now = new Date();
	const expiringSoon = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000).toISOString();
	const staleSyncCutoff = new Date(now.getTime() - 30 * 60 * 1000).toISOString();
	const listeningCutoff = new Date(now.getTime() - 24 * 60 * 60 * 1000).toISOString();
	const failedCronCutoff = new Date(now.getTime() - 24 * 60 * 60 * 1000).toISOString();
	const staleCronCutoff = new Date(now.getTime() - 20 * 60 * 1000).toISOString();
	const [
		approvals,
		failedPosts,
		userPosts,
		threadNeedsReauth,
		threadExpiring,
		instagramNeedsReauth,
		instagramExpiring,
		failedSyncJobs,
		staleSyncJobs,
		webhookFailures,
		overdueReports,
		threadMentions,
		igMentions,
		dmConversations,
		listeningAlerts,
		anomalyAlerts,
		failedCronRuns,
		staleCronRuns,
		queueDeadLetters,
		queueDispatchBacklog,
	] = await Promise.all([
		db
			.from("agent_approvals")
			.select("id, context, urgency, status, expires_at, proposed_actions, created_at")
			.eq("user_id", userId)
			.eq("status", "pending")
			.order("created_at", { ascending: false })
			.limit(50),
		db
			.from("posts")
			.select("id, account_id, platform, content, status, error_message, updated_at")
			.eq("user_id", userId)
			.eq("status", "failed")
			.order("updated_at", { ascending: false })
			.limit(50),
		db
			.from("posts")
			.select("id, account_id")
			.eq("user_id", userId)
			.eq("status", "published")
			.order("created_at", { ascending: false })
			.limit(5000),
		db
			.from("accounts")
			.select("id, username, group_id, status, needs_reauth, token_expires_at, is_active, is_retired, last_synced_at")
			.eq("user_id", userId)
			.eq("is_active", true)
			.eq("needs_reauth", true)
			.order("token_expires_at", { ascending: true, nullsFirst: false })
			.limit(50),
		db
			.from("accounts")
			.select("id, username, group_id, status, needs_reauth, token_expires_at, is_active, is_retired, last_synced_at")
			.eq("user_id", userId)
			.eq("is_active", true)
			.lte("token_expires_at", expiringSoon)
			.order("token_expires_at", { ascending: true, nullsFirst: false })
			.limit(50),
		db
			.from("instagram_accounts")
			.select("id, username, group_id, status, needs_reauth, token_expires_at, is_active, last_synced_at")
			.eq("user_id", userId)
			.eq("is_active", true)
			.eq("needs_reauth", true)
			.order("token_expires_at", { ascending: true, nullsFirst: false })
			.limit(50),
		db
			.from("instagram_accounts")
			.select("id, username, group_id, status, needs_reauth, token_expires_at, is_active, last_synced_at")
			.eq("user_id", userId)
			.eq("is_active", true)
			.lte("token_expires_at", expiringSoon)
			.order("token_expires_at", { ascending: true, nullsFirst: false })
			.limit(50),
		db
			.from("sync_jobs")
			.select("id, job_type, status, account_count, failed_count, error_message, started_at, updated_at, created_at")
			.eq("user_id", userId)
			.eq("status", "failed")
			.order("updated_at", { ascending: false })
			.limit(25),
		db
			.from("sync_jobs")
			.select("id, job_type, status, account_count, failed_count, error_message, started_at, updated_at, created_at")
			.eq("user_id", userId)
			.in("status", ["queued", "processing"])
			.lt("updated_at", staleSyncCutoff)
			.order("updated_at", { ascending: false })
			.limit(25),
		db
			.from("webhook_deliveries")
			.select("id, event, status, attempts, max_attempts, last_error, next_retry_at, created_at, subscription_id")
			.eq("user_id", userId)
			.in("status", ["failed", "dead_letter"])
			.order("created_at", { ascending: false })
			.limit(25),
		db
			.from("reports")
			.select("id, name, type, cadence, status, next_run_at, last_run_at")
			.eq("user_id", userId)
			.eq("status", "active")
			.lt("next_run_at", now.toISOString())
			.order("next_run_at", { ascending: true })
			.limit(25),
		db
			.from("mentions")
			.select("id, account_id, mentioned_by_username, content, permalink, mentioned_at, is_read")
			.eq("user_id", userId)
			.eq("is_read", false)
			.order("mentioned_at", { ascending: false })
			.limit(25),
		db
			.from("ig_mentions")
			.select("id, ig_account_id, username, caption, permalink, mentioned_at, is_read")
			.eq("user_id", userId)
			.eq("is_read", false)
			.order("mentioned_at", { ascending: false })
			.limit(25),
		db
			.from("inbox_dm_cache")
			.select("id, account_id, participant_username, last_message_text, last_message_at, is_read")
			.eq("user_id", userId)
			.eq("is_read", false)
			.order("last_message_at", { ascending: false })
			.limit(25),
		db
			.from("listening_alerts")
			.select("id, workspace_id, keyword, alert_type, threshold_value, last_triggered_at")
			.eq("user_id", userId)
			.eq("is_active", true)
			.limit(100),
		db
			.from("anomaly_alerts")
			.select("id, account_id, instagram_account_id, platform, alert_type, severity, title, description, created_at")
			.eq("user_id", userId)
			.is("dismissed_at", null)
			.gte("created_at", listeningCutoff)
			.order("created_at", { ascending: false })
			.limit(50),
		db
			.from("cron_runs")
			.select("id, job_name, status, started_at, completed_at, duration_ms, items_processed, error_message, metadata, created_at")
			.eq("status", "failed")
			.gte("created_at", failedCronCutoff)
			.order("created_at", { ascending: false })
			.limit(15),
		db
			.from("cron_runs")
			.select("id, job_name, status, started_at, completed_at, duration_ms, items_processed, error_message, metadata, created_at")
			.eq("status", "running")
			.lt("started_at", staleCronCutoff)
			.order("started_at", { ascending: false })
			.limit(15),
		db
			.from("auto_post_queue")
			.select("id, workspace_id, group_id, account_id, status, scheduled_for, next_retry_at, retry_count, last_error, error_message, dead_letter_reason, qstash_message_id")
			.eq("user_id", userId)
			.eq("status", "dead_letter")
			.order("scheduled_for", { ascending: false })
			.limit(50),
		db
			.from("auto_post_queue")
			.select("id, workspace_id, group_id, account_id, status, scheduled_for, next_retry_at, retry_count, last_error, error_message, qstash_message_id")
			.eq("user_id", userId)
			.in("status", ["pending", "queued", "retrying"])
			.lte("scheduled_for", now.toISOString())
			.is("qstash_message_id", null)
			.order("scheduled_for", { ascending: true })
			.limit(50),
	]);

	const postRows = uniqueById(userPosts.data || []);
	const postIds = postRows.map((post) => String(post.id)).filter(Boolean);
	const accountByPostId = new Map(postRows.map((post) => [String(post.id), stringOrNull(post.account_id)]));
	const alertRows = uniqueById(listeningAlerts.data || []);
	const alertIds = alertRows.map((alert) => String(alert.id)).filter(Boolean);
	const alertById = new Map(alertRows.map((alert) => [String(alert.id), alert]));
	const [threadReplies, igComments, listeningResults] = await Promise.all([
		postIds.length
			? db
				.from("post_replies")
				.select("id, post_id, username, content, created_at, is_read")
				.in("post_id", postIds)
				.eq("is_read", false)
				.order("created_at", { ascending: false })
				.limit(50)
			: Promise.resolve({ data: [] }),
		postIds.length
			? db
				.from("ig_comments")
				.select("id, post_id, username, text, created_at, is_read")
				.in("post_id", postIds)
				.eq("is_read", false)
				.order("created_at", { ascending: false })
				.limit(50)
			: Promise.resolve({ data: [] }),
		alertIds.length
			? db
				.from("listening_results")
				.select("id, alert_id, workspace_id, keyword, source, result_count, sentiment_breakdown, sample_posts, checked_at")
				.in("alert_id", alertIds)
				.gt("result_count", 0)
				.gte("checked_at", listeningCutoff)
				.order("checked_at", { ascending: false })
				.limit(50)
			: Promise.resolve({ data: [] }),
	]);

	const approvalRows = (approvals.data || []).map((approval: Record<string, unknown>) => {
		const urgency = typeof approval.urgency === "string" ? approval.urgency : "medium";
		const proposedAction = firstRecord(approval.proposed_actions);
		return {
			user_id: userId,
			source: "approval",
			source_id: String(approval.id),
			title: String(approval.context || "Review agent approval"),
			priority: urgency === "high" ? "high" : "medium",
			status: "open",
			workspace_id: stringOrNull(proposedAction.workspaceId ?? proposedAction.workspace_id),
			group_id: stringOrNull(proposedAction.groupId ?? proposedAction.group_id),
			account_id: stringOrNull(proposedAction.accountId ?? proposedAction.account_id),
			due_at: stringOrNull(approval.expires_at),
			sla_at: stringOrNull(approval.expires_at),
			recommended_action: {
				type: "review_approval",
				approval_id: approval.id,
				intent_id: proposedAction.intentId ?? proposedAction.intent_id,
			},
			linked_entity_type: "agent_approval",
			linked_entity_id: String(approval.id),
			payload: {
				context: approval.context,
				urgency,
				proposed_action: proposedAction,
			},
		};
	});

	const failedPostRows = (failedPosts.data || []).map((post: Record<string, unknown>) => ({
		user_id: userId,
		source: "failed_publish",
		source_id: String(post.id),
		title: `Recover failed ${post.platform || "social"} post`,
		priority: "high",
		status: "open",
		account_id: stringOrNull(post.account_id),
		recommended_action: {
			type: "recover_failed_post",
			post_id: post.id,
			platform: post.platform,
		},
		linked_entity_type: "post",
		linked_entity_id: String(post.id),
		payload: {
			content: post.content,
			error_message: post.error_message,
			updated_at: post.updated_at,
		},
	}));

	const tokenRows = [
		...uniqueById([...(threadNeedsReauth.data || []), ...(threadExpiring.data || [])]).map((account) =>
			accountTokenTask(userId, account, "threads"),
		),
		...uniqueById([...(instagramNeedsReauth.data || []), ...(instagramExpiring.data || [])]).map((account) =>
			accountTokenTask(userId, account, "instagram"),
		),
	].filter((row): row is Record<string, unknown> => Boolean(row));

	const syncRows = uniqueById([...(failedSyncJobs.data || []), ...(staleSyncJobs.data || [])]).map((job) => {
		const isFailed = job.status === "failed";
		return {
			user_id: userId,
			source: isFailed ? "sync_failed" : "sync_stale",
			source_id: String(job.id),
			title: isFailed
				? `Recover failed ${job.job_type || "sync"} job`
				: `Inspect stale ${job.job_type || "sync"} job`,
			priority: isFailed ? "high" : "medium",
			status: "open",
			recommended_action: {
				type: isFailed ? "recover_sync_job" : "inspect_stale_sync",
				sync_job_id: job.id,
				job_type: job.job_type,
			},
			linked_entity_type: "sync_job",
			linked_entity_id: String(job.id),
			payload: {
				status: job.status,
				account_count: job.account_count,
				failed_count: job.failed_count,
				error_message: job.error_message,
				started_at: job.started_at,
				updated_at: job.updated_at,
				created_at: job.created_at,
			},
		};
	});

	const webhookRows = (webhookFailures.data || []).map((delivery: Record<string, unknown>) => ({
		user_id: userId,
		source: "webhook_delivery",
		source_id: String(delivery.id),
		title:
			delivery.status === "dead_letter"
				? `Replay dead-letter webhook: ${delivery.event || "event"}`
				: `Repair failed webhook: ${delivery.event || "event"}`,
		priority: delivery.status === "dead_letter" ? "high" : "medium",
		status: "open",
		due_at: stringOrNull(delivery.next_retry_at),
		sla_at: stringOrNull(delivery.next_retry_at),
		recommended_action: {
			type: delivery.status === "dead_letter" ? "replay_webhook_delivery" : "inspect_webhook_delivery",
			webhook_delivery_id: delivery.id,
			subscription_id: delivery.subscription_id,
		},
		linked_entity_type: "webhook_delivery",
		linked_entity_id: String(delivery.id),
		payload: {
			event: delivery.event,
			status: delivery.status,
			attempts: delivery.attempts,
			max_attempts: delivery.max_attempts,
			last_error: delivery.last_error,
			created_at: delivery.created_at,
		},
	}));

	const reportRows = (overdueReports.data || []).map((report: Record<string, unknown>) => ({
		user_id: userId,
		source: "report_overdue",
		source_id: String(report.id),
		title: `Run overdue report: ${report.name || "scheduled report"}`,
		priority: "medium",
		status: "open",
		due_at: stringOrNull(report.next_run_at),
		sla_at: stringOrNull(report.next_run_at),
		recommended_action: {
			type: "run_overdue_report",
			report_id: report.id,
		},
		linked_entity_type: "report",
		linked_entity_id: String(report.id),
		payload: {
			name: report.name,
			type: report.type,
			cadence: report.cadence,
			next_run_at: report.next_run_at,
			last_run_at: report.last_run_at,
		},
	}));

	const inboxRows = [
		...(threadReplies.data || []).map((message: Record<string, unknown>) =>
			inboxTask(userId, message, "threads_reply", accountByPostId.get(String(message.post_id)) ?? null),
		),
		...(igComments.data || []).map((message: Record<string, unknown>) =>
			inboxTask(userId, message, "ig_comment", accountByPostId.get(String(message.post_id)) ?? null),
		),
		...(threadMentions.data || []).map((message: Record<string, unknown>) =>
			inboxTask(userId, message, "threads_mention", stringOrNull(message.account_id)),
		),
		...(igMentions.data || []).map((message: Record<string, unknown>) =>
			inboxTask(userId, message, "ig_mention", stringOrNull(message.ig_account_id)),
		),
		...(dmConversations.data || []).map((message: Record<string, unknown>) =>
			inboxTask(userId, message, "ig_dm", stringOrNull(message.account_id)),
		),
	];

	const listeningRows = (listeningResults.data || []).map((result: Record<string, unknown>) => {
		const alert = alertById.get(String(result.alert_id)) || {};
		const count = Number(result.result_count || 0);
		return {
			user_id: userId,
			source: "listening_signal",
			source_id: String(result.id),
			title: `${count} listening ${count === 1 ? "hit" : "hits"} for "${result.keyword || alert.keyword || "keyword"}"`,
			priority: count >= Number(alert.threshold_value || 10) ? "high" : "medium",
			status: "open",
			workspace_id: stringOrNull(result.workspace_id ?? alert.workspace_id),
			due_at: stringOrNull(result.checked_at),
			sla_at: stringOrNull(result.checked_at),
			recommended_action: {
				type: "review_listening_signal",
				result_id: result.id,
				alert_id: result.alert_id,
				keyword: result.keyword ?? alert.keyword,
			},
			linked_entity_type: "listening_result",
			linked_entity_id: String(result.id),
			payload: {
				alert_type: alert.alert_type,
				threshold_value: alert.threshold_value,
				result_count: result.result_count,
				sentiment_breakdown: result.sentiment_breakdown,
				sample_posts: result.sample_posts,
				checked_at: result.checked_at,
			},
		};
	});

	const anomalyRows = (anomalyAlerts.data || []).map((alert: Record<string, unknown>) => ({
		user_id: userId,
		source: "anomaly_alert",
		source_id: String(alert.id),
		title: String(alert.title || "Review anomaly alert"),
		priority:
			alert.severity === "critical" || alert.severity === "high"
				? "high"
				: "medium",
		status: "open",
		account_id: stringOrNull(alert.account_id ?? alert.instagram_account_id),
		due_at: stringOrNull(alert.created_at),
		sla_at: stringOrNull(alert.created_at),
		recommended_action: {
			type: "review_anomaly_alert",
			anomaly_alert_id: alert.id,
			alert_type: alert.alert_type,
			platform: alert.platform,
		},
		linked_entity_type: "anomaly_alert",
		linked_entity_id: String(alert.id),
		payload: {
			platform: alert.platform,
			alert_type: alert.alert_type,
			severity: alert.severity,
			description: alert.description,
			created_at: alert.created_at,
		},
	}));

	const qstashDlqRows = (queueDeadLetters.data || []).map((item: Record<string, unknown>) => ({
		user_id: userId,
		source: "qstash_dlq",
		source_id: String(item.id),
		title: "Recover dead-letter auto-post queue item",
		priority: "high",
		status: "open",
		workspace_id: stringOrNull(item.workspace_id),
		group_id: stringOrNull(item.group_id),
		account_id: stringOrNull(item.account_id),
		due_at: stringOrNull(item.next_retry_at ?? item.scheduled_for),
		sla_at: stringOrNull(item.next_retry_at ?? item.scheduled_for),
		recommended_action: {
			type: "review_auto_post_dlq",
			queue_item_id: item.id,
			route: "/admin/dead-letters",
		},
		linked_entity_type: "auto_post_queue",
		linked_entity_id: String(item.id),
		payload: {
			status: item.status,
			scheduled_for: item.scheduled_for,
			retry_count: item.retry_count,
			last_error: item.last_error ?? item.error_message ?? item.dead_letter_reason,
			qstash_message_id: item.qstash_message_id,
		},
	}));

	const qstashBacklogRows = (queueDispatchBacklog.data || []).map((item: Record<string, unknown>) => ({
		user_id: userId,
		source: "qstash_dispatch_backlog",
		source_id: String(item.id),
		title: "Dispatch overdue auto-post queue item",
		priority: "high",
		status: "open",
		workspace_id: stringOrNull(item.workspace_id),
		group_id: stringOrNull(item.group_id),
		account_id: stringOrNull(item.account_id),
		due_at: stringOrNull(item.scheduled_for),
		sla_at: stringOrNull(item.scheduled_for),
		recommended_action: {
			type: "inspect_qstash_dispatch_backlog",
			queue_item_id: item.id,
			route: "/calendar?status=queued",
		},
		linked_entity_type: "auto_post_queue",
		linked_entity_id: String(item.id),
		payload: {
			status: item.status,
			scheduled_for: item.scheduled_for,
			next_retry_at: item.next_retry_at,
			retry_count: item.retry_count,
			last_error: item.last_error ?? item.error_message,
			qstash_message_id: item.qstash_message_id,
		},
	}));

	const cronRows = uniqueById([...(failedCronRuns.data || []), ...(staleCronRuns.data || [])]).map((run) => {
		const isFailed = run.status === "failed";
		return {
			user_id: userId,
			source: isFailed ? "cron_failed" : "cron_stale",
			source_id: String(run.id),
			title: isFailed
				? `Inspect failed cron: ${run.job_name || "unknown job"}`
				: `Inspect stale cron: ${run.job_name || "unknown job"}`,
			priority: isFailed ? "high" : "medium",
			status: "open",
			due_at: stringOrNull(run.started_at ?? run.created_at),
			sla_at: stringOrNull(run.started_at ?? run.created_at),
			recommended_action: {
				type: isFailed ? "inspect_failed_cron" : "inspect_stale_cron",
				cron_run_id: run.id,
				job_name: run.job_name,
			},
			linked_entity_type: "cron_run",
			linked_entity_id: String(run.id),
			payload: {
				job_name: run.job_name,
				status: run.status,
				started_at: run.started_at,
				completed_at: run.completed_at,
				duration_ms: run.duration_ms,
				items_processed: run.items_processed,
				error_message: run.error_message,
				metadata: run.metadata,
			},
		};
	});

	let reliabilityRows: Array<Record<string, unknown>> = [];
	try {
		const reliability = await loadReliabilitySections(db, userId);
		reliabilityRows = buildReliabilityOperatorTasks(userId, reliability);
	} catch {
		reliabilityRows = [];
	}

	await upsertOperatorTasks(db, [
		...approvalRows,
		...failedPostRows,
		...tokenRows,
		...syncRows,
		...webhookRows,
		...reportRows,
		...inboxRows,
		...listeningRows,
		...anomalyRows,
		...qstashDlqRows,
		...qstashBacklogRows,
		...cronRows,
		...reliabilityRows,
	]);
}

function buildReliabilityOperatorTasks(
	userId: string,
	reliability: Awaited<ReturnType<typeof loadReliabilitySections>>,
): Array<Record<string, unknown>> {
	const rowsOut: Array<Record<string, unknown>> = [];
	if (reliability.reliabilitySlo.tone !== "healthy") {
		rowsOut.push({
			user_id: userId,
			source: "reliability_slo",
			source_id: `publish-slo:${new Date().toISOString().slice(0, 10)}`,
			title: "Review scheduled publishing SLO breach",
			priority: reliability.reliabilitySlo.tone === "critical" ? "critical" : "high",
			status: "open",
			recommended_action: {
				type: "inspect_reliability_slo",
				route: "/reliability",
			},
			linked_entity_type: "reliability_slo",
			linked_entity_id: `publish-slo:${new Date().toISOString().slice(0, 10)}`,
			payload: reliability.reliabilitySlo,
		});
	}
	if (reliability.metaApiUsage.tone !== "healthy") {
		rowsOut.push({
			user_id: userId,
			source: "meta_api_usage",
			source_id: `meta-api:${new Date().toISOString().slice(0, 10)}`,
			title: "Meta API usage is near a platform limit",
			priority: reliability.metaApiUsage.tone === "critical" ? "critical" : "medium",
			status: "open",
			recommended_action: {
				type: "inspect_meta_api_usage",
				route: "/reliability",
			},
			linked_entity_type: "meta_api_usage",
			linked_entity_id: `meta-api:${new Date().toISOString().slice(0, 10)}`,
			payload: reliability.metaApiUsage,
		});
	}
	if (reliability.tokenSlo.tone !== "healthy") {
		rowsOut.push({
			user_id: userId,
			source: "token_slo",
			source_id: `token-slo:${new Date().toISOString().slice(0, 10)}`,
			title: "Token SLO needs account reconnect or refresh",
			priority: reliability.tokenSlo.tone === "critical" ? "critical" : "medium",
			status: "open",
			recommended_action: {
				type: "inspect_token_slo",
				route: "/reliability",
			},
			linked_entity_type: "token_slo",
			linked_entity_id: `token-slo:${new Date().toISOString().slice(0, 10)}`,
			payload: reliability.tokenSlo,
		});
	}
	return rowsOut;
}

type OpsHealthTone = "healthy" | "warning" | "critical";

type OpsHealthIssue = {
	key: string;
	title: string;
	severity: "warning" | "critical";
	source: string;
	route: string;
	account_id?: string | null;
	group_id?: string | null;
	workspace_id?: string | null;
};

type OpsHealthMetric = {
	key: string;
	label: string;
	value: number | string | null;
	status: OpsHealthTone;
	route: string;
};

type OpsHealthAccount = {
	accountId: string;
	handle: string;
	platform: "threads" | "instagram";
	group_id?: string | null;
	status?: string | null;
	severity: "warning" | "critical";
	reasons: string[];
	needsReauth: boolean;
	tokenExpiresAt?: string | null;
	lastSyncedAt?: string | null;
	isActive: boolean;
	route: string;
};

async function loadOperatorOpsHealth(db: ReturnType<typeof getPrivilegedSupabaseAny>, userId: string) {
	const now = Date.now();
	const cronFreshCutoff = new Date(now - 60 * 60 * 1000).toISOString();
	const staleRunningCutoff = new Date(now - 20 * 60 * 1000).toISOString();
	const stuckPublishCutoff = new Date(now - 20 * 60 * 1000).toISOString();
	const tokenSoon = new Date(now + 7 * 24 * 60 * 60 * 1000).toISOString();
	const syncStaleCutoff = new Date(now - 30 * 60 * 1000).toISOString();
	const retryCutoff = new Date(now).toISOString();

	const [
		recentCron,
		failedCron,
		staleCron,
		webhookFailures,
		threadsWebhookDlq,
		igWebhookDlq,
		queueBacklog,
		queueDlq,
		stuckPosts,
		failedPosts,
		recentPublishedScheduledPosts,
		syncLag,
		threadTokenIssues,
		igTokenIssues,
		threadHealthAccounts,
		igHealthAccounts,
	] = await Promise.all([
		db
			.from("cron_runs")
			.select("id, job_name, status, completed_at, started_at, created_at")
			.in("status", ["success", "completed"])
			.gte("completed_at", cronFreshCutoff)
			.order("completed_at", { ascending: false })
			.limit(20),
		db
			.from("cron_runs")
			.select("id, job_name, status, error_message, created_at")
			.eq("status", "failed")
			.gte("created_at", new Date(now - 24 * 60 * 60 * 1000).toISOString())
			.order("created_at", { ascending: false })
			.limit(20),
		db
			.from("cron_runs")
			.select("id, job_name, status, started_at")
			.eq("status", "running")
			.lt("started_at", staleRunningCutoff)
			.order("started_at", { ascending: false })
			.limit(20),
		db
			.from("webhook_deliveries")
			.select("id, event, status, next_retry_at, created_at")
			.eq("user_id", userId)
			.in("status", ["failed", "dead_letter"])
			.order("created_at", { ascending: false })
			.limit(50),
		db
			.from("threads_webhook_events")
			.select("id, account_id, dead_letter, dead_letter_at")
			.eq("user_id", userId)
			.eq("dead_letter", true)
			.order("dead_letter_at", { ascending: false })
			.limit(50),
		db
			.from("ig_webhook_events")
			.select("id, ig_account_id, dead_letter, dead_letter_at")
			.eq("user_id", userId)
			.eq("dead_letter", true)
			.order("dead_letter_at", { ascending: false })
			.limit(50),
		db
			.from("auto_post_queue")
			.select("id, workspace_id, group_id, account_id, status, scheduled_for, next_retry_at")
			.eq("user_id", userId)
			.in("status", ["pending", "processing", "retrying"])
			.lte("scheduled_for", retryCutoff)
			.order("scheduled_for", { ascending: true })
			.limit(100),
		db
			.from("auto_post_queue")
			.select("id, workspace_id, group_id, account_id, status, dead_letter_at")
			.eq("user_id", userId)
			.eq("status", "dead_letter")
			.order("dead_letter_at", { ascending: false })
			.limit(100),
		db
			.from("posts")
			.select("id, account_id, platform, status, updated_at")
			.eq("user_id", userId)
			.in("status", ["publishing", "scheduled"])
			.lt("updated_at", stuckPublishCutoff)
			.order("updated_at", { ascending: true })
			.limit(100),
		db
			.from("posts")
			.select("id, account_id, platform, status, updated_at")
			.eq("user_id", userId)
			.eq("status", "failed")
			.order("updated_at", { ascending: false })
			.limit(100),
		db
			.from("posts")
			.select("id, account_id, instagram_account_id, platform, scheduled_for, published_at")
			.eq("user_id", userId)
			.eq("status", "published")
			.not("scheduled_for", "is", null)
			.not("published_at", "is", null)
			.gte("published_at", new Date(now - 24 * 60 * 60 * 1000).toISOString())
			.order("published_at", { ascending: false })
			.limit(200),
		db
			.from("sync_jobs")
			.select("id, job_type, status, account_count, failed_count, updated_at")
			.eq("user_id", userId)
			.in("status", ["queued", "processing", "failed"])
			.lt("updated_at", syncStaleCutoff)
			.order("updated_at", { ascending: false })
			.limit(100),
		db
			.from("accounts")
			.select("id, group_id, needs_reauth, token_expires_at")
			.eq("user_id", userId)
			.eq("is_active", true)
			.or(`needs_reauth.eq.true,token_expires_at.lte.${tokenSoon}`)
			.limit(100),
		db
			.from("instagram_accounts")
			.select("id, group_id, needs_reauth, token_expires_at")
			.eq("user_id", userId)
			.eq("is_active", true)
			.or(`needs_reauth.eq.true,token_expires_at.lte.${tokenSoon}`)
			.limit(100),
		db
			.from("accounts")
			.select("id, username, group_id, status, needs_reauth, token_expires_at, last_synced_at, is_active, is_retired")
			.eq("user_id", userId)
			.limit(500),
		db
			.from("instagram_accounts")
			.select("id, username, group_id, status, needs_reauth, token_expires_at, last_synced_at, is_active")
			.eq("user_id", userId)
			.limit(500),
	]);

	const issues: OpsHealthIssue[] = [];
	const metrics: OpsHealthMetric[] = [];
	const pushMetric = (
		key: string,
		label: string,
		value: number | string | null,
		status: OpsHealthTone,
		route: string,
	) => metrics.push({ key, label, value, status, route });
	const pushIssue = (
		key: string,
		title: string,
		severity: "warning" | "critical",
		source: string,
		route: string,
		scope?: Partial<OpsHealthIssue>,
	) => issues.push({ key, title, severity, source, route, ...scope });

	const failedCronRows = rows(failedCron);
	const staleCronRows = rows(staleCron);
	const webhookRows = rows(webhookFailures);
	const threadsDlqRows = rows(threadsWebhookDlq);
	const igDlqRows = rows(igWebhookDlq);
	const queueRows = rows(queueBacklog);
	const queueDlqRows = rows(queueDlq);
	const stuckPostRows = rows(stuckPosts);
	const failedPostRows = rows(failedPosts);
	const recentScheduledPublishRows = rows(recentPublishedScheduledPosts);
	const syncRows = rows(syncLag);
	const tokenRows = [...rows(threadTokenIssues), ...rows(igTokenIssues)];
	const recentCronRows = rows(recentCron);
	const unhealthyAccounts = buildOpsHealthAccounts(
		[...rows(threadHealthAccounts).map((row) => ({ ...row, platform: "threads" })), ...rows(igHealthAccounts).map((row) => ({ ...row, platform: "instagram" }))],
		now,
		tokenSoon,
		syncStaleCutoff,
	);
	const publishDriftRows = recentScheduledPublishRows
		.map((row) => {
			const scheduledAt = Date.parse(String(row.scheduled_for || ""));
			const publishedAt = Date.parse(String(row.published_at || ""));
			if (!Number.isFinite(scheduledAt) || !Number.isFinite(publishedAt)) return null;
			return { row, driftSeconds: Math.max(0, Math.round((publishedAt - scheduledAt) / 1000)) };
		})
		.filter((entry): entry is { row: Record<string, unknown>; driftSeconds: number } => !!entry);
	const avgPublishDriftSeconds =
		publishDriftRows.length > 0
			? Math.round(publishDriftRows.reduce((sum, entry) => sum + entry.driftSeconds, 0) / publishDriftRows.length)
			: 0;
	const overFiveMinuteDrift = publishDriftRows.filter((entry) => entry.driftSeconds > 300);

	pushMetric("cron_freshness", "Fresh cron runs", recentCronRows.length, recentCronRows.length > 0 ? "healthy" : "warning", "/settings?tab=ops");
	pushMetric("webhook_backlog", "Webhook failures", webhookRows.length + threadsDlqRows.length + igDlqRows.length, webhookRows.length + threadsDlqRows.length + igDlqRows.length > 0 ? "warning" : "healthy", "/settings?tab=webhooks");
	pushMetric("queue_backlog", "Due queue items", queueRows.length, queueRows.length > 20 ? "critical" : queueRows.length > 0 ? "warning" : "healthy", "/calendar?status=queued");
	pushMetric("qstash_dlq", "Auto-post DLQ", queueDlqRows.length, queueDlqRows.length > 0 ? "critical" : "healthy", "/admin/dead-letters");
	pushMetric("failed_posts", "Failed posts", failedPostRows.length, failedPostRows.length > 0 ? "critical" : "healthy", "/calendar?status=failed");
	pushMetric(
		"publish_drift",
		"Publish drift avg",
		publishDriftRows.length > 0 ? `${avgPublishDriftSeconds}s` : null,
		overFiveMinuteDrift.length > 0 ? "warning" : "healthy",
		"/calendar?status=published",
	);
	pushMetric("sync_lag", "Stale sync jobs", syncRows.length, syncRows.length > 0 ? "warning" : "healthy", "/accounts?status=flagged");
	pushMetric("token_health", "Token issues", tokenRows.length, tokenRows.length > 0 ? "critical" : "healthy", "/accounts?status=flagged");
	pushMetric("stuck_publishing", "Stuck posts", stuckPostRows.length, stuckPostRows.length > 0 ? "critical" : "healthy", "/calendar?status=scheduled");
	pushMetric("account_health", "Unhealthy accounts", unhealthyAccounts.length, unhealthyAccounts.some((account) => account.severity === "critical") ? "critical" : unhealthyAccounts.length > 0 ? "warning" : "healthy", "/accounts?status=flagged");

	for (const row of failedCronRows.slice(0, 3)) {
		pushIssue(`cron_failed:${row.id}`, `Cron failed: ${row.job_name || "unknown job"}`, "critical", "cron_runs", "/settings?tab=ops");
	}
	for (const row of staleCronRows.slice(0, 3)) {
		pushIssue(`cron_stale:${row.id}`, `Cron still running: ${row.job_name || "unknown job"}`, "warning", "cron_runs", "/settings?tab=ops");
	}
	for (const row of queueDlqRows.slice(0, 3)) {
		pushIssue(`queue_dlq:${row.id}`, "Auto-post queue item is dead-lettered", "critical", "auto_post_queue", "/admin/dead-letters", scopeFromRow(row));
	}
	for (const row of failedPostRows.slice(0, 3)) {
		pushIssue(`failed_post:${row.id}`, `Failed ${row.platform || "social"} post needs recovery`, "critical", "posts", "/calendar?status=failed", scopeFromRow(row));
	}
	for (const entry of overFiveMinuteDrift.slice(0, 3)) {
		pushIssue(
			`publish_drift:${entry.row.id}`,
			`Scheduled publish drifted by ${entry.driftSeconds}s`,
			entry.driftSeconds > 900 ? "critical" : "warning",
			"posts",
			"/calendar?status=published",
			scopeFromRow(entry.row),
		);
	}
	for (const row of tokenRows.slice(0, 3)) {
		pushIssue(`token:${row.id}`, "Account token needs attention", "critical", "accounts", "/accounts?status=flagged", scopeFromRow(row));
	}
	for (const row of syncRows.slice(0, 3)) {
		pushIssue(`sync:${row.id}`, `Stale ${row.job_type || "sync"} job`, "warning", "sync_jobs", "/accounts?status=flagged");
	}
	for (const row of webhookRows.slice(0, 3)) {
		pushIssue(`webhook:${row.id}`, `Webhook delivery ${row.status || "failed"}`, row.status === "dead_letter" ? "critical" : "warning", "webhook_deliveries", "/settings?tab=webhooks");
	}

	const criticalCount = issues.filter((issue) => issue.severity === "critical").length;
	const warningCount = issues.filter((issue) => issue.severity === "warning").length;
	const score = Math.max(0, 100 - criticalCount * 18 - warningCount * 7);
	const tone: OpsHealthTone = criticalCount > 0 ? "critical" : warningCount > 0 ? "warning" : "healthy";
	const impactedAccountIds = Array.from(
		new Set(
			issues
				.map((issue) => issue.account_id)
				.concat(unhealthyAccounts.map((account) => account.accountId))
				.filter((value): value is string => typeof value === "string" && value.length > 0),
		),
	);

	return {
		generatedAt: new Date().toISOString(),
		score,
		tone,
		summary: {
			critical: criticalCount,
			warning: warningCount,
			healthy: criticalCount === 0 && warningCount === 0,
			impactedAccountCount: impactedAccountIds.length,
		},
		metrics,
		issues: issues.slice(0, 12),
		impactedAccountIds,
		unhealthyAccounts: unhealthyAccounts.slice(0, 200),
		unhealthyAccountTotal: unhealthyAccounts.length,
		lastSuccessfulCronAt: stringOrNull(recentCronRows[0]?.completed_at ?? recentCronRows[0]?.created_at),
	};
}

function buildOpsHealthAccounts(
	rows: Array<Record<string, unknown>>,
	now: number,
	tokenSoonIso: string,
	syncStaleCutoffIso: string,
): OpsHealthAccount[] {
	const tokenSoon = Date.parse(tokenSoonIso);
	const syncStaleCutoff = Date.parse(syncStaleCutoffIso);
	return rows
		.map((row): OpsHealthAccount | null => {
			const accountId = stringOrNull(row.id);
			if (!accountId) return null;
			const platform = row.platform === "instagram" ? "instagram" : "threads";
			const status = stringOrNull(row.status);
			const tokenExpiresAt = stringOrNull(row.token_expires_at);
			const lastSyncedAt = stringOrNull(row.last_synced_at);
			const tokenTime = tokenExpiresAt ? Date.parse(tokenExpiresAt) : NaN;
			const syncTime = lastSyncedAt ? Date.parse(lastSyncedAt) : NaN;
			const isActive = row.is_active !== false;
			const isRetired = row.is_retired === true;
			const needsReauth = row.needs_reauth === true || status === "needs_reauth";
			const tokenExpired = Number.isFinite(tokenTime) && tokenTime <= now;
			const tokenExpiring = Number.isFinite(tokenTime) && tokenTime > now && tokenTime <= tokenSoon;
			const staleSync = !Number.isFinite(syncTime) || syncTime < syncStaleCutoff;
			const reasons = [
				needsReauth ? "Needs reauth" : "",
				tokenExpired ? "Token expired" : "",
				!tokenExpired && tokenExpiring ? "Token expiring" : "",
				!isActive ? "Inactive" : "",
				isRetired ? "Retired" : "",
				staleSync ? "Stale sync" : "",
			].filter(Boolean);
			if (!reasons.length) return null;
			return {
				accountId,
				handle: stringOrNull(row.username) ?? accountId,
				platform,
				group_id: stringOrNull(row.group_id),
				status,
				severity: needsReauth || tokenExpired || !isActive ? "critical" : "warning",
				reasons,
				needsReauth,
				tokenExpiresAt,
				lastSyncedAt,
				isActive,
				route: `/accounts?status=flagged&accountId=${encodeURIComponent(accountId)}`,
			};
		})
		.filter((row): row is OpsHealthAccount => !!row)
		.sort((a, b) => severityRank(b.severity) - severityRank(a.severity) || a.handle.localeCompare(b.handle));
}

function severityRank(severity: "warning" | "critical"): number {
	return severity === "critical" ? 2 : 1;
}

async function loadOperatorFleetCapacity(
	db: ReturnType<typeof getPrivilegedSupabaseAny>,
	userId: string,
	capacityStart?: string | null,
) {
	const parsedStart = capacityStart ? Date.parse(`${capacityStart}T00:00:00`) : NaN;
	const start = Number.isFinite(parsedStart) ? new Date(parsedStart) : new Date();
	start.setHours(0, 0, 0, 0);
	const end = new Date(start.getTime() + 8 * 24 * 60 * 60 * 1000);

	const [accounts, igAccounts, groups, posts, queue] = await Promise.all([
		db
			.from("accounts")
			.select("id, group_id, username, display_name, is_active")
			.eq("user_id", userId)
			.eq("is_active", true)
			.limit(500),
		db
			.from("instagram_accounts")
			.select("id, group_id, username, display_name, is_active")
			.eq("user_id", userId)
			.eq("is_active", true)
			.limit(500),
		db
			.from("account_groups")
			.select("id, name, color")
			.eq("user_id", userId)
			.limit(500),
		db
			.from("posts")
			.select("id, account_id, instagram_account_id, group_id, platform, status, scheduled_for, approval_status")
			.eq("user_id", userId)
			.gte("scheduled_for", start.toISOString())
			.lt("scheduled_for", end.toISOString())
			.in("status", ["scheduled", "publishing", "failed"])
			.order("scheduled_for", { ascending: true })
			.limit(2000),
		db
			.from("auto_post_queue")
			.select("id, account_id, group_id, status, scheduled_for, pool_status")
			.eq("user_id", userId)
			.gte("scheduled_for", start.toISOString())
			.lt("scheduled_for", end.toISOString())
			.in("status", ["pending", "processing", "retrying", "dead_letter"])
			.order("scheduled_for", { ascending: true })
			.limit(2000),
	]);

	const groupRows = rows(groups);
	const groupById = new Map(groupRows.map((group) => [String(group.id), group]));
	const activeAccountRows: Array<Record<string, unknown> & { platform: string }> = [
		...rows(accounts).map((row) => ({ ...row, platform: "threads" })),
		...rows(igAccounts).map((row) => ({ ...row, platform: "instagram" })),
	];
	const activeAccountIds = new Set(activeAccountRows.map((row) => stringOrNull(row.id)).filter(Boolean) as string[]);
	const days = Array.from({ length: 7 }, (_, index) => {
		const date = new Date(start.getTime() + index * 24 * 60 * 60 * 1000);
		const key = date.toISOString().slice(0, 10);
		return {
			date: key,
			scheduled: 0,
			publishing: 0,
			failed: 0,
			pendingQueue: 0,
			deadLetter: 0,
			approvalPending: 0,
			accountIds: [] as string[],
			gapCount: 0,
			tone: "healthy" as OpsHealthTone,
		};
	});
	const dayByKey = new Map(days.map((day) => [day.date, day]));
	const accountDayRows = activeAccountRows.map((account) => {
		const groupId = stringOrNull(account.group_id);
		const group = groupId ? groupById.get(groupId) : null;
		const accountId = String(account.id);
		return {
			accountId,
			handle: stringOrNull(account.username) ? `@${String(account.username)}` : accountId,
			displayName: stringOrNull(account.display_name) ?? stringOrNull(account.username) ?? "Unnamed account",
			groupId,
			groupName: stringOrNull(group?.name) ?? "Ungrouped",
			groupColor: stringOrNull(group?.color),
			platform: String(account.platform || "threads"),
			days: days.map((day) => ({
				date: day.date,
				planned: 0,
				scheduled: 0,
				publishing: 0,
				failed: 0,
				pendingQueue: 0,
				deadLetter: 0,
				approvalPending: 0,
				hasGap: true,
				hasConflict: false,
				tone: "warning" as OpsHealthTone,
				recommendedAction: "fill_gap",
			})),
		};
	});
	const accountById = new Map(accountDayRows.map((account) => [account.accountId, account]));
	const recommendations: Array<Record<string, unknown>> = [];

	for (const post of rows(posts)) {
		const key = dayKey(post.scheduled_for);
		const day = key ? dayByKey.get(key) : null;
		if (!day) continue;
		const status = String(post.status || "");
		const accountId = stringOrNull(post.account_id ?? post.instagram_account_id);
		const accountDay = accountId
			? accountById.get(accountId)?.days.find((item) => item.date === key)
			: null;
		if (status === "failed") day.failed += 1;
		else if (status === "publishing") day.publishing += 1;
		else day.scheduled += 1;
		if (post.approval_status === "pending") day.approvalPending += 1;
		if (accountDay) {
			if (status === "failed") accountDay.failed += 1;
			else if (status === "publishing") accountDay.publishing += 1;
			else accountDay.scheduled += 1;
			if (post.approval_status === "pending") accountDay.approvalPending += 1;
		}
		if (accountId && !day.accountIds.includes(accountId)) day.accountIds.push(accountId);
	}

	for (const item of rows(queue)) {
		const key = dayKey(item.scheduled_for);
		const day = key ? dayByKey.get(key) : null;
		if (!day) continue;
		if (item.status === "dead_letter") day.deadLetter += 1;
		else day.pendingQueue += 1;
		const accountId = stringOrNull(item.account_id);
		const accountDay = accountId
			? accountById.get(accountId)?.days.find((entry) => entry.date === key)
			: null;
		if (accountDay) {
			if (item.status === "dead_letter") accountDay.deadLetter += 1;
			else accountDay.pendingQueue += 1;
		}
		if (accountId && !day.accountIds.includes(accountId)) day.accountIds.push(accountId);
	}

	for (const account of accountDayRows) {
		for (const day of account.days) {
			day.planned = day.scheduled + day.publishing + day.pendingQueue;
			day.hasGap = day.planned === 0 && day.failed === 0 && day.deadLetter === 0;
			day.hasConflict = day.planned >= 4;
			day.tone =
				day.failed > 0 || day.deadLetter > 0
					? "critical"
					: day.hasGap || day.hasConflict || day.approvalPending > 0
						? "warning"
						: "healthy";
			day.recommendedAction =
				day.failed > 0 || day.deadLetter > 0
					? "recover_failed"
					: day.approvalPending > 0
						? "review_approval"
						: day.hasConflict
							? "rebalance_conflict"
							: day.hasGap
								? "fill_gap"
								: "none";
			if (day.recommendedAction !== "none") {
				recommendations.push({
					type: day.recommendedAction,
					accountId: account.accountId,
					accountHandle: account.handle,
					groupId: account.groupId,
					platform: account.platform,
					date: day.date,
					priority: day.tone === "critical" ? "high" : "medium",
				});
			}
		}
	}

	for (const day of days) {
		day.gapCount = Math.max(0, activeAccountIds.size - day.accountIds.length);
		day.tone = day.failed > 0 || day.deadLetter > 0
			? "critical"
			: day.gapCount > Math.max(10, activeAccountIds.size * 0.5) || day.approvalPending > 0
				? "warning"
				: "healthy";
	}

	const totals = days.reduce(
		(acc, day) => ({
			scheduled: acc.scheduled + day.scheduled,
			publishing: acc.publishing + day.publishing,
			failed: acc.failed + day.failed,
			pendingQueue: acc.pendingQueue + day.pendingQueue,
			deadLetter: acc.deadLetter + day.deadLetter,
			approvalPending: acc.approvalPending + day.approvalPending,
			gapCount: acc.gapCount + day.gapCount,
		}),
		{ scheduled: 0, publishing: 0, failed: 0, pendingQueue: 0, deadLetter: 0, approvalPending: 0, gapCount: 0 },
	);
	const criticalDays = days.filter((day) => day.tone === "critical").length;
	const warningDays = days.filter((day) => day.tone === "warning").length;
	return {
		generatedAt: new Date().toISOString(),
		windowDays: 7,
		activeAccountCount: activeAccountIds.size,
		score: Math.max(0, 100 - criticalDays * 18 - warningDays * 8),
		tone: criticalDays > 0 ? "critical" : warningDays > 0 ? "warning" : "healthy",
		totals,
		days: days.map((day) => ({
			...day,
			accountCount: day.accountIds.length,
			accountIds: day.accountIds.slice(0, 50),
		})),
		groups: groupRows.map((group) => ({
			id: String(group.id),
			name: stringOrNull(group.name) ?? "Untitled group",
			color: stringOrNull(group.color),
			accountCount: accountDayRows.filter((account) => account.groupId === String(group.id)).length,
		})),
		accounts: accountDayRows,
		recommendations: recommendations.slice(0, 100),
	};
}

async function loadOperatorAIEvalSummary(db: ReturnType<typeof getPrivilegedSupabaseAny>, userId: string) {
	const since = new Date(Date.now() - 14 * 24 * 60 * 60 * 1000).toISOString();
	const { data } = await db
		.from("ai_eval_snapshots")
		.select("id, suite_name, case_id, category, provider, model, regression_score, passed, failures, captured_at")
		.eq("user_id", userId)
		.gte("captured_at", since)
		.order("captured_at", { ascending: false })
		.limit(250);
	const snapshots = rows({ data });
	const report = buildAIEvalReport(snapshots);
	const directSurfaceSet = new Set(
		snapshots
			.filter((row) => String(row.suite_name || "").startsWith("live:"))
			.map((row) => String(row.suite_name || "").replace(/^live:/, "")),
	);
	const uncoveredDirectSurfaces = AI_EVAL_DIRECT_GENERATIVE_SURFACES.filter(
		(surface) => !directSurfaceSet.has(surface),
	);
	return {
		generatedAt: new Date().toISOString(),
		windowDays: 14,
		total: report.total,
		passed: report.passed,
		failed: report.failed,
		passRate: report.passRate,
		avgRegressionScore: report.avgRegressionScore,
		tone: report.failed > 0 || !report.thresholds.passed
			? (report.passRate < 80 || !report.thresholds.passed ? "critical" : "warning")
			: "healthy",
		latestFailures: report.latestFailures,
		trend: report.trend,
		suites: report.suites,
		thresholds: report.thresholds,
		coverage: {
			hasGoldenEvals: snapshots.some((row) => String(row.suite_name || "").includes("golden")),
			hasLiveSnapshots: snapshots.some((row) => String(row.suite_name || "").includes("live")),
			directGenerativeSurfaceCount: AI_EVAL_DIRECT_GENERATIVE_SURFACES.length,
			directGenerativeCoveredCount:
				AI_EVAL_DIRECT_GENERATIVE_SURFACES.length - uncoveredDirectSurfaces.length,
			documentedNonGenerativeCount: AI_EVAL_DOCUMENTED_NON_GENERATIVE_SURFACES.length,
			uncoveredDirectSurfaces,
		},
	};
}

function rows(result: unknown): Record<string, unknown>[] {
	const data = (result as { data?: unknown } | null)?.data;
	return Array.isArray(data) ? data.filter((row): row is Record<string, unknown> => !!row && typeof row === "object" && !Array.isArray(row)) : [];
}

function dayKey(value: unknown): string | null {
	const iso = stringOrNull(value);
	if (!iso) return null;
	const time = Date.parse(iso);
	if (!Number.isFinite(time)) return null;
	return new Date(time).toISOString().slice(0, 10);
}

function scopeFromRow(row: Record<string, unknown>): Partial<OpsHealthIssue> {
	return {
		account_id: stringOrNull(row.account_id ?? row.instagram_account_id ?? row.ig_account_id),
		group_id: stringOrNull(row.group_id),
		workspace_id: stringOrNull(row.workspace_id),
	};
}

function inboxTask(
	userId: string,
	message: Record<string, unknown>,
	source: "threads_reply" | "threads_mention" | "ig_comment" | "ig_mention" | "ig_dm",
	accountId: string | null,
): Record<string, unknown> {
	const text =
		stringOrNull(message.content) ??
		stringOrNull(message.text) ??
		stringOrNull(message.caption) ??
		stringOrNull(message.last_message_text) ??
		"Unread inbox item";
	const username =
		stringOrNull(message.username) ??
		stringOrNull(message.mentioned_by_username) ??
		stringOrNull(message.participant_username) ??
		"unknown";
	const occurredAt =
		stringOrNull(message.created_at) ??
		stringOrNull(message.mentioned_at) ??
		stringOrNull(message.last_message_at);
	return {
		user_id: userId,
		source: "inbox_attention",
		source_id: `${source}:${String(message.id)}`,
		title: `${inboxSourceLabel(source)} from @${username}`,
		priority: source === "ig_dm" ? "high" : "medium",
		status: "open",
		account_id: accountId,
		due_at: occurredAt,
		sla_at: occurredAt,
		recommended_action: {
			type: "review_inbox_item",
			inbox_source: source,
			message_id: `${source}_${String(message.id)}`,
		},
		linked_entity_type: source,
		linked_entity_id: String(message.id),
		payload: {
			username,
			text,
			occurred_at: occurredAt,
			post_id: message.post_id,
			permalink: message.permalink,
		},
	};
}

function accountTokenTask(
	userId: string,
	account: Record<string, unknown>,
	platform: "threads" | "instagram",
): Record<string, unknown> | null {
	const expiresAt = stringOrNull(account.token_expires_at);
	const expiresMs = expiresAt ? Date.parse(expiresAt) : Number.NaN;
	const expired = Number.isFinite(expiresMs) && expiresMs <= Date.now();
	const needsReauth = account.needs_reauth === true || account.status === "needs_reauth" || expired;
	if (!needsReauth && !expiresAt) return null;
	return {
		user_id: userId,
		source: needsReauth ? "token_reauth" : "token_expiring",
		source_id: `${platform}:${String(account.id)}`,
		title: needsReauth
			? `Reconnect ${platformLabel(platform)} account ${accountHandle(account)}`
			: `${platformLabel(platform)} token expires soon: ${accountHandle(account)}`,
		priority: needsReauth ? "critical" : "high",
		status: "open",
		account_id: stringOrNull(account.id),
		group_id: stringOrNull(account.group_id),
		due_at: expiresAt,
		sla_at: expiresAt,
		recommended_action: {
			type: needsReauth ? "reconnect_account" : "refresh_account_token",
			platform,
			account_id: account.id,
		},
		linked_entity_type: `${platform}_account`,
		linked_entity_id: String(account.id),
		payload: {
			platform,
			username: account.username,
			status: account.status,
			needs_reauth: account.needs_reauth,
			token_expires_at: account.token_expires_at,
			last_synced_at: account.last_synced_at,
		},
	};
}

async function upsertOperatorTasks(
	db: ReturnType<typeof getPrivilegedSupabaseAny>,
	rows: Array<Record<string, unknown>>,
) {
	for (const row of rows) await upsertOperatorTask(db, row);
}

async function upsertOperatorTask(
	db: ReturnType<typeof getPrivilegedSupabaseAny>,
	row: Record<string, unknown>,
): Promise<Record<string, unknown> | null> {
	const { data: existing } = await db
		.from("operator_tasks")
		.select("id, status")
		.eq("user_id", row.user_id)
		.eq("source", row.source)
		.eq("source_id", row.source_id)
		.maybeSingle();

	if (existing) {
		if (["resolved", "ignored"].includes(String(existing.status))) return existing;
		const { data } = await db
			.from("operator_tasks")
			.update({
				...row,
				status: existing.status,
				updated_at: new Date().toISOString(),
			})
			.eq("id", existing.id)
			.select("*")
			.maybeSingle();
		return data ?? existing;
	}

	const { data } = await db.from("operator_tasks").insert(row).select("*").maybeSingle();
	return data ?? null;
}

async function updateOperatorTaskRecord(
	db: ReturnType<typeof getPrivilegedSupabaseAny>,
	userId: string,
	input: TaskUpdateInput,
): Promise<
	| { ok: true; task: Record<string, unknown> }
	| { ok: false; status: number; message: string }
> {
	if (!input.id && (!input.source || !input.source_id)) {
		return { ok: false, status: 400, message: "Task id or source/source_id is required" };
	}
	const patch = {
		status: input.status,
		resolution_reason: input.resolution_reason ?? null,
		snoozed_until: input.snoozed_until ?? null,
		resolved_at: ["resolved", "ignored"].includes(input.status)
			? new Date().toISOString()
			: null,
		updated_at: new Date().toISOString(),
	};
	let updateQuery = db
		.from("operator_tasks")
		.update(patch)
		.eq("user_id", userId);
	updateQuery = input.id
		? updateQuery.eq("id", input.id)
		: updateQuery
			.eq("source", input.source)
			.eq("source_id", input.source_id);
	const { data, error } = await updateQuery
		.select("*")
		.single();
	if (error || !data) return { ok: false, status: 404, message: "Operator task not found" };
	return { ok: true, task: data };
}

function readInboxSource(messageId: string):
	| "ig_mention"
	| "threads_mention"
	| "threads_reply"
	| "ig_comment"
	| "ig_dm"
	| "fallback" {
	if (messageId.startsWith("ig_mention_")) return "ig_mention";
	if (messageId.startsWith("threads_mention_")) return "threads_mention";
	if (messageId.startsWith("threads_reply_")) return "threads_reply";
	if (messageId.startsWith("ig_comment_")) return "ig_comment";
	if (messageId.startsWith("ig_dm_")) return "ig_dm";
	return "fallback";
}

function stripInboxPrefix(messageId: string, prefix: string): string {
	return messageId.startsWith(prefix) ? messageId.slice(prefix.length) : messageId;
}

async function markInboxMessageReadForOperator(
	db: ReturnType<typeof getPrivilegedSupabaseAny>,
	userId: string,
	messageId: string,
	read: boolean,
): Promise<{ ok: true } | { ok: false; status: number; message: string }> {
	const source = readInboxSource(messageId);
	if (source === "ig_mention") {
		const { error } = await db
			.from("ig_mentions")
			.update({ is_read: read })
			.eq("id", stripInboxPrefix(messageId, "ig_mention_"))
			.eq("user_id", userId);
		if (error) return { ok: false, status: 500, message: "Failed to update Instagram mention" };
	} else if (source === "threads_mention") {
		const { error } = await db
			.from("mentions")
			.update({ is_read: read })
			.eq("id", stripInboxPrefix(messageId, "threads_mention_"))
			.eq("user_id", userId);
		if (error) return { ok: false, status: 500, message: "Failed to update Threads mention" };
	} else if (source === "ig_dm") {
		const { error } = await db
			.from("inbox_dm_cache")
			.update({ is_read: read })
			.eq("id", stripInboxPrefix(messageId, "ig_dm_"))
			.eq("user_id", userId);
		if (error) return { ok: false, status: 500, message: "Failed to update Instagram DM" };
	} else if (source === "threads_reply") {
		const replyId = stripInboxPrefix(messageId, "threads_reply_");
		const { data: reply } = await db
			.from("post_replies")
			.select("id, post_id")
			.eq("id", replyId)
			.maybeSingle();
		const { data: post } = reply?.post_id
			? await db
				.from("posts")
				.select("id")
				.eq("id", reply.post_id)
				.eq("user_id", userId)
				.maybeSingle()
			: { data: null };
		if (!post?.id) return { ok: false, status: 404, message: "Threads reply not found" };
		const { error } = await db
			.from("post_replies")
			.update({ is_read: read })
			.eq("id", replyId);
		if (error) return { ok: false, status: 500, message: "Failed to update Threads reply" };
	} else if (source === "ig_comment") {
		const commentId = stripInboxPrefix(messageId, "ig_comment_");
		const { data: comment } = await db
			.from("ig_comments")
			.select("id, post_id")
			.eq("id", commentId)
			.maybeSingle();
		const { data: post } = comment?.post_id
			? await db
				.from("posts")
				.select("id")
				.eq("id", comment.post_id)
				.eq("user_id", userId)
				.maybeSingle()
			: { data: null };
		if (!post?.id) return { ok: false, status: 404, message: "Instagram comment not found" };
		const { error } = await db
			.from("ig_comments")
			.update({ is_read: read })
			.eq("id", commentId);
		if (error) return { ok: false, status: 500, message: "Failed to update Instagram comment" };
	} else {
		return { ok: false, status: 400, message: "Unsupported inbox message id" };
	}

	const sourceId = `${source}:${stripInboxPrefix(messageId, `${source}_`)}`;
	await db
		.from("operator_tasks")
		.update({
			status: read ? "resolved" : "open",
			resolution_reason: read ? "Marked done by approved operator action" : null,
			resolved_at: read ? new Date().toISOString() : null,
			snoozed_until: null,
			updated_at: new Date().toISOString(),
		})
		.eq("user_id", userId)
		.eq("source", "inbox_attention")
		.eq("source_id", sourceId);

	return { ok: true };
}

async function updateSourceWorkflowState(
	db: ReturnType<typeof getPrivilegedSupabaseAny>,
	userId: string,
	input: SourceWorkflowUpdate,
): Promise<
	| { ok: true; task: Record<string, unknown> }
	| { ok: false; status: number; message: string }
> {
	const now = new Date().toISOString();
	const completed = ["resolved", "ignored"].includes(input.status);
	const patch = {
		status: input.status,
		resolution_reason: input.resolution_reason ?? workflowResolution(input),
		resolved_at: completed ? now : null,
		snoozed_until: input.status === "snoozed" ? input.snoozed_until : null,
		updated_at: now,
	};

	if (input.source === "anomaly_alert") {
		const { data: alert, error } = await db
			.from("anomaly_alerts")
			.select("id, user_id, account_id, instagram_account_id, platform, alert_type, severity, title, description, created_at")
			.eq("id", input.source_id)
			.eq("user_id", userId)
			.maybeSingle();
		if (error || !alert) return { ok: false, status: 404, message: "Anomaly alert not found" };
		const dismissAt = completed ? now : null;
		const { error: dismissError } = await db
			.from("anomaly_alerts")
			.update({ dismissed_at: dismissAt })
			.eq("id", input.source_id)
			.eq("user_id", userId);
		if (dismissError) return { ok: false, status: 500, message: "Failed to update anomaly alert" };
		input = {
			...input,
			title: input.title ?? String(alert.title || "Review anomaly alert"),
			priority:
				input.priority ??
				(alert.severity === "critical" || alert.severity === "high" ? "high" : "medium"),
			account_id: input.account_id ?? stringOrNull(alert.account_id ?? alert.instagram_account_id),
			payload: input.payload ?? {
				platform: alert.platform,
				alert_type: alert.alert_type,
				severity: alert.severity,
				description: alert.description,
				created_at: alert.created_at,
			},
		};
	}

	const { data: existing } = await db
		.from("operator_tasks")
		.select("*")
		.eq("user_id", userId)
		.eq("source", input.source)
		.eq("source_id", input.source_id)
		.maybeSingle();

	if (existing) {
		const { data, error } = await db
			.from("operator_tasks")
			.update(patch)
			.eq("id", existing.id)
			.eq("user_id", userId)
			.select("*")
			.single();
		if (error || !data) return { ok: false, status: 500, message: "Failed to update workflow task" };
		return { ok: true, task: data };
	}

	const row = {
		user_id: userId,
		source: input.source,
		source_id: input.source_id,
		title: input.title ?? defaultWorkflowTitle(input.source),
		priority: input.priority ?? "medium",
		status: input.status,
		workspace_id: input.workspace_id ?? null,
		group_id: input.group_id ?? null,
		account_id: input.account_id ?? null,
		snoozed_until: input.status === "snoozed" ? input.snoozed_until : null,
		resolved_at: completed ? now : null,
		resolution_reason: input.resolution_reason ?? workflowResolution(input),
		recommended_action: {
			type: workflowActionType(input.source),
			source: input.source,
			source_id: input.source_id,
		},
		linked_entity_type: input.source,
		linked_entity_id: input.source_id,
		payload: input.payload ?? {},
	};
	const { data, error } = await db
		.from("operator_tasks")
		.insert(row)
		.select("*")
		.single();
	if (error || !data) return { ok: false, status: 500, message: "Failed to create workflow task" };
	return { ok: true, task: data };
}

function defaultWorkflowTitle(source: SourceWorkflowUpdate["source"]): string {
	switch (source) {
		case "anomaly_alert":
			return "Review anomaly alert";
		case "competitor_signal":
			return "Review competitor signal";
		case "trend_signal":
			return "Review trend signal";
		default:
			return "Review listening signal";
	}
}

function workflowActionType(source: SourceWorkflowUpdate["source"]): string {
	switch (source) {
		case "anomaly_alert":
			return "review_anomaly_alert";
		case "competitor_signal":
			return "review_competitor_signal";
		case "trend_signal":
			return "review_trend_signal";
		default:
			return "review_listening_signal";
	}
}

function workflowResolution(input: SourceWorkflowUpdate): string | null {
	if (input.status === "resolved") return "Marked handled from workflow surface";
	if (input.status === "ignored") return "Ignored from workflow surface";
	if (input.status === "snoozed") return "Snoozed from workflow surface";
	return null;
}

function buildExactProposedAction(intent: Record<string, unknown>) {
	return {
		intentId: intent.id,
		toolName: intent.action_name,
		actionName: intent.action_name,
		actionHash: intent.payload_hash,
		payloadHash: intent.payload_hash,
		contentHash: intent.content_hash ?? null,
		idempotencyKey: intent.idempotency_key,
		riskLevel: intent.risk_level,
		scope: {
			workspaceId: intent.workspace_id ?? null,
			groupId: intent.group_id ?? null,
			accountId: intent.account_id ?? null,
		},
		workspaceId: intent.workspace_id ?? null,
		groupId: intent.group_id ?? null,
		accountId: intent.account_id ?? null,
		normalizedPayload: intent.normalized_payload,
		expiresAt: intent.expires_at,
	};
}

function urgencyForRisk(risk: unknown) {
	return risk === "critical" || risk === "high" ? "high" : "medium";
}

function summarizeManifest(actions: OperatorManifestEntry[]) {
	return {
		total: actions.length,
		requiresApproval: actions.filter((action) => action.requiresApproval).length,
		requiresIdempotencyKey: actions.filter((action) => action.requiresIdempotencyKey).length,
		critical: actions.filter((action) => action.riskLevel === "critical").length,
		high: actions.filter((action) => action.riskLevel === "high").length,
	};
}

function firstRecord(value: unknown): Record<string, unknown> {
	const first = Array.isArray(value) ? value[0] : value;
	return first && typeof first === "object" && !Array.isArray(first)
		? (first as Record<string, unknown>)
		: {};
}

function stringOrNull(value: unknown): string | null {
	return typeof value === "string" && value.length > 0 ? value : null;
}

function operatorScope(value: Record<string, unknown>) {
	return {
		workspaceId: stringOrNull(value.workspace_id),
		groupId: stringOrNull(value.group_id),
		accountId: stringOrNull(value.account_id),
	};
}

function scopeFromIntent(intent: Record<string, unknown>) {
	return {
		workspaceId: stringOrNull(intent.workspace_id),
		groupId: stringOrNull(intent.group_id),
		accountId: stringOrNull(intent.account_id),
	};
}

function isHighRisk(risk: unknown) {
	return risk === "high" || risk === "critical";
}

function requiresQualityGateForOperatorAction(
	actionName: string,
	riskLevel: string,
	payload: Record<string, unknown>,
) {
	if (typeof payload.content !== "string" || payload.content.trim().length === 0) {
		return false;
	}
	if (isHighRisk(riskLevel)) return true;
	return /publish|schedule|queue|reply|post|autopilot|composer/i.test(actionName);
}

function uniqueById(rows: unknown[]): Record<string, unknown>[] {
	const seen = new Set<string>();
	const output: Record<string, unknown>[] = [];
	for (const row of rows) {
		if (!row || typeof row !== "object" || Array.isArray(row)) continue;
		const record = row as Record<string, unknown>;
		const key = String(record.id || "");
		if (!key || seen.has(key)) continue;
		seen.add(key);
		output.push(record);
	}
	return output;
}

function accountHandle(account: Record<string, unknown>): string {
	const username = typeof account.username === "string" && account.username.trim()
		? account.username.trim()
		: null;
	return username ? `@${username}` : String(account.id || "unknown");
}

function platformLabel(platform: "threads" | "instagram"): string {
	return platform === "instagram" ? "Instagram" : "Threads";
}

function inboxSourceLabel(
	source: "threads_reply" | "threads_mention" | "ig_comment" | "ig_mention" | "ig_dm",
): string {
	if (source === "threads_reply") return "Threads reply";
	if (source === "threads_mention") return "Threads mention";
	if (source === "ig_comment") return "Instagram comment";
	if (source === "ig_mention") return "Instagram mention";
	return "Instagram DM";
}

function buildRecommendedActions(counts: {
	taskCount: number;
	approvalCount: number;
	failedPostCount: number;
}) {
	const actions: Array<{ key: string; label: string; priority: string }> = [];
	if (counts.approvalCount > 0) {
		actions.push({ key: "review_approvals", label: "Review pending approvals", priority: "high" });
	}
	if (counts.failedPostCount > 0) {
		actions.push({ key: "repair_failed_posts", label: "Inspect failed posts", priority: "high" });
	}
	if (counts.taskCount > 0) {
		actions.push({ key: "work_operator_queue", label: "Work open operator tasks", priority: "medium" });
	}
	if (!actions.length) {
		actions.push({ key: "system_clear", label: "No urgent operator tasks detected", priority: "low" });
	}
	return actions;
}

function normalizePayload(value: unknown): Record<string, unknown> {
	return value && typeof value === "object" && !Array.isArray(value)
		? sortObject(value as Record<string, unknown>)
		: { value };
}

function sortObject(value: Record<string, unknown>): Record<string, unknown> {
	const out: Record<string, unknown> = {};
	for (const [key, child] of Object.entries(value).sort(([a], [b]) => a.localeCompare(b))) {
		if (child && typeof child === "object" && !Array.isArray(child)) {
			out[key] = sortObject(child as Record<string, unknown>);
		} else {
			out[key] = child;
		}
	}
	return out;
}

function hashJson(value: unknown): string {
	return hashString(JSON.stringify(value));
}

function hashString(value: string): string {
	return createHash("sha256").update(value).digest("hex");
}

function approvalMatchesIntent(proposedActions: unknown, intent: Record<string, unknown>) {
	const actions = Array.isArray(proposedActions) ? proposedActions : [];
	return actions.some((action) => {
		if (!action || typeof action !== "object") return false;
		const candidate = action as Record<string, unknown>;
		return (
			candidate.intentId === intent.id ||
			candidate.intent_id === intent.id ||
			(candidate.actionHash === intent.payload_hash && candidate.toolName === intent.action_name) ||
			(candidate.action_hash === intent.payload_hash && candidate.tool_name === intent.action_name)
		);
	});
}
