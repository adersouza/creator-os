/**
 * Account Autoposter State — DB accessors for the single-source-of-truth table.
 *
 * Phase 1 of the auto-poster simplification plan.
 * Replaces 9 Redis key patterns with one `account_autoposter_state` table.
 *
 * These functions are used by:
 * - Phase 2: stateEvaluator cron (writes)
 * - Phase 3: accountPlanner (reads)
 * - Phase 5: MCP tools (reads + overrides)
 */

import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";
import type { RestartWarmupStatus } from "./restartWarmup.js";

// biome-ignore lint/suspicious/noExplicitAny: auto_post tables not in generated types
const db = (): any => getSupabaseAny();

// ============================================================================
// Types
// ============================================================================

export type AccountAutoposterStatus =
	| "active"
	| "warming_silent"
	| "warming_limited"
	| "viral_suppress"
	| "flop_delay"
	| "view_cooldown"
	| "suppressed"
	| "suppressed_probe"
	| "shadowban_throttle"
	| "inactive";

export interface AccountAutoposterState {
	account_id: string;
	group_id: string;
	workspace_id: string;
	status: AccountAutoposterStatus;
	status_reason: string | null;
	blocked_until: string | null;
	flop_proven_remaining: number;
	probe_posts_remaining: number;
	warming_posts_today: number;
	last_14d_avg_views: number | null;
	median_30d_views: number | null;
	max_30d_views: number | null;
	pct_under_5_views: number | null;
	last_skip_reason: string | null;
	last_skip_at: string | null;
	account_health_score?: number | null | undefined;
	account_health_reason?: string | null | undefined;
	last_health_recomputed_at?: string | null | undefined;
	avg_views_24h_30d?: number | null | undefined;
	median_views_24h_30d?: number | null | undefined;
	posts_above_100_views_rate?: number | null | undefined;
	profile_click_rate_30d?: number | null | undefined;
	revenue_per_post_30d?: number | null | undefined;
	recommended_posts_per_day?: number | null | undefined;
	recommended_strategy_mode?:
		| "scale"
		| "clone_winners"
		| "test_market"
		| "reduce"
		| "suppress"
		| null
		| undefined;
	last_performance_recomputed_at?: string | null | undefined;
	restart_warmup_status?: RestartWarmupStatus | null | undefined;
	restart_warmup_started_at?: string | null | undefined;
	restart_warmup_day?: number | null | undefined;
	restart_warmup_allowed_posts_per_day?: number | null | undefined;
	restart_warmup_reason?: string | null | undefined;
	restart_warmup_next_ramp_at?: string | null | undefined;
	restart_warmup_last_post_views?: number | null | undefined;
	restart_warmup_last_evaluated_at?: string | null | undefined;
	/** Post ID that triggered the current flop_delay — prevents re-extending for same post */
	last_flop_post_id: string | null;
	/** When the current flop_delay was first triggered — enables max duration cap (8h) */
	flop_triggered_at: string | null;
	/** Completed suppression probe cycles. After 2 → permanently suppressed */
	probe_cycles_completed: number;
	evaluated_at: string;
	created_at: string;
	updated_at: string;
}

export type AccountStateUpsert = Pick<
	AccountAutoposterState,
	"account_id" | "group_id" | "workspace_id"
> &
	Partial<
		Omit<
			AccountAutoposterState,
			"account_id" | "group_id" | "workspace_id" | "created_at"
		>
	>;

// ============================================================================
// Read operations
// ============================================================================

/** Get state for a single account. Returns null if no row exists yet. */
export async function getAccountState(
	accountId: string,
): Promise<AccountAutoposterState | null> {
	const { data, error } = await db()
		.from("account_autoposter_state")
		.select("*")
		.eq("account_id", accountId)
		.maybeSingle();

	if (error) {
		logger.error("[accountState] Failed to get state", {
			accountId,
			error: error.message,
		});
		return null;
	}
	return data as AccountAutoposterState | null;
}

