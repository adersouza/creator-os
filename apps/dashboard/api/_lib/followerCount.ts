/**
 * Canonical column names for follower count across tables.
 *
 * - `accounts` (Threads)       → `followers_count` (plural)
 * - `instagram_accounts`       → `follower_count`  (singular)
 * - `account_analytics`        → `followers_count` (plural, used for both platforms)
 *
 * Use these constants in Supabase `.select()` strings to avoid typos.
 */
export const THREADS_FOLLOWER_COL = "followers_count" as const;
export const IG_FOLLOWER_COL = "follower_count" as const;

/** Pick the right column name for a Supabase `.select()` string based on platform. */
export function followerColForPlatform(
	platform: "threads" | "instagram",
): typeof THREADS_FOLLOWER_COL | typeof IG_FOLLOWER_COL {
	return platform === "instagram" ? IG_FOLLOWER_COL : THREADS_FOLLOWER_COL;
}

/**
 * Read follower count from a row that may come from either `accounts` or
 * `instagram_accounts`. Handles the column name mismatch transparently.
 */
export function getFollowerCount(
	row:
		| { followers_count?: number | null | undefined }
		| { follower_count?: number | null | undefined }
		| Record<string, unknown>,
): number {
	if ("followers_count" in row) return (row.followers_count as number) ?? 0;
	if ("follower_count" in row) return (row.follower_count as number) ?? 0;
	return 0;
}
