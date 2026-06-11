// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Monitoring handler modules for auto-post API.
 * Handles: health-check, auto-reply queue, toggle auto-reply,
 *          verify autoposter state, publish log, account health
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../../apiResponse.js";
import { decrypt } from "../../../encryption.js";
import { logger } from "../../../logger.js";
import { requireMinTier } from "../../../tierGate.js";
import {
	db,
	resolveWorkspaceId,
	verifyWorkspaceAccess,
} from "./routeHelpers.js";

export async function handleHealthCheck(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	let { workspaceId } = req.body || {};

	// Fall back to user's default (first owned) workspace
	if (!workspaceId) {
		const { data: defaultWs } = await db()
			.from("workspaces")
			.select("id, owner_id")
			.eq("owner_id", userId)
			.order("created_at", { ascending: true })
			.limit(1)
			.maybeSingle();
		if (!defaultWs) {
			return apiError(res, 404, "No workspace found for user");
		}
		workspaceId = defaultWs.id;
	}

	if (!(await requireMinTier(userId, "empire", res))) return;

	// Verify user owns this workspace
	const { data: workspace } = await db()
		.from("workspaces")
		.select("id, owner_id")
		.eq("id", workspaceId)
		.maybeSingle();

	if (!workspace) {
		return apiError(res, 404, "Workspace not found");
	}

	if (workspace.owner_id !== userId) {
		// Check if user is a member
		const { data: member } = await db()
			.from("workspace_members")
			.select("id")
			.eq("workspace_id", workspaceId)
			.eq("user_id", userId)
			.maybeSingle();
		if (!member) return apiError(res, 403, "Not authorized for this workspace");
	}

	// Get ALL accounts with tokens — Threads + IG in parallel
	// NOTE: This health check is REPORTING ONLY — it does NOT affect the autoposter
	// publishing pipeline. Every account with a token gets posts via round-robin
	// regardless of what the health check reports.
	const [{ data: allAccounts }, { data: allIgAccounts }] = await Promise.all([
		db()
			.from("accounts")
			.select(
				"id, username, threads_user_id, threads_access_token_encrypted, status",
			)
			.eq("user_id", workspace.owner_id)
			.not("threads_access_token_encrypted", "is", null)
			.order("created_at", { ascending: false }),
		db()
			.from("instagram_accounts")
			.select(
				"id, instagram_user_id, username, instagram_access_token_encrypted",
			)
			.eq("user_id", workspace.owner_id)
			.not("instagram_access_token_encrypted", "is", null),
	]);

	// Cap at 20 per platform to stay within function timeout (API-check each account)
	const accounts = (allAccounts || []).slice(0, 20);
	const igAccounts = (allIgAccounts || []).slice(0, 20);
	const skippedThreads = (allAccounts || []).length - accounts.length;
	const skippedIg = (allIgAccounts || []).length - igAccounts.length;

	if (
		(!accounts || accounts.length === 0) &&
		(!igAccounts || igAccounts.length === 0)
	) {
		return apiSuccess(res, { accounts: [], summary: "No accounts found" });
	}

	// Check all accounts in parallel (3s timeout per request to prevent hanging)
	const checkThreadsAccount = async (
		account: NonNullable<typeof accounts>[0],
	) => {
		try {
			const token = decrypt(account.threads_access_token_encrypted);
			const response = await fetch(
				`https://graph.threads.net/v1.0/${account.threads_user_id}?fields=id,username`,
				{
					headers: { Authorization: `Bearer ${token}` },
					signal: AbortSignal.timeout(3000),
				},
			);
			const data = await response.json();
			if (data.error) {
				return {
					username: account.username,
					dbStatus: account.status || "unknown",
					apiStatus: "error" as const,
					apiMessage: `${data.error.message} (code=${data.error.code}, type=${data.error.type})`,
					threadsUserId: account.threads_user_id,
				};
			}
			return {
				username: account.username,
				dbStatus: account.status || "unknown",
				apiStatus: "ok" as const,
				threadsUserId: account.threads_user_id,
			};
		} catch (err: unknown) {
			return {
				username: account.username,
				dbStatus: account.status || "unknown",
				apiStatus: "error" as const,
				apiMessage:
					(err instanceof Error ? err.message : undefined) || "Unknown error",
				threadsUserId: account.threads_user_id,
			};
		}
	};

	const checkIgAccount = async (igAcc: NonNullable<typeof igAccounts>[0]) => {
		try {
			if (!igAcc.instagram_access_token_encrypted) throw new Error("No token");
			const token = decrypt(igAcc.instagram_access_token_encrypted);
			const resp = await fetch(
				`https://graph.instagram.com/v25.0/me?fields=id,username`,
				{
					headers: { Authorization: `Bearer ${token}` },
					signal: AbortSignal.timeout(3000),
				},
			);
			return {
				id: igAcc.id,
				username: igAcc.username || undefined,
				status: (resp.ok ? "healthy" : "error") as "healthy" | "error",
				error: resp.ok ? undefined : `HTTP ${resp.status}`,
			};
		} catch (err) {
			return {
				id: igAcc.id,
				username: igAcc.username || undefined,
				status: "error" as const,
				error: err instanceof Error ? err.message : "Unknown error",
			};
		}
	};

	// Run ALL checks in parallel — reduces N×10s sequential to max(3s)
	const [results, igAccountHealth] = await Promise.all([
		Promise.all((accounts || []).map(checkThreadsAccount)),
		Promise.all((igAccounts || []).map(checkIgAccount)),
	]);

	const healthy = results.filter((r) => r.apiStatus === "ok").length;
	const unhealthy = results.filter((r) => r.apiStatus === "error").length;
	const igHealthy = igAccountHealth.filter(
		(r) => r.status === "healthy",
	).length;
	const igUnhealthy = igAccountHealth.filter(
		(r) => r.status === "error",
	).length;

	// Diagnostic: read workspace-level auto_post_config and surface warnings
	const diagnostics: string[] = [];
	const { data: wsConfig } = await db()
		.from("auto_post_config")
		.select("is_enabled, enable_ai_queue_fill, group_mode_enabled")
		.eq("workspace_id", workspaceId)
		.maybeSingle();

	if (wsConfig) {
		if (!wsConfig.is_enabled) {
			diagnostics.push(
				"Master switch is OFF — auto-poster will not publish anything",
			);
		}
		if (wsConfig.is_enabled && !wsConfig.enable_ai_queue_fill) {
			diagnostics.push(
				"AI queue fill is disabled — queue will drain and not replenish",
			);
		}
		if (!wsConfig.group_mode_enabled) {
			diagnostics.push("Group mode disabled — using legacy mode");
		}
	} else {
		diagnostics.push(
			"No auto_post_config found for this workspace — auto-poster not initialized",
		);
	}

	return apiSuccess(res, {
		summary: `Threads: ${healthy} healthy, ${unhealthy} unhealthy out of ${results.length} checked${skippedThreads > 0 ? ` (${skippedThreads} not API-checked due to timeout cap — still receive posts)` : ""} | Instagram: ${igHealthy} healthy, ${igUnhealthy} unhealthy out of ${igAccountHealth.length} checked${skippedIg > 0 ? ` (${skippedIg} not API-checked due to timeout cap — still receive posts)` : ""}`,
		threads: {
			healthy,
			unhealthy,
			total: results.length,
			skipped: skippedThreads,
			accounts: results,
		},
		instagram: {
			healthy: igHealthy,
			unhealthy: igUnhealthy,
			total: igAccountHealth.length,
			skipped: skippedIg,
			accounts: igAccountHealth,
		},
		diagnostics: diagnostics.length > 0 ? diagnostics : undefined,
	});
}

