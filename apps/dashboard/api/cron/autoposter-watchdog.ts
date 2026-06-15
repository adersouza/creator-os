// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Autoposter Watchdog Cron
 *
 * Runs every 30 minutes. Checks 8 health dimensions across all enabled
 * workspaces and groups:
 *
 * 1. Silent groups — groups that should be posting but haven't in 2+ hours
 * 2. Empty/low queues — groups below their fill threshold
 * 3. Stuck processing — queue items in "processing" for >30 min (survived multiple recovery cycles)
 * 4. Content filter rejection rate — >50% means Gemini prompt needs tuning
 * 5. Zero-view accounts — possible shadowban (aggregated per-workspace, not per-account)
 * 6. AI generation cap — approaching daily limit
 * 7. Stuck scheduled — QStash items past their scheduled_for
 * 8. Expiring tokens — emergency refresh for tokens expiring within 6 hours
 *
 * Noise reduction:
 * - Dedup: won't re-fire an alert if the same check is already unresolved within the last 2h
 * - Zero-view: aggregated into one alert, skips already-flagged accounts, requires recent posts
 * - Stuck processing: 30-min threshold (orphan recovery handles 15-min in publish-worker)
 * - Silent groups: skips groups with empty queues (already caught by low-queue check)
 *
 * Alerts are written to the watchdog_alerts table and sent to Discord
 * (per-workspace URL or global fallback).
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { AlertLevel, alert } from "../_lib/alerting.js";
import { trackCronRun, withCronLock } from "../_lib/cronUtils.js";
import { isAutoposterHardDisabled } from "../_lib/handlers/auto-post/killSwitch.js";
import {
	deadLetterQueueItems,
	recoverQueueItemsToPending,
} from "../_lib/handlers/auto-post/queueState.js";
import { logger } from "../_lib/logger.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";
import { isDefinitiveOAuthError } from "../_lib/retryUtils.js";
import { refreshThreadsToken } from "../_lib/tokenRefresh.js";

const db = () =>
	getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.autoposterWatchdog);

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface WatchdogAlert {
	workspace_id: string;
	check_name: string;
	severity: string;
	message: string;
	details: Record<string, unknown>;
}

interface GroupConfig {
	group_id: string;
	workspace_id: string;
	enabled: boolean;
	min_interval_minutes: number;
	posts_per_account_per_day: number;
	active_hours_start: number;
	active_hours_end: number;
	timezone: string;
}

interface WorkspaceConfig {
	workspace_id: string;
	is_enabled: boolean;
	enable_ai_queue_fill: boolean;
	ai_queue_min_threshold: number;
	ai_daily_generation_limit: number;
	ai_generations_today: number;
	ai_last_generation_date: string | null;
	discord_webhook_url: string | null;
}

interface AccountGroupNameRow {
	id: string;
	name: string;
	account_ids: string[] | null;
}

interface WarmupStateRow {
	account_id: string;
	status: string | null;
	restart_warmup_status: string | null;
	restart_warmup_allowed_posts_per_day: number | null;
	recommended_strategy_mode?: string | null;
	recommended_posts_per_day?: number | null;
}

interface AccountScheduleDemandRow {
	account_id: string;
	posts_per_day: number | null;
	paused?: boolean | null;
	status?: string | null;
	blocked_until?: string | null;
}

interface WatchdogAccountRow {
	id: string;
	username: string | null;
	followers_count: number | null;
	created_at: string | null;
	is_shadowbanned: boolean | null;
	needs_reauth: boolean | null;
	status: string | null;
}

interface WatchdogCheckResult {
	currentAlerts: WatchdogAlert[];
	notificationAlerts: WatchdogAlert[];
	suppressedDuplicateCount: number;
}

const DEFAULT_OPEN_ALERT_TTL_MS = 24 * 60 * 60 * 1000;
const SHORT_LIVED_OPEN_ALERT_TTL_MS = 3 * 60 * 60 * 1000;
const SHORT_LIVED_ALERT_CHECKS = new Set([
	"empty-queue",
	"low-queue",
	"high-filter-rejection",
	"queue-fill-not-executing",
	"silent-group",
]);

const ALERT_OWNER = "threads_autoposter_ops";

const ALERT_RESOLUTION_CONDITIONS: Record<string, string> = {
	"empty-queue": "group has pending/queued publishable rows or no uncovered capacity",
	"low-queue": "ready depth meets demand-aware threshold or no uncovered capacity",
	"high-filter-rejection":
		"recent queue-fill inserts rows or queue depth recovers above threshold",
	"queue-fill-not-executing":
		"queue-fill run starts after scheduler dispatch or queue recovers",
	"silent-group":
		"group has publish activity or skip outcomes are expected safety decisions",
	"stuck-processing": "stuck rows are recovered or moved to terminal state",
	"zero-views": "recent posts receive views or account enters reduced/suppressed mode",
	"ai-cap-warning": "AI generation count drops below cap warning threshold",
	"stuck-scheduled": "overdue scheduled rows publish, requeue, or become terminal",
	"stuck-publishing": "publishing rows finalize, requeue, or dead-letter",
	"expiring-tokens": "tokens are refreshed or accounts are marked for reauth",
};

const ALERT_RESOLUTION_BATCH_SIZE = 100;
const OPEN_ALERT_FETCH_PAGE_SIZE = 1000;

export function openAlertTtlMs(checkName: string): number {
	return SHORT_LIVED_ALERT_CHECKS.has(checkName)
		? SHORT_LIVED_OPEN_ALERT_TTL_MS
		: DEFAULT_OPEN_ALERT_TTL_MS;
}

export function isOpenAlertExpired(
	checkName: string,
	createdAt: string | null | undefined,
	nowMs = Date.now(),
): boolean {
	if (!createdAt) return false;
	const createdMs = new Date(createdAt).getTime();
	if (!Number.isFinite(createdMs)) return false;
	return nowMs - createdMs > openAlertTtlMs(checkName);
}

function alertOperationalDetails(a: WatchdogAlert): Record<string, unknown> {
	const baseDetails =
		a.details && typeof a.details === "object" && !Array.isArray(a.details)
			? (a.details as Record<string, unknown>)
			: {};
	return {
		...baseDetails,
		owner: baseDetails.owner ?? ALERT_OWNER,
		severity: baseDetails.severity ?? a.severity,
		ttlMs: baseDetails.ttlMs ?? openAlertTtlMs(a.check_name),
		evidenceGeneratedAt:
			baseDetails.evidenceGeneratedAt ?? new Date().toISOString(),
		resolutionCondition:
			baseDetails.resolutionCondition ??
			ALERT_RESOLUTION_CONDITIONS[a.check_name] ??
			"condition no longer appears in current watchdog evidence",
	};
}

