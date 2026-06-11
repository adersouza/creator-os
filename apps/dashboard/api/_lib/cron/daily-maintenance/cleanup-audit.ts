/**
 * Phase 4: Cleanup Audit Logs
 * Calls the cleanup_old_audit_logs() RPC to purge old audit log entries.
 */

import type { Logger, PhaseMetadata, TypedSupabaseClient } from "./shared.js";

export async function phaseCleanupAuditLogs(
	supabase: TypedSupabaseClient,
	logger: Logger,
): Promise<PhaseMetadata["cleanupAudit"]> {
	const { data, error } = await supabase.rpc("cleanup_old_audit_logs");

	if (error) {
		logger.error("[daily-maintenance] Audit log cleanup failed", {
			error: error.message,
		});
		throw new Error(`Cleanup failed: ${error.message}`);
	}

	const deletedCount = data ?? 0;
	logger.info("[daily-maintenance] Audit log cleanup completed", {
		deletedCount,
	});

	return { ok: true, deleted: deletedCount };
}
