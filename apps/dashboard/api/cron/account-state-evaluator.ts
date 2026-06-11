// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Account State Evaluator Cron — Every 15 minutes
 *
 * Phase 2 of the auto-poster simplification plan.
 * Loads all active accounts + their post history, evaluates each one
 * through the unified stateEvaluator, and batch-upserts results to
 * `account_autoposter_state`.
 *
 * Runs in PARALLEL with existing Redis-based checks (Phase 2 = write-only).
 * Phase 3 will switch accountPlanner to read from this table.
 */

import { alertCronFailure } from "../_lib/alerting.js";
import { trackCronRun, withCronLock } from "../_lib/cronUtils.js";
import type { AccountStateUpsert } from "../_lib/handlers/auto-post/accountState.js";
import {
	bulkUpsertAccountStates,
	getGroupAccountStates,
} from "../_lib/handlers/auto-post/accountState.js";
import {
	calculateAutoposterAccountHealth,
	isPublishAttemptFailureForAccountHealth,
} from "../_lib/handlers/auto-post/accountHealth.js";
import {
	type AccountScheduleSyncState,
	syncAccountScheduleStatuses,
} from "../_lib/handlers/auto-post/accountScheduleStatusSync.js";
import {
	type AccountEvalInput,
	evaluateAccountState,
	type PostViewRecord,
	type PostWithVelocity,
} from "../_lib/handlers/auto-post/stateEvaluator.js";
import { evaluateRestartWarmup } from "../_lib/handlers/auto-post/restartWarmup.js";
import {
	cleanupPersistedStaleWarmupReadyRows,
	cleanupStaleWarmupReadyRows,
} from "../_lib/handlers/auto-post/warmupCapacity.js";
import { logger } from "../_lib/logger.js";
import { withCron } from "../_lib/middleware.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";

export const config = {
	maxDuration: 120,
};

const JOB_NAME = "account-state-evaluator";

// biome-ignore lint/suspicious/noExplicitAny: auto_post tables not in generated types
const db = (): any =>
	getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.accountStateEvaluator);

export default withCron(async (_req, res) => {
	const startTime = Date.now();
	const supabase = db();

	const lockResult = await withCronLock(
		supabase,
		JOB_NAME,
		async () => {
			return trackCronRun(supabase, JOB_NAME, async () => {
				const summary = await runAccountStateEvaluation(startTime);
				return {
					itemsProcessed: summary.upserted,
					metadata: summary,
				};
			});
		},
		125,
	);

	if (!("result" in lockResult)) {
		return res.json({ ok: true, skipped: "locked" });
	}

	return res.json({ ok: true, ...lockResult.result.metadata });
});