// ---------------------------------------------------------------------------
// Main handler
// ---------------------------------------------------------------------------

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../_lib/apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const globalStart = Date.now();
	try {
		if (isAutoposterHardDisabled()) {
			logger.info("[watchdog] Skipping due to global hard disable");
			return res
				.status(200)
				.json({ ok: true, skipped: true, reason: "hard_disabled" });
		}

		const supabase = db();
		const lockResult = await withCronLock(
			supabase as SupabaseClient,
			"autoposter-watchdog",
			async () => {
				return trackCronRun(
					supabase as SupabaseClient,
					"autoposter-watchdog",
					async () => {
						// 110s soft timeout — leave 10s headroom for response + cleanup
						const timeoutMs = 110_000;
						const timeoutPromise = new Promise<WatchdogCheckResult>(
							(_, reject) =>
								setTimeout(
									() => reject(new Error("watchdog_time_budget_exceeded")),
									timeoutMs - (Date.now() - globalStart),
								),
						);
						const checkResult = await Promise.race([
							runAllChecks(),
							timeoutPromise,
						]);

						await persistAlerts(
							checkResult.notificationAlerts,
							checkResult.currentAlerts,
						);
						if (checkResult.notificationAlerts.length > 0) {
							await sendDiscordAlerts(checkResult.notificationAlerts);
						}

						return {
							itemsProcessed: checkResult.notificationAlerts.length,
							metadata: {
								alertCount: checkResult.notificationAlerts.length,
								currentAlertCount: checkResult.currentAlerts.length,
								suppressedDuplicateCount:
									checkResult.suppressedDuplicateCount,
								checks: [
									"silent-groups",
									"low-queues",
									"stuck-processing",
									"filter-rejection-rate",
									"zero-views",
									"ai-cap-warning",
									"stuck-scheduled",
									"expiring-tokens",
									"stuck-publishing",
								],
							},
						};
					},
				);
			},
			125,
		);

		if ("skipped" in lockResult && lockResult.skipped) {
			return res.status(200).json({ skipped: true });
		}

		return res.status(200).json({ ok: true, ...lockResult });
	} catch (err: unknown) {
		const msg = err instanceof Error ? err.message : String(err);
		logger.error("[watchdog] Fatal error", { error: msg });
		const { alertCronFailure } = await import("../_lib/alerting.js");
		await alertCronFailure("autoposter-watchdog", msg);
		return res.status(500).json({ error: "Watchdog failed" });
	}
}

// ---------------------------------------------------------------------------
// Orchestrator — runs all 8 checks
// ---------------------------------------------------------------------------

async function runAllChecks(): Promise<WatchdogCheckResult> {
	// Load all enabled workspace configs
	const { data: workspaces } = await db()
		.from("auto_post_config")
		.select(
			"workspace_id, is_enabled, enable_ai_queue_fill, ai_queue_min_threshold, ai_daily_generation_limit, ai_generations_today, ai_last_generation_date, discord_webhook_url, scheduler_version",
		)
		.eq("is_enabled", true);

	const allWorkspaces = (workspaces ?? []) as Array<
		WorkspaceConfig & { scheduler_version?: number | null | undefined }
	>;

	if (allWorkspaces.length === 0) {
		return {
			currentAlerts: [],
			notificationAlerts: [],
			suppressedDuplicateCount: 0,
		};
	}

	// Load all enabled group configs
	const wsIds = allWorkspaces.map((w) => w.workspace_id);
	const { data: groups } = await db()
		.from("auto_post_group_config")
		.select(
			"group_id, workspace_id, enabled, min_interval_minutes, posts_per_account_per_day, active_hours_start, active_hours_end, timezone",
		)
		.in("workspace_id", wsIds)
		.eq("enabled", true);

	if (!groups || groups.length === 0) {
		return {
			currentAlerts: [],
			notificationAlerts: [],
			suppressedDuplicateCount: 0,
		};
	}

	const groupConfigs = groups as unknown as GroupConfig[];
	const wsConfigs = allWorkspaces as WorkspaceConfig[];

	// Load recently-fired alerts for dedup (don't re-fire same check within 2h)
	const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
	const { data: recentAlerts } = await db()
		.from("watchdog_alerts")
		.select("workspace_id, check_name")
		.is("resolved_at", null)
		.gte("created_at", twoHoursAgo);

	const recentKeys = new Set(
		(recentAlerts || []).map(
			(a: { workspace_id: string; check_name: string }) =>
				`${a.workspace_id}:${a.check_name}`,
		),
	);

	const alerts: WatchdogAlert[] = [];

	// Run all 9 checks (expiring-tokens is independent of autoposter workspaces)
	const results = await Promise.allSettled([
		checkSilentGroups(groupConfigs, alerts),
		checkLowQueues(groupConfigs, wsConfigs, alerts),
		checkStuckProcessing(wsConfigs, alerts),
		checkFilterRejectionRate(wsConfigs, alerts),
		checkZeroViewAccounts(wsIds, alerts),
		checkAICapWarning(wsConfigs, alerts),
		checkStuckScheduled(wsConfigs, alerts),
		checkExpiringTokens(alerts),
		checkStuckPublishing(wsConfigs, alerts),
	]);

	for (const result of results) {
		if (result.status === "rejected") {
			logger.error("[watchdog] Check failed", {
				error: String(result.reason),
			});
		}
	}

	// Dedup: drop alerts that already have an unresolved entry within last 2h
	const deduped = alerts.filter(
		(a) => !recentKeys.has(`${a.workspace_id}:${a.check_name}`),
	);

	const suppressed = alerts.length - deduped.length;
	if (suppressed > 0) {
		logger.info("[watchdog] Suppressed duplicate alerts", { suppressed });
	}

	logger.info("[watchdog] Completed", {
		alertCount: deduped.length,
		currentAlertCount: alerts.length,
		suppressed,
	});
	return {
		currentAlerts: alerts,
		notificationAlerts: deduped,
		suppressedDuplicateCount: suppressed,
	};
}

// ---------------------------------------------------------------------------
// Check 1: Silent groups — should be posting but haven't in last hour
// ---------------------------------------------------------------------------

async function checkSilentGroups(
	groupConfigs: GroupConfig[],
	alerts: WatchdogAlert[],
): Promise<void> {
	const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();

	// Get group names
	const groupIds = groupConfigs.map((g) => g.group_id);
	const { data: groupNames } = await db()
		.from("account_groups")
		.select("id, name, account_ids")
		.in("id", groupIds);
	const nameMap = new Map(
		(groupNames || []).map((g: { id: string; name: string }) => [g.id, g.name]),
	);
	const accountCountMap = new Map(
		(groupNames || []).map(
			(g: { id: string; account_ids: string[] | null }) => [
				g.id,
				(g.account_ids || []).length,
			],
		),
	);

	// Batch: count pending items per group to skip empty queues (caught by low-queue check)
	const pendingByGroup = new Map<string, number>();
	for (const gc of groupConfigs) {
		const { count } = await db()
			.from("auto_post_queue")
			.select("*", { count: "exact", head: true })
			.eq("workspace_id", gc.workspace_id)
			.eq("group_id", gc.group_id)
			.in("status", ["pending", "queued"]);
		pendingByGroup.set(gc.group_id, count || 0);
	}

	// Collect silent groups, then emit ONE aggregated alert per workspace
	const silentByWorkspace = new Map<string, string[]>();

	for (const gc of groupConfigs) {
		// Skip groups with 0 accounts
		const accountCount = accountCountMap.get(gc.group_id) || 0;
		if (accountCount === 0) continue;

		// Skip groups with empty queue — already caught by low-queue check
		if ((pendingByGroup.get(gc.group_id) || 0) === 0) continue;

		// Check if group is in active hours right now
		const now = new Date();
		const currentHour = getHourInTimezone(now, gc.timezone);
		if (
			!isInActiveHours(currentHour, gc.active_hours_start, gc.active_hours_end)
		)
			continue;

		// Count posts published in last 2 hours for this group
		const { count } = await db()
			.from("auto_post_queue")
			.select("*", { count: "exact", head: true })
			.eq("workspace_id", gc.workspace_id)
			.eq("group_id", gc.group_id)
			.in("status", ["posted", "published"])
			.gte("posted_at", twoHoursAgo);

		if ((count || 0) === 0) {
			const name = nameMap.get(gc.group_id) || gc.group_id.slice(0, 8);
			const list = silentByWorkspace.get(gc.workspace_id) || [];
			list.push(name);
			silentByWorkspace.set(gc.workspace_id, list);
		}
	}

	// One alert per workspace listing all silent groups
	for (const [wsId, groupNamesList] of Array.from(silentByWorkspace)) {
		alerts.push({
			workspace_id: wsId,
			check_name: "silent-group",
			severity: "warn",
			message: `${groupNamesList.length} group(s) silent for 2+ hours during active hours: ${groupNamesList.join(", ")}`,
			details: { groups: groupNamesList },
		});
	}
}

