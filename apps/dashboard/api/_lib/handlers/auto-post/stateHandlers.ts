// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * State Handlers — API handlers for account state visibility + control.
 *
 * Phase 5 of the auto-poster simplification plan.
 * Backs 3 MCP tools: get_account_states, get_queue_fill_explain, override_account_state.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";
import {
	type AccountAutoposterStatus,
	getGroupAccountStates,
	getWorkspaceAccountStates,
	statusLabel,
	upsertAccountState,
} from "./accountState.js";

// biome-ignore lint/suspicious/noExplicitAny: auto_post tables not in generated types
const db = (): any => getSupabaseAny();

// ============================================================================
// get_account_states — "Why aren't my accounts posting?"
// ============================================================================

export async function handleGetAccountStates(
	req: VercelRequest,
	res: VercelResponse,
	_userId: string,
): Promise<VercelResponse | undefined> {
	const { workspaceId, groupId } = req.body as {
		workspaceId?: string | undefined;
		groupId?: string | undefined;
	};

	if (!workspaceId) {
		return apiError(res, 400, "workspaceId required");
	}

	const states = groupId
		? await getGroupAccountStates(groupId)
		: await getWorkspaceAccountStates(workspaceId);

	// Enrich with username from accounts table
	const accountIds = states.map((s) => s.account_id);
	const { data: accounts } = await db()
		.from("accounts")
		.select("id, username")
		.in("id", accountIds);

	const usernameMap = new Map<string, string>();
	if (accounts) {
		for (const a of accounts as Array<{ id: string; username: string }>) {
			usernameMap.set(a.id, a.username);
		}
	}

	// Build summary
	const statusCounts: Record<string, number> = {};
	const enriched = states.map((s) => {
		statusCounts[s.status] = (statusCounts[s.status] ?? 0) + 1;
		return {
			account_id: s.account_id,
			username: usernameMap.get(s.account_id) ?? "unknown",
			status: s.status,
			status_label: statusLabel(s.status),
			status_reason: s.status_reason,
			blocked_until: s.blocked_until,
			performance: {
				avg_views_14d: s.last_14d_avg_views,
				median_views_30d: s.median_30d_views,
				max_views_30d: s.max_30d_views,
				pct_under_5_views: s.pct_under_5_views,
			},
			counters: {
				flop_proven_remaining: s.flop_proven_remaining,
				probe_posts_remaining: s.probe_posts_remaining,
				warming_posts_today: s.warming_posts_today,
			},
			evaluated_at: s.evaluated_at,
		};
	});

	return apiSuccess(res, {
		total: states.length,
		summary: statusCounts,
		accounts: enriched,
	});
}

// ============================================================================
// get_queue_fill_explain — "Why did the last fill produce 0 posts?"
// ============================================================================

export async function handleGetQueueFillExplain(
	req: VercelRequest,
	res: VercelResponse,
	_userId: string,
): Promise<VercelResponse | undefined> {
	const { workspaceId, groupId, limit } = req.body as {
		workspaceId?: string | undefined;
		groupId?: string | undefined;
		limit?: number | undefined;
	};

	if (!workspaceId) {
		return apiError(res, 400, "workspaceId required");
	}

	const maxItems = Math.min(limit ?? 10, 50);

	let query = db()
		.from("queue_fill_log")
		.select("*")
		.eq("workspace_id", workspaceId)
		.order("completed_at", { ascending: false })
		.limit(maxItems);

	if (groupId) {
		query = query.eq("group_id", groupId);
	}

	const { data, error } = await query;

	if (error) {
		logger.error("[stateHandlers] Failed to query queue_fill_log", {
			error: error.message,
		});
		return apiError(res, 500, "Failed to query fill logs");
	}

	const fills = (data ?? []).map((row: Record<string, unknown>) => ({
		id: row.id,
		group_id: row.group_id,
		started_at: row.started_at,
		completed_at: row.completed_at,
		posts_inserted: row.posts_inserted,
		posts_generated: row.posts_generated,
		posts_rejected: row.posts_rejected,
		rejection_summary: row.rejection_summary,
		account_summary: row.account_summary,
		skip_details: row.skip_details,
		duration_ms: row.duration_ms,
		early_exit_reason: row.early_exit_reason,
	}));

	return apiSuccess(res, { fills, count: fills.length });
}

