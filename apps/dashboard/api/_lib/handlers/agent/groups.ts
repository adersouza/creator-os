/**
 * Account Group CRUD
 *
 * GET    /api/agent/groups               — list all groups with account counts
 * POST   /api/agent/groups?action=create — create group { name, voiceProfile? }
 * PATCH  /api/agent/groups?action=update — update { groupId, name?, voiceProfile? }
 * DELETE /api/agent/groups?action=delete — delete group (unassigns all accounts first)
 * POST   /api/agent/groups?action=assign — assign accounts { accountIds, platform, groupId }
 */

import * as crypto from "node:crypto";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";

// biome-ignore lint/suspicious/noExplicitAny: new columns not in generated types
const db = (): any => getSupabase();

// ---------------------------------------------------------------------------
// Sync account_groups.account_ids array from accounts/instagram_accounts FK
// ---------------------------------------------------------------------------
async function syncGroupAccountIds(
	userId: string,
	table: string,
	newGroupId: string | null,
	movedAccountIds: string[],
) {
	// Collect all groups that need resyncing:
	// 1. The target group (if assigning, not unassigning)
	// 2. Any groups the accounts were previously in
	const groupsToSync = new Set<string>();
	if (newGroupId) groupsToSync.add(newGroupId);

	// Find previous groups for the moved accounts
	// They've already been updated, so check account_groups that contain these IDs
	const { data: allGroups } = await db()
		.from("account_groups")
		.select("id, account_ids")
		.eq("user_id", userId);

	for (const g of allGroups ?? []) {
		const ids = (g.account_ids ?? []) as string[];
		if (ids.some((id: string) => movedAccountIds.includes(id))) {
			groupsToSync.add(g.id);
		}
	}

	// Resync each affected group
	for (const gid of groupsToSync) {
		const { data: currentAccounts } = await db()
			.from(table)
			.select("id")
			.eq("user_id", userId)
			.eq("group_id", gid);

		const freshIds = ((currentAccounts ?? []) as { id: string }[]).map(
			(a) => a.id,
		);

		await db()
			.from("account_groups")
			.update({ account_ids: freshIds, updated_at: new Date().toISOString() })
			.eq("id", gid)
			.eq("user_id", userId);
	}
}

// ---------------------------------------------------------------------------
// GET — list all groups
// ---------------------------------------------------------------------------
async function handleList(res: VercelResponse, userId: string) {
	const { data: groups, error } = await db()
		.from("account_groups")
		.select("id, name, voice_profile, content_strategy, created_at")
		.eq("user_id", userId)
		.order("name", { ascending: true });

	if (error) return apiError(res, 500, "Failed to fetch groups");

	// Count accounts per group from both tables
	const groupIds: string[] = (groups ?? []).map((g: { id: string }) => g.id);

	const [threadsResult, igResult] = await Promise.all([
		groupIds.length
			? db()
					.from("accounts")
					.select("group_id")
					.eq("user_id", userId)
					.in("group_id", groupIds)
			: Promise.resolve({ data: [] }),
		groupIds.length
			? db()
					.from("instagram_accounts")
					.select("group_id")
					.eq("user_id", userId)
					.in("group_id", groupIds)
			: Promise.resolve({ data: [] }),
	]);

	const threadsCounts: Record<string, number> = {};
	for (const row of (threadsResult.data ?? []) as { group_id: string }[]) {
		threadsCounts[row.group_id] = (threadsCounts[row.group_id] ?? 0) + 1;
	}
	const igCounts: Record<string, number> = {};
	for (const row of (igResult.data ?? []) as { group_id: string }[]) {
		igCounts[row.group_id] = (igCounts[row.group_id] ?? 0) + 1;
	}

	const result = (groups ?? []).map(
		(g: {
			id: string;
			name: string;
			voice_profile: unknown;
			content_strategy: unknown;
			created_at: string;
		}) => ({
			groupId: g.id,
			name: g.name,
			voiceProfile: g.voice_profile ?? null,
			contentStrategy: g.content_strategy ?? null,
			accountCounts: {
				threads: threadsCounts[g.id] ?? 0,
				instagram: igCounts[g.id] ?? 0,
				total: (threadsCounts[g.id] ?? 0) + (igCounts[g.id] ?? 0),
			},
			createdAt: g.created_at,
		}),
	);

	return apiSuccess(res, { groups: result, total: result.length });
}