// ---------------------------------------------------------------------------
// Check 2: Empty/low queues
// ---------------------------------------------------------------------------

async function checkLowQueues(
	groupConfigs: GroupConfig[],
	wsConfigs: WorkspaceConfig[],
	alerts: WatchdogAlert[],
): Promise<void> {
	const thresholdMap = new Map(
		wsConfigs.map((w) => [w.workspace_id, w.ai_queue_min_threshold || 3]),
	);

	// Get group names for readable output
	const groupIds = groupConfigs.map((g) => g.group_id);
	const { data: groupNames } = await db()
		.from("account_groups")
		.select("id, name, account_ids")
		.in("id", groupIds);
	const nameMap = new Map(
		((groupNames || []) as AccountGroupNameRow[]).map((g) => [g.id, g.name]),
	);
	const accountIdsByGroup = new Map(
		((groupNames || []) as AccountGroupNameRow[]).map((g) => [
			g.id,
			g.account_ids || [],
		]),
	);
	const allAccountIds = Array.from(
		new Set(Array.from(accountIdsByGroup.values()).flat()),
	);
	const stateByAccount = new Map<string, WarmupStateRow>();
	if (allAccountIds.length > 0) {
		const { data: states } = await db()
			.from("account_autoposter_state")
			.select(
				"account_id, status, restart_warmup_status, restart_warmup_allowed_posts_per_day, recommended_strategy_mode, recommended_posts_per_day",
			)
			.in("account_id", allAccountIds);
		for (const state of (states || []) as WarmupStateRow[]) {
			stateByAccount.set(state.account_id, state);
		}
	}
	const scheduleByAccount = new Map<string, AccountScheduleDemandRow>();
	if (allAccountIds.length > 0) {
		const { data: schedules } = await db()
			.from("account_schedule")
			.select("account_id, posts_per_day, paused, status, blocked_until")
			.in("account_id", allAccountIds);
		for (const schedule of (schedules || []) as AccountScheduleDemandRow[]) {
			scheduleByAccount.set(schedule.account_id, schedule);
		}
	}

	// Collect empty/low groups per workspace, then emit one alert each
	const emptyByWorkspace = new Map<string, string[]>();
	const lowByWorkspace = new Map<string, string[]>();

	for (const gc of groupConfigs) {
		const { count } = await db()
			.from("auto_post_queue")
			.select("*", { count: "exact", head: true })
			.eq("workspace_id", gc.workspace_id)
			.eq("group_id", gc.group_id)
			.in("status", ["pending", "queued"]);

		const pending = count || 0;
		const configuredThreshold = thresholdMap.get(gc.workspace_id) || 3;
		const threshold = calculateDemandAwareQueueThreshold({
			configuredThreshold,
			groupDailyCap: gc.posts_per_account_per_day,
			accountIds: accountIdsByGroup.get(gc.group_id) || [],
			stateByAccount,
			scheduleByAccount,
		});
		const name = nameMap.get(gc.group_id) || gc.group_id.slice(0, 8);

		if (pending === 0) {
			const list = emptyByWorkspace.get(gc.workspace_id) || [];
			list.push(name);
			emptyByWorkspace.set(gc.workspace_id, list);
		} else if (pending < lowQueueWarningWatermark(threshold)) {
			const list = lowByWorkspace.get(gc.workspace_id) || [];
			list.push(`${name} (${pending}/${threshold})`);
			lowByWorkspace.set(gc.workspace_id, list);
		}
	}

	for (const [wsId, groupNamesList] of Array.from(emptyByWorkspace)) {
		alerts.push({
			workspace_id: wsId,
			check_name: "empty-queue",
			severity: "error",
			message: `${groupNamesList.length} group(s) with empty queue: ${groupNamesList.join(", ")}`,
			details: { groups: groupNamesList },
		});
	}

	for (const [wsId, groupNamesList] of Array.from(lowByWorkspace)) {
		alerts.push({
			workspace_id: wsId,
			check_name: "low-queue",
			severity: "warn",
			message: `${groupNamesList.length} group(s) with low queue: ${groupNamesList.join(", ")}`,
			details: { groups: groupNamesList },
		});
	}
}

export function calculateDemandAwareQueueThreshold({
	configuredThreshold,
	groupDailyCap,
	accountIds,
	stateByAccount,
	scheduleByAccount = new Map<string, AccountScheduleDemandRow>(),
}: {
	configuredThreshold: number;
	groupDailyCap: number;
	accountIds: string[];
	stateByAccount: Map<string, WarmupStateRow>;
	scheduleByAccount?: Map<string, AccountScheduleDemandRow>;
}): number {
	if (accountIds.length === 0) return Math.max(3, configuredThreshold);

	let expectedDailyDemand = 0;
	const nowMs = Date.now();
	for (const accountId of accountIds) {
		const state = stateByAccount.get(accountId);
		const status = state?.restart_warmup_status || state?.status || "none";
		const strategyMode = state?.recommended_strategy_mode || null;
		const accountSchedule = scheduleByAccount.get(accountId);
		const scheduleStatus = accountSchedule?.status ?? null;
		const scheduleBlockedUntil = accountSchedule?.blocked_until
			? new Date(accountSchedule.blocked_until).getTime()
			: null;
		if (
			accountSchedule?.paused === true ||
			(scheduleStatus && !["active", "enabled"].includes(scheduleStatus)) ||
			(typeof scheduleBlockedUntil === "number" &&
				Number.isFinite(scheduleBlockedUntil) &&
				scheduleBlockedUntil > nowMs)
		) {
			continue;
		}
		if (
			status === "suppressed" ||
			strategyMode === "suppress" ||
			state?.status === "suppressed" ||
			state?.status === "shadowban_throttle" ||
			state?.status === "inactive"
		) {
			continue;
		}

		if (status === "warming" || status === "held") {
			const restartCap = Math.max(
				0,
				state?.restart_warmup_allowed_posts_per_day ?? 1,
			);
			const recommendedCap =
				strategyMode === "reduce" || strategyMode === "suppressed_probe"
					? Math.max(1, state?.recommended_posts_per_day ?? 1)
					: restartCap;
			expectedDailyDemand += Math.min(restartCap, recommendedCap);
			continue;
		}

		if (strategyMode === "reduce" || strategyMode === "suppressed_probe") {
			expectedDailyDemand += Math.max(
				1,
				state?.recommended_posts_per_day ?? 1,
			);
			continue;
		}

		const accountScheduleCap = accountSchedule?.posts_per_day;
		expectedDailyDemand += Math.max(
			0,
			accountScheduleCap ?? groupDailyCap ?? 0,
		);
	}

	const demandThreshold = Math.max(
		3,
		Math.ceil(expectedDailyDemand),
	);
	return Math.max(3, Math.min(configuredThreshold, demandThreshold));
}

