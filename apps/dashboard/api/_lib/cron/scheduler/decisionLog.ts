/**
 * Scheduler Decision Log — tracks every scheduling decision per run.
 *
 * Each account evaluation within a scheduler run produces a decision record
 * that captures what happened and why (eligible, skipped, dispatched, etc.).
 * Decisions are accumulated in memory during the run, then batch-inserted
 * to the `scheduler_decisions` table via flushDecisions().
 */

import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";

// biome-ignore lint/suspicious/noExplicitAny: scheduler tables not in generated types
const db = (): any => getSupabaseAny();

// ============================================================================
// Types
// ============================================================================

export type DecisionOutcome =
	| "dispatched"
	| "skipped_blocked"
	| "skipped_outside_window"
	| "skipped_daily_cap"
	| "skipped_min_interval"
	| "skipped_weekend"
	| "skipped_no_content"
	| "fill_triggered"
	| "error";

export interface SchedulerDecision {
	run_id: string;
	workspace_id: string;
	group_id: string;
	account_id: string;
	/** Maps to DB column `decision` */
	outcome: DecisionOutcome;
	reason: string;
	/** Account state at decision time */
	account_status?: string | null | undefined;
	/** Local hour in group timezone — maps to DB column `window_hour` */
	local_hour?: number | null | undefined;
	/** Posts published today — maps to DB column `cap_used` */
	posts_today?: number | null | undefined;
	/** Minutes since last post */
	minutes_since_last_post?: number | null | undefined;
	/** Pending queue depth for this group */
	queue_depth?: number | null | undefined;
	/** Queue item dispatched (for dispatched/error outcomes) */
	queue_item_id?: string | null | undefined;
}

// ============================================================================
// Flush to DB
// ============================================================================

const BATCH_SIZE = 200;

/**
 * Batch insert all decisions for a scheduler run.
 * Non-critical — failures are logged but don't break the scheduler.
 */
export async function flushDecisions(
	decisions: SchedulerDecision[],
): Promise<{ inserted: number; failed: number }> {
	if (decisions.length === 0) return { inserted: 0, failed: 0 };

	let inserted = 0;
	let failed = 0;
	const now = new Date().toISOString();

	for (let i = 0; i < decisions.length; i += BATCH_SIZE) {
		const batch = decisions.slice(i, i + BATCH_SIZE).map((d) => ({
			run_id: d.run_id,
			workspace_id: d.workspace_id,
			group_id: d.group_id,
			account_id: d.account_id,
			decision: d.outcome,
			reason: d.reason,
			account_status: d.account_status ?? null,
			window_hour: d.local_hour ?? null,
			cap_used: d.posts_today ?? null,
			minutes_since_last_post: d.minutes_since_last_post ?? null,
			queue_depth: d.queue_depth ?? null,
			created_at: now,
		}));

		const { error } = await db().from("scheduler_decisions").insert(batch);

		if (error) {
			logger.warn("[scheduler/decisionLog] Batch insert failed", {
				batchStart: i,
				batchSize: batch.length,
				error: error.message,
			});
			failed += batch.length;
		} else {
			inserted += batch.length;
		}
	}

	logger.info("[scheduler/decisionLog] Flushed decisions", {
		inserted,
		failed,
		total: decisions.length,
	});
	return { inserted, failed };
}
