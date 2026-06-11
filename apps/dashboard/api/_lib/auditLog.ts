/**
 * Audit Logging Helper
 *
 * Records user actions for compliance and debugging.
 * Fire-and-forget — never blocks or throws.
 *
 * Usage:
 *   import { logAudit } from "./_lib/auditLog.js";
 *   await logAudit(userId, "account.connect", { resourceType: "account", resourceId: accountId, metadata: { platform: "threads" } });
 */

import type { VercelRequest } from "@vercel/node";
import type { Database, Json } from "../../types/supabase.js";
import { logger } from "./logger.js";
import { getSupabase } from "./supabase.js";

interface AuditOptions {
	resourceType?: string | undefined;
	resourceId?: string | undefined;
	metadata?: Record<string, unknown> | undefined;
	req?: VercelRequest | undefined;
}

type AuditLogInsert = Database["public"]["Tables"]["audit_logs"]["Insert"];

/**
 * Log an audit event. Fire-and-forget.
 */
export async function logAudit(
	userId: string,
	action: string,
	options?: AuditOptions,
): Promise<void> {
	try {
		const db = getSupabase();
		const auditLog: AuditLogInsert = {
			user_id: userId,
			action,
			resource_type: options?.resourceType ?? null,
			resource_id: options?.resourceId ?? null,
			metadata: (options?.metadata || {}) as Json,
			ip_address:
				options?.req?.headers["x-forwarded-for"]?.toString().split(",")[0] ||
				null,
			user_agent:
				options?.req?.headers["user-agent"]?.toString().slice(0, 500) || null,
		};
		await db.from("audit_logs").insert(auditLog);
	} catch (err: unknown) {
		// Never let audit logging crash the caller
		logger.error("Audit log insert failed", {
			action,
			userId,
			error: err instanceof Error ? err.message : String(err),
		});
	}
}

/**
 * Track API usage for metering. Fire-and-forget.
 */
export async function trackUsage(
	userId: string,
	endpoint: string,
): Promise<void> {
	try {
		const db = getSupabase();
		await db.rpc("increment_api_usage", {
			p_user_id: userId,
			p_endpoint: endpoint,
		});
	} catch (err: unknown) {
		logger.error("Usage tracking failed", {
			endpoint,
			userId,
			error: err instanceof Error ? err.message : String(err),
		});
	}
}