// ============================================================================
// override_account_state — Force-resume, force-pause, or clear cooldown
// ============================================================================

export async function handleOverrideAccountState(
	req: VercelRequest,
	res: VercelResponse,
	_userId: string,
): Promise<VercelResponse | undefined> {
	const { accountId, groupId, workspaceId, action, reason } = req.body as {
		accountId?: string | undefined;
		groupId?: string | undefined;
		workspaceId?: string | undefined;
		action?: string | undefined;
		reason?: string | undefined;
	};

	if (!accountId || !groupId || !workspaceId) {
		return apiError(res, 400, "accountId, groupId, and workspaceId required");
	}

	const validActions = ["resume", "pause", "clear_cooldown"];
	if (!action || !validActions.includes(action)) {
		return apiError(
			res,
			400,
			`action must be one of: ${validActions.join(", ")}`,
		);
	}

	let status: AccountAutoposterStatus;
	let statusReason: string;
	let blockedUntil: string | null = null;

	switch (action) {
		case "resume":
			status = "active";
			statusReason = reason ?? "Manual override: resumed by operator";
			break;
		case "pause":
			status = "inactive";
			statusReason = reason ?? "Manual override: paused by operator";
			blockedUntil = new Date(
				Date.now() + 30 * 24 * 60 * 60 * 1000,
			).toISOString(); // 30 days
			break;
		case "clear_cooldown":
			status = "active";
			statusReason = reason ?? "Manual override: cooldown cleared by operator";
			break;
		default:
			return apiError(res, 400, `Unknown action: ${action}`);
	}

	const success = await upsertAccountState(accountId, {
		group_id: groupId,
		workspace_id: workspaceId,
		status,
		status_reason: statusReason,
		blocked_until: blockedUntil,
		// Reset counters on resume/clear
		...(action !== "pause"
			? {
					flop_proven_remaining: 0,
					probe_posts_remaining: 0,
				}
			: {}),
	});

	if (!success) {
		return apiError(res, 500, "Failed to update account state");
	}

	// Also clear Redis keys if resuming (so legacy path doesn't re-block)
	if (action === "resume" || action === "clear_cooldown") {
		try {
			const { getRedis } = await import("../../redis.js");
			const redis = getRedis();
			await Promise.all([
				redis.del(`suppressed:${accountId}`),
				redis.del(`suppressed-probe:${accountId}`),
				redis.del(`view-cooldown:${accountId}`),
				redis.del(`viral-suppress:${accountId}`),
				redis.del(`flop-delay:${accountId}`),
				redis.del(`flop-proven:${accountId}`),
			]);
		} catch {
			// Redis unavailable — DB state is authoritative, Redis will expire naturally
		}
	}

	logger.info("[stateHandlers] Account state overridden", {
		accountId,
		action,
		status,
		reason: statusReason,
	});

	return apiSuccess(res, {
		accountId,
		action,
		newStatus: status,
		reason: statusReason,
		blockedUntil,
		note: "State evaluator will re-evaluate on next run (≤15 min)",
	});
}

// ============================================================================
// get_autoposter_snapshot — Full system context in one call
// ============================================================================

