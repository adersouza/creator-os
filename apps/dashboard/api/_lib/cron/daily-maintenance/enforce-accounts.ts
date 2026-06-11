/**
 * Phase 6: Enforce Account Limits
 * Catchall for webhook enforcement failures — deactivates excess accounts
 * for users on limited subscription tiers.
 */

import type { Logger, PhaseMetadata, TypedSupabaseClient } from "./shared.js";

export async function phaseEnforceAccountLimits(
	supabase: TypedSupabaseClient,
	logger: Logger,
): Promise<PhaseMetadata["enforceAccounts"]> {
	let enforced = 0;

	// Get all users on limited tiers, including purchased add-on slots
	const { data: profiles, error } = await supabase
		.from("profiles")
		.select("id, subscription_tier, extra_accounts")
		.in("subscription_tier", ["free", "pro"]);

	if (error || !profiles?.length) {
		if (error) {
			logger.error(
				"[daily-maintenance] Failed to query profiles for account limit enforcement",
				{ error: error.message },
			);
		}
		return { enforced: 0 };
	}

	const userIds = profiles.map((p) => p.id);
	const tierMap = new Map(
		profiles.map((p) => [p.id, p.subscription_tier] as [string, string | null]),
	);
	const extraAccountsMap = new Map(
		profiles.map(
			(p) =>
				[
					p.id,
					(p as unknown as { extra_accounts?: number | undefined }).extra_accounts ?? 0,
				] as [string, number],
		),
	);

	// Batch fetch all active accounts for these users
	const [{ data: allThreads }, { data: allIg }] = await Promise.all([
		supabase
			.from("accounts")
			.select("id, user_id, created_at")
			.in("user_id", userIds)
			.eq("is_active", true),
		supabase
			.from("instagram_accounts")
			.select("id, user_id, created_at")
			.in("user_id", userIds)
			.eq("is_active", true),
	]);

	// Group by user
	const userAccounts = new Map<
		string,
		Array<{ id: string; created_at: string; table: string }>
	>();
	for (const a of allThreads || []) {
		if (!userAccounts.has(a.user_id)) userAccounts.set(a.user_id, []);
		userAccounts
			.get(a.user_id)
			?.push({ id: a.id, created_at: a.created_at ?? "", table: "accounts" });
	}
	for (const a of allIg || []) {
		if (!userAccounts.has(a.user_id)) userAccounts.set(a.user_id, []);
		userAccounts.get(a.user_id)?.push({
			id: a.id,
			created_at: a.created_at ?? "",
			table: "instagram_accounts",
		});
	}

	for (const [userId, accounts] of userAccounts) {
		const tier = tierMap.get(userId) as string | undefined;
		const extra = extraAccountsMap.get(userId) ?? 0;
		const { getAccountLimit } = await import("../../billing.js");
		const limit = getAccountLimit(tier || "", extra);
		if (limit === Infinity || accounts.length <= limit) continue;

		// Sort oldest first, deactivate excess
		accounts.sort(
			(a, b) =>
				new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
		);
		const excess = accounts.slice(limit);
		const threadIds = excess
			.filter((a) => a.table === "accounts")
			.map((a) => a.id);
		const igIds = excess
			.filter((a) => a.table === "instagram_accounts")
			.map((a) => a.id);
		const now = new Date().toISOString();

		if (threadIds.length > 0) {
			await supabase
				.from("accounts")
				.update({ is_active: false, updated_at: now })
				.in("id", threadIds);
		}
		if (igIds.length > 0) {
			await supabase
				.from("instagram_accounts")
				.update({ is_active: false, updated_at: now })
				.in("id", igIds);
		}

		logger.info("[daily-maintenance] Enforced account limits", {
			userId,
			tier,
			deactivated: excess.length,
		});
		enforced++;
	}

	return { enforced };
}
