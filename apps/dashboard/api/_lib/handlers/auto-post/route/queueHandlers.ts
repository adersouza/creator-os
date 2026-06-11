// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Queue handler modules for auto-post API.
 * Handles: group queue, bulk clear, queue counts, reply chain stats,
 *          delete queue item, queue content audit, retry dead letter,
 *          trigger queue fill, filter rejections
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../../apiResponse.js";
import { logger } from "../../../logger.js";
import { requireMinTier } from "../../../tierGate.js";
import { z } from "../../../zodCompat.js";
import { buildPublishFingerprint } from "../publishFingerprint.js";
import {
	cancelQueueItemsByIds,
	hardDeleteQueueItems,
	retryQueueItem,
} from "../queueState.js";
import {
	db,
	resolveWorkspaceId,
	verifyGroupBelongsToWorkspace,
	verifyWorkspaceAccess,
} from "./routeHelpers.js";

const AddQueueItemsSchema = z.object({
	workspaceId: z.string().min(1),
	groupId: z.string().optional().nullable(),
	items: z
		.array(
			z.object({
				content: z.string().min(1).max(1000),
				platform: z.enum(["threads", "instagram"]).optional(),
			}),
		)
		.min(1)
		.max(100),
});

const ReorderQueueSchema = z.object({
	workspaceId: z.string().min(1),
	orderedPostIds: z.array(z.string().min(1)).min(1).max(500),
	baseTime: z.number().optional(),
});

export async function handleGetGroupQueue(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { workspaceId, groupId, status, limit } = req.body;
	if (!workspaceId) return apiError(res, 400, "workspaceId is required");

	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;

	const maxItems = Math.min(Math.max(Number(limit) || 20, 1), 100);

	// Determine status filter
	const validStatuses = [
		"pending",
		"queued",
		"published",
		"cancelled",
		"dead_letter",
		"failed",
		"processing",
		"scheduled",
		"needs_review",
	];
	let statusFilter: string[];
	if (status === "all") {
		statusFilter = validStatuses;
	} else if (status === "published") {
		statusFilter = ["published"];
	} else if (status && validStatuses.includes(status)) {
		statusFilter = [status];
	} else {
		statusFilter = ["queued", "pending", "scheduled"];
	}

	// Support workspace-level queries (no groupId) or group-level
	let query = db()
		.from("auto_post_queue")
		.select(
			"id, content, status, source_type, source_content, source_competitor_id, source_competitor_username, account_id, group_id, scheduled_for, posted_at, created_at, views_at_24h, engagement_rate, last_error, content_type, media_urls, dna_id, dna_version, dna_fit_score, voice_fit_score, topic_fit_score, mood_fit_score, uniqueness_score, sibling_collision_score, genericness_score, dna_decision, dna_reasons",
		)
		.eq("workspace_id", workspaceId)
		.in("status", statusFilter)
		.limit(maxItems);

	if (statusFilter.includes("published")) {
		query = query.order("posted_at", { ascending: false });
	} else {
		query = query.order("scheduled_for", {
			ascending: true,
			nullsFirst: false,
		});
	}

	if (groupId) {
		query = query.eq("group_id", groupId);
	}

	const { data, error } = await query;

	if (error) {
		logger.error("Failed to fetch group queue", {
			workspaceId,
			groupId,
			status: status ?? null,
			userId,
			error: String(error),
		});
		return apiError(res, 500, "Internal server error");
	}

	// Resolve account_id → username for readability
	const items = data || [];
	const accountIds = [
		...new Set(
			items.map((i: Record<string, unknown>) => i.account_id).filter(Boolean),
		),
	] as string[];
	const usernameMap = new Map<string, string>();
	if (accountIds.length > 0) {
		const { data: accounts } = await db()
			.from("accounts")
			.select("id, username")
			.in("id", accountIds);
		for (const a of accounts || []) {
			usernameMap.set(a.id, a.username);
		}
	}

	// Resolve group_id → name when returning workspace-level results
	const groupIds = [
		...new Set(
			items.map((i: Record<string, unknown>) => i.group_id).filter(Boolean),
		),
	] as string[];
	const groupNameMap = new Map<string, string>();
	if (groupIds.length > 0) {
		const { data: groups } = await db()
			.from("account_groups")
			.select("id, name")
			.in("id", groupIds);
		for (const g of groups || []) {
			groupNameMap.set(g.id, g.name);
		}
	}

	const enriched = items.map((item: Record<string, unknown>) => ({
		...item,
		account_username: usernameMap.get(item.account_id as string) || null,
		group_name: groupNameMap.get(item.group_id as string) || null,
	}));

	return apiSuccess(res, {
		queue: enriched,
		count: enriched.length,
		statusFilter: statusFilter.join(","),
		scope: groupId ? "group" : "workspace",
	});
}

