/**
 * Shared account eligibility checks.
 *
 * Single source of truth for "can this account publish right now?"
 * Used by: bulk scheduling, publishSinglePost, scheduled-posts cron rescue,
 * and auto-poster queue rotation (which adds its own checks on top).
 *
 * This ensures the scheduler and publisher always agree on eligibility.
 */

export interface EligibilityResult {
	eligible: boolean;
	reason?: "account_inactive" | "needs_reauth" | "suspended" | "token_expired" | undefined;
}

/**
 * Check if an account can publish right now.
 * Works for both Threads accounts and Instagram accounts.
 */
export function isAccountPublishable(account: {
	is_active: boolean;
	status?: string | null | undefined;
	needs_reauth?: boolean | null | undefined;
	token_expires_at?: string | null | undefined;
}): EligibilityResult {
	if (!account.is_active) {
		return { eligible: false, reason: "account_inactive" };
	}
	if (account.status === "suspended") {
		return { eligible: false, reason: "suspended" };
	}
	if (account.needs_reauth) {
		return { eligible: false, reason: "needs_reauth" };
	}
	if (
		account.token_expires_at &&
		new Date(account.token_expires_at) < new Date()
	) {
		return { eligible: false, reason: "token_expired" };
	}
	return { eligible: true };
}

/**
 * Apply publishable-account filters to a Supabase query builder.
 * Use in SELECT queries to exclude ineligible accounts at the DB level.
 *
 * Handles the Supabase .neq() NULL trap: uses .or() for nullable columns
 * so NULL values are not silently excluded.
 */
// biome-ignore lint/suspicious/noExplicitAny: Supabase query builder requires any for chaining
export function publishableAccountFilters(query: any): any {
	return query
		.eq("is_active", true)
		.or("needs_reauth.is.null,needs_reauth.eq.false")
		.or("status.is.null,status.neq.suspended");
}
