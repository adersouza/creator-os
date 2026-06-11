// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Unified Scheduler — Core Account Loop
 *
 * Phase 1 of the autoposter v2 migration. Replaces 4 independent crons
 * (dawn-planner, publish-worker Phases 3-4, account-state-evaluator,
 * autoposter-watchdog) with a single scheduler loop that runs every 5 min.
 *
 * For each enabled group:
 *   1. Batch-loads all accounts, states, overrides, post counts, last post times
 *   2. Evaluates account state via the existing pure stateEvaluator
 *   3. Checks eligibility (active window, daily cap, min interval, weekends)
 *   4. If eligible: picks a pending queue item and dispatches via QStash
 *   5. If queue low: triggers a fill via QStash
 *   6. Logs every decision to scheduler_decisions table
 */

import * as crypto from "node:crypto";
import type { AccountStateUpsert } from "../../handlers/auto-post/accountState.js";
import {
	bulkUpsertAccountStates,
	getGroupAccountStates,
	isBlocked,
} from "../../handlers/auto-post/accountState.js";
import {
	calculateAutoposterAccountHealth,
	isPublishAttemptFailureForAccountHealth,
} from "../../handlers/auto-post/accountHealth.js";
import {
	markQueueItemDispatched,
	queueQueueItemForDispatch,
} from "../../handlers/auto-post/queueState.js";
import {
	type AccountEvalInput,
	evaluateAccountState,
	type PostViewRecord,
	type PostWithVelocity,
} from "../../handlers/auto-post/stateEvaluator.js";
import { evaluateRestartWarmup } from "../../handlers/auto-post/restartWarmup.js";
import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";
import { flushDecisions, type SchedulerDecision } from "./decisionLog.js";
import { checkEligibility, type EligibilityInput } from "./eligibility.js";

// biome-ignore lint/suspicious/noExplicitAny: auto_post tables not in generated types
const db = (): any => getSupabaseAny();

// ============================================================================
// Types
// ============================================================================

interface GroupConfigRow {
	group_id: string;
	workspace_id: string;
	scheduler_version: number;
	enabled: boolean;
	posts_per_account_per_day: number;
	min_interval_minutes: number;
	active_hours_start: number;
	active_hours_end: number;
	timezone: string;
	post_on_weekends: boolean;
}

interface GroupInfoEntry {
	id: string;
	name: string;
	user_id: string;
	account_ids: string[];
}

interface AccountScheduleFlat {
	timezone?: string | null | undefined;
}

interface SchedulerSummary {
	runId: string;
	groupsProcessed: number;
	accountsEvaluated: number;
	dispatched: number;
	fillsTriggered: number;
	statesUpserted: number;
	decisionsLogged: number;
	errors: string[];
	durationMs: number;
}

function getDateKeyInTimezone(
	value: string | Date,
	timezone: string | undefined,
): string {
	const tz = timezone || "America/New_York";
	try {
		return new Intl.DateTimeFormat("en-CA", {
			timeZone: tz,
			year: "numeric",
			month: "2-digit",
			day: "2-digit",
		}).format(typeof value === "string" ? new Date(value) : value);
	} catch {
		return new Intl.DateTimeFormat("en-CA", {
			timeZone: "UTC",
			year: "numeric",
			month: "2-digit",
			day: "2-digit",
		}).format(typeof value === "string" ? new Date(value) : value);
	}
}

function getEffectiveTimezone(
	accountId: string,
	groupId: string,
	groupTimezone: string,
	schedulerVersion: number,
	flatScheduleMap: Map<string, AccountScheduleFlat>,
	overrideMap: Map<string, Record<string, unknown>>,
): string {
	if (schedulerVersion >= 4) {
		return flatScheduleMap.get(accountId)?.timezone ?? groupTimezone;
	}
	return (
		(overrideMap.get(`${groupId}:${accountId}`)?.timezone as
			| string
			| undefined) ?? groupTimezone
	);
}

// ============================================================================
// Main loop
// ============================================================================

