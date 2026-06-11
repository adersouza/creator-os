import type { VercelRequest } from "@vercel/node";
import {
	OperatorAuditError,
	recordOperatorActionAudit,
	requireOperatorActionAudit,
	type OperatorAuditInput,
} from "./operatorAudit.js";
import {
	checkOperatorKillSwitch,
	type OperatorRiskLevel,
} from "./operatorKillSwitches.js";
import { logger } from "./logger.js";
import { getSupabaseAny } from "./supabase.js";

type SupabaseAny = ReturnType<typeof getSupabaseAny>;

export type OutboundOperatorGuardInput = {
	db?: SupabaseAny;
	req?: VercelRequest;
	userId: string;
	actionName: string;
	riskLevel?: OperatorRiskLevel;
	scope?: {
		workspaceId?: string | null;
		groupId?: string | null;
		accountId?: string | null;
	} | null;
	payload?: unknown;
	idempotencyKey?: string | null;
	metadata?: Record<string, unknown> | null;
	failClosedOnAudit?: boolean;
};

export type OutboundOperatorGuardResult =
	| { allowed: true; auditId: string | null }
	| {
			allowed: false;
			reason: string;
			code: "audit_failed" | "kill_switch";
			auditId: string | null;
	  };

const HIGH_RISK = new Set(["high", "critical"]);

/**
 * Shared guard for outbound writes that can affect external accounts.
 * It records an attempt, checks hierarchical kill switches, and records a
 * failure if the switch blocks the action. High/critical writes fail closed
 * when the audit row cannot be persisted.
 */
export async function enforceOutboundOperatorGuard(
	input: OutboundOperatorGuardInput,
): Promise<OutboundOperatorGuardResult> {
	const db = input.db ?? getSupabaseAny();
	const riskLevel = input.riskLevel ?? "high";
	const failClosedOnAudit =
		input.failClosedOnAudit ?? HIGH_RISK.has(riskLevel);
	let auditId: string | null = null;

	const auditInput: OperatorAuditInput = {
		db,
		userId: input.userId,
		phase: "execute",
		actionName: input.actionName,
		riskLevel,
		scope: input.scope ?? null,
		payload: input.payload,
		idempotencyKey: input.idempotencyKey ?? null,
		outcome: "attempted",
		message: "Outbound write guard attempt",
		metadata: input.metadata ?? {},
		...(input.req ? { req: input.req } : {}),
	};

	try {
		if (failClosedOnAudit) {
			auditId = await requireOperatorActionAudit(auditInput);
		} else {
			const auditResult = await recordOperatorActionAudit(auditInput);
			auditId = auditResult.ok ? auditResult.id : null;
		}
	} catch (error) {
		const message =
			error instanceof OperatorAuditError
				? error.message
				: error instanceof Error
					? error.message
					: String(error);
		logger.error("[outboundOperatorGuard] Audit persistence failed", {
			userId: input.userId,
			actionName: input.actionName,
			error: message,
		});
		return {
			allowed: false,
			reason: "Execution audit persistence is required for outbound writes.",
			code: "audit_failed",
			auditId,
		};
	}

	const killSwitch = await checkOperatorKillSwitch(db, {
		userId: input.userId,
		workspaceId: input.scope?.workspaceId,
		groupId: input.scope?.groupId,
		accountId: input.scope?.accountId,
		actionName: input.actionName,
		riskLevel,
	});

	if (killSwitch.blocked) {
		await recordOperatorActionAudit({
			db,
			userId: input.userId,
			phase: "execute",
			actionName: input.actionName,
			riskLevel,
			scope: input.scope ?? null,
			payload: input.payload,
			idempotencyKey: input.idempotencyKey ?? null,
			outcome: "failure",
			message: killSwitch.reason,
			metadata: {
				...(input.metadata ?? {}),
				blockedByKillSwitch: true,
				switchId: killSwitch.switchId,
				scopeType: killSwitch.scopeType,
				scopeId: killSwitch.scopeId,
			},
			...(input.req ? { req: input.req } : {}),
		});
		return {
			allowed: false,
			reason: killSwitch.reason,
			code: "kill_switch",
			auditId,
		};
	}

	return { allowed: true, auditId };
}

export async function recordOutboundOperatorResult(
	input: OutboundOperatorGuardInput & {
		outcome: "success" | "failure";
		message?: string | null;
		error?: string | null;
	},
): Promise<void> {
	await recordOperatorActionAudit({
		userId: input.userId,
		phase: "execute",
		actionName: input.actionName,
		riskLevel: input.riskLevel ?? "high",
		scope: input.scope ?? null,
		payload: input.payload,
		idempotencyKey: input.idempotencyKey ?? null,
		outcome: input.outcome,
		message: input.message ?? null,
		error: input.error ?? null,
		metadata: input.metadata ?? {},
		...(input.db ? { db: input.db } : {}),
		...(input.req ? { req: input.req } : {}),
	});
}