export function lowQueueWarningWatermark(threshold: number): number {
	return Math.max(2, Math.floor(threshold / 3));
}

// ---------------------------------------------------------------------------
// Check 3: Stuck processing — items in "processing" for >10 min
// ---------------------------------------------------------------------------

async function checkStuckProcessing(
	wsConfigs: WorkspaceConfig[],
	alerts: WatchdogAlert[],
): Promise<void> {
	// 30-min threshold: orphan recovery in publish-worker handles 15-min items every 5 min.
	// If something is still stuck after 30 min, it survived multiple recovery cycles → real problem.
	const thirtyMinAgo = new Date(Date.now() - 30 * 60 * 1000).toISOString();

	for (const ws of wsConfigs) {
		const { data: stuck } = await db()
			.from("auto_post_queue")
			.select("id, group_id, content, created_at")
			.eq("workspace_id", ws.workspace_id)
			.eq("status", "processing")
			.lt("created_at", thirtyMinAgo)
			.limit(10);

		// Only alert for 3+ stuck items — 1-2 is transient during normal publishing
		if (stuck && stuck.length >= 3) {
			alerts.push({
				workspace_id: ws.workspace_id,
				check_name: "stuck-processing",
				severity: "error",
				message: `${stuck.length} queue item(s) stuck in "processing" for >30 min (orphan recovery failed)`,
				details: {
					count: stuck.length,
					items: stuck.map((s) => ({
						id: s.id,
						groupId: s.group_id,
						contentPreview: (s.content || "").slice(0, 50),
					})),
				},
			});
		}
	}
}

// ---------------------------------------------------------------------------
// Check 4: Content filter rejection rate — >50% means prompt needs tuning
// ---------------------------------------------------------------------------

export async function checkFilterRejectionRate(
	wsConfigs: WorkspaceConfig[],
	alerts: WatchdogAlert[],
): Promise<void> {
	const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();

	for (const ws of wsConfigs) {
		if (!ws.enable_ai_queue_fill) continue;

		// Count AI-generated posts inserted in the last 3h
		const { count: inserted } = await db()
			.from("auto_post_queue")
			.select("*", { count: "exact", head: true })
			.eq("workspace_id", ws.workspace_id)
			.eq("source_type", "ai")
			.gte("created_at", threeHoursAgo);

		// We can't directly count rejections from DB (they're only logged),
		// but we can detect the symptom: AI fill enabled, queue still low,
		// and very few insertions relative to expected fill rate.
		// If ai_generations_today > 0 but queue is very low, something is being filtered.
		const genToday = ws.ai_generations_today || 0;
		const insertedCount = inserted || 0;

		// If we've attempted fills (generations > 10) but inserted very few, flag it
		if (genToday > 10 && insertedCount < Math.ceil(genToday * 0.3)) {
			// Check pending queue count as confirmation
			const { count: pending } = await db()
				.from("auto_post_queue")
				.select("*", { count: "exact", head: true })
				.eq("workspace_id", ws.workspace_id)
				.in("status", ["pending", "queued"]);

			const threshold = ws.ai_queue_min_threshold || 3;
			if ((pending || 0) < threshold) {
				const { data: schedulerRuns } = await db()
					.from("cron_runs")
					.select("metadata")
					.eq("job_name", "scheduler")
					.gte("started_at", threeHoursAgo)
					.order("started_at", { ascending: false })
					.limit(20);
				const fillDispatches = (schedulerRuns ?? []).reduce(
					(sum: number, run: { metadata?: Record<string, unknown> | null }) =>
						sum +
						Number(
							run.metadata &&
								Object.hasOwn(run.metadata, "dispatched")
								? run.metadata.dispatched
								: (run.metadata?.fillsTriggered ?? 0),
						),
					0,
				);
				const { data: queueFillRows } = await db()
					.from("queue_fill_log")
					.select("posts_inserted, posts_generated, early_exit_reason, started_at")
					.gte("started_at", threeHoursAgo);
				const queueFillRuns = queueFillRows?.length || 0;
				const recentSuccessfulFill = (queueFillRows || []).some(
					(row: {
						posts_inserted?: number | null;
						posts_generated?: number | null;
						early_exit_reason?: string | null;
					}) => Number(row.posts_inserted || 0) > 0,
				);

				if (fillDispatches > 0 && queueFillRuns === 0) {
					alerts.push({
						workspace_id: ws.workspace_id,
						check_name: "queue-fill-not-executing",
						severity: "error",
						message: `Scheduler dispatched ${fillDispatches} queue-fill job(s) in 3h, but no queue_fill run started. Queue is below threshold.`,
						details: {
							fillDispatches,
							queueFillRuns,
							pendingQueue: pending || 0,
							threshold,
							hint: "Check /api/queue-fill QStash delivery, signature, ownership validation, and outbound guard logs.",
						},
					});
					continue;
				}

				if (recentSuccessfulFill) continue;

				alerts.push({
					workspace_id: ws.workspace_id,
					check_name: "high-filter-rejection",
					severity: "warn",
					message: `Possible high content filter rejection rate: ${insertedCount} posts inserted in 3h but ${genToday} AI generations today. Queue still below threshold.`,
					details: {
						generationsToday: genToday,
						insertedLast3h: insertedCount,
						queueFillRuns,
						pendingQueue: pending || 0,
						threshold,
						hint: "Queue-fill ran but inserted too little. Check rejection summaries, content filters, LLM judge, and DB insert failures.",
					},
				});
			}
		}
	}
}

// ---------------------------------------------------------------------------
// Check 5: Zero-view accounts — possible shadowban
// ---------------------------------------------------------------------------