async function runAccountStateEvaluation(startTime: number): Promise<{
	skipped?: string | undefined;
	groups: number;
	accounts: number;
	upserted: number;
	retirements: number;
	scheduleStatusRepaired: number;
	scheduleStatusMismatches: number;
	staleWarmupReadyRowsCleaned: number;
	durationMs: number;
}> {
	// 1. Load legacy workspaces with auto-poster enabled
	const { data: workspaceConfigs } = await db()
		.from("auto_post_config")
		.select("workspace_id, scheduler_version")
		.eq("is_enabled", true);

	const legacyWorkspaceIds = (
		(workspaceConfigs ?? []) as Array<{
			workspace_id: string;
			scheduler_version?: number | null | undefined;
		}>
	)
		.filter((cfg) => (cfg.scheduler_version ?? 1) < 2)
		.map((cfg) => cfg.workspace_id);

	if (legacyWorkspaceIds.length === 0) {
		let staleWarmupReadyRowsCleaned = 0;
		const workspaceIds = [
			...new Set(
				((workspaceConfigs ?? []) as Array<{ workspace_id: string }>).map(
					(cfg) => cfg.workspace_id,
				),
			),
		];
		for (const workspaceId of workspaceIds) {
			const cleanupReport = await cleanupPersistedStaleWarmupReadyRows({
				workspaceId,
			});
			staleWarmupReadyRowsCleaned += cleanupReport.movedToReview;
			if (cleanupReport.movedToReview > 0) {
				logger.info(`[${JOB_NAME}] Cleaned stale warm-up ready rows`, {
					workspaceId,
					checkedRows: cleanupReport.checkedRows,
					keptRows: cleanupReport.keptRows,
					movedToReview: cleanupReport.movedToReview,
					reasons: cleanupReport.reasons,
					source: "persisted_state",
				});
			}
		}
		return {
			skipped: "no_legacy_workspaces",
			groups: 0,
			accounts: 0,
			upserted: 0,
			retirements: 0,
			scheduleStatusRepaired: 0,
			scheduleStatusMismatches: 0,
			staleWarmupReadyRowsCleaned,
			durationMs: Date.now() - startTime,
		};
	}

	const { data: configs } = await db()
		.from("auto_post_group_config")
		.select("workspace_id, group_id, enabled")
		.in("workspace_id", legacyWorkspaceIds)
		.eq("enabled", true);

	if (!configs || configs.length === 0) {
		logger.info(`[${JOB_NAME}] No enabled groups found`);
		return {
			groups: 0,
			accounts: 0,
			upserted: 0,
			retirements: 0,
			scheduleStatusRepaired: 0,
			scheduleStatusMismatches: 0,
			staleWarmupReadyRowsCleaned: 0,
			durationMs: Date.now() - startTime,
		};
	}

	// 2. Get unique workspace+group pairs
	const groups = configs as Array<{ workspace_id: string; group_id: string }>;
	logger.info(`[${JOB_NAME}] Evaluating ${groups.length} groups`);

	let totalAccounts = 0;
	let totalUpserted = 0;
	let totalScheduleStatusRepaired = 0;
	let totalScheduleStatusMismatches = 0;
	let totalStaleWarmupReadyRowsCleaned = 0;
	const allStates: AccountStateUpsert[] = [];

	// 3. Process each group
	for (const group of groups) {
		try {
			const states = await evaluateGroup(group.workspace_id, group.group_id);
			allStates.push(...states);
			totalAccounts += states.length;
		} catch (err) {
			logger.error(`[${JOB_NAME}] Failed to evaluate group`, {
				groupId: group.group_id,
				error: err instanceof Error ? err.message : String(err),
			});
			// Alert per-group failures so they don't go unnoticed
			alertCronFailure(
				JOB_NAME,
				`Group ${group.group_id}: ${err instanceof Error ? err.message : String(err)}`,
				Date.now() - startTime,
			);
		}
	}

	// 4. Handle auto-retirements before upserting
	const retirements: Array<{ account_id: string; username: string }> = [];
	for (const state of allStates) {
		if ((state as Record<string, unknown>).should_retire) {
			try {
				// Mark account as retired in accounts table
				await db()
					.from("accounts")
					.update({ is_retired: true, is_active: false })
					.eq("id", state.account_id);
				const acctRow = await db()
					.from("accounts")
					.select("username")
					.eq("id", state.account_id)
					.maybeSingle();
				retirements.push({
					account_id: state.account_id,
					username: acctRow?.data?.username ?? "unknown",
				});
			} catch (err) {
				logger.warn(`[${JOB_NAME}] Failed to retire account`, {
					accountId: state.account_id,
					error: String(err),
				});
			}
		}
	}

	// Fire Discord alert for retirements
	if (retirements.length > 0) {
		try {
			const { alert, AlertLevel } = await import("../_lib/alerting.js");
			await alert(
				AlertLevel.WARN,
				`${retirements.length} account(s) auto-retired (shadowbanned)`,
				{
					accounts: retirements.map((r) => `@${r.username}`).join(", "),
					action:
						"Add replacement accounts. These failed 2 probe cycles with near-zero views.",
				},
			);
		} catch {
			/* best-effort */
		}
	}

	// 5. Batch upsert all states
	if (allStates.length > 0) {
		const { success, failed } = await bulkUpsertAccountStates(allStates);
		totalUpserted = success;
		if (failed > 0) {
			logger.warn(`[${JOB_NAME}] Some upserts failed`, { success, failed });
		}
	}

	const statesByWorkspace = new Map<string, AccountScheduleSyncState[]>();
	for (const state of allStates) {
		if (!state.status) continue;
		const syncState: AccountScheduleSyncState = {
			account_id: state.account_id,
			group_id: state.group_id,
			workspace_id: state.workspace_id,
			status: state.status,
			...(state.account_health_score !== undefined
				? { account_health_score: state.account_health_score }
				: {}),
			...(state.restart_warmup_status !== undefined
				? { restart_warmup_status: state.restart_warmup_status }
				: {}),
			...(state.recommended_strategy_mode !== undefined
				? { recommended_strategy_mode: state.recommended_strategy_mode }
				: {}),
			...(state.status_reason !== undefined
				? { status_reason: state.status_reason }
				: {}),
		};
		const list = statesByWorkspace.get(state.workspace_id) ?? [];
		list.push(syncState);
		statesByWorkspace.set(state.workspace_id, list);
	}
	for (const [workspaceId, states] of statesByWorkspace) {
		const report = await syncAccountScheduleStatuses({
			workspaceId,
			states,
			dryRun: false,
		});
		totalScheduleStatusRepaired += report.repaired;
		totalScheduleStatusMismatches += report.mismatches;
		if (report.repaired > 0 || report.mismatches > 0) {
			logger.info(`[${JOB_NAME}] Synced account_schedule statuses`, {
				workspaceId,
				checked: report.checked,
				mismatches: report.mismatches,
				repaired: report.repaired,
				skippedPaused: report.skippedPaused,
				remainingBlocked: report.remainingBlocked,
			});
		}

		const cleanupReport = await cleanupStaleWarmupReadyRows({
			workspaceId,
			states: allStates.filter((state) => state.workspace_id === workspaceId),
		});
		totalStaleWarmupReadyRowsCleaned += cleanupReport.movedToReview;
		if (cleanupReport.movedToReview > 0) {
			logger.info(`[${JOB_NAME}] Cleaned stale warm-up ready rows`, {
				workspaceId,
				checkedRows: cleanupReport.checkedRows,
				keptRows: cleanupReport.keptRows,
				movedToReview: cleanupReport.movedToReview,
				reasons: cleanupReport.reasons,
			});
		}
	}

	const duration = Date.now() - startTime;
	logger.info(`[${JOB_NAME}] Complete`, {
		groups: groups.length,
		accounts: totalAccounts,
		upserted: totalUpserted,
		scheduleStatusRepaired: totalScheduleStatusRepaired,
		staleWarmupReadyRowsCleaned: totalStaleWarmupReadyRowsCleaned,
		durationMs: duration,
	});

	return {
		groups: groups.length,
		accounts: totalAccounts,
		upserted: totalUpserted,
		retirements: retirements.length,
		scheduleStatusRepaired: totalScheduleStatusRepaired,
		scheduleStatusMismatches: totalScheduleStatusMismatches,
		staleWarmupReadyRowsCleaned: totalStaleWarmupReadyRowsCleaned,
		durationMs: duration,
	};
}