/** Get all account states for a group. Used by accountPlanner (Phase 3). */
export async function getGroupAccountStates(
	groupId: string,
): Promise<AccountAutoposterState[]> {
	const { data, error } = await db()
		.from("account_autoposter_state")
		.select("*")
		.eq("group_id", groupId);

	if (error) {
		logger.error("[accountState] Failed to get group states", {
			groupId,
			error: error.message,
		});
		return [];
	}
	return (data ?? []) as AccountAutoposterState[];
}

/** Get all account states for a workspace. Used by MCP tools (Phase 5). */
export async function getWorkspaceAccountStates(
	workspaceId: string,
): Promise<AccountAutoposterState[]> {
	const { data, error } = await db()
		.from("account_autoposter_state")
		.select("*")
		.eq("workspace_id", workspaceId);

	if (error) {
		logger.error("[accountState] Failed to get workspace states", {
			workspaceId,
			error: error.message,
		});
		return [];
	}
	return (data ?? []) as AccountAutoposterState[];
}

// ============================================================================
// Write operations
// ============================================================================

/** Upsert a single account's state. Used by override tool (Phase 5). */
export async function upsertAccountState(
	accountId: string,
	patch: Omit<AccountStateUpsert, "account_id">,
): Promise<boolean> {
	const row = {
		account_id: accountId,
		...patch,
		updated_at: new Date().toISOString(),
	};

	const { error } = await db()
		.from("account_autoposter_state")
		.upsert(row as Record<string, unknown>, { onConflict: "account_id" });

	if (error) {
		logger.error("[accountState] Failed to upsert", {
			accountId,
			error: error.message,
		});
		return false;
	}
	return true;
}

/** Batch upsert states for all accounts in a group. Used by state evaluator cron (Phase 2). */
export async function bulkUpsertAccountStates(
	states: AccountStateUpsert[],
): Promise<{ success: number; failed: number }> {
	if (states.length === 0) return { success: 0, failed: 0 };

	const now = new Date().toISOString();
	const rows = states.map((s) => ({
		...s,
		updated_at: now,
		evaluated_at: now,
	}));

	// Supabase upsert supports batch — up to 1000 rows per call
	const BATCH_SIZE = 500;
	let success = 0;
	let failed = 0;

	for (let i = 0; i < rows.length; i += BATCH_SIZE) {
		const batch = rows.slice(i, i + BATCH_SIZE);
		const { error } = await db()
			.from("account_autoposter_state")
			.upsert(batch as Record<string, unknown>[], { onConflict: "account_id" });

		if (error) {
			logger.error("[accountState] Batch upsert failed", {
				batchStart: i,
				batchSize: batch.length,
				error: error.message,
			});
			failed += batch.length;
		} else {
			success += batch.length;
		}
	}

	logger.info("[accountState] Bulk upsert complete", {
		success,
		failed,
		total: states.length,
	});
	return { success, failed };
}

// ============================================================================
// Helpers
// ============================================================================

/** Check if an account is currently blocked (non-active status with future blocked_until). */
export function isBlocked(state: AccountAutoposterState | null): boolean {
	if (!state) return false;
	if (state.status === "active") return false;
	// Some statuses block without a time limit (inactive, suppressed)
	if (state.status === "inactive" || state.status === "suppressed") return true;
	// Others block until a specific time
	if (
		state.blocked_until &&
		new Date(state.blocked_until).getTime() > Date.now()
	)
		return true;
	return false;
}

/** Human-readable status label for dashboard/MCP display. */
export function statusLabel(status: AccountAutoposterStatus): string {
	const labels: Record<AccountAutoposterStatus, string> = {
		active: "Active",
		warming_silent: "Warming (silent)",
		warming_limited: "Warming (limited)",
		viral_suppress: "Viral suppress",
		flop_delay: "Flop recovery",
		view_cooldown: "View decline cooldown",
		suppressed: "Suppressed",
		suppressed_probe: "Probing",
		shadowban_throttle: "Shadowban throttle",
		inactive: "Inactive",
	};
	return labels[status] ?? status;
}
