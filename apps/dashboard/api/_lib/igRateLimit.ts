/**
 * Shared IG rate limit check via Supabase RPC.
 *
 * Used by publishPost.ts and scheduled-posts.ts before publishing to Instagram.
 * The RPC atomically checks + increments the daily counter.
 */

import { getSupabase } from "./supabase.js";

interface RateLimitResult {
	allowed: boolean;
	reason?: string | undefined;
}

/**
 * Check and increment the Instagram daily rate limit for an account.
 * Returns `{ allowed, reason }` or `null` if the RPC call failed.
 */
export async function checkIGRateLimit(
	accountId: string,
	dailyLimit = 100,
): Promise<RateLimitResult | null> {
	const { data, error } = await (
		getSupabase() as unknown as {
			rpc: (
				fn: string,
				args: Record<string, unknown>,
			) => Promise<{
				data: Array<RateLimitResult> | null;
				error: { message: string } | null;
			}>;
		}
	).rpc("ig_check_and_increment_rate_limit", {
		p_account_id: accountId,
		p_daily_limit: dailyLimit,
	});

	if (error || !data || !data[0]) {
		return null;
	}

	return data[0];
}