async function checkZeroViewAccounts(
	wsIds: string[],
	alerts: WatchdogAlert[],
): Promise<void> {
	// Get all accounts linked to these workspaces via groups
	const { data: groupData } = await db()
		.from("auto_post_group_config")
		.select("workspace_id, group_id")
		.in("workspace_id", wsIds)
		.eq("enabled", true);

	if (!groupData || groupData.length === 0) return;

	const groupIds = groupData.map((g: { group_id: string }) => g.group_id);
	const { data: groups } = await db()
		.from("account_groups")
		.select("id, account_ids, name")
		.in("id", groupIds);

	if (!groups) return;

	// Build account→workspace mapping
	const accountToWorkspace = new Map<string, string>();
	const accountToGroup = new Map<string, string>();
	for (const group of groups) {
		const wsId = groupData.find(
			(g: { group_id: string }) => g.group_id === group.id,
		)?.workspace_id;
		if (!wsId) continue;
		for (const aid of group.account_ids || []) {
			accountToWorkspace.set(aid, wsId);
			accountToGroup.set(aid, group.name || group.id);
		}
	}

	const allAccountIds = Array.from(accountToWorkspace.keys());
	if (allAccountIds.length === 0) return;

	// Batch-fetch account info (skip already-shadowbanned and small/new accounts)
	const { data: accountRows } = await db()
		.from("accounts")
		.select(
			"id, username, followers_count, created_at, is_shadowbanned, needs_reauth, status",
		)
		.in("id", allAccountIds);

	if (!accountRows) return;

	const MIN_FOLLOWERS_FOR_SHADOWBAN = 50;
	const MIN_ACCOUNT_AGE_DAYS = 14;
	// Collect flagged accounts per workspace, separated by confidence level
	const confirmedDeadByWorkspace = new Map<
		string,
		{ username: string; group: string; posts: number }[]
	>();
	const dataLagByWorkspace = new Map<
		string,
		{ username: string; group: string; posts: number; unsynced: number }[]
	>();

	const sevenDaysAgo = new Date(
		Date.now() - 7 * 24 * 60 * 60 * 1000,
	).toISOString();

	for (const account of (accountRows ?? []) as WatchdogAccountRow[]) {
		const accountId = account.id;
		const wsId = accountToWorkspace.get(accountId);
		if (!wsId) continue;

		// Skip accounts already flagged — no point re-alerting
		if (
			account.is_shadowbanned ||
			account.needs_reauth ||
			account.status === "suspended"
		)
			continue;

		// Skip new/small accounts — 0 views is expected
		const followers = account.followers_count ?? 0;
		const accountAgeDays = account.created_at
			? (Date.now() - new Date(account.created_at).getTime()) / 86_400_000
			: 0;
		if (
			followers < MIN_FOLLOWERS_FOR_SHADOWBAN &&
			accountAgeDays < MIN_ACCOUNT_AGE_DAYS
		)
			continue;

		// Get ALL published posts in last 7 days (need 10+ for confident diagnosis)
		const { data: recentPosts } = await db()
			.from("auto_post_queue")
			.select("id, views_at_24h, posted_at, engagement_fetched_at")
			.eq("account_id", accountId)
			.in("status", ["posted", "published"])
			.not("posted_at", "is", null)
			.gte("posted_at", sevenDaysAgo)
			.order("posted_at", { ascending: false })
			.limit(20);

		if (!recentPosts || recentPosts.length === 0) continue;

		// Split into synced (engagement_fetched_at IS NOT NULL) and unsynced
		const syncedPosts = recentPosts.filter(
			(p: { engagement_fetched_at: string | null }) =>
				p.engagement_fetched_at != null,
		);
		const unsyncedPosts = recentPosts.filter(
			(p: { engagement_fetched_at: string | null }) =>
				p.engagement_fetched_at == null,
		);

		const username = (account.username as string) || accountId.slice(0, 8);
		const group = accountToGroup.get(accountId) || "unknown";

		// Confirmed dead: 10+ published posts, engagement synced, STILL 0 views
		if (syncedPosts.length >= 10) {
			const totalViews = syncedPosts.reduce(
				(sum: number, p: { views_at_24h: number | null }) =>
					sum + ((p.views_at_24h as number) || 0),
				0,
			);

			if (totalViews === 0) {
				const list = confirmedDeadByWorkspace.get(wsId) || [];
				list.push({ username, group, posts: syncedPosts.length });
				confirmedDeadByWorkspace.set(wsId, list);
			}
		} else if (syncedPosts.length < 10 && unsyncedPosts.length > 0) {
			// Data lag: has unsynced posts, can't confirm dead yet
			// Only flag if there are enough total posts to be worth mentioning
			if (recentPosts.length >= 5 && syncedPosts.length === 0) {
				const list = dataLagByWorkspace.get(wsId) || [];
				list.push({
					username,
					group,
					posts: recentPosts.length,
					unsynced: unsyncedPosts.length,
				});
				dataLagByWorkspace.set(wsId, list);
			}
		}
	}

	// Emit ONE aggregated alert per workspace for CONFIRMED dead accounts
	for (const [wsId, flagged] of Array.from(confirmedDeadByWorkspace)) {
		if (flagged.length === 0) continue;

		const usernames = flagged.map((f) => `@${f.username}`).join(", ");
		alerts.push({
			workspace_id: wsId,
			check_name: "zero-views",
			severity: "warn",
			message: `${flagged.length} confirmed dead account(s) — 0 views on 10+ synced posts in 7 days: ${usernames}`,
			details: {
				count: flagged.length,
				accounts: flagged,
				note: "All accounts have engagement_fetched_at set and 10+ published posts with 0 views",
			},
		});
	}

	// Separate INFO-level alert for data lag accounts (not actionable yet)
	for (const [wsId, lagged] of Array.from(dataLagByWorkspace)) {
		if (lagged.length === 0) continue;

		// Only log, don't alert — these are not confirmed dead
		logger.info(
			"[watchdog] Accounts with unsynced engagement data (not alerting)",
			{
				workspace: wsId,
				count: lagged.length,
				accounts: lagged.map((l) => `@${l.username} (${l.unsynced} unsynced)`),
			},
		);
	}
}

// ---------------------------------------------------------------------------
// Check 6: AI generation cap warning
// ---------------------------------------------------------------------------

async function checkAICapWarning(
	wsConfigs: WorkspaceConfig[],
	alerts: WatchdogAlert[],
): Promise<void> {
	const today = new Date().toISOString().split("T")[0]!;

	for (const ws of wsConfigs) {
		if (!ws.enable_ai_queue_fill) continue;

		const limit = ws.ai_daily_generation_limit || 10;
		const used = ws.ai_generations_today || 0;

		// Only relevant if the counter is from today
		if (ws.ai_last_generation_date !== today) continue;

		const pctUsed = (used / limit) * 100;

		if (pctUsed >= 90) {
			alerts.push({
				workspace_id: ws.workspace_id,
				check_name: "ai-cap-warning",
				severity: pctUsed >= 100 ? "error" : "warn",
				message: `AI generation at ${Math.round(pctUsed)}% of daily limit (${used}/${limit})`,
				details: {
					used,
					limit,
					pctUsed: Math.round(pctUsed),
					exhausted: used >= limit,
				},
			});
		}
	}
}

// ---------------------------------------------------------------------------
// Check 7: Stuck scheduled/queued — QStash-backed items past scheduled_for by 30+ min
// ---------------------------------------------------------------------------