export async function handleAddQueueItems(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const parsed = AddQueueItemsSchema.safeParse(req.body);
	if (!parsed.success) return apiError(res, 400, "Invalid queue item payload");

	const { workspaceId, groupId, items } = parsed.data;
	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;
	if (
		groupId &&
		!(await verifyGroupBelongsToWorkspace(groupId, workspaceId, res))
	)
		return;

	const now = new Date().toISOString();
	const rows = items.map((item) => {
		const platform = item.platform ?? "threads";
		const fingerprint = buildPublishFingerprint({
			workspaceId,
			accountId: null,
			platform,
			content: item.content,
			mediaUrls: null,
		});
		return {
			workspace_id: workspaceId,
			group_id: groupId ?? null,
			account_id: null,
			content: item.content,
			status: "queued",
			scheduled_for: now,
			platform,
			source_type: "manual",
			normalized_text_hash: fingerprint.normalizedTextHash,
			media_fingerprint: fingerprint.mediaFingerprint,
			publish_fingerprint: fingerprint.publishFingerprint,
			duplicate_window_hours: fingerprint.duplicateWindowHours,
			content_fingerprint: fingerprint.normalizedTextHash,
			provenance_status: "manual_allowed",
			provenance_error: null,
		};
	});

	const { data, error } = await db()
		.from("auto_post_queue")
		.insert(rows)
		.select("id");

	if (error) {
		logger.error("Failed to add queue items", {
			workspaceId,
			groupId,
			userId,
			error: String(error),
		});
		return apiError(res, 500, "Failed to add queue items");
	}

	return apiSuccess(res, {
		inserted: Array.isArray(data) ? data.length : 0,
		ids: Array.isArray(data) ? data.map((row: { id: string }) => row.id) : [],
	});
}

export async function handleReorderQueue(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const parsed = ReorderQueueSchema.safeParse(req.body);
	if (!parsed.success)
		return apiError(res, 400, "Invalid queue reorder payload");

	const { workspaceId, orderedPostIds, baseTime = Date.now() } = parsed.data;
	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;

	const { data: existing, error: fetchError } = await db()
		.from("auto_post_queue")
		.select("id")
		.eq("workspace_id", workspaceId)
		.in("id", orderedPostIds);
	if (fetchError) {
		logger.error("Failed to verify queue reorder items", {
			workspaceId,
			userId,
			error: String(fetchError),
		});
		return apiError(res, 500, "Failed to verify queue reorder items");
	}
	const foundIds = new Set(
		(existing ?? []).map((row: { id: string }) => row.id),
	);
	if (foundIds.size !== orderedPostIds.length) {
		return apiError(
			res,
			403,
			"One or more queue items are not in this workspace",
		);
	}

	const upsertRows = orderedPostIds.map((id, index) => ({
		id,
		workspace_id: workspaceId,
		created_at: new Date(baseTime + index).toISOString(),
	}));
	const { error } = await db()
		.from("auto_post_queue")
		.upsert(upsertRows, { onConflict: "id" });
	if (error) {
		logger.error("Failed to reorder queue", {
			workspaceId,
			userId,
			error: String(error),
		});
		return apiError(res, 500, "Failed to reorder queue");
	}

	return apiSuccess(res, { reordered: orderedPostIds.length });
}

// ============================================================================
// Bulk Clear Queue — cancel all pending items for a group
// ============================================================================