// ---------------------------------------------------------------------------
// POST?action=create
// ---------------------------------------------------------------------------
async function handleCreate(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { name, voiceProfile } = req.body ?? {};
	if (!name || typeof name !== "string") {
		return apiError(res, 400, "name is required");
	}

	const id = crypto.randomUUID();
	const now = new Date().toISOString();

	const { error } = await db()
		.from("account_groups")
		.insert({
			id,
			user_id: userId,
			name: name.trim(),
			voice_profile: voiceProfile ?? null,
			content_strategy: {},
			created_at: now,
			updated_at: now,
		});

	if (error) return apiError(res, 500, "Failed to create group");

	// Auto-create a default auto_post_group_config row so the group is visible
	// to the autoposter cron. Disabled by default — must be explicitly enabled.
	try {
		const [{ data: workspace }, { data: profile }] = await Promise.all([
			db()
				.from("workspaces")
				.select("id")
				.eq("owner_id", userId)
				.order("created_at", { ascending: true })
				.limit(1)
				.maybeSingle(),
			db().from("profiles").select("timezone").eq("id", userId).maybeSingle(),
		]);

		if (workspace) {
			await db()
				.from("auto_post_group_config")
				.insert({
					workspace_id: workspace.id,
					group_id: id,
					enabled: false,
					posts_per_account_per_day: 4,
					min_interval_minutes: 90,
					active_hours_start: 8,
					active_hours_end: 22,
					timezone: profile?.timezone || "UTC",
					post_on_weekends: true,
				});
		}
	} catch {
		// Non-fatal — group was created, config can be added later via upsert
	}

	return apiSuccess(res, { groupId: id, name: name.trim() });
}

// ---------------------------------------------------------------------------
// PATCH?action=update
// ---------------------------------------------------------------------------
async function handleUpdate(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { groupId, name, voiceProfile } = req.body ?? {};
	if (!groupId || typeof groupId !== "string") {
		return apiError(res, 400, "groupId is required");
	}
	if (name === undefined && voiceProfile === undefined) {
		return apiError(
			res,
			400,
			"At least one of name or voiceProfile is required",
		);
	}

	// Verify ownership
	const { data: existing } = await db()
		.from("account_groups")
		.select("id")
		.eq("id", groupId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!existing) return apiError(res, 404, "Group not found");

	const updates: Record<string, unknown> = {
		updated_at: new Date().toISOString(),
	};
	if (name !== undefined) updates.name = name.trim();
	if (voiceProfile !== undefined) updates.voice_profile = voiceProfile;

	const { error } = await db()
		.from("account_groups")
		.update(updates)
		.eq("id", groupId)
		.eq("user_id", userId);

	if (error) return apiError(res, 500, "Failed to update group");

	return apiSuccess(res, {
		groupId,
		updated: Object.keys(updates).filter((k) => k !== "updated_at"),
	});
}

// ---------------------------------------------------------------------------
// DELETE?action=delete
// ---------------------------------------------------------------------------
async function handleDelete(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { groupId } = req.body ?? {};
	if (!groupId || typeof groupId !== "string") {
		return apiError(res, 400, "groupId is required");
	}

	// Verify ownership
	const { data: existing } = await db()
		.from("account_groups")
		.select("id, name")
		.eq("id", groupId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!existing) return apiError(res, 404, "Group not found");

	// Unassign all accounts first (cascade safety)
	await Promise.all([
		db()
			.from("accounts")
			.update({ group_id: null })
			.eq("group_id", groupId)
			.eq("user_id", userId),
		db()
			.from("instagram_accounts")
			.update({ group_id: null })
			.eq("group_id", groupId)
			.eq("user_id", userId),
	]);

	const { error } = await db()
		.from("account_groups")
		.delete()
		.eq("id", groupId)
		.eq("user_id", userId);

	if (error) return apiError(res, 500, "Failed to delete group");

	return apiSuccess(res, { groupId, deleted: true, name: existing.name });
}

// ---------------------------------------------------------------------------
// POST?action=assign
// ---------------------------------------------------------------------------
async function handleAssign(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { accountIds, platform, groupId } = req.body ?? {};

	if (!Array.isArray(accountIds) || accountIds.length === 0) {
		return apiError(res, 400, "accountIds must be a non-empty array");
	}
	if (!platform || !["threads", "instagram"].includes(platform)) {
		return apiError(res, 400, "platform must be 'threads' or 'instagram'");
	}

	// If groupId provided (not null), verify it belongs to user
	if (groupId) {
		const { data: group } = await db()
			.from("account_groups")
			.select("id")
			.eq("id", groupId)
			.eq("user_id", userId)
			.maybeSingle();

		if (!group) return apiError(res, 404, "Group not found");
	}

	const table = platform === "instagram" ? "instagram_accounts" : "accounts";
	const uniqueIds = [...new Set(accountIds as string[])];

	const { data: existingAccounts } = await db()
		.from(table)
		.select("id")
		.in("id", uniqueIds)
		.eq("user_id", userId);

	const existingSet = new Set(
		((existingAccounts ?? []) as { id: string }[]).map((a) => a.id),
	);
	const missingIds = uniqueIds.filter((id) => !existingSet.has(id));
	if (missingIds.length > 0) {
		return apiError(
			res,
			404,
			`${missingIds.length} account(s) not found or not owned by user`,
		);
	}

	const { error } = await db()
		.from(table)
		.update({ group_id: groupId ?? null })
		.in("id", uniqueIds)
		.eq("user_id", userId);

	if (error) return apiError(res, 500, "Failed to assign accounts");

	// Sync account_groups.account_ids for affected groups
	await syncGroupAccountIds(userId, table, groupId ?? null, uniqueIds);

	return apiSuccess(res, {
		assigned: uniqueIds.length,
		platform,
		groupId: groupId ?? null,
	});
}