async function checkStuckScheduled(
	wsConfigs: WorkspaceConfig[],
	alerts: WatchdogAlert[],
): Promise<void> {
	const thirtyMinAgo = new Date(Date.now() - 30 * 60 * 1000).toISOString();

	for (const ws of wsConfigs) {
		const { data: stuck } = await db()
			.from("auto_post_queue")
			.select("id, group_id, scheduled_for, content, status, pool_status")
			.eq("workspace_id", ws.workspace_id)
			.in("status", ["scheduled", "queued"])
			.lt("scheduled_for", thirtyMinAgo)
			.limit(20);

		if (stuck && stuck.length > 0) {
			// Auto-recover: reset to pending so scheduler/reconciliation can claim them again.
			// For pool-mode rows, also reopen the pool slot.
			await recoverQueueItemsToPending(
				stuck.map((item) => item.id),
				"Watchdog: stuck in queued/scheduled > 30 min past scheduled_for — recovered to pending",
				{ poolStatus: "available" },
			);

			alerts.push({
				workspace_id: ws.workspace_id,
				check_name: "stuck-scheduled",
				severity: "warn",
				message: `${stuck.length} queued/scheduled item(s) stuck > 30 min past scheduled_for — auto-recovered to pending`,
				details: {
					count: stuck.length,
					items: stuck.slice(0, 5).map((s) => ({
						id: s.id,
						groupId: s.group_id,
						status: s.status,
						scheduledFor: s.scheduled_for,
						contentPreview: (s.content || "").slice(0, 50),
					})),
				},
			});
		}
	}
}

// ---------------------------------------------------------------------------
// Check 8: Expiring tokens — emergency refresh for tokens expiring within 6h
//
// Closes the 22-hour gap between daily cron token-refresh runs. The daily
// cron refreshes tokens within a 7-day window; this catch-all handles any
// tokens that slipped through and are now critically close to expiry.
// ---------------------------------------------------------------------------

async function checkExpiringTokens(alerts: WatchdogAlert[]): Promise<void> {
	const { decrypt, encrypt } = await import("../_lib/encryption.js");
	const { alertTokenRefreshFailure } = await import("../_lib/alerting.js");

	const supabase = getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.autoposterWatchdog,
	);

	const sixHoursFromNow = new Date(
		Date.now() + 6 * 60 * 60 * 1000,
	).toISOString();
	const now = new Date().toISOString();

	let threadsRefreshed = 0;
	let threadsErrors = 0;
	let igRefreshed = 0;
	let igErrors = 0;

	// ── Threads accounts with tokens expiring within 6 hours ──────────────
	try {
		const { data: threadsAccounts } = await supabase
			.from("accounts")
			.select(
				"id, user_id, username, threads_access_token_encrypted, token_expires_at, updated_at",
			)
			.eq("is_active", true)
			.or("needs_reauth.is.null,needs_reauth.neq.true")
			.not("threads_access_token_encrypted", "is", null)
			.not("token_expires_at", "is", null)
			.lte("token_expires_at", sixHoursFromNow)
			.gte("token_expires_at", now);

		if (threadsAccounts && threadsAccounts.length > 0) {
			logger.warn(
				`[watchdog] Emergency token refresh: ${threadsAccounts.length} Threads token(s) expiring within 6h`,
			);

			for (const account of threadsAccounts) {
				try {
					const currentToken = decrypt(account.threads_access_token_encrypted);

					const refreshResult = await refreshThreadsToken(currentToken);
					const refreshData = refreshResult.data;

					if (!refreshResult.ok || refreshData.error) {
						const errorMsg = String(
							refreshData?.error?.message ||
								refreshData?.error ||
								"Unknown error",
						);
						logger.warn(
							`[watchdog] Emergency refresh failed for Threads @${account.username}`,
							{ error: errorMsg },
						);
						threadsErrors++;

						if (isDefinitiveOAuthError(errorMsg)) {
							await supabase
								.from("accounts")
								.update({
									needs_reauth: true,
									status: "needs_reauth",
									updated_at: new Date().toISOString(),
								})
								.eq("id", account.id);

							await alertTokenRefreshFailure(
								"threads",
								account.username || account.id,
								`Emergency refresh: ${errorMsg}`,
							);
						}
						continue;
					}

					const newEncryptedToken = encrypt(refreshData.access_token as string);
					const expiresIn = refreshData.expires_in || 5184000; // 60 days default

					await supabase
						.from("accounts")
						.update({
							threads_access_token_encrypted: newEncryptedToken,
							token_expires_at: new Date(
								Date.now() + expiresIn * 1000,
							).toISOString(),
							updated_at: new Date().toISOString(),
							consecutive_refresh_failures: 0,
						})
						.eq("id", account.id);

					threadsRefreshed++;
					logger.info(
						`[watchdog] Emergency refresh succeeded for Threads @${account.username}`,
					);
				} catch (err) {
					const errorMsg = err instanceof Error ? err.message : String(err);
					logger.warn(
						`[watchdog] Emergency refresh error for Threads @${account.username}`,
						{ error: errorMsg },
					);
					threadsErrors++;

					if (isDefinitiveOAuthError(errorMsg)) {
						await supabase
							.from("accounts")
							.update({
								needs_reauth: true,
								status: "needs_reauth",
								updated_at: new Date().toISOString(),
							})
							.eq("id", account.id);

						await alertTokenRefreshFailure(
							"threads",
							account.username || account.id,
							`Emergency refresh: ${errorMsg}`,
						);
					}
				}
			}
		}
	} catch (err) {
		logger.error("[watchdog] Emergency token check query failed (Threads)", {
			error: String(err),
		});
	}

	// ── Instagram accounts with tokens expiring within 6 hours ───────────
	try {
		const { data: igAccounts } = await supabase
			.from("instagram_accounts")
			.select(
				"id, user_id, username, instagram_access_token_encrypted, login_type, token_expires_at, updated_at",
			)
			.eq("is_active", true)
			.or("needs_reauth.is.null,needs_reauth.neq.true")
			.not("instagram_access_token_encrypted", "is", null)
			.not("token_expires_at", "is", null)
			.lte("token_expires_at", sixHoursFromNow)
			.gte("token_expires_at", now);

		if (igAccounts && igAccounts.length > 0) {
			logger.warn(
				`[watchdog] Emergency token refresh: ${igAccounts.length} IG token(s) expiring within 6h`,
			);

			for (const account of igAccounts) {
				try {
					const currentToken = decrypt(
						account.instagram_access_token_encrypted,
					);
					const loginType = account.login_type || "instagram";

					const { refreshTokenByLoginType } = await import(
						"../_lib/tokenRefresh.js"
					);
					const refreshResult = await refreshTokenByLoginType(
						currentToken,
						loginType,
					);
					const refreshData = refreshResult.data;

					if (!refreshResult.ok || refreshData.error) {
						const errorMsg = String(
							refreshData?.error?.message ||
								refreshData?.error ||
								"Unknown error",
						);
						logger.warn(
							`[watchdog] Emergency refresh failed for IG @${account.username}`,
							{ error: errorMsg },
						);
						igErrors++;

						if (isDefinitiveOAuthError(errorMsg)) {
							await supabase
								.from("instagram_accounts")
								.update({
									needs_reauth: true,
									status: "needs_reauth",
									updated_at: new Date().toISOString(),
								})
								.eq("id", account.id);

							await alertTokenRefreshFailure(
								"instagram",
								account.username || account.id,
								`Emergency refresh: ${errorMsg}`,
							);
						}
						continue;
					}

					const newEncryptedToken = encrypt(refreshData.access_token as string);
					const expiresIn = refreshData.expires_in || 5184000;

					await supabase
						.from("instagram_accounts")
						.update({
							instagram_access_token_encrypted: newEncryptedToken,
							token_expires_at: new Date(
								Date.now() + expiresIn * 1000,
							).toISOString(),
							updated_at: new Date().toISOString(),
							consecutive_refresh_failures: 0,
						})
						.eq("id", account.id);

					igRefreshed++;
					logger.info(
						`[watchdog] Emergency refresh succeeded for IG @${account.username}`,
					);
				} catch (err) {
					const errorMsg = err instanceof Error ? err.message : String(err);
					logger.warn(
						`[watchdog] Emergency refresh error for IG @${account.username}`,
						{ error: errorMsg },
					);
					igErrors++;

					if (isDefinitiveOAuthError(errorMsg)) {
						await supabase
							.from("instagram_accounts")
							.update({
								needs_reauth: true,
								status: "needs_reauth",
								updated_at: new Date().toISOString(),
							})
							.eq("id", account.id);

						await alertTokenRefreshFailure(
							"instagram",
							account.username || account.id,
							`Emergency refresh: ${errorMsg}`,
						);
					}
				}
			}
		}
	} catch (err) {
		logger.error("[watchdog] Emergency token check query failed (IG)", {
			error: String(err),
		});
	}

	// Emit alerts for any activity
	const totalRefreshed = threadsRefreshed + igRefreshed;
	const totalErrors = threadsErrors + igErrors;

	if (totalRefreshed > 0 || totalErrors > 0) {
		// Use a synthetic workspace_id for global token alerts
		alerts.push({
			workspace_id: "__global__",
			check_name: "expiring-tokens",
			severity: totalErrors > 0 ? "error" : "info",
			message: `Emergency token refresh: ${totalRefreshed} refreshed, ${totalErrors} failed (Threads: ${threadsRefreshed}/${threadsErrors}, IG: ${igRefreshed}/${igErrors})`,
			details: {
				threadsRefreshed,
				threadsErrors,
				igRefreshed,
				igErrors,
			},
		});
	}

	if (totalRefreshed > 0 || totalErrors > 0) {
		logger.info("[watchdog] Emergency token refresh complete", {
			threadsRefreshed,
			threadsErrors,
			igRefreshed,
			igErrors,
		});
	}
}