// ============================================================================
// Auto-Reply Queue Handlers
// ============================================================================

export async function handleGetAutoReplyQueue(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { status, limit } = req.body || {};
	const workspaceId = await resolveWorkspaceId(
		req.body?.workspaceId,
		userId,
		res,
	);
	if (!workspaceId) return;

	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;

	let query = db()
		.from("auto_reply_queue")
		.select("*")
		.eq("workspace_id", workspaceId)
		.order("created_at", { ascending: false })
		.limit(Math.min(Number(limit) || 20, 100));

	if (status) {
		query = query.eq("status", status);
	}

	const { data, error } = await query;
	if (error) {
		logger.error("Failed to fetch auto-reply queue", { error: error.message });
		return apiError(res, 500, "Internal server error");
	}

	return apiSuccess(res, { queue: data || [] });
}

export async function handleToggleAutoReply(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { workspaceId, groupId, config: replyConfig } = req.body || {};
	if (!workspaceId || !groupId)
		return apiError(res, 400, "workspaceId and groupId are required");

	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;

	// Validate config values
	const update: Record<string, unknown> = {};
	if (replyConfig?.enable_auto_reply !== undefined)
		update.enable_auto_reply = Boolean(replyConfig.enable_auto_reply);
	if (replyConfig?.auto_reply_daily_limit !== undefined) {
		const limit = Number(replyConfig.auto_reply_daily_limit);
		if (limit < 1 || limit > 50)
			return apiError(res, 400, "auto_reply_daily_limit must be 1-50");
		update.auto_reply_daily_limit = limit;
	}
	if (replyConfig?.auto_reply_ratio !== undefined) {
		const ratio = Number(replyConfig.auto_reply_ratio);
		if (ratio < 0 || ratio > 1)
			return apiError(res, 400, "auto_reply_ratio must be 0-1");
		update.auto_reply_ratio = ratio;
	}
	if (replyConfig?.auto_reply_trigger_count !== undefined) {
		const count = Number(replyConfig.auto_reply_trigger_count);
		if (count < 1 || count > 100)
			return apiError(res, 400, "auto_reply_trigger_count must be 1-100");
		update.auto_reply_trigger_count = count;
	}
	if (replyConfig?.auto_reply_window_hours !== undefined) {
		const hours = Number(replyConfig.auto_reply_window_hours);
		if (hours < 1 || hours > 168)
			return apiError(res, 400, "auto_reply_window_hours must be 1-168");
		update.auto_reply_window_hours = hours;
	}

	if (Object.keys(update).length === 0)
		return apiError(res, 400, "No valid config fields provided");

	const { error } = await db()
		.from("auto_post_group_config")
		.update(update)
		.eq("workspace_id", workspaceId)
		.eq("group_id", groupId);

	if (error) {
		logger.error("Failed to toggle auto-reply", { error: error.message });
		return apiError(res, 500, "Internal server error");
	}

	return apiSuccess(res, { updated: true, config: update });
}