export async function handleBulkClearQueue(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { workspaceId, groupId, dryRun = true } = req.body;
	if (!workspaceId || !groupId)
		return apiError(res, 400, "workspaceId and groupId are required");

	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;
	if (!(await verifyGroupBelongsToWorkspace(groupId, workspaceId, res))) return;

	const { data: pending, error: countErr } = await db()
		.from("auto_post_queue")
		.select("id, qstash_message_id, status")
		.eq("workspace_id", workspaceId)
		.eq("group_id", groupId)
		.in("status", ["pending", "queued", "scheduled"]);

	if (countErr) {
		logger.error("Failed to fetch group queue items for bulk clear", {
			workspaceId,
			groupId,
			userId,
			error: String(countErr),
		});
		return apiError(res, 500, "Internal server error");
	}

	const count = pending?.length ?? 0;
	if (count === 0)
		return apiSuccess(res, {
			cancelledCount: 0,
			message: "No pending items to clear",
		});

	if (dryRun) {
		return apiSuccess(res, {
			dryRun: true,
			wouldCancel: count,
			hint: "Set dryRun to false to execute this action.",
		});
	}

	// Cancel any outstanding QStash messages (best-effort).
	// Pending/queued rows can already have scheduled deliveries attached.
	const scheduledItems = (
		pending as {
			id: string;
			qstash_message_id: string | null;
			status: string;
		}[]
	).filter((r) => r.qstash_message_id);
	if (scheduledItems.length > 0) {
		try {
			const { getQStashClient } = await import("../../../qstash.js");
			const qstash = getQStashClient();
			await Promise.allSettled(
				scheduledItems.map((item) =>
					qstash.messages.delete(item.qstash_message_id ?? ""),
				),
			);
		} catch (qstashErr) {
			logger.warn("Failed to cancel some QStash messages during bulk clear", {
				error: String(qstashErr),
			});
		}
	}

	const ids = (pending as { id: string }[]).map((r) => r.id);
	await cancelQueueItemsByIds(ids, "Bulk cleared by user");

	return apiSuccess(res, { cancelledCount: count });
}

// ============================================================================
// Bulk Clear ALL Queues — cancel all pending items across entire workspace
// ============================================================================

export async function handleBulkClearAllQueues(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { workspaceId, dryRun = true } = req.body;
	if (!workspaceId) return apiError(res, 400, "workspaceId is required");

	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;

	// Get counts per group for the response (include scheduled items)
	const { data: pending, error: countErr } = await db()
		.from("auto_post_queue")
		.select("id, group_id, qstash_message_id, status")
		.eq("workspace_id", workspaceId)
		.in("status", ["pending", "queued", "scheduled"]);

	if (countErr) {
		logger.error("Failed to fetch workspace queue items for bulk clear", {
			workspaceId,
			userId,
			error: String(countErr),
		});
		return apiError(res, 500, "Internal server error");
	}

	const items = pending || [];
	const total = items.length;

	if (total === 0) {
		return apiSuccess(res, {
			cancelledCount: 0,
			message: "No pending items in any group",
			byGroup: [],
		});
	}

	// Count per group
	const groupCounts = new Map<string, number>();
	for (const item of items) {
		const gid = (item as { group_id: string }).group_id || "ungrouped";
		groupCounts.set(gid, (groupCounts.get(gid) || 0) + 1);
	}

	// Resolve group names
	const groupIds = [...groupCounts.keys()].filter((g) => g !== "ungrouped");
	const groupNameMap = new Map<string, string>();
	if (groupIds.length > 0) {
		const { data: groups } = await db()
			.from("account_groups")
			.select("id, name")
			.in("id", groupIds);
		for (const g of groups || []) {
			groupNameMap.set(g.id, g.name);
		}
	}

	const byGroup = [...groupCounts.entries()].map(([gid, count]) => ({
		groupId: gid,
		groupName: groupNameMap.get(gid) || gid,
		pending: count,
	}));

	if (dryRun) {
		return apiSuccess(res, {
			dryRun: true,
			wouldCancel: total,
			byGroup,
			hint: "Set dryRun to false to cancel all pending items across ALL groups.",
		});
	}

	// Cancel any outstanding QStash messages (best-effort).
	const scheduledWithQStash = (
		items as { id: string; qstash_message_id: string | null; status: string }[]
	).filter((r) => r.qstash_message_id);
	if (scheduledWithQStash.length > 0) {
		try {
			const { getQStashClient } = await import("../../../qstash.js");
			const qstash = getQStashClient();
			await Promise.allSettled(
				scheduledWithQStash.map((item) =>
					qstash.messages.delete(item.qstash_message_id ?? ""),
				),
			);
		} catch (qstashErr) {
			logger.warn(
				"Failed to cancel some QStash messages during bulk clear all",
				{
					error: String(qstashErr),
				},
			);
		}
	}

	const ids = (items as { id: string }[]).map((r) => r.id);
	await cancelQueueItemsByIds(ids, "Bulk cleared (all groups) by user");

	return apiSuccess(res, {
		cancelledCount: total,
		byGroup,
	});
}

