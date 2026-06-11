/**
 * Workspace-scoped account resolver for API routes.
 * Resolves "ALL" to a filtered list of account IDs based on workspace membership.
 *
 * When workspaceId is null, returns all accounts for the user (backward compatible).
 * When workspaceId is provided, returns accounts belonging to all workspace members.
 */

import { logger } from "./logger.js";
import { getSupabase } from "./supabase.js";

/**
 * Returns account IDs visible in the given workspace context.
 *
 * @param userId - The requesting user's ID (used as fallback and always included)
 * @param workspaceId - If provided, scopes to workspace members' accounts
 * @param platform - If provided, filters to only Threads or Instagram accounts
 */
export async function getAccountIdsForContext(
	userId: string,
	workspaceId: string | null,
	platform?: "threads" | "instagram",
): Promise<string[]> {
	const db = getSupabase();

	// Determine which user_ids to query accounts for
	let userIds: string[];

	if (workspaceId) {
		const { data: members, error } = await db
			.from("workspace_members")
			.select("user_id")
			.eq("workspace_id", workspaceId);

		if (error) {
			logger.warn(
				"[getAccountIdsForContext] Failed to fetch workspace members, falling back to userId",
				{ workspaceId, error },
			);
			userIds = [userId];
		} else {
			userIds = (members || []).map((m) => m.user_id);
			// Always include the requesting user even if not yet in member list
			if (!userIds.includes(userId)) userIds.push(userId);
		}
	} else {
		userIds = [userId];
	}

	const ids: string[] = [];

	if (!platform || platform === "threads") {
		const { data: accounts } = await db
			.from("accounts")
			.select("id")
			.in("user_id", userIds);
		if (accounts) ids.push(...accounts.map((a) => a.id));
	}

	if (!platform || platform === "instagram") {
		const { data: igAccounts } = await db
			.from("instagram_accounts")
			.select("id")
			.in("user_id", userIds);
		if (igAccounts) ids.push(...igAccounts.map((a) => a.id));
	}

	return ids;
}
