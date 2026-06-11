/**
 * Workspace-scoped account resolver for frontend code.
 * Frontend counterpart to api/_lib/workspaceAccounts.ts.
 *
 * Uses the authenticated Supabase client (RLS applies).
 * For single-user workspaces this is equivalent to the current behavior.
 * For team workspaces, workspace_members RLS must permit cross-member visibility.
 */

import { supabase } from "@/services/supabase.js";

/**
 * Returns account IDs visible in the given workspace context.
 *
 * @param userId - The current user's ID (used as fallback and always included)
 * @param workspaceId - If provided, scopes to workspace members' accounts
 * @param platform - If provided, filters to only Threads or Instagram accounts
 */
export async function getAccountIdsForContext(
	userId: string,
	workspaceId: string | null,
	platform?: "threads" | "instagram",
): Promise<string[]> {
	let userIds: string[];

	if (workspaceId) {
		const { data: members } = await supabase
			.from("workspace_members")
			.select("user_id")
			.eq("workspace_id", workspaceId);

		userIds = (members || []).map((m: { user_id: string }) => m.user_id);
		if (!userIds.includes(userId)) userIds.push(userId);
	} else {
		userIds = [userId];
	}

	const ids: string[] = [];

	if (!platform || platform === "threads") {
		const { data: accounts } = await supabase
			.from("accounts")
			.select("id")
			.in("user_id", userIds);
		if (accounts) ids.push(...accounts.map((a) => a.id));
	}

	if (!platform || platform === "instagram") {
		const { data: igAccounts } = await supabase
			.from("instagram_accounts")
			.select("id")
			.in("user_id", userIds);
		if (igAccounts) ids.push(...igAccounts.map((a) => a.id));
	}

	return ids;
}
