/**
 * Shared billing utilities — single source of truth for account limits.
 *
 * IMPORTANT: All account limit checks MUST use getAccountLimit() from this file.
 * Do not define TIER_ACCOUNT_LIMITS or ACCOUNT_LIMITS inline in other files.
 */

import { logAudit } from "./auditLog.js";
import { logger } from "./logger.js";
import { getSupabase } from "./supabase.js";

/**
 * Base account limits per tier (without add-on extras).
 * Empire/agency = unlimited (returns Infinity).
 */
const BASE_LIMITS: Record<string, number> = {
	free: 1,
	pro: 5,
};

/**
 * Returns the maximum number of accounts allowed for a given tier + extras.
 * Used by auth callbacks, enforcement crons, and Stripe webhooks.
 *
 * @param tier - The user's subscription tier (free, pro, agency, empire)
 * @param extraAccounts - Number of purchased add-on account slots (default 0)
 */
export function getAccountLimit(tier: string, extraAccounts = 0): number {
	const base = BASE_LIMITS[tier];
	if (base === undefined) return Infinity; // empire, agency, or unknown → no limit
	if (tier === "pro" && extraAccounts > 0) {
		return base + Math.min(extraAccounts, 5); // max 5 add-on slots
	}
	return base;
}

/**
 * After a downgrade or add-on reduction, deactivate accounts that exceed the tier's limit.
 * Keeps the oldest accounts active, deactivates the newest excess ones.
 *
 * @param userId - The user whose accounts should be enforced
 * @param newTier - The user's subscription tier after the change
 * @param extraAccounts - Purchased add-on slots (optional; looked up from DB for "pro" tier if omitted)
 */
export async function enforceAccountLimits(
	userId: string,
	newTier: string,
	extraAccounts?: number,
): Promise<void> {
	// For Pro tier, add-on slots expand the allowed account count.
	// If not supplied by the caller, look up the current value from the profile
	// so we don't incorrectly deactivate accounts the user has paid for.
	let effectiveExtraAccounts = extraAccounts ?? 0;
	if (newTier === "pro" && extraAccounts === undefined) {
		const { data: profile } = await getSupabase()
			.from("profiles")
			.select("extra_accounts")
			.eq("id", userId)
			.maybeSingle();
		effectiveExtraAccounts =
			(profile as { extra_accounts?: number | undefined } | null)?.extra_accounts ?? 0;
	}

	const limit = getAccountLimit(newTier, effectiveExtraAccounts);

	// Deactivate excess accounts (skip for unlimited tiers)
	if (limit !== Infinity) {
		try {
			const [{ data: threadsAccounts }, { data: igAccounts }] =
				await Promise.all([
					getSupabase()
						.from("accounts")
						.select("id, created_at")
						.eq("user_id", userId)
						.eq("is_active", true)
						.order("created_at", { ascending: true }),
					getSupabase()
						.from("instagram_accounts")
						.select("id, created_at")
						.eq("user_id", userId)
						.eq("is_active", true)
						.order("created_at", { ascending: true }),
				]);

			interface AccountEntry {
				id: string;
				created_at: string;
				table: string;
			}
			const allAccounts: AccountEntry[] = [
				...(threadsAccounts || []).map((a) => ({
					id: a.id,
					created_at: a.created_at ?? "",
					table: "accounts",
				})),
				...(igAccounts || []).map((a) => ({
					id: a.id,
					created_at: a.created_at ?? "",
					table: "instagram_accounts",
				})),
			].sort(
				(a, b) =>
					new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
			);

			if (allAccounts.length > limit) {
				const excess = allAccounts.slice(limit);
				const threadExcess = excess
					.filter((a) => a.table === "accounts")
					.map((a) => a.id);
				const igExcess = excess
					.filter((a) => a.table === "instagram_accounts")
					.map((a) => a.id);
				const now = new Date().toISOString();

				await Promise.all([
					threadExcess.length > 0
						? getSupabase()
								.from("accounts")
								.update({
									is_active: false,
									status: "deactivated",
									updated_at: now,
								})
								.in("id", threadExcess)
						: Promise.resolve(),
					igExcess.length > 0
						? getSupabase()
								.from("instagram_accounts")
								.update({
									is_active: false,
									status: "deactivated",
									updated_at: now,
								})
								.in("id", igExcess)
						: Promise.resolve(),
				]);

				logger.info("[billing] Deactivated excess accounts on downgrade", {
					userId,
					newTier,
					threadsExcess: threadExcess.length,
					igExcess: igExcess.length,
					kept: limit,
				});
			}
		} catch (err) {
			logger.error("[billing] Failed to enforce account limits on downgrade", {
				userId,
				newTier,
				error: err instanceof Error ? err.message : String(err),
			});
		}
	}

	// Cancel orphaned auto-post queue items if user lost Empire tier
	if (newTier !== "empire") {
		await cancelOrphanedQueueItems(userId);
	}
}

/**
 * After a downgrade from Empire, cancel all pending auto-post queue items
 * for workspaces owned by this user. Items are set to 'canceled' (not deleted)
 * to preserve an audit trail. The auto-post cron already skips non-Empire
 * workspaces, but this provides defense-in-depth.
 */
export async function cancelOrphanedQueueItems(
	userId: string,
): Promise<number> {
	try {
		// Find all workspaces owned by this user
		const { data: workspaces } = await getSupabase()
			.from("workspaces")
			.select("id")
			.eq("owner_id", userId);

		if (!workspaces || workspaces.length === 0) return 0;

		const workspaceIds = workspaces.map((w) => w.id);

		// Cancel all pending/processing queue items for these workspaces
		const { data: cancelled } = await getSupabase()
			.from("auto_post_queue")
			.update({
				status: "cancelled",
				error_message: "Cancelled: workspace owner downgraded from Empire tier",
			})
			.in("workspace_id", workspaceIds)
			.in("status", ["pending", "processing"])
			.select("id");

		const count = cancelled?.length || 0;

		if (count > 0) {
			logger.info("[billing] Cancelled orphaned auto-post queue items", {
				userId,
				workspaceIds,
				cancelledCount: count,
			});

			logAudit(userId, "billing.queue_items_canceled", {
				metadata: { canceledCount: count, workspaceIds },
			});
		}

		return count;
	} catch (err) {
		logger.error("[billing] Failed to cancel orphaned queue items", {
			userId,
			error: err instanceof Error ? err.message : String(err),
		});
		return 0;
	}
}