export async function handleGetAutoposterSnapshot(
	req: VercelRequest,
	res: VercelResponse,
	_userId: string,
): Promise<VercelResponse | undefined> {
	const { workspaceId } = req.body as { workspaceId?: string | undefined };
	if (!workspaceId) return apiError(res, 400, "workspaceId required");

	const now = new Date();

	// Run all queries in parallel
	const [
		statesResult,
		groupsResult,
		overridesResult,
		queueResult,
		fillsResult,
		configResult,
		publishedTodayResult,
	] = await Promise.all([
		// 1. All account states
		db()
			.from("account_autoposter_state")
			.select("*")
			.eq("workspace_id", workspaceId),
		// 2. All enabled groups with config
		db()
			.from("auto_post_group_config")
			.select(
				"group_id, enabled, media_attachment_chance, media_source, media_group_id, active_hours_start, active_hours_end, timezone, posts_per_account_per_day, post_on_weekends",
			)
			.eq("workspace_id", workspaceId)
			.eq("enabled", true),
		// 3. All account overrides (active hours)
		db()
			.from("auto_post_account_overrides")
			.select("account_id, group_id, overrides")
			.eq("workspace_id", workspaceId),
		// 4. Queue counts by status
		db()
			.from("auto_post_queue")
			.select("status")
			.eq("workspace_id", workspaceId)
			.in("status", ["pending", "published", "failed", "dead_letter"]),
		// 5. Last 3 fills per group
		db()
			.from("queue_fill_log")
			.select(
				"group_id, posts_inserted, posts_generated, posts_rejected, rejection_summary, account_summary, early_exit_reason, completed_at, duration_ms",
			)
			.eq("workspace_id", workspaceId)
			.order("completed_at", { ascending: false })
			.limit(20),
		// 6. Master config
		db()
			.from("auto_post_config")
			.select("is_enabled, group_mode_enabled, enable_ai_queue_fill")
			.eq("workspace_id", workspaceId)
			.maybeSingle(),
		// 7. Posts published today
		db()
			.from("auto_post_queue")
			.select(
				"account_id, posted_at, content, group_id, views_at_24h, media_urls",
			)
			.eq("workspace_id", workspaceId)
			.eq("status", "published")
			.gte("posted_at", `${now.toISOString().split("T")[0]!}T00:00:00Z`)
			.order("posted_at", { ascending: false }),
	]);

	// Enrich states with usernames + group names
	const accountIds = (statesResult.data ?? []).map(
		(s: { account_id: string }) => s.account_id,
	);
	const groupIds = (groupsResult.data ?? []).map(
		(g: { group_id: string }) => g.group_id,
	);

	const [accountsResult, groupNamesResult, mediaCountsResult] =
		await Promise.all([
			db()
				.from("accounts")
				.select(
					"id, username, is_active, needs_reauth, token_expires_at, followers_count",
				)
				.in("id", accountIds),
			db()
				.from("account_groups")
				.select("id, name, account_ids")
				.in("id", groupIds),
			db().from("media").select("group_id").in("group_id", groupIds),
		]);

	const usernameMap = new Map<string, Record<string, unknown>>();
	for (const a of (accountsResult.data ?? []) as Array<
		Record<string, unknown>
	>) {
		usernameMap.set(a.id as string, a);
	}
	const groupNameMap = new Map<string, Record<string, unknown>>();
	for (const g of (groupNamesResult.data ?? []) as Array<
		Record<string, unknown>
	>) {
		groupNameMap.set(g.id as string, g);
	}

	// Media count per group
	const mediaByGroup: Record<string, number> = {};
	for (const m of (mediaCountsResult.data ?? []) as Array<{
		group_id: string;
	}>) {
		mediaByGroup[m.group_id] = (mediaByGroup[m.group_id] ?? 0) + 1;
	}

	// Override map: accountId → overrides
	const overrideMap = new Map<string, Record<string, unknown>>();
	for (const o of (overridesResult.data ?? []) as Array<{
		account_id: string;
		overrides: Record<string, unknown>;
	}>) {
		overrideMap.set(o.account_id, o.overrides);
	}

	// Build status summary
	const statusCounts: Record<string, number> = {};
	const accountsByStatus: Record<string, Array<Record<string, unknown>>> = {};

	for (const s of (statesResult.data ?? []) as Array<Record<string, unknown>>) {
		const status = s.status as string;
		statusCounts[status] = (statusCounts[status] ?? 0) + 1;
		if (!accountsByStatus[status]) accountsByStatus[status] = [];

		const acct = usernameMap.get(s.account_id as string);
		const override = overrideMap.get(s.account_id as string);

		accountsByStatus[status].push({
			account_id: s.account_id,
			username: acct?.username ?? "unknown",
			status_reason: s.status_reason,
			blocked_until: s.blocked_until,
			active_hours: override
				? `${override.active_hours_start ?? "?"}-${override.active_hours_end ?? "?"}`
				: "group_default",
			avg_views_14d: s.last_14d_avg_views,
			token_ok: acct ? !!(acct.is_active && !acct.needs_reauth) : false,
		});
	}

	// Build group summary
	const groups = (groupsResult.data ?? []).map(
		(gc: Record<string, unknown>) => {
			const info = groupNameMap.get(gc.group_id as string);
			const totalAccounts = info
				? ((info.account_ids as string[])?.length ?? 0)
				: 0;
			return {
				group_id: gc.group_id,
				name: (info?.name as string) ?? "unknown",
				total_accounts: totalAccounts,
				posts_per_account_per_day: gc.posts_per_account_per_day,
				media_count: mediaByGroup[gc.group_id as string] ?? 0,
				media_source: gc.media_source,
				media_group_id: gc.media_group_id,
				active_hours: `${gc.active_hours_start}-${gc.active_hours_end} ${gc.timezone ?? "UTC"}`,
				media_attachment_chance: gc.media_attachment_chance,
			};
		},
	);

	// Queue counts
	const queueCounts: Record<string, number> = {};
	for (const q of (queueResult.data ?? []) as Array<{ status: string }>) {
		queueCounts[q.status] = (queueCounts[q.status] ?? 0) + 1;
	}

	// Last fills (grouped by group, last 2 each)
	const fillsByGroup: Record<string, Array<Record<string, unknown>>> = {};
	for (const f of (fillsResult.data ?? []) as Array<Record<string, unknown>>) {
		const gid = f.group_id as string;
		if (!fillsByGroup[gid]) fillsByGroup[gid] = [];
		if (fillsByGroup[gid].length < 2) {
			fillsByGroup[gid].push({
				posts_inserted: f.posts_inserted,
				posts_generated: f.posts_generated,
				posts_rejected: f.posts_rejected,
				rejection_summary: f.rejection_summary,
				account_summary: f.account_summary,
				early_exit_reason: f.early_exit_reason,
				completed_at: f.completed_at,
				duration_ms: f.duration_ms,
			});
		}
	}

	// Published today summary
	const publishedToday = (publishedTodayResult.data ?? []).map(
		(p: Record<string, unknown>) => ({
			account_id: p.account_id,
			username: usernameMap.get(p.account_id as string)?.username ?? "unknown",
			posted_at: p.posted_at,
			content_preview: ((p.content as string) ?? "").substring(0, 60),
			has_media: !!(p.media_urls && (p.media_urls as string[]).length > 0),
			views_at_24h: p.views_at_24h,
		}),
	);

	return apiSuccess(res, {
		snapshot_at: now.toISOString(),
		master: {
			enabled: configResult.data?.is_enabled ?? false,
			group_mode: configResult.data?.group_mode_enabled ?? false,
			ai_fill: configResult.data?.enable_ai_queue_fill ?? false,
		},
		account_states: {
			total: accountIds.length,
			summary: statusCounts,
			by_status: accountsByStatus,
		},
		groups,
		queue: queueCounts,
		last_fills: fillsByGroup,
		published_today: { count: publishedToday.length, posts: publishedToday },
	});
}