// ---------------------------------------------------------------------------
// Persistence — write alerts to watchdog_alerts table
// ---------------------------------------------------------------------------

export async function persistAlerts(
	alertsToInsert: WatchdogAlert[],
	currentAlerts: WatchdogAlert[] = alertsToInsert,
): Promise<void> {
	for (const a of alertsToInsert) {
		const { error } = await db().from("watchdog_alerts").insert({
			workspace_id: a.workspace_id,
			check_name: a.check_name,
			severity: a.severity,
			message: a.message,
			details: alertOperationalDetails(a),
		});

		if (error) {
			logger.error("[watchdog] Failed to persist alert", {
				check: a.check_name,
				error: String(error),
			});
		}
	}

	// Resolve alerts that haven't fired in this cycle
	// using the full current evidence set, not only deduped Discord notifications.
	const firedKeys = new Set(
		currentAlerts.map((a) => `${a.workspace_id}:${a.check_name}`),
	);
	const currentAlertByKey = new Map(
		currentAlerts.map((a) => [`${a.workspace_id}:${a.check_name}`, a]),
	);

	const openAlerts: Array<{
		id: string;
		workspace_id: string;
		check_name: string;
		created_at?: string | null | undefined;
	}> = [];
	for (let from = 0; ; from += OPEN_ALERT_FETCH_PAGE_SIZE) {
		const to = from + OPEN_ALERT_FETCH_PAGE_SIZE - 1;
		const { data, error } = await db()
			.from("watchdog_alerts")
			.select("id, workspace_id, check_name, created_at")
			.is("resolved_at", null)
			.range(from, to);
		if (error) {
			logger.error("[watchdog] Failed to load open alerts for resolution", {
				from,
				to,
				error: String(error),
			});
			break;
		}
		const rows = (data ?? []) as Array<{
			id: string;
			workspace_id: string;
			check_name: string;
			created_at?: string | null | undefined;
		}>;
		openAlerts.push(...rows);
		if (rows.length < OPEN_ALERT_FETCH_PAGE_SIZE) break;
	}

	if (openAlerts.length > 0) {
		const alertsByKey = new Map<
			string,
			Array<{
				id: string;
				workspace_id: string;
				check_name: string;
				created_at?: string | null | undefined;
			}>
		>();
		for (const a of openAlerts) {
			const key = `${a.workspace_id}:${a.check_name}`;
			const rows = alertsByKey.get(key) ?? [];
			rows.push(a);
			alertsByKey.set(key, rows);
		}

		const toResolve: Array<{ id: string }> = [];
		const toRefresh: Array<{ id: string; alert: WatchdogAlert }> = [];
		const nowMs = Date.now();
		for (const [key, rows] of alertsByKey.entries()) {
			if (!firedKeys.has(key)) {
				toResolve.push(...rows);
				continue;
			}

			const newestOpen = rows
				.slice()
				.sort(
					(a, b) =>
						new Date(b.created_at ?? 0).getTime() -
						new Date(a.created_at ?? 0).getTime(),
				)[0];
			for (const row of rows) {
				if (row.id !== newestOpen?.id) {
					toResolve.push(row);
					continue;
				}
				if (isOpenAlertExpired(row.check_name, row.created_at, nowMs)) {
					toResolve.push(row);
				}
			}
			const currentAlert = currentAlertByKey.get(key);
			if (
				currentAlert &&
				newestOpen &&
				!isOpenAlertExpired(newestOpen.check_name, newestOpen.created_at, nowMs)
			) {
				toRefresh.push({ id: newestOpen.id, alert: currentAlert });
			}
		}

		if (toResolve.length > 0) {
			const resolvedAt = new Date().toISOString();
			for (let i = 0; i < toResolve.length; i += ALERT_RESOLUTION_BATCH_SIZE) {
				const batch = toResolve.slice(i, i + ALERT_RESOLUTION_BATCH_SIZE);
				const { error } = await db()
					.from("watchdog_alerts")
					.update({ resolved_at: resolvedAt })
					.in(
						"id",
						batch.map((a) => a.id),
					);
				if (error) {
					logger.error("[watchdog] Failed to resolve stale alerts", {
						count: batch.length,
						error: String(error),
					});
				}
			}
		}

		for (const row of toRefresh) {
			const { error } = await db()
				.from("watchdog_alerts")
				.update({
					severity: row.alert.severity,
					message: row.alert.message,
					details: alertOperationalDetails(row.alert),
				})
				.eq("id", row.id);
			if (error) {
				logger.error("[watchdog] Failed to refresh active alert evidence", {
					id: row.id,
					check: row.alert.check_name,
					error: String(error),
				});
			}
		}
	}
}