// ---------------------------------------------------------------------------
// POST?action=bulk-assign — assign up to 200 accounts with per-account reporting
// ---------------------------------------------------------------------------
const MAX_BULK_ASSIGN = 200;

async function handleBulkAssign(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { accountIds, platform, groupId } = req.body ?? {};

	if (!Array.isArray(accountIds) || accountIds.length === 0) {
		return apiError(res, 400, "accountIds must be a non-empty array");
	}
	if (accountIds.length > MAX_BULK_ASSIGN) {
		return apiError(res, 400, `Max ${MAX_BULK_ASSIGN} accounts per request`);
	}
	if (!platform || !["threads", "instagram"].includes(platform)) {
		return apiError(res, 400, "platform must be 'threads' or 'instagram'");
	}

	// If groupId provided (not null), verify it belongs to user
	if (groupId) {
		const { data: group } = await db()
			.from("account_groups")
			.select("id")
			.eq("id", groupId)
			.eq("user_id", userId)
			.maybeSingle();

		if (!group) return apiError(res, 404, "Group not found");
	}

	const table = platform === "instagram" ? "instagram_accounts" : "accounts";
	const uniqueIds = [...new Set(accountIds as string[])];

	// First, check which accounts actually exist and belong to user
	const { data: existingAccounts } = await db()
		.from(table)
		.select("id")
		.in("id", uniqueIds)
		.eq("user_id", userId);

	const existingSet = new Set(
		((existingAccounts ?? []) as { id: string }[]).map((a) => a.id),
	);
	const validIds = uniqueIds.filter((id) => existingSet.has(id));
	const failedIds = uniqueIds.filter((id) => !existingSet.has(id));

	// Bulk update the valid ones
	const assigned: string[] = [];
	const failed: { accountId: string; reason: string }[] = failedIds.map(
		(id) => ({ accountId: id, reason: "Not found or not owned by user" }),
	);

	if (validIds.length > 0) {
		const { error } = await db()
			.from(table)
			.update({ group_id: groupId ?? null })
			.in("id", validIds)
			.eq("user_id", userId);

		if (error) {
			// All valid accounts failed
			for (const id of validIds) {
				failed.push({ accountId: id, reason: "DB update failed" });
			}
		} else {
			assigned.push(...validIds);
			// Sync account_groups.account_ids for affected groups
			await syncGroupAccountIds(userId, table, groupId ?? null, validIds);
		}
	}

	return apiSuccess(res, {
		groupId: groupId ?? null,
		platform,
		assigned,
		failed,
		totalRequested: uniqueIds.length,
		assignedCount: assigned.length,
		failedCount: failed.length,
	});
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------
export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		const userId = user.id;
		// Sub-action comes from body because the parent router (/api/agent)
		// consumes req.query.action as "groups". MCP tools send the sub-action
		// (create/assign/update/delete) in the body or as a secondary query param.
		const action =
			(req.body?.action as string) ||
			(req.query.subaction as string) ||
			(req.query.action as string) ||
			undefined;

		try {
			if (req.method === "GET") {
				return handleList(res, userId);
			}

			if (req.method === "POST") {
				if (action === "create") return handleCreate(req, res, userId);
				if (action === "assign") return handleAssign(req, res, userId);
				if (action === "bulk-assign") return handleBulkAssign(req, res, userId);
				return apiError(res, 400, `Unknown action: ${action}`);
			}

			if (req.method === "PATCH") {
				if (action === "update") return handleUpdate(req, res, userId);
				return apiError(res, 400, `Unknown action: ${action}`);
			}

			if (req.method === "DELETE") {
				if (action === "delete") return handleDelete(req, res, userId);
				return apiError(res, 400, `Unknown action: ${action}`);
			}

			return apiError(res, 405, "Method not allowed");
		} catch (err: unknown) {
			return apiError(
				res,
				500,
				err instanceof Error ? err.message : "Internal server error",
			);
		}
	},
);
