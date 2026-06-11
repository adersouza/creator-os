/**
 * Authorization helpers for post-level operations.
 *
 * Extracted for testability — all functions accept the db client as a
 * parameter so tests can inject a mock without touching module-level state.
 */

export interface PostAuthRow {
	user_id: string;
}

export interface WorkspaceMemberRow {
	workspace_id: string;
}

/**
 * Returns true when `requesterId` is allowed to approve/reject the post.
 *
 * Rules:
 *  1. The requester owns the post → allowed.
 *  2. The requester is admin/owner in a workspace that contains the post's
 *     account owner, scoped to workspaces where the account owner is a member
 *     (cross-workspace approval is NOT allowed).
 *  3. Everything else → denied.
 *
 * `db` is the Supabase admin client (or a test mock).
 * `accountId` scopes the workspace check to the post's account context.
 */
export async function canApprovePost(
	db: ReturnType<typeof import("./supabase.js").getSupabase>,
	requesterId: string,
	postOwnerId: string,
	accountId?: string | null,
): Promise<boolean> {
	// Fast path: requester owns the post
	if (requesterId === postOwnerId) return true;

	// If accountId is provided, scope to the specific workspace that owns the account.
	// This prevents cross-workspace approval: an admin in workspace A cannot approve
	// a post from workspace B even if the same user belongs to both.
	let targetWorkspaceIds: string[];

	if (accountId) {
		// Find the workspace that owns this account via account_groups.
		// Try Threads accounts table first, then Instagram accounts table
		// (instagram_accounts.id is UUID, accounts.id is TEXT — both work with .eq())
		let groupId: string | null = null;

		// biome-ignore lint/suspicious/noExplicitAny: supabase client lacks precise generics for dynamic table queries
		const { data: threadsAcct } = await (db.from("accounts") as any)
			.select("group_id")
			.eq("id", accountId)
			.maybeSingle();
		groupId = threadsAcct?.group_id || null;

		if (!groupId) {
			// biome-ignore lint/suspicious/noExplicitAny: supabase client lacks precise generics for dynamic table queries
			const { data: igAcct } = await (db.from("instagram_accounts") as any)
				.select("group_id")
				.eq("id", accountId)
				.maybeSingle();
			groupId = igAcct?.group_id || null;
		}

		if (groupId) {
			// biome-ignore lint/suspicious/noExplicitAny: supabase client lacks precise generics for dynamic table queries
			const { data: group } = await (db.from("account_groups") as any)
				.select("workspace_id")
				.eq("id", groupId)
				.maybeSingle();
			targetWorkspaceIds = group?.workspace_id ? [group.workspace_id] : [];
		} else {
			// accountId was provided but couldn't be resolved — fail closed.
			// Widening to all owner workspaces would reintroduce the cross-workspace hole.
			return false;
		}
	} else {
		// No accountId — can't scope authorization safely. Fail closed.
		// Widening to all owner workspaces would reintroduce the cross-workspace
		// hole: an admin in workspace A could approve posts owned by someone in
		// both workspace A and B. A post without an account can't be published
		// anyway, so only the owner (fast path above) can approve it.
		return false;
	}

	if (targetWorkspaceIds.length === 0) return false;

	// Check if the requester is admin/owner in the target workspace(s)
	// biome-ignore lint/suspicious/noExplicitAny: supabase client lacks precise generics for dynamic table queries
	const { data: overlap } = await (db.from("workspace_members") as any)
		.select("workspace_id")
		.eq("user_id", requesterId)
		.in("workspace_id", targetWorkspaceIds)
		.in("role", ["admin", "owner"])
		.limit(1)
		.maybeSingle();

	return overlap !== null && overlap !== undefined;
}