// ---------------------------------------------------------------------------
// Discord notification — per-workspace URL or global fallback
// ---------------------------------------------------------------------------

async function sendDiscordAlerts(alerts: WatchdogAlert[]): Promise<void> {
	// Group alerts by workspace to batch into single embeds
	const byWorkspace = new Map<string, WatchdogAlert[]>();
	for (const a of alerts) {
		if (!byWorkspace.has(a.workspace_id)) {
			byWorkspace.set(a.workspace_id, []);
		}
		byWorkspace.get(a.workspace_id)?.push(a);
	}

	// Load workspace discord URLs
	const { data: configs } = await db()
		.from("auto_post_config")
		.select("workspace_id, discord_webhook_url")
		.in("workspace_id", Array.from(byWorkspace.keys()));

	const urlMap = new Map<string, string | null>();
	if (configs) {
		for (const c of configs) {
			urlMap.set(
				c.workspace_id as string,
				c.discord_webhook_url as string | null,
			);
		}
	}

	for (const [wsId, wsAlerts] of Array.from(byWorkspace)) {
		const wsUrl = urlMap.get(wsId);

		// Determine highest severity for color
		const maxSeverity = wsAlerts.reduce((max, a) => {
			const order = { info: 0, warn: 1, error: 2, critical: 3 };
			const aLevel = order[a.severity as keyof typeof order] ?? 0;
			const mLevel = order[max as keyof typeof order] ?? 0;
			return aLevel > mLevel ? a.severity : max;
		}, "info");

		// Build summary for the centralized alert system
		const summary = wsAlerts
			.map((a) => `[${a.severity.toUpperCase()}] ${a.message}`)
			.join("\n");

		// Send to per-workspace Discord if configured
		if (wsUrl) {
			try {
				await sendToDiscord(wsUrl, wsAlerts, maxSeverity);
			} catch (err) {
				logger.error("[watchdog] Failed to send workspace Discord alert", {
					wsId,
					error: String(err),
				});
			}
			// Mirror only higher-severity watchdog summaries to the global channel.
			if (maxSeverity !== "error" && maxSeverity !== "critical") {
				continue;
			}
		}

		const level =
			maxSeverity === "critical"
				? AlertLevel.CRITICAL
				: maxSeverity === "error"
					? AlertLevel.ERROR
					: AlertLevel.WARN;

		await alert(level, `Watchdog: ${wsAlerts.length} alert(s)`, {
			workspace: wsId,
			alerts: summary.slice(0, 1000),
		});
	}
}

async function sendToDiscord(
	webhookUrl: string,
	alerts: WatchdogAlert[],
	maxSeverity: string,
): Promise<void> {
	const COLORS: Record<string, number> = {
		info: 0x3498db,
		warn: 0xf39c12,
		error: 0xe74c3c,
		critical: 0x9b59b6,
	};
	const EMOJI: Record<string, string> = {
		info: "ℹ️",
		warn: "⚠️",
		error: "🔴",
		critical: "🚨",
	};

	const fields = alerts.slice(0, 25).map((a) => ({
		name: `${EMOJI[a.severity] || "⚠️"} ${a.check_name}`,
		value: a.message.slice(0, 1024),
		inline: false,
	}));

	const payload = {
		embeds: [
			{
				title: `${EMOJI[maxSeverity] || "⚠️"} Autoposter Watchdog — ${alerts.length} alert(s)`,
				color: COLORS[maxSeverity] || COLORS.warn,
				fields,
				timestamp: new Date().toISOString(),
				footer: { text: "Juno33 Watchdog" },
			},
		],
	};

	await fetch(webhookUrl, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(payload),
		signal: AbortSignal.timeout(5000),
	});
}

// ---------------------------------------------------------------------------
// Check 9: Stuck publishing — items claimed by auto-post-publish but never
// completed. auto-post-publish.ts sets status="publishing" via atomic claim
// (line 103). If the endpoint crashes mid-request, status stays "publishing"
// forever. Existing check 3 looks for "processing" (different status value),
// so this closes the gap.
// ---------------------------------------------------------------------------

async function checkStuckPublishing(
	wsConfigs: WorkspaceConfig[],
	alerts: WatchdogAlert[],
): Promise<void> {
	const nowIso = new Date().toISOString();
	const tenMinAgo = new Date(Date.now() - 10 * 60 * 1000).toISOString();

	for (const ws of wsConfigs) {
		const { data: stuck } = await db()
			.from("auto_post_queue")
			.select(
				"id, group_id, content, retry_count, claimed_at, claim_expires_at",
			)
			.eq("workspace_id", ws.workspace_id)
			.eq("status", "publishing")
			.or(
				`claim_expires_at.lte.${nowIso},and(claim_expires_at.is.null,claimed_at.lt.${tenMinAgo})`,
			)
			.limit(50);

		if (!stuck || stuck.length === 0) continue;

		// Auto-recover: items with retry_count < 3 → reset to pending.
		// Items at max retries → dead_letter.
		const toRetry = stuck.filter(
			(s: { retry_count?: number | undefined }) => (s.retry_count || 0) < 3,
		);
		const toDead = stuck.filter(
			(s: { retry_count?: number | undefined }) => (s.retry_count || 0) >= 3,
		);

		if (toRetry.length > 0) {
			const retryCountById = new Map(
				toRetry.map((item) => [
					(item as { id: string }).id,
					((item as { retry_count?: number | undefined }).retry_count || 0) + 1,
				]),
			);
			await recoverQueueItemsToPending(
				toRetry.map((item) => (item as { id: string }).id),
				"Watchdog: stuck in publishing > 10 min — recovered to pending",
				{
					accountId: null,
					poolStatus: "available",
					retryCountById,
				},
			);
		}

		if (toDead.length > 0) {
			await deadLetterQueueItems(
				toDead.map((s: { id: string }) => s.id),
				"Watchdog: stuck in publishing > 10 min, max retries reached",
			);
		}

		alerts.push({
			workspace_id: ws.workspace_id,
			check_name: "stuck-publishing",
			severity: "error",
			message: `${stuck.length} queue item(s) stuck in "publishing" for > 10 min — ${toRetry.length} recovered, ${toDead.length} moved to dead letter`,
			details: {
				total: stuck.length,
				recovered: toRetry.length,
				deadLettered: toDead.length,
				items: stuck
					.slice(0, 5)
					.map((s: { id: string; group_id: string; content: string }) => ({
						id: s.id,
						groupId: s.group_id,
						contentPreview: (s.content || "").slice(0, 50),
					})),
			},
		});
	}
}

// ---------------------------------------------------------------------------
// Time helpers
// ---------------------------------------------------------------------------

function getHourInTimezone(date: Date, timezone: string): number {
	try {
		const formatter = new Intl.DateTimeFormat("en-US", {
			hour: "numeric",
			hour12: false,
			timeZone: timezone,
		});
		return Number.parseInt(formatter.format(date), 10);
	} catch {
		return date.getUTCHours();
	}
}

function isInActiveHours(
	currentHour: number,
	start: number,
	end: number,
): boolean {
	if (start <= end) {
		return currentHour >= start && currentHour < end;
	}
	// Wrap-around (e.g., 22-6)
	return currentHour >= start || currentHour < end;
}