export async function runSchedulerLoop(): Promise<SchedulerSummary> {
	const startTime = Date.now();
	const runId = crypto.randomUUID();
	const decisions: SchedulerDecision[] = [];
	const errors: string[] = [];

	let groupsProcessed = 0;
	let accountsEvaluated = 0;
	let dispatched = 0;
	let fillsTriggered = 0;
	let statesUpserted = 0;

	try {
		// 1. Load v2+ enabled workspaces
		const { data: workspaceConfigs, error: workspaceConfigsError } = await db()
			.from("auto_post_config")
			.select("workspace_id, scheduler_version, group_mode_enabled")
			.eq("is_enabled", true);
		if (workspaceConfigsError) {
			throw new Error(
				`scheduler workspace config query failed: ${workspaceConfigsError.message}`,
			);
		}

		const schedulerWorkspaceMap = new Map<string, number>(
			((workspaceConfigs ?? []) as Array<Record<string, unknown>>)
				.filter(
					(row) =>
						(row.group_mode_enabled ?? false) === true &&
						Number(row.scheduler_version ?? 1) >= 2,
				)
				.map((row) => [
					row.workspace_id as string,
					Number(row.scheduler_version ?? 1),
				]),
		);

		if (schedulerWorkspaceMap.size === 0) {
			logger.info("[scheduler] No scheduler v2+ workspaces found");
			return makeSummary(runId, 0, 0, 0, 0, 0, 0, [], startTime);
		}

		// 2. Load all enabled groups for those workspaces
		const { data: enabledGroups, error: enabledGroupsError } = await db()
			.from("auto_post_group_config")
			.select(
				"group_id, workspace_id, enabled, posts_per_account_per_day, min_interval_minutes, active_hours_start, active_hours_end, timezone, post_on_weekends",
			)
			.eq("enabled", true);
		if (enabledGroupsError) {
			throw new Error(
				`scheduler group config query failed: ${enabledGroupsError.message}`,
			);
		}

		if (!enabledGroups?.length) {
			logger.info("[scheduler] No enabled groups found");
			return makeSummary(runId, 0, 0, 0, 0, 0, 0, [], startTime);
		}

		const groups = (enabledGroups as Array<Record<string, unknown>>)
			.filter((group) =>
				schedulerWorkspaceMap.has(group.workspace_id as string),
			)
			.map((group) => ({
				...(group as Omit<GroupConfigRow, "scheduler_version">),
				scheduler_version:
					schedulerWorkspaceMap.get(group.workspace_id as string) ?? 2,
			})) as GroupConfigRow[];

		if (groups.length === 0) {
			logger.info("[scheduler] No enabled groups for scheduler v2+ workspaces");
			return makeSummary(runId, 0, 0, 0, 0, 0, 0, [], startTime);
		}

		// 3. Batch-load group info (account_ids, user_id, name)
		const groupIds = groups.map((g) => g.group_id);
		const { data: groupInfoRows, error: groupInfoError } = await db()
			.from("account_groups")
			.select("id, name, user_id, account_ids")
			.in("id", groupIds);
		if (groupInfoError) {
			throw new Error(
				`scheduler account_groups query failed: ${groupInfoError.message}`,
			);
		}

		const groupInfoMap = new Map<string, GroupInfoEntry>(
			(groupInfoRows ?? []).map(
				(g: GroupInfoEntry) => [g.id, g] as [string, GroupInfoEntry],
			),
		);

		// 4. Process each group
		for (const gc of groups) {
			try {
				const result = await processGroup(
					runId,
					gc,
					groupInfoMap,
					decisions,
					gc.scheduler_version,
				);
				groupsProcessed++;
				accountsEvaluated += result.accountsEvaluated;
				dispatched += result.dispatched;
				fillsTriggered += result.fillsTriggered;
				statesUpserted += result.statesUpserted;
			} catch (err) {
				const errMsg = `group ${gc.group_id}: ${err instanceof Error ? err.message : String(err)}`;
				errors.push(errMsg);
				logger.error("[scheduler] Group processing failed", {
					groupId: gc.group_id,
					error: err instanceof Error ? err.message : String(err),
				});
			}
		}

		// 4. Flush all decisions
		const { inserted } = await flushDecisions(decisions);
		const decisionsLogged = inserted;

		// 5. Run alert engine (Phase 4) — queries scheduler_decisions for anomalies
		try {
			const { runAlertEngine } = await import("./alertEngine.js");
			await runAlertEngine();
		} catch (err) {
			logger.warn("[scheduler] Alert engine failed (non-fatal)", {
				error: err instanceof Error ? err.message : String(err),
			});
		}

		return makeSummary(
			runId,
			groupsProcessed,
			accountsEvaluated,
			dispatched,
			fillsTriggered,
			statesUpserted,
			decisionsLogged,
			errors,
			startTime,
		);
	} catch (err) {
		errors.push(
			`top-level: ${err instanceof Error ? err.message : String(err)}`,
		);
		logger.error("[scheduler] Top-level error", { error: String(err) });
		return makeSummary(
			runId,
			groupsProcessed,
			accountsEvaluated,
			dispatched,
			fillsTriggered,
			statesUpserted,
			0,
			errors,
			startTime,
		);
	}
}

// ============================================================================
// Per-group processing
// ============================================================================

interface GroupResult {
	accountsEvaluated: number;
	dispatched: number;
	fillsTriggered: number;
	statesUpserted: number;
}