// ============================================================================
// Group evaluation — loads all data for a group, runs evaluator per account
// ============================================================================

async function evaluateGroup(
	workspaceId: string,
	groupId: string,
): Promise<AccountStateUpsert[]> {
	// Load accounts via account_groups.account_ids (source of truth)
	// accounts.group_id can point to a different group for shared/feeder accounts
	const { data: groupRow } = await db()
		.from("account_groups")
		.select("account_ids")
		.eq("id", groupId)
		.maybeSingle();

	const groupAccountIds = (groupRow?.account_ids || []) as string[];
	if (groupAccountIds.length === 0) return [];

	const { data: accounts } = await db()
		.from("accounts")
		.select(
			"id, username, created_at, is_shadowbanned, is_retired, needs_reauth, is_active, status, followers_count, user_id",
		)
		.in("id", groupAccountIds)
		.not("threads_access_token_encrypted", "is", null)
		.or("status.is.null,status.neq.suspended");

	if (!accounts || accounts.length === 0) return [];

	const accountIds = accounts.map(
		(a: Record<string, unknown>) => a.id as string,
	);
	const now = new Date();
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

	// Batch load all post data for all accounts in this group at once
	const [
		posts30dResult,
		posts2hResult,
		publishedCountsResult,
		posts48hResult,
		publishAttemptsResult,
		engagementFetchResult,
		autoposterRecentResult,
	] =
		await Promise.all([
			// All posts last 30d with views > 0 (for suppression, flop, baseline)
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
		["publishAttempts", publishAttemptsResult],
		["engagementFetch", engagementFetchResult],
		["autoposterRecent", autoposterRecentResult],
	] as const) {
		if (result.error) {
			logger.error("[account-state-evaluator] Failed to load post data", {
				groupId,
				label,
				error: result.error.message,
			});
			throw new Error(
				`account-state-evaluator ${label} query failed: ${result.error.message}`,
			);
		}
	}

	// Index post data by account
	const posts30dByAccount = new Map<string, PostViewRecord[]>();
	const posts14dByAccount = new Map<string, PostViewRecord[]>();
	const posts2hByAccount = new Map<string, PostWithVelocity[]>();
	const publishedCounts = new Map<string, number>();
	const posts48hCounts = new Map<string, number>();
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
		// 30d bucket
		const posts30dBucket = posts30dByAccount.get(p.account_id) ?? [];
		posts30dBucket.push(record);
		posts30dByAccount.set(p.account_id, posts30dBucket);

		// 14d bucket
		if (
			new Date(p.published_at).getTime() >= new Date(fourteenDaysAgo).getTime()
		) {
			const posts14dBucket = posts14dByAccount.get(p.account_id) ?? [];
			posts14dBucket.push(record);
			posts14dByAccount.set(p.account_id, posts14dBucket);
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
		const posts2hBucket = posts2hByAccount.get(p.account_id) ?? [];
		posts2hBucket.push(record);
		posts2hByAccount.set(p.account_id, posts2hBucket);
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

	// Load previous states for continuity (probe/flop counters)
	const previousStates = await getGroupAccountStates(groupId);
	const previousMap = new Map(previousStates.map((s) => [s.account_id, s]));

	// Evaluate each account
	const results: AccountStateUpsert[] = [];

	for (const account of accounts as Array<Record<string, unknown>>) {
		const accountId = account.id as string;
		const acctPosts30d = posts30dByAccount.get(accountId) ?? [];
		const acctPosts14d = posts14dByAccount.get(accountId) ?? [];

		// Recent 3 posts (newest first, with views > 0)
		const recent3 = acctPosts14d
			.filter((p) => p.views_count > 0)
			.sort(
				(a, b) =>
					new Date(b.published_at).getTime() -
					new Date(a.published_at).getTime(),
			)
			.slice(0, 3);

		// Latest post >2h old (for flop check)
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
			group_id: groupId,
			workspace_id: workspaceId,
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
			isProbeMode: evalResult.status === "suppressed_probe",
			isThreads: true,
		});

		results.push({
			account_id: accountId,
			group_id: groupId,
			workspace_id: workspaceId,
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
	}

	return results;
}