// ============================================================================
// Get Queue Counts — lightweight counts across all groups in a workspace
// ============================================================================

export async function handleGetQueueCounts(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const workspaceId = await resolveWorkspaceId(
		req.body?.workspaceId,
		userId,
		res,
	);
	if (!workspaceId) return;

	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;

	// Single query: count pending + scheduled items grouped by group_id
	const { data: items, error } = await db()
		.from("auto_post_queue")
		.select("group_id")
		.eq("workspace_id", workspaceId)
		.in("status", ["pending", "queued", "scheduled"]);

	if (error) {
		logger.error("Failed to fetch queue counts", {
			workspaceId,
			userId,
			error: String(error),
		});
		return apiError(res, 500, "Internal server error");
	}

	const rows = items || [];
	const groupCounts = new Map<string, number>();
	for (const row of rows) {
		const gid = (row as { group_id: string }).group_id || "ungrouped";
		groupCounts.set(gid, (groupCounts.get(gid) || 0) + 1);
	}

	// Resolve group names
	const groupIds = [...groupCounts.keys()].filter((g) => g !== "ungrouped");
	const groupNameMap = new Map<string, string>();
	if (groupIds.length > 0) {
		const { data: groups } = await db()
			.from("account_groups")
			.select("id, name")
			.in("id", groupIds);
		for (const g of groups || []) {
			groupNameMap.set(g.id, g.name);
		}
	}

	const byGroup = [...groupCounts.entries()]
		.map(([gid, count]) => ({
			groupId: gid,
			name: groupNameMap.get(gid) || gid,
			pending: count,
		}))
		.sort((a, b) => b.pending - a.pending);

	return apiSuccess(res, {
		totalPending: rows.length,
		groupCount: byGroup.length,
		byGroup,
	});
}

// ============================================================================
// Reply Chain Stats — self-reply and cross-reply metrics
// ============================================================================

export async function handleGetReplyChainStats(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const days = Number(req.body?.days || req.query?.days || 7);
	const since = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();

	// Self-replies
	const { data: selfReplies } = await db()
		.from("auto_self_replies")
		.select(
			"id, status, reply_number, group_id, views_at_check, replies_at_check, eligible_reason, created_at, published_at",
		)
		.eq("user_id", userId)
		.gte("created_at", since);

	const selfStats = {
		total: selfReplies?.length || 0,
		published: (selfReplies || []).filter(
			(r: { status: string }) => r.status === "published",
		).length,
		pending: (selfReplies || []).filter(
			(r: { status: string }) => r.status === "pending",
		).length,
		failed: (selfReplies || []).filter(
			(r: { status: string }) => r.status === "failed",
		).length,
		skipped: (selfReplies || []).filter(
			(r: { status: string }) => r.status === "skipped",
		).length,
	};

	// Cross-replies
	const { data: crossReplies } = await db()
		.from("auto_cross_replies")
		.select("id, status, group_id, chain_position, created_at, published_at")
		.eq("user_id", userId)
		.gte("created_at", since);

	const crossStats = {
		total: crossReplies?.length || 0,
		published: (crossReplies || []).filter(
			(r: { status: string }) => r.status === "published",
		).length,
		pending: (crossReplies || []).filter(
			(r: { status: string }) => r.status === "pending",
		).length,
		failed: (crossReplies || []).filter(
			(r: { status: string }) => r.status === "failed",
		).length,
	};

	// Account health summary
	const { data: healthData } = await db()
		.from("account_health_snapshots")
		.select(
			"account_name, health_score, health_tier, posts_per_day_override, is_shadowbanned, consecutive_dead_days, auto_disabled",
		)
		.eq("user_id", userId)
		.eq("account_table", "accounts")
		.eq("period_days", 7)
		.order("health_score", { ascending: false });

	const tierCounts: Record<string, number> = {
		star: 0,
		healthy: 0,
		struggling: 0,
		dead: 0,
	};
	for (const h of healthData || []) {
		if (h.health_tier in tierCounts) tierCounts[h.health_tier]!++;
	}

	return apiSuccess(res, {
		period: `${days}d`,
		selfReplies: selfStats,
		crossReplies: crossStats,
		accountHealth: {
			tiers: tierCounts,
			totalAccounts: healthData?.length || 0,
			shadowbanned: (healthData || []).filter(
				(h: { is_shadowbanned: boolean }) => h.is_shadowbanned,
			).length,
			autoDisabled: (healthData || []).filter(
				(h: { auto_disabled: boolean }) => h.auto_disabled,
			).length,
			topAccounts: (healthData || [])
				.slice(0, 10)
				.map((h: Record<string, unknown>) => ({
					name: h.account_name,
					score: h.health_score,
					tier: h.health_tier,
					postsPerDay: h.posts_per_day_override,
				})),
		},
	});
}