async function processGroup(
	runId: string,
	gc: GroupConfigRow,
	groupInfoMap: Map<string, GroupInfoEntry>,
	decisions: SchedulerDecision[],
	schedulerVersion = 2,
): Promise<GroupResult> {
	const grpInfo = groupInfoMap.get(gc.group_id);
	if (!grpInfo?.account_ids?.length) {
		return {
			accountsEvaluated: 0,
			dispatched: 0,
			fillsTriggered: 0,
			statesUpserted: 0,
		};
	}

	const groupAccountIds = grpInfo.account_ids;
	const now = new Date();
	const nowIso = now.toISOString();

	// ── Batch-load all data for this group ──

	const [
		accountsResult,
		overridesResult,
		queueCountResult,
		pendingItemsResult,
	] = await Promise.all([
		// Accounts with valid tokens
		db()
			.from("accounts")
			.select(
				"id, username, created_at, is_shadowbanned, is_retired, needs_reauth, is_active, status, followers_count, user_id",
			)
			.in("id", groupAccountIds)
			.not("threads_access_token_encrypted", "is", null)
			.or("status.is.null,status.neq.suspended"),
		// Per-account config: v4+ uses flat account_schedule, legacy uses overrides
		schedulerVersion >= 4
			? db()
					.from("account_schedule")
					.select(
						"account_id, posts_per_day, min_interval_minutes, active_hours_start, active_hours_end, timezone, post_on_weekends, paused, status, blocked_until",
					)
					.eq("group_id", gc.group_id)
			: db()
					.from("auto_post_account_overrides")
					.select("account_id, group_id, overrides")
					.eq("group_id", gc.group_id),
		// Pending queue depth — pool items + any legacy stragglers
		db()
			.from("auto_post_queue")
			.select("*", { count: "exact", head: true })
			.eq("group_id", gc.group_id)
			.or("pool_status.eq.available,pool_status.is.null")
			.in("status", ["pending", "queued"]),
		// Pending queue items (for dispatching)
		// Picks pool_status='available' items AND legacy items (pool_status IS NULL, status=pending)
		db()
			.from("auto_post_queue")
			.select(
				"id, workspace_id, group_id, account_id, scheduled_for, pool_status",
			)
			.eq("group_id", gc.group_id)
			.or("pool_status.eq.available,pool_status.is.null")
			.eq("status", "pending")
			.lte("scheduled_for", nowIso)
			.or(`next_retry_at.is.null,next_retry_at.lte.${nowIso}`)
			.order("scheduled_for", { ascending: true })
			.limit(20),
	]);

	for (const [label, result] of [
		["accounts", accountsResult],
		["overrides", overridesResult],
		["queueCount", queueCountResult],
		["pendingItems", pendingItemsResult],
	] as const) {
		if (result.error) {
			logger.error("[scheduler] Failed to load group data", {
				groupId: gc.group_id,
				label,
				error: result.error.message,
			});
			throw new Error(
				`scheduler ${label} query failed: ${result.error.message}`,
			);
		}
	}

	const accounts = (accountsResult.data ?? []) as Array<
		Record<string, unknown>
	>;
	if (accounts.length === 0) {
		return {
			accountsEvaluated: 0,
			dispatched: 0,
			fillsTriggered: 0,
			statesUpserted: 0,
		};
	}

	const accountIds = accounts.map((a) => a.id as string);
	const queueDepth = queueCountResult.count ?? 0;
	const pendingItems = (pendingItemsResult.data ?? []) as Array<{
		id: string;
		workspace_id: string;
		group_id: string;
		account_id: string | null;
		scheduled_for: string;
		pool_status: string | null;
	}>;

	// Build override map (key: "groupId:accountId")
	// v4+: account_schedule rows are the flat source of truth
	// Legacy: auto_post_account_overrides has an overrides blob
	const overrideMap = new Map<string, Record<string, unknown>>();
	const flatScheduleMap = new Map<string, Record<string, unknown>>();
	if (schedulerVersion >= 4) {
		for (const row of (overridesResult.data ?? []) as Array<
			Record<string, unknown>
		>) {
			flatScheduleMap.set(row.account_id as string, row);
			// Build override in the same shape checkEligibility expects
			overrideMap.set(`${gc.group_id}:${row.account_id}`, {
				active_hours_start: row.active_hours_start,
				active_hours_end: row.active_hours_end,
				timezone: row.timezone,
				posts_per_account_per_day: row.posts_per_day,
				min_interval_minutes: row.min_interval_minutes,
				post_on_weekends: row.post_on_weekends,
			});
		}
	} else {
		for (const ov of (overridesResult.data ?? []) as Array<{
			account_id: string;
			group_id: string;
			overrides: Record<string, unknown>;
		}>) {
			overrideMap.set(`${ov.group_id}:${ov.account_id}`, ov.overrides ?? {});
		}
	}

	// ── Load post history for state evaluation ──

	const twoHoursAgo = new Date(
		now.getTime() - 2 * 60 * 60 * 1000,
	).toISOString();
	const fourteenDaysAgo = new Date(
		now.getTime() - 14 * 24 * 60 * 60 * 1000,
	).toISOString();
	const thirtyDaysAgo = new Date(
		now.getTime() - 30 * 24 * 60 * 60 * 1000,
	).toISOString();
	const fortyEightHoursAgo = new Date(
		now.getTime() - 48 * 60 * 60 * 1000,
	).toISOString();
	const todayKeyByAccount = new Map<string, string>();
	for (const account of accounts) {
		const accountId = account.id as string;
		todayKeyByAccount.set(
			accountId,
			getDateKeyInTimezone(
				now,
				getEffectiveTimezone(
					accountId,
					gc.group_id,
					gc.timezone,
					schedulerVersion,
					flatScheduleMap,
					overrideMap,
				),
			),
		);
	}

	const [
		posts30dResult,
		posts2hResult,
		publishedCountsResult,
		posts48hResult,
		lastPostResult,
		publishAttemptsResult,
		engagementFetchResult,
		autoposterRecentResult,
	] = await Promise.all([
		// Posts last 30d with views (for state evaluation)
		db()
			.from("posts")
			.select("id, account_id, published_at, views_count")
			.in("account_id", accountIds)
			.eq("status", "published")
			.gte("published_at", thirtyDaysAgo)
			.order("published_at", { ascending: false })
			.limit(5000),
		// Recent posts in last 2h (for viral check)
		db()
			.from("posts")
			.select("id, account_id, published_at, views_count")
			.in("account_id", accountIds)
			.eq("status", "published")
			.gte("published_at", twoHoursAgo)
			.gt("views_count", 0),
		// Total published posts per account (for warming gate)
		db()
			.from("posts")
			.select("account_id")
			.in("account_id", accountIds)
			.eq("status", "published"),
		// Posts in last 48h (for shadowban throttle)
		db()
			.from("posts")
			.select("account_id")
			.in("account_id", accountIds)
			.eq("status", "published")
			.gte("published_at", fortyEightHoursAgo),
		// Last post time per account (for min interval)
		db()
			.from("posts")
			.select("account_id, published_at")
			.in("account_id", accountIds)
			.eq("status", "published")
			.order("published_at", { ascending: false })
			.limit(500),
		db()
			.from("publish_attempts")
			.select("account_id, result, error_code, error_message, completed_at")
			.in("account_id", accountIds)
			.gte("started_at", fourteenDaysAgo)
			.limit(5000),
		db()
			.from("auto_post_queue")
			.select("account_id, engagement_fetched_at")
			.in("account_id", accountIds)
			.eq("status", "published")
			.gte("posted_at", fourteenDaysAgo)
			.not("engagement_fetched_at", "is", null)
			.limit(5000),
		db()
			.from("auto_post_queue")
			.select("account_id, posted_at")
			.in("account_id", accountIds)
			.eq("status", "published")
			.gte("posted_at", thirtyDaysAgo)
			.order("posted_at", { ascending: false })
			.limit(5000),
	]);
	for (const [label, result] of [
		["posts30d", posts30dResult],
		["posts2h", posts2hResult],
		["publishedCounts", publishedCountsResult],
		["posts48h", posts48hResult],
		["lastPost", lastPostResult],
		["publishAttempts", publishAttemptsResult],
		["engagementFetch", engagementFetchResult],
		["autoposterRecent", autoposterRecentResult],
	] as const) {
		if (result.error) {
			logger.error("[scheduler] Failed to load post history", {
				groupId: gc.group_id,
				label,
				error: result.error.message,
			});
			throw new Error(
				`scheduler ${label} query failed: ${result.error.message}`,
			);
		}
	}

	// ── Index post data by account ──

	const posts30dByAccount = new Map<string, PostViewRecord[]>();
	const posts14dByAccount = new Map<string, PostViewRecord[]>();
	const posts2hByAccount = new Map<string, PostWithVelocity[]>();
	const publishedCounts = new Map<string, number>();
	const posts48hCounts = new Map<string, number>();
	const postsTodayByAccount = new Map<string, number>();
	const lastPostTimeByAccount = new Map<string, number>();
	const engagementFetchSuccesses = new Map<string, number>();
	const lastAutoposterPublishedAt = new Map<string, string>();

	for (const p of (posts30dResult.data ?? []) as Array<{
		id: string;
		account_id: string;
		published_at: string;
		views_count: number;
	}>) {
		const record: PostViewRecord = {
			id: p.id,
			views_count: p.views_count ?? 0,
			published_at: p.published_at,
		};

		if (!posts30dByAccount.has(p.account_id))
			posts30dByAccount.set(p.account_id, []);
		posts30dByAccount.get(p.account_id)?.push(record);

		if (
			new Date(p.published_at).getTime() >= new Date(fourteenDaysAgo).getTime()
		) {
			if (!posts14dByAccount.has(p.account_id))
				posts14dByAccount.set(p.account_id, []);
			posts14dByAccount.get(p.account_id)?.push(record);
		}

		const todayKey = todayKeyByAccount.get(p.account_id);
		if (
			todayKey &&
			getDateKeyInTimezone(
				p.published_at,
				getEffectiveTimezone(
					p.account_id,
					gc.group_id,
					gc.timezone,
					schedulerVersion,
					flatScheduleMap,
					overrideMap,
				),
			) === todayKey
		) {
			postsTodayByAccount.set(
				p.account_id,
				(postsTodayByAccount.get(p.account_id) ?? 0) + 1,
			);
		}
	}

	for (const p of (posts2hResult.data ?? []) as Array<{
		id: string;
		account_id: string;
		published_at: string;
		views_count: number;
	}>) {
		const hours = Math.max(
			(now.getTime() - new Date(p.published_at).getTime()) / 3600000,
			0.25,
		);
		const record: PostWithVelocity = {
			id: p.id,
			views_count: p.views_count ?? 0,
			published_at: p.published_at,
			velocity: (p.views_count ?? 0) / hours,
		};
		if (!posts2hByAccount.has(p.account_id))
			posts2hByAccount.set(p.account_id, []);
		posts2hByAccount.get(p.account_id)?.push(record);
	}

	for (const p of (publishedCountsResult.data ?? []) as Array<{
		account_id: string;
	}>) {
		publishedCounts.set(
			p.account_id,
			(publishedCounts.get(p.account_id) ?? 0) + 1,
		);
	}

	for (const p of (posts48hResult.data ?? []) as Array<{
		account_id: string;
	}>) {
		posts48hCounts.set(
			p.account_id,
			(posts48hCounts.get(p.account_id) ?? 0) + 1,
		);
	}

	// Last post time: only keep the most recent per account
	for (const p of (lastPostResult.data ?? []) as Array<{
		account_id: string;
		published_at: string;
	}>) {
		if (!lastPostTimeByAccount.has(p.account_id)) {
			lastPostTimeByAccount.set(
				p.account_id,
				new Date(p.published_at).getTime(),
			);
		}
	}

	for (const p of (engagementFetchResult.data ?? []) as Array<{
		account_id: string | null;
	}>) {
		if (!p.account_id) continue;
		engagementFetchSuccesses.set(
			p.account_id,
			(engagementFetchSuccesses.get(p.account_id) ?? 0) + 1,
		);
	}

	for (const p of (autoposterRecentResult.data ?? []) as Array<{
		account_id: string | null;
		posted_at: string | null;
	}>) {
		if (!p.account_id || !p.posted_at) continue;
		if (!lastAutoposterPublishedAt.has(p.account_id)) {
			lastAutoposterPublishedAt.set(p.account_id, p.posted_at);
		}
	}

	const attemptSignals = new Map<
		string,
		{
			oauthFailures: number;
			transientPublishFailures: number;
			deadLetters: number;
			quotaWarnings: number;
			duplicateBlocks: number;
			recentPublishSuccesses: number;
		}
	>();
	for (const attempt of (publishAttemptsResult.data ?? []) as Array<{
		account_id: string | null;
		result: string | null;
		error_code: string | null;
		error_message: string | null;
	}>) {
		if (!attempt.account_id) continue;
		const signals = attemptSignals.get(attempt.account_id) ?? {
			oauthFailures: 0,
			transientPublishFailures: 0,
			deadLetters: 0,
			quotaWarnings: 0,
			duplicateBlocks: 0,
			recentPublishSuccesses: 0,
		};
		const result = attempt.result ?? "";
		const errorText =
			`${attempt.error_code ?? ""} ${attempt.error_message ?? ""}`.toLowerCase();
		if (result === "published" || result === "reconciled") {
			signals.recentPublishSuccesses++;
		}
		if (result === "dead_letter") signals.deadLetters++;
		if (result === "duplicate_fingerprint_blocked") signals.duplicateBlocks++;
		if (
			isPublishAttemptFailureForAccountHealth({
				result,
				errorCode: attempt.error_code,
				errorMessage: attempt.error_message,
			})
		) {
			signals.transientPublishFailures++;
		}
		if (
			errorText.includes("oauth") ||
			errorText.includes("reauth") ||
			errorText.includes("token")
		) {
			signals.oauthFailures++;
		}
		if (
			errorText.includes("quota") ||
			errorText.includes("rate_limit") ||
			errorText.includes("rate limit")
		) {
			signals.quotaWarnings++;
		}
		attemptSignals.set(attempt.account_id, signals);
	}

	// ── Load previous states for continuity ──

	const previousStates = await getGroupAccountStates(gc.group_id);
	const previousMap = new Map(previousStates.map((s) => [s.account_id, s]));

	// ── Evaluate each account ──

	const allStates: AccountStateUpsert[] = [];
	let groupDispatched = 0;
	let groupFills = 0;
	// Track which queue items have been claimed this run
	const claimedItemIds = new Set<string>();

	for (const account of accounts) {
		const accountId = account.id as string;

		// ── v4+: check account_schedule paused/blocked ──
		if (schedulerVersion >= 4) {
			const sched = flatScheduleMap.get(accountId);
			if (sched?.paused) {
				decisions.push({
					run_id: runId,
					workspace_id: gc.workspace_id,
					group_id: gc.group_id,
					account_id: accountId,
					outcome: "skipped_blocked",
					reason: "paused_in_account_schedule",
					account_status: (sched.status as string) ?? "paused",
					posts_today: postsTodayByAccount.get(accountId) ?? 0,
					queue_depth: queueDepth,
				});
				continue;
			}
			if (sched?.blocked_until) {
				const blockedUntil = new Date(sched.blocked_until as string);
				if (blockedUntil > now) {
					decisions.push({
						run_id: runId,
						workspace_id: gc.workspace_id,
						group_id: gc.group_id,
						account_id: accountId,
						outcome: "skipped_blocked",
						reason: `blocked_until_${blockedUntil.toISOString()}`,
						account_status: (sched.status as string) ?? "blocked",
						posts_today: postsTodayByAccount.get(accountId) ?? 0,
						queue_depth: queueDepth,
					});
					continue;
				}
			}
		}

		// ── State evaluation (reuse from account-state-evaluator) ──
		const acctPosts30d = posts30dByAccount.get(accountId) ?? [];
		const acctPosts14d = posts14dByAccount.get(accountId) ?? [];

		const recent3 = acctPosts14d
			.filter((p) => p.views_count > 0)
			.sort(
				(a, b) =>
					new Date(b.published_at).getTime() -
					new Date(a.published_at).getTime(),
			)
			.slice(0, 3);

		const olderPosts = acctPosts14d
			.filter(
				(p) =>
					new Date(p.published_at).getTime() <
						new Date(twoHoursAgo).getTime() && p.views_count > 0,
			)
			.sort(
				(a, b) =>
					new Date(b.published_at).getTime() -
					new Date(a.published_at).getTime(),
			);
		const latestOver2h = olderPosts.length > 0 ? olderPosts[0] : null;

		const evalInput: AccountEvalInput = {
			account_id: accountId,
			group_id: gc.group_id,
			workspace_id: gc.workspace_id,
			username: account.username as string,
			is_active: account.is_active !== false,
			is_retired: !!account.is_retired,
			needs_reauth: !!account.needs_reauth,
			is_shadowbanned: !!account.is_shadowbanned,
			created_at: account.created_at as string | null,
			followers_count: account.followers_count as number | null,
			posts_last_30d: acctPosts30d,
			posts_last_14d: acctPosts14d,
			recent_3_posts: recent3,
			posts_last_2h: posts2hByAccount.get(accountId) ?? [],
			latest_post_over_2h: latestOver2h!,
			total_published_posts: publishedCounts.get(accountId) ?? 0,
			posts_last_48h: posts48hCounts.get(accountId) ?? 0,
		};

		const prev = previousMap.get(accountId);
		const evalResult = evaluateAccountState(
			evalInput,
			now,
			prev
				? {
						status: prev.status,
						status_reason: prev.status_reason ?? null,
						blocked_until: prev.blocked_until,
						probe_posts_remaining: prev.probe_posts_remaining,
						flop_proven_remaining: prev.flop_proven_remaining,
						last_flop_post_id: prev.last_flop_post_id,
						flop_triggered_at: prev.flop_triggered_at,
						probe_cycles_completed: prev.probe_cycles_completed,
						consecutive_flops:
							((prev as unknown as Record<string, unknown>)
								.consecutive_flops as number) ?? 0,
					}
				: null,
		);
		const publishSignals = attemptSignals.get(accountId);
		const health = calculateAutoposterAccountHealth({
			oauthFailures:
				(account.needs_reauth ? 1 : 0) + (publishSignals?.oauthFailures ?? 0),
			transientPublishFailures: publishSignals?.transientPublishFailures ?? 0,
			deadLetters: publishSignals?.deadLetters ?? 0,
			quotaWarnings: publishSignals?.quotaWarnings ?? 0,
			duplicateBlocks: publishSignals?.duplicateBlocks ?? 0,
			recentPublishSuccesses: publishSignals?.recentPublishSuccesses ?? 0,
			engagementFetchSuccesses: engagementFetchSuccesses.get(accountId) ?? 0,
			isShadowbanned: !!account.is_shadowbanned,
			isSuppressed:
				evalResult.status === "suppressed" ||
				evalResult.status === "shadowban_throttle",
		});
		const recentWarmupViews = acctPosts14d
			.sort(
				(a, b) =>
					new Date(b.published_at).getTime() -
					new Date(a.published_at).getTime(),
			)
			.slice(0, 3)
			.map((post) => post.views_count ?? 0);
		const restartWarmup = evaluateRestartWarmup({
			now,
			previous: previousMap.get(accountId),
			accountId,
			healthScore: health.score,
			lastAutoposterPublishedAt: lastAutoposterPublishedAt.get(accountId),
			recentWarmupViews,
			isSuppressed:
				evalResult.status === "suppressed" ||
				evalResult.status === "inactive" ||
				evalResult.status === "shadowban_throttle",
			isThreads: true,
		});

		allStates.push({
			account_id: accountId,
			group_id: gc.group_id,
			workspace_id: gc.workspace_id,
			status: evalResult.status,
			status_reason: evalResult.status_reason,
			blocked_until: evalResult.blocked_until,
			flop_proven_remaining: evalResult.flop_proven_remaining,
			probe_posts_remaining: evalResult.probe_posts_remaining,
			warming_posts_today: evalResult.warming_posts_today,
			last_14d_avg_views: evalResult.last_14d_avg_views,
			median_30d_views: evalResult.median_30d_views,
			max_30d_views: evalResult.max_30d_views,
			pct_under_5_views: evalResult.pct_under_5_views,
			last_flop_post_id: evalResult.last_flop_post_id,
			flop_triggered_at: evalResult.flop_triggered_at,
			probe_cycles_completed: evalResult.probe_cycles_completed,
			account_health_score: health.score,
			account_health_reason: health.reason,
			last_health_recomputed_at: now.toISOString(),
			restart_warmup_status: restartWarmup.status,
			restart_warmup_started_at: restartWarmup.startedAt,
			restart_warmup_day: restartWarmup.day,
			restart_warmup_allowed_posts_per_day:
				restartWarmup.allowedPostsPerDay,
			restart_warmup_reason: restartWarmup.reason,
			restart_warmup_next_ramp_at: restartWarmup.nextRampAt,
			restart_warmup_last_post_views: restartWarmup.lastPostViews,
			restart_warmup_last_evaluated_at: restartWarmup.lastEvaluatedAt,
			consecutive_flops: evalResult.consecutive_flops,
			should_retire: evalResult.should_retire,
		} as AccountStateUpsert & Record<string, unknown>);

		// ── Check if account is blocked by state ──
		const stateForBlockCheck = {
			account_id: accountId,
			group_id: gc.group_id,
			workspace_id: gc.workspace_id,
			status: evalResult.status,
			status_reason: evalResult.status_reason ?? null,
			blocked_until: evalResult.blocked_until ?? null,
			flop_proven_remaining: evalResult.flop_proven_remaining ?? 0,
			probe_posts_remaining: evalResult.probe_posts_remaining ?? 0,
			warming_posts_today: evalResult.warming_posts_today ?? 0,
			last_14d_avg_views: evalResult.last_14d_avg_views ?? null,
			median_30d_views: evalResult.median_30d_views ?? null,
			max_30d_views: evalResult.max_30d_views ?? null,
			pct_under_5_views: evalResult.pct_under_5_views ?? null,
			last_skip_reason: null,
			last_skip_at: null,
			last_flop_post_id: evalResult.last_flop_post_id ?? null,
			flop_triggered_at: evalResult.flop_triggered_at ?? null,
			probe_cycles_completed: evalResult.probe_cycles_completed ?? 0,
			evaluated_at: now.toISOString(),
			created_at: now.toISOString(),
			updated_at: now.toISOString(),
		};

		if (isBlocked(stateForBlockCheck)) {
			decisions.push({
				run_id: runId,
				workspace_id: gc.workspace_id,
				group_id: gc.group_id,
				account_id: accountId,
				outcome: "skipped_blocked",
				reason: `${evalResult.status}: ${evalResult.status_reason ?? "blocked"}`,
				account_status: evalResult.status,
				posts_today: postsTodayByAccount.get(accountId) ?? 0,
				queue_depth: queueDepth,
			});
			continue;
		}

		// ── Eligibility checks (active window, cap, interval, weekends) ──
		const acctOverride = overrideMap.get(`${gc.group_id}:${accountId}`);
		const isWarmingLimited = evalResult.status === "warming_limited";
		const effectiveOverride = isWarmingLimited
			? { ...(acctOverride ?? {}), posts_per_account_per_day: 1 }
			: acctOverride;
		const postsToday = postsTodayByAccount.get(accountId) ?? 0;
		const lastPost = lastPostTimeByAccount.get(accountId) ?? null;

		const eligibility = checkEligibility({
			activeHoursStart: gc.active_hours_start,
			activeHoursEnd: gc.active_hours_end,
			timezone: gc.timezone,
			dailyCap: isWarmingLimited ? 1 : gc.posts_per_account_per_day,
			minIntervalMinutes: gc.min_interval_minutes,
			postOnWeekends: gc.post_on_weekends,
			override: effectiveOverride as EligibilityInput["override"],
			lastPostTime: lastPost,
			postsToday,
			now,
		});

		if (!eligibility.eligible) {
			// Map reason to outcome
			let outcome: SchedulerDecision["outcome"] = "skipped_outside_window";
			if (eligibility.reason.startsWith("daily_cap"))
				outcome = "skipped_daily_cap";
			else if (eligibility.reason.startsWith("min_interval"))
				outcome = "skipped_min_interval";
			else if (eligibility.reason.startsWith("weekend"))
				outcome = "skipped_weekend";

			decisions.push({
				run_id: runId,
				workspace_id: gc.workspace_id,
				group_id: gc.group_id,
				account_id: accountId,
				outcome,
				reason: eligibility.reason,
				account_status: evalResult.status,
				local_hour: eligibility.localHour,
				posts_today: postsToday,
				minutes_since_last_post: lastPost
					? Math.round((now.getTime() - lastPost) / 60000)
					: null,
				queue_depth: queueDepth,
			});
			continue;
		}

		// ── Pick a pending queue item ──
		// v3+ pool mode: all items are account-agnostic, just grab the next unclaimed one
		// v2 legacy: items may be pre-assigned to specific accounts
		const available = pendingItems.find(
			(item) =>
				!claimedItemIds.has(item.id) &&
				(schedulerVersion >= 3 ||
					item.account_id === null ||
					item.account_id === accountId),
		);

		if (!available) {
			decisions.push({
				run_id: runId,
				workspace_id: gc.workspace_id,
				group_id: gc.group_id,
				account_id: accountId,
				outcome: "skipped_no_content",
				reason: "no_pending_queue_items",
				account_status: evalResult.status,
				local_hour: eligibility.localHour,
				posts_today: postsToday,
				queue_depth: queueDepth,
			});
			continue;
		}

		// Claim this item
		claimedItemIds.add(available.id);

		// ── Dispatch via QStash ──
		try {
			const { getQStashClient } = await import("../../qstash.js");
			const { RETRIES, getFailureCallbackUrl, getRequiredAppBaseUrl } =
				await import("../../qstashDefaults.js");
			const { recordInfraEvent } = await import("../../infraTelemetry.js");
			const qstash = getQStashClient();
			const baseUrl = getRequiredAppBaseUrl();
			const failureCb = getFailureCallbackUrl();
			const scheduledUnix = Math.max(
				Math.floor(Date.now() / 1000),
				Math.floor(new Date(available.scheduled_for).getTime() / 1000),
			);
			const scheduleNonce = `sched-${available.id}-${scheduledUnix}`;

			// Claim only items that are already due. Preserve the original scheduled_for
			// so the intended cadence remains observable in the queue/history.
			await queueQueueItemForDispatch(available.id, {
				accountId,
				scheduleNonce,
				...(schedulerVersion >= 3 ? { poolStatus: "claimed" } : {}),
			});

			const result = await qstash.publishJSON({
				url: `${baseUrl}/api/auto-post-publish`,
				body: {
					queueItemId: available.id,
					workspaceId: gc.workspace_id,
					groupId: gc.group_id,
					ownerId: grpInfo.user_id,
					groupName: grpInfo.name,
					accountId,
					scheduleNonce,
					traceId: `sched-${runId.slice(0, 8)}-${Date.now()}`,
				},
				retries: RETRIES.CRITICAL,
				notBefore: scheduledUnix,
				deduplicationId: scheduleNonce,
				failureCallback: failureCb,
			});
			await markQueueItemDispatched(available.id, {
				qstashMessageId: result.messageId,
				scheduleNonce,
			});
			await recordInfraEvent("autopost-scheduler-dispatch", {
				queueItemId: available.id,
				scheduleNonce,
				qstashMessageId: result.messageId,
				groupId: gc.group_id,
				workspaceId: gc.workspace_id,
				accountId,
			});

			groupDispatched++;
			decisions.push({
				run_id: runId,
				workspace_id: gc.workspace_id,
				group_id: gc.group_id,
				account_id: accountId,
				outcome: "dispatched",
				reason: "eligible_content_available",
				queue_item_id: available.id,
				account_status: evalResult.status,
				local_hour: eligibility.localHour,
				posts_today: postsToday,
				minutes_since_last_post: lastPost
					? Math.round((now.getTime() - lastPost) / 60000)
					: null,
				queue_depth: queueDepth,
			});

			logger.info("[scheduler] Dispatched publish", {
				runId: runId.slice(0, 8),
				groupId: gc.group_id,
				accountId,
				queueItemId: available.id,
			});
		} catch (err) {
			const { recordInfraEvent } = await import("../../infraTelemetry.js");
			await recordInfraEvent("autopost-scheduler-dispatch-failed", {
				queueItemId: available.id,
				groupId: gc.group_id,
				workspaceId: gc.workspace_id,
				accountId,
				error: err instanceof Error ? err.message : String(err),
			});
			decisions.push({
				run_id: runId,
				workspace_id: gc.workspace_id,
				group_id: gc.group_id,
				account_id: accountId,
				outcome: "error",
				reason: `dispatch_failed: ${err instanceof Error ? err.message : String(err)}`,
				queue_item_id: available.id,
				account_status: evalResult.status,
				local_hour: eligibility.localHour,
				posts_today: postsToday,
				queue_depth: queueDepth,
			});
			logger.warn("[scheduler] QStash dispatch failed", {
				accountId,
				queueItemId: available.id,
				error: err instanceof Error ? err.message : String(err),
			});
		}
	}

	// ── Upsert account states ──
	let statesResult = 0;
	if (allStates.length > 0) {
		const { success } = await bulkUpsertAccountStates(allStates);
		statesResult = success;
	}

	// ── Trigger queue fill if low ──
	const effectiveQueueThreshold = Math.max(
		3,
		groupAccountIds.length * (gc.posts_per_account_per_day ?? 1),
	);
	if (queueDepth - claimedItemIds.size < effectiveQueueThreshold) {
		try {
			const { dispatchQueueFill } = await import(
				"../../handlers/auto-post/queue.js"
			);
			const fillDispatch = await dispatchQueueFill(
				gc.workspace_id,
				grpInfo.user_id,
				gc.group_id,
				grpInfo.name,
			);
			if (fillDispatch.dispatched) {
				groupFills++;
				logger.info("[scheduler] Triggered queue fill", {
					groupId: gc.group_id,
					queueDepth,
					claimed: claimedItemIds.size,
					effectiveQueueThreshold,
				});
			} else {
				logger.info("[scheduler] Queue fill not dispatched", {
					groupId: gc.group_id,
					queueDepth,
					claimed: claimedItemIds.size,
					effectiveQueueThreshold,
					reason: fillDispatch.reason,
				});
			}
		} catch (err) {
			logger.warn("[scheduler] Queue fill dispatch failed", {
				groupId: gc.group_id,
				error: err instanceof Error ? err.message : String(err),
			});
		}
	}

	return {
		accountsEvaluated: accounts.length,
		dispatched: groupDispatched,
		fillsTriggered: groupFills,
		statesUpserted: statesResult,
	};
}

// ============================================================================
// Helpers
// ============================================================================

function makeSummary(
	runId: string,
	groupsProcessed: number,
	accountsEvaluated: number,
	dispatched: number,
	fillsTriggered: number,
	statesUpserted: number,
	decisionsLogged: number,
	errors: string[],
	startTime: number,
): SchedulerSummary {
	return {
		runId,
		groupsProcessed,
		accountsEvaluated,
		dispatched,
		fillsTriggered,
		statesUpserted,
		decisionsLogged,
		errors,
		durationMs: Date.now() - startTime,
	};
}
