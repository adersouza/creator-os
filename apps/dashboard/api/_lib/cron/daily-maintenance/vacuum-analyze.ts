/**
 * Phase 7: VACUUM ANALYZE Small High-Churn Tables
 * Runs ANALYZE on small high-churn tables that rarely trigger autovacuum's
 * built-in ANALYZE (threshold=50 dead tuples). Fresh statistics keep the
 * query planner accurate.
 */

import type { Logger, PhaseMetadata, TypedSupabaseClient } from "./shared.js";

export async function phaseVacuumAnalyze(
	supabase: TypedSupabaseClient,
	logger: Logger,
): Promise<PhaseMetadata["vacuumAnalyze"]> {
	const { error } = await supabase.rpc("analyze_small_tables");
	if (error) {
		logger.error("[daily-maintenance] ANALYZE small tables failed", {
			error: error.message,
		});
		return { ok: false, error: error.message };
	}
	logger.info("[daily-maintenance] ANALYZE small tables completed");
	return { ok: true };
}
