/**
 * Shared helpers used across auto-post handler modules.
 */

import type { VercelResponse } from "@vercel/node";
import { apiError } from "../../../apiResponse.js";
import {
	ENGAGEMENT_JOB_PREFIX,
	ENGAGEMENT_QUEUE_KEY,
	ENGAGEMENT_USER_JOB_PREFIX,
	type EngagementSyncJob,
} from "../../../queueKeys.js";
import { getRedis } from "../../../redis.js";
import { getSupabaseAny } from "../../../supabase.js";

export const db = () => getSupabaseAny();

// Lazy import to avoid module-level crashes
export async function getPostMetricsLazy(
	encryptedToken: string,
	postId: string,
) {
	const { getPostMetrics } = await import("../../../threadsApi.js");
	return getPostMetrics(encryptedToken, postId);
}

export async function getUserCurrentEngagementJob(
	userId: string,
	type: string,
): Promise<EngagementSyncJob | null> {
	const redis = getRedis();
	if (!redis) return null;
	const jobId = await redis.get(
		`${ENGAGEMENT_USER_JOB_PREFIX}${userId}:${type}`,
	);
	if (!jobId) return null;
	const data = await redis.get(`${ENGAGEMENT_JOB_PREFIX}${jobId}`);
	if (!data) return null;
	return typeof data === "string"
		? JSON.parse(data)
		: (data as EngagementSyncJob);
}

export async function queueEngagementSyncJob(
	userId: string,
	type: "auto-post-engagement" | "reply-metrics" | "mentions",
	extra: {
		workspaceId?: string | undefined;
		accountIds?: string[] | undefined;
	} = {},
): Promise<EngagementSyncJob> {
	const redis = getRedis();
	if (!redis) throw new Error("Redis not configured");

	const jobId = `eng_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
	const job: EngagementSyncJob & {
		workspaceId?: string | undefined;
		accountIds?: string[] | undefined;
	} = {
		id: jobId,
		userId,
		type,
		status: "queued",
		createdAt: Date.now(),
		...extra,
	};

	await redis.set(`${ENGAGEMENT_JOB_PREFIX}${jobId}`, JSON.stringify(job), {
		ex: 3600,
	});
	await redis.set(`${ENGAGEMENT_USER_JOB_PREFIX}${userId}:${type}`, jobId, {
		ex: 3600,
	});
	await redis.lpush(ENGAGEMENT_QUEUE_KEY, jobId);
	await redis.expire(ENGAGEMENT_QUEUE_KEY, 86400).catch(() => {});

	return job;
}

/**
 * Resolve workspaceId — use provided value, or fall back to user's first owned workspace.
 * Returns the workspace ID or null (after sending 404).
 */
export async function resolveWorkspaceId(
	workspaceId: string | undefined | null,
	userId: string,
	res: VercelResponse,
): Promise<string | null> {
	if (workspaceId) return workspaceId;

	const { data: defaultWs } = await db()
		.from("workspaces")
		.select("id")
		.eq("owner_id", userId)
		.order("created_at", { ascending: true })
		.limit(1)
		.maybeSingle();

	if (!defaultWs) {
		apiError(res, 404, "No workspace found for user");
		return null;
	}
	return defaultWs.id as string;
}

/**
 * Verify that a group belongs to the specified workspace.
 * Prevents cross-workspace group manipulation.
 *
 * account_groups has no workspace_id column — groups are user-owned.
 * A group "belongs to" a workspace if its owner (user_id) is the workspace
 * owner or a workspace member.
 */
export async function verifyGroupBelongsToWorkspace(
	groupId: string,
	workspaceId: string,
	res: VercelResponse,
): Promise<boolean> {
	const { data: group } = await db()
		.from("account_groups")
		.select("id, user_id")
		.eq("id", groupId)
		.maybeSingle();

	if (!group) {
		apiError(res, 404, "Group not found");
		return false;
	}

	// Check if the group's owner is the workspace owner
	const { data: workspace } = await db()
		.from("workspaces")
		.select("owner_id")
		.eq("id", workspaceId)
		.maybeSingle();

	if (!workspace) {
		apiError(res, 404, "Workspace not found");
		return false;
	}

	if (workspace.owner_id === group.user_id) return true;

	// Check if the group's owner is a workspace member
	const { data: member } = await db()
		.from("workspace_members")
		.select("user_id")
		.eq("workspace_id", workspaceId)
		.eq("user_id", group.user_id)
		.maybeSingle();

	if (!member) {
		apiError(res, 404, "Group not found in this workspace");
		return false;
	}

	return true;
}

/**
 * Verify user is owner or member of the specified workspace.
 * Returns true if authorized, false if denied (403/404 already sent).
 */
export async function verifyWorkspaceAccess(
	userId: string,
	workspaceId: string,
	res: VercelResponse,
): Promise<boolean> {
	const { data: workspace } = await db()
		.from("workspaces")
		.select("id, owner_id")
		.eq("id", workspaceId)
		.maybeSingle();

	if (!workspace) {
		apiError(res, 404, "Workspace not found");
		return false;
	}

	if (workspace.owner_id === userId) return true;

	const { data: member } = await db()
		.from("workspace_members")
		.select("id")
		.eq("workspace_id", workspaceId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!member) {
		apiError(res, 403, "Not authorized for this workspace");
		return false;
	}

	return true;
}

/**
 * Verify user can mutate workspace-level configuration.
 * Owners and workspace admins can write; plain members are read-only here.
 */
export async function verifyWorkspaceWriteAccess(
	userId: string,
	workspaceId: string,
	res: VercelResponse,
): Promise<boolean> {
	const { data: workspace } = await db()
		.from("workspaces")
		.select("id, owner_id")
		.eq("id", workspaceId)
		.maybeSingle();

	if (!workspace) {
		apiError(res, 404, "Workspace not found");
		return false;
	}

	if (workspace.owner_id === userId) return true;

	const { data: member } = await db()
		.from("workspace_members")
		.select("role")
		.eq("workspace_id", workspaceId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!member || !["owner", "admin"].includes(String(member.role))) {
		apiError(res, 403, "Admin access required for this workspace");
		return false;
	}

	return true;
}

export async function verifyAccountBelongsToGroup(
	accountId: string,
	groupId: string,
	res: VercelResponse,
): Promise<boolean> {
	const { data: group } = await db()
		.from("account_groups")
		.select("account_ids")
		.eq("id", groupId)
		.maybeSingle();

	if (!group) {
		apiError(res, 404, "Account group not found");
		return false;
	}

	const accountIds = Array.isArray(group.account_ids)
		? (group.account_ids as unknown[])
		: [];
	if (!accountIds.includes(accountId)) {
		apiError(res, 404, "Account not found in this group");
		return false;
	}

	return true;
}