// ============================================================================
// Delete Queue Item — cancel a single queue item by ID
// ============================================================================

export async function handleDeleteQueueItem(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { queueItemId, dryRun = true } = req.body;
	if (!queueItemId) return apiError(res, 400, "queueItemId is required");

	const { data: item, error: fetchErr } = await db()
		.from("auto_post_queue")
		.select("id, workspace_id, group_id, status, content, qstash_message_id")
		.eq("id", queueItemId)
		.maybeSingle();

	if (fetchErr) {
		logger.error("Failed to fetch queue item for deletion", {
			queueItemId,
			userId,
			error: String(fetchErr),
		});
		return apiError(res, 500, "Internal server error");
	}
	if (!item) return apiError(res, 404, "Queue item not found");
	if (!["pending", "queued", "scheduled"].includes(item.status))
		return apiError(
			res,
			400,
			`Cannot cancel item with status "${item.status}"`,
		);

	if (!(await verifyWorkspaceAccess(userId, item.workspace_id, res))) return;

	if (dryRun) {
		return apiSuccess(res, {
			dryRun: true,
			wouldCancel: {
				id: item.id,
				status: item.status,
				content: item.content?.slice(0, 100),
			},
			hint: "Set dryRun to false to execute this action.",
		});
	}

	// Cancel any outstanding QStash message (best-effort).
	if (item.qstash_message_id) {
		try {
			const { getQStashClient } = await import("../../../qstash.js");
			const qstash = getQStashClient();
			await qstash.messages.delete(item.qstash_message_id);
		} catch (qstashErr) {
			logger.warn("Failed to cancel QStash message for queue item", {
				queueItemId,
				error: String(qstashErr),
			});
		}
	}

	const deleted = await hardDeleteQueueItems([queueItemId]);

	if (deleted === 0) {
		logger.error("Failed to delete queue item from database", {
			queueItemId,
			userId,
		});
		return apiError(res, 500, "Failed to delete queue item from database");
	}

	return apiSuccess(res, { cancelled: true, deleted: true, id: queueItemId });
}

// ============================================================================
// Tool #1: Queue Content Audit — merge published queue items with post metrics
// ============================================================================

