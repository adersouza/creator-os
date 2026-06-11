/**
 * Workspace Access Verification Helper
 *
 * Deduplicates the pattern of checking workspace_members then workspace owner
 * that was copy-pasted across multiple API handlers.
 */

import type { getSupabase } from "./supabase.js";

/** Tables that support workspace-based access verification */
type WorkspaceTable = "accounts" | "instagram_accounts";
export type WorkspaceAccess = {
	hasAccess: boolean;
	role: string | null;
	isOwner: boolean;
};
export type WorkspaceRole = "owner" | "admin" | "member";

const ALLOWED_TABLES: ReadonlySet<string> = new Set<WorkspaceTable>([
	"accounts",
	"instagram_accounts",
]);

/**
 * Verify that a user has access to a workspace (either as owner or member).
 *
 * @returns `true` if the user has access, `false` otherwise.
 */
export async function verifyWorkspaceAccess(
	supabase: ReturnType<typeof getSupabase>,
	userId: string,
	workspaceId: string,
): Promise<boolean> {
	const access = await getWorkspaceAccess(supabase, userId, workspaceId);
	return access.hasAccess;
}

/**
 * Resolve workspace access plus the caller's effective role.
 *
 * Owners may not always appear in `workspace_members`; in that case their
 * effective role is normalized to `owner`.
 */
export async function getWorkspaceAccess(
	supabase: ReturnType<typeof getSupabase>,
	userId: string,
	workspaceId: string,
): Promise<WorkspaceAccess> {
	// Check membership first (most common path)
	const { data: wsMember } = await supabase
		.from("workspace_members")
		.select("role")
		.eq("workspace_id", workspaceId)
		.eq("user_id", userId)
		.maybeSingle();

	if (wsMember) {
		return {
			hasAccess: true,
			role: wsMember.role ?? null,
			isOwner: wsMember.role === "owner",
		};
	}

	// Fall back to checking if user is the workspace owner
	const { data: ws } = await supabase
		.from("workspaces")
		.select("owner_id")
		.eq("id", workspaceId)
		.maybeSingle();

	const isOwner = !!ws && ws.owner_id === userId;
	return {
		hasAccess: isOwner,
		role: isOwner ? "owner" : null,
		isOwner,
	};
}

export function workspaceAccessHasRole(
	access: WorkspaceAccess,
	allowedRoles: readonly WorkspaceRole[],
): boolean {
	if (!access.hasAccess) return false;
	if (access.isOwner && allowedRoles.includes("owner")) return true;
	return !!access.role && allowedRoles.includes(access.role as WorkspaceRole);
}

/**
 * Given an account ID, look up its workspace_id and verify access.
 * Works for both `accounts` and `instagram_accounts` tables.
 *
 * @returns `true` if the user owns the account (when no workspace) or has workspace access.
 */
export async function verifyAccountWorkspaceAccess(
	supabase: ReturnType<typeof getSupabase>,
	userId: string,
	accountId: string,
	table: WorkspaceTable = "accounts",
): Promise<boolean> {
	// Runtime guard: only allow known table names (defense-in-depth)
	if (!ALLOWED_TABLES.has(table)) {
		return false;
	}

	// Cast needed to avoid deep Supabase type recursion; table name is validated above
	// biome-ignore lint/suspicious/noExplicitAny: table name is runtime-validated; avoids deep Supabase type recursion
	const { data: account } = await (supabase as any)
		.from(table)
		.select("workspace_id, user_id")
		.eq("id", accountId)
		.maybeSingle();

	// No account found → deny access
	if (!account) return false;

	// No workspace attached → check account ownership (solo-user access)
	if (!account.workspace_id) return account.user_id === userId;

	return verifyWorkspaceAccess(supabase, userId, account.workspace_id);
}
