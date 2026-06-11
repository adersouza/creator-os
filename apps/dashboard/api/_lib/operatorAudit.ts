import type { VercelRequest } from "@vercel/node";
import { createHash } from "node:crypto";
import { logger } from "./logger.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "./privilegedDb.js";

export type OperatorAuditPhase = "dry-run" | "request-approval" | "execute";
export type OperatorAuditOutcome = "attempted" | "success" | "failure";

type SupabaseAny = ReturnType<typeof getPrivilegedSupabaseAny>;

export class OperatorAuditError extends Error {
	constructor(message: string) {
		super(message);
		this.name = "OperatorAuditError";
	}
}

export type OperatorAuditInput = {
	db?: SupabaseAny;
	req?: VercelRequest;
	userId: string;
	actorUserId?: string | null;
	phase: OperatorAuditPhase;
	actionName: string;
	riskLevel?: string | null;
	scope?: {
		workspaceId?: string | null;
		groupId?: string | null;
		accountId?: string | null;
	} | null;
	payload?: unknown;
	payloadHash?: string | null;
	body?: unknown;
	bodyHash?: string | null;
	contentHash?: string | null;
	intentId?: string | null;
	approvalId?: string | null;
	idempotencyKey?: string | null;
	outcome: OperatorAuditOutcome;
	message?: string | null;
	error?: string | null;
	metadata?: Record<string, unknown> | null;
};

export type OperatorAuditResult =
	| { ok: true; id: string | null }
	| { ok: false; error: string };

export async function recordOperatorActionAudit(
	input: OperatorAuditInput,
): Promise<OperatorAuditResult> {
	const db =
		input.db ??
		getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.operatorAudit);
	const row = buildOperatorActionAuditRow(input);

	try {
		const { data, error } = await db
			.from("operator_action_audit_logs")
			.insert(row)
			.select("id")
			.maybeSingle();
		if (error) {
			const message = error.message || "Failed to persist operator audit log";
			logger.error("Operator audit insert failed", {
				phase: input.phase,
				actionName: input.actionName,
				userId: input.userId,
				error: message,
			});
			return { ok: false, error: message };
		}
		return { ok: true, id: typeof data?.id === "string" ? data.id : null };
	} catch (err: unknown) {
		const message = err instanceof Error ? err.message : String(err);
		logger.error("Operator audit insert threw", {
			phase: input.phase,
			actionName: input.actionName,
			userId: input.userId,
			error: message,
		});
		return { ok: false, error: message };
	}
}

export async function requireOperatorActionAudit(
	input: OperatorAuditInput,
): Promise<string | null> {
	const result = await recordOperatorActionAudit(input);
	if (!result.ok) {
		throw new OperatorAuditError(result.error);
	}
	return result.id;
}

export function hashOperatorAuditValue(value: unknown): string {
	return hashString(JSON.stringify(stableAuditValue(value)));
}

function buildOperatorActionAuditRow(input: OperatorAuditInput): Record<string, unknown> {
	const scope = input.scope ?? {};
	const requestMetadata = extractRequestMetadata(input.req);
	return {
		user_id: input.userId,
		actor_user_id: input.actorUserId ?? input.userId,
		phase: input.phase,
		action_name: input.actionName,
		risk_level: input.riskLevel ?? null,
		workspace_id: scope.workspaceId ?? null,
		group_id: scope.groupId ?? null,
		account_id: scope.accountId ?? null,
		scope: {
			workspaceId: scope.workspaceId ?? null,
			groupId: scope.groupId ?? null,
			accountId: scope.accountId ?? null,
		},
		payload_hash: input.payloadHash ?? hashIfPresent(input.payload),
		body_hash: input.bodyHash ?? hashIfPresent(input.body),
		content_hash: input.contentHash ?? null,
		intent_id: input.intentId ?? null,
		approval_id: input.approvalId ?? null,
		idempotency_key: input.idempotencyKey ?? null,
		outcome: input.outcome,
		message: input.message ?? null,
		error: input.error ?? null,
		request_method: requestMetadata.method,
		request_path: requestMetadata.path,
		ip_address: requestMetadata.ipAddress,
		user_agent: requestMetadata.userAgent,
		request_id: requestMetadata.requestId,
		metadata: input.metadata ?? {},
	};
}

function hashIfPresent(value: unknown): string | null {
	return typeof value === "undefined" ? null : hashOperatorAuditValue(value);
}

function stableAuditValue(value: unknown): unknown {
	if (Array.isArray(value)) return value.map(stableAuditValue);
	if (!value || typeof value !== "object") return value;

	const out: Record<string, unknown> = {};
	for (const [key, child] of Object.entries(value).sort(([a], [b]) => a.localeCompare(b))) {
		out[key] = stableAuditValue(child);
	}
	return out;
}

function hashString(value: string): string {
	return createHash("sha256").update(value).digest("hex");
}

function extractRequestMetadata(req: VercelRequest | undefined) {
	const forwardedFor = header(req, "x-forwarded-for");
	const ipAddress = forwardedFor?.split(",")[0]?.trim() || header(req, "x-real-ip") || null;
	const requestId = header(req, "x-request-id") || header(req, "x-vercel-id") || null;
	return {
		method: req?.method ?? null,
		path: req?.url?.slice(0, 1000) ?? null,
		ipAddress,
		userAgent: header(req, "user-agent")?.slice(0, 500) ?? null,
		requestId,
	};
}

function header(req: VercelRequest | undefined, name: string): string | null {
	const value = req?.headers[name];
	if (Array.isArray(value)) return value[0] ?? null;
	return typeof value === "string" && value.length > 0 ? value : null;
}