export async function handleQueueContentAudit(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { workspaceId, groupId, limit } = req.body;
	if (!workspaceId) return apiError(res, 400, "workspaceId is required");
	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;

	const maxItems = Math.min(Math.max(Number(limit) || 20, 1), 50);

	let query = db()
		.from("auto_post_queue")
		.select(
			"id, content, source_type, source_competitor_username, account_id, group_id, posted_at, created_at, content_type, threads_post_id",
		)
		.eq("workspace_id", workspaceId)
		.eq("status", "published")
		.not("posted_at", "is", null)
		.order("posted_at", { ascending: false })
		.limit(maxItems);
	if (groupId) query = query.eq("group_id", groupId);

	const { data: queueItems, error: qErr } = await query;
	if (qErr) {
		logger.error("Failed to fetch queue items for content audit", {
			workspaceId,
			groupId,
			userId,
			error: String(qErr),
		});
		return apiError(res, 500, "Failed to fetch queue items");
	}

	// Collect threads_post_ids to look up metrics from posts table
	const items = (queueItems || []) as Array<Record<string, unknown>>;
	const threadIds = items
		.map((i) => i.threads_post_id)
		.filter(Boolean) as string[];

	const metricsMap = new Map<string, Record<string, unknown>>();
	if (threadIds.length > 0) {
		const { data: posts } = await db()
			.from("posts")
			.select(
				"threads_post_id, views_count, likes_count, replies_count, reposts_count, quotes_count",
			)
			.in("threads_post_id", threadIds);
		for (const p of (posts || []) as Array<Record<string, unknown>>) {
			metricsMap.set(p.threads_post_id as string, p);
		}
	}

	// Resolve account + group names
	const accountIds = [
		...new Set(items.map((i) => i.account_id).filter(Boolean)),
	] as string[];
	const usernameMap = new Map<string, string>();
	if (accountIds.length > 0) {
		const { data: accounts } = await db()
			.from("accounts")
			.select("id, username")
			.in("id", accountIds);
		for (const a of (accounts || []) as Array<{ id: string; username: string }>)
			usernameMap.set(a.id, a.username);
	}
	const groupIds = [
		...new Set(items.map((i) => i.group_id).filter(Boolean)),
	] as string[];
	const groupMap = new Map<string, string>();
	if (groupIds.length > 0) {
		const { data: groups } = await db()
			.from("account_groups")
			.select("id, name")
			.in("id", groupIds);
		for (const g of (groups || []) as Array<{ id: string; name: string }>)
			groupMap.set(g.id, g.name);
	}

	const audit = items.map((item) => {
		const content = (item.content as string) || "";
		const metrics = metricsMap.get(item.threads_post_id as string) || {};
		return {
			content,
			chars: content.length,
			source_type: item.source_type,
			source_competitor: item.source_competitor_username || null,
			content_type: item.content_type || null,
			account: usernameMap.get(item.account_id as string) || item.account_id,
			group: groupMap.get(item.group_id as string) || item.group_id,
			posted_at: item.posted_at,
			views: (metrics as Record<string, unknown>).views_count ?? null,
			likes: (metrics as Record<string, unknown>).likes_count ?? null,
			replies: (metrics as Record<string, unknown>).replies_count ?? null,
			reposts: (metrics as Record<string, unknown>).reposts_count ?? null,
		};
	});

	return apiSuccess(res, { audit, count: audit.length });
}

// ============================================================================
// Tool: Retry Dead Letter — re-queue a failed/dead_letter item
// ============================================================================

export async function handleRetryDeadLetter(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { queueItemId, dryRun = true } = req.body;
	if (!queueItemId) return apiError(res, 400, "queueItemId is required");

	const { data: item, error: fetchErr } = await db()
		.from("auto_post_queue")
		.select(
			"id, workspace_id, group_id, status, content, last_error, retry_count, scheduled_for, source_type, created_at",
		)
		.eq("id", queueItemId)
		.maybeSingle();

	if (fetchErr) {
		logger.error("Failed to fetch queue item for retry", {
			queueItemId,
			userId,
			error: String(fetchErr),
		});
		return apiError(res, 500, "Internal server error");
	}
	if (!item) return apiError(res, 404, "Queue item not found");

	if (!["dead_letter", "failed", "cancelled"].includes(item.status)) {
		return apiError(
			res,
			400,
			`Cannot retry item with status "${item.status}" — only dead_letter, failed, or cancelled items can be retried`,
		);
	}

	if (!(await verifyWorkspaceAccess(userId, item.workspace_id, res))) return;

	if (dryRun) {
		return apiSuccess(res, {
			dryRun: true,
			wouldRetry: {
				id: item.id,
				status: item.status,
				content: item.content?.slice(0, 100),
				last_error: item.last_error,
				retry_count: item.retry_count,
				source_type: item.source_type,
				created_at: item.created_at,
			},
			hint: "Set dryRun to false to execute this action.",
		});
	}

	const scheduledFor = new Date(Date.now() + 5 * 60 * 1000).toISOString();

	await retryQueueItem(queueItemId, scheduledFor);

	return apiSuccess(res, {
		retried: true,
		id: queueItemId,
		newStatus: "pending",
		scheduledFor,
	});
}

// ============================================================================
// Tool: Trigger Queue Fill — manually dispatch AI queue fill for a group
// ============================================================================