// ============================================================================
// verify-autoposter-state — Pre-flight safety check
// ============================================================================

export async function handleVerifyAutoposterState(
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

	const now = new Date().toISOString();

	// 1. Master switch status
	const { data: config } = await db()
		.from("auto_post_config")
		.select("is_enabled, group_mode_enabled, enable_ai_queue_fill")
		.eq("workspace_id", workspaceId)
		.maybeSingle();

	// 2. Queue counts by status
	const { data: queueCounts } = await db()
		.from("auto_post_queue")
		.select("status")
		.eq("workspace_id", workspaceId);

	const statusCounts: Record<string, number> = {};
	for (const row of queueCounts || []) {
		statusCounts[row.status] = (statusCounts[row.status] || 0) + 1;
	}

	// 3. Items with scheduled_for < NOW (would publish immediately)
	const { data: _overdueItems, count: overdueCount } = await db()
		.from("auto_post_queue")
		.select("id", { count: "exact", head: true })
		.eq("workspace_id", workspaceId)
		.in("status", ["pending", "queued"])
		.lte("scheduled_for", now);

	// 4. Last 5 published posts with timestamps + gaps
	const { data: recentPublished } = await db()
		.from("auto_post_queue")
		.select("id, account_id, posted_at, content, group_id")
		.eq("workspace_id", workspaceId)
		.eq("status", "published")
		.not("posted_at", "is", null)
		.order("posted_at", { ascending: false })
		.limit(20);

	// Build last-5 with gap calculation per account
	const lastPostByAccount = new Map<string, string>();
	const last5WithGaps: Array<Record<string, unknown>> = [];
	for (const post of recentPublished || []) {
		const prevTime = lastPostByAccount.get(post.account_id);
		const gapMinutes = prevTime
			? Math.round(
					(new Date(prevTime).getTime() - new Date(post.posted_at).getTime()) /
						60000,
				)
			: null;
		lastPostByAccount.set(post.account_id, post.posted_at);

		if (last5WithGaps.length < 5) {
			last5WithGaps.push({
				account_id: post.account_id,
				posted_at: post.posted_at,
				gap_minutes_to_next_on_same_account: gapMinutes,
				content_preview: post.content?.substring(0, 60),
				group_id: post.group_id,
			});
		}
	}

	// 5. Burst detection — accounts that posted twice within 45min today
	const todayStart = new Date();
	todayStart.setUTCHours(0, 0, 0, 0);
	const { data: todayPosts } = await db()
		.from("auto_post_queue")
		.select("account_id, posted_at")
		.eq("workspace_id", workspaceId)
		.eq("status", "published")
		.not("posted_at", "is", null)
		.gte("posted_at", todayStart.toISOString())
		.order("posted_at", { ascending: true });

	const burstAccounts: Array<{
		account_id: string;
		gap_minutes: number;
		post1: string;
		post2: string;
	}> = [];
	const accountTimelines = new Map<string, string[]>();
	for (const post of todayPosts || []) {
		const times = accountTimelines.get(post.account_id) || [];
		times.push(post.posted_at);
		accountTimelines.set(post.account_id, times);
	}
	for (const [accountId, times] of accountTimelines) {
		for (let i = 1; i < times.length; i++) {
			const gap =
				(new Date(times[i]!).getTime() - new Date(times[i - 1]!).getTime()) /
				60000;
			if (gap < 45) {
				burstAccounts.push({
					account_id: accountId,
					gap_minutes: Math.round(gap),
					post1: times[i - 1]!,
					post2: times[i]!,
				});
			}
		}
	}

	// 6. Failed/stuck items
	const { count: failedCount } = await db()
		.from("auto_post_queue")
		.select("id", { count: "exact", head: true })
		.eq("workspace_id", workspaceId)
		.in("status", ["failed", "dead_letter"]);

	const { count: stuckCount } = await db()
		.from("auto_post_queue")
		.select("id", { count: "exact", head: true })
		.eq("workspace_id", workspaceId)
		.eq("status", "publishing")
		.lte("created_at", new Date(Date.now() - 10 * 60 * 1000).toISOString());

	return apiSuccess(res, {
		master_switch: config?.is_enabled ?? false,
		group_mode_enabled: config?.group_mode_enabled ?? false,
		ai_queue_fill_enabled: config?.enable_ai_queue_fill ?? false,
		queue_counts: statusCounts,
		overdue_items_count: overdueCount ?? 0,
		last_5_published: last5WithGaps,
		burst_alerts: burstAccounts,
		failed_count: failedCount ?? 0,
		stuck_publishing_count: stuckCount ?? 0,
		checked_at: now,
	});
}