export async function handleTriggerQueueFill(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { workspaceId, groupId } = req.body;
	if (!workspaceId) return apiError(res, 400, "workspaceId is required");
	if (!groupId) return apiError(res, 400, "groupId is required");

	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;
	if (!(await verifyGroupBelongsToWorkspace(groupId, workspaceId, res))) return;

	// Get workspace owner
	const { data: workspace } = await db()
		.from("workspaces")
		.select("owner_id")
		.eq("id", workspaceId)
		.maybeSingle();

	if (!workspace) return apiError(res, 404, "Workspace not found");

	// Get group name for logging
	const { data: group } = await db()
		.from("account_groups")
		.select("name")
		.eq("id", groupId)
		.maybeSingle();

	const groupName = group?.name || groupId;

	const { enforceOutboundOperatorGuard } = await import(
		"../../../outboundOperatorGuard.js"
	);
	const outboundGuard = await enforceOutboundOperatorGuard({
		req,
		userId,
		actionName: "queue_fill",
		riskLevel: "high",
		scope: {
			workspaceId,
			groupId,
		},
		payload: {
			workspaceId,
			groupId,
			trigger: "manual",
		},
		idempotencyKey: `manual-queue-fill:${workspaceId}:${groupId}`,
		metadata: { groupName },
	});
	if (!outboundGuard.allowed) {
		logger.warn("Manual queue-fill blocked by outbound operator guard", {
			workspaceId,
			groupId,
			code: outboundGuard.code,
			reason: outboundGuard.reason,
		});
		return apiError(res, 403, outboundGuard.reason);
	}

	// Dispatch via QStash (same mechanism as the cron)
	try {
		const { getQStashClient } = await import("../../../qstash.js");
		const { RETRIES } = await import("../../../qstashDefaults.js");
		const qstash = getQStashClient();
		const baseUrl = process.env.VERCEL_URL
			? `https://${process.env.VERCEL_URL}`
			: "https://juno33.com";

		await qstash.publishJSON({
			url: `${baseUrl}/api/queue-fill`,
			body: {
				workspaceId,
				ownerId: workspace.owner_id,
				groupId,
				traceId: `manual-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
			},
			retries: RETRIES.IMPORTANT,
		});

		logger.info("Manual queue-fill dispatched via MCP", {
			groupId,
			groupName,
			userId,
		});

		return apiSuccess(res, {
			dispatched: true,
			groupId,
			groupName,
			message: `AI queue fill dispatched for "${groupName}". Content will appear in the queue within ~30 seconds.`,
		});
	} catch (err) {
		logger.error("Failed to dispatch manual queue-fill", {
			groupId,
			error: err instanceof Error ? err.message : String(err),
		});
		return apiError(res, 500, "Failed to dispatch queue fill job");
	}
}

// ============================================================================
// Tool: Get Filter Rejections — view content filter rejection log
// ============================================================================

export async function handleGetFilterRejections(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { workspaceId, groupId, limit } = req.body;
	if (!workspaceId) return apiError(res, 400, "workspaceId is required");
	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;

	const maxItems = Math.min(limit || 20, 100);

	// Query rejected items: status='rejected' OR cancelled with content filter error
	let query = db()
		.from("auto_post_queue")
		.select(
			"id, content, status, last_error, rejection_reason, source_type, created_at, group_id",
		)
		.eq("workspace_id", workspaceId)
		.or(
			"status.eq.rejected,and(status.eq.cancelled,last_error.ilike.Content filter%)",
		)
		.order("created_at", { ascending: false })
		.limit(maxItems);

	if (groupId) {
		query = query.eq("group_id", groupId);
	}

	const { data: items, error } = await query;

	if (error) {
		logger.error("Failed to fetch filter rejections", {
			workspaceId,
			groupId,
			userId,
			error: String(error),
		});
		return apiError(res, 500, "Failed to fetch rejections");
	}

	const rejections = ((items || []) as Array<Record<string, unknown>>).map(
		(item) => ({
			id: item.id,
			content_preview: ((item.content as string) || "").slice(0, 80),
			status: item.status,
			rejection_reason: item.rejection_reason || item.last_error || "unknown",
			source_type: item.source_type || "unknown",
			group_id: item.group_id,
			created_at: item.created_at,
		}),
	);

	return apiSuccess(res, {
		rejections,
		count: rejections.length,
		groupId: groupId || "all",
	});
}