// ============================================================================
// get-publish-log — Recent publishes with gap analysis
// ============================================================================

export async function handleGetPublishLog(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { limit } = req.body || {};
	const workspaceId = await resolveWorkspaceId(
		req.body?.workspaceId,
		userId,
		res,
	);
	if (!workspaceId) return;
	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;

	const maxItems = Math.min(Math.max(Number(limit) || 30, 1), 100);

	// Get published items joined with account info + group info
	const { data: published } = await db()
		.from("auto_post_queue")
		.select("id, account_id, posted_at, content, group_id")
		.eq("workspace_id", workspaceId)
		.eq("status", "published")
		.not("posted_at", "is", null)
		.order("posted_at", { ascending: false })
		.limit(maxItems + 50); // fetch extra for gap calculation

	if (!published || published.length === 0) {
		return apiSuccess(res, { posts: [], total: 0 });
	}

	// Get account usernames
	const accountIds = [
		...new Set(
			published
				.map((p: { account_id: string }) => p.account_id)
				.filter(Boolean),
		),
	];
	const { data: accounts } = await db()
		.from("accounts")
		.select("id, username")
		.in("id", accountIds);
	const accountMap = new Map(
		(accounts || []).map((a: { id: string; username: string }) => [
			a.id,
			a.username,
		]),
	);

	// Get group names
	const groupIds = [
		...new Set(
			published.map((p: { group_id: string }) => p.group_id).filter(Boolean),
		),
	];
	const { data: groups } = await db()
		.from("account_groups")
		.select("id, name")
		.in("id", groupIds);
	const groupMap = new Map(
		(groups || []).map((g: { id: string; name: string }) => [g.id, g.name]),
	);

	// Calculate per-account gaps
	const lastPostByAccount = new Map<string, string>();
	const result: Array<Record<string, unknown>> = [];

	for (const post of published) {
		const prevTime = lastPostByAccount.get(post.account_id);
		const gapSeconds = prevTime
			? Math.round(
					(new Date(prevTime).getTime() - new Date(post.posted_at).getTime()) /
						1000,
				)
			: null;
		lastPostByAccount.set(post.account_id, post.posted_at);

		if (result.length < maxItems) {
			result.push({
				account_username: accountMap.get(post.account_id) || post.account_id,
				published_at: post.posted_at,
				seconds_since_previous_on_same_account: gapSeconds,
				content_preview: post.content?.substring(0, 80),
				group_name: groupMap.get(post.group_id) || post.group_id,
			});
		}
	}

	return apiSuccess(res, { posts: result, total: result.length });
}

// ============================================================================
// Tool: Get Account Health — token/reauth status for all accounts
// ============================================================================

export async function handleGetAccountHealth(
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

	// Get workspace owner to query their accounts
	const { data: workspace } = await db()
		.from("workspaces")
		.select("owner_id")
		.eq("id", workspaceId)
		.maybeSingle();

	if (!workspace) return apiError(res, 404, "Workspace not found");

	const ownerId = workspace.owner_id;

	// Fetch Threads + IG accounts in parallel
	const [
		{ data: threadAccounts, error: tErr },
		{ data: igAccounts, error: iErr },
	] = await Promise.all([
		db()
			.from("accounts")
			.select(
				"id, username, threads_user_id, is_active, needs_reauth, is_retired, is_shadowbanned, status, updated_at",
			)
			.eq("user_id", ownerId)
			.order("username"),
		db()
			.from("instagram_accounts")
			.select(
				"id, username, instagram_user_id, is_active, needs_reauth, updated_at",
			)
			.eq("user_id", ownerId)
			.order("username"),
	]);

	if (tErr || iErr) {
		logger.error("[monitoringHandlers] Failed to fetch accounts for health check", {
			threadsError: tErr ? String(tErr) : undefined,
			instagramError: iErr ? String(iErr) : undefined,
		});
		return apiError(res, 500, "Failed to fetch accounts");
	}

	// Also get group assignments for context
	const { data: groups } = await db()
		.from("account_groups")
		.select("id, name, account_ids")
		.eq("user_id", ownerId);

	const groupMap = new Map<string, string>();
	for (const g of (groups || []) as Array<{
		id: string;
		name: string;
		account_ids: string[];
	}>) {
		for (const aid of g.account_ids || []) {
			groupMap.set(aid, g.name);
		}
	}

	const threads = (
		(threadAccounts || []) as Array<Record<string, unknown>>
	).map((a) => ({
		account_id: a.id,
		username: a.username,
		platform: "threads",
		is_active: a.is_active ?? false,
		needs_reauth: a.needs_reauth ?? false,
		is_retired: a.is_retired ?? false,
		is_shadowbanned: a.is_shadowbanned ?? false,
		status: a.status || "unknown",
		group: groupMap.get(a.id as string) || null,
		last_sync_at: a.updated_at,
	}));

	const instagram = ((igAccounts || []) as Array<Record<string, unknown>>).map(
		(a) => ({
			account_id: a.id,
			username: a.username,
			platform: "instagram",
			is_active: a.is_active ?? false,
			needs_reauth: a.needs_reauth ?? false,
			is_retired: false,
			is_shadowbanned: false,
			status: a.is_active ? "active" : "inactive",
			group: null,
			last_sync_at: a.updated_at,
		}),
	);

	const combined = [...threads, ...instagram];
	const needsAttention = combined.filter(
		(a) => a.needs_reauth || a.is_retired || a.is_shadowbanned || !a.is_active,
	);

	return apiSuccess(res, {
		accounts: combined,
		total: combined.length,
		healthy: combined.length - needsAttention.length,
		needsAttention: needsAttention.length,
		issues: needsAttention.map((a) => ({
			username: a.username,
			platform: a.platform,
			reason: a.needs_reauth
				? "needs_reauth"
				: a.is_retired
					? "retired"
					: a.is_shadowbanned
						? "shadowbanned"
						: "inactive",
		})),
	});
}
