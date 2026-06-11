// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Account Planner — pre-assigns accounts to queue items at fill time.
 *
 * Moves account selection from publish time to fill time. Uses a single
 * batch read from `account_autoposter_state` (populated by the state
 * evaluator cron every 15 min) instead of 7 sequential Redis/DB checks.
 *
 * The publisher still validates the pre-assigned account is active at
 * publish time (lightweight check), but the heavy lifting is done here.
 */

import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";
import {
	type AccountAutoposterState,
	getGroupAccountStates,
	isBlocked,
} from "./accountState.js";
import {
	autoposterHealthSortValue,
	isAutoposterHealthSuppressed,
} from "./accountHealth.js";
import { checkAccountEligibility, type EligibilityCheck } from "./queue.js";
import {
	restartWarmupPolicyFromState,
	type RestartWarmupPolicy,
} from "./restartWarmup.js";
import type { GroupConfig } from "./types.js";
import {
	countUsedPostingCapacityForAccount,
	deriveEffectivePostingCap,
	loadCapacityRowsForAccounts,
} from "./warmupCapacity.js";

// biome-ignore lint/suspicious/noExplicitAny: auto_post tables not in generated types
const db = (): any => getSupabaseAny();

export interface PlannedSlot {
	accountId: string;
	/** Which index in the round-robin this account was at */
	roundRobinIndex: number;
	/** If true, this is a probe post for a previously-suppressed account — use top historical content, text-only */
	isProbe?: boolean | undefined;
	warmupPolicy?: RestartWarmupPolicy | undefined;
	timezone?: string | undefined;
	activeHoursStart?: number | undefined;
	activeHoursEnd?: number | undefined;
	minIntervalMinutes?: number | undefined;
}

export interface SkippedAccount {
	account_id: string;
	username: string;
	reason: string;
}

export interface PlanResult {
	slots: PlannedSlot[];
	skipped: SkippedAccount[];
	totalAccounts: number;
	eligibleCount: number;
}

interface AccountCandidate {
	id: string;
	username: string;
	created_at: string | null;
	is_shadowbanned: boolean;
	followers_count: number | null;
	sync_cohort?: string | null | undefined;
}

interface AccountScheduleRow {
	account_id: string;
	active_hours_start?: number | null;
	active_hours_end?: number | null;
	timezone?: string | null;
	min_interval_minutes?: number | null;
	paused?: boolean | null;
	status?: string | null;
	blocked_until?: string | null;
}

// ── Human-like randomization helpers ─────────────────────────────────────
// Deterministic per-account: same account+date = same result, but every
// account gets a different schedule. Re-rolls daily/weekly automatically.

function simpleHash(str: string): number {
	let hash = 0;
	for (let i = 0; i < str.length; i++) {
		hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
	}
	return Math.abs(hash);
}

function getISOWeek(date: Date): number {
	const d = new Date(
		Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()),
	);
	const dayNum = d.getUTCDay() || 7;
	d.setUTCDate(d.getUTCDate() + 4 - dayNum);
	const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
	return Math.ceil(((d.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
}

function safeTimeZone(timezone?: string): string {
	const tz = timezone || "UTC";
	try {
		new Intl.DateTimeFormat("en-US", { timeZone: tz }).format(new Date());
		return tz;
	} catch {
		return "UTC";
	}
}

function getDateKeyInTimezone(value: Date | string, timezone?: string): string {
	const date = value instanceof Date ? value : new Date(value);
	const parts = new Intl.DateTimeFormat("en-CA", {
		timeZone: safeTimeZone(timezone),
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
	}).formatToParts(date);
	const byType = Object.fromEntries(
		parts.map((part) => [part.type, part.value]),
	);
	return `${byType.year}-${byType.month}-${byType.day}`;
}

/**
 * Returns true if today is a rest day for this account.
 * Picks `restDaysPerWeek` unique days per account per week using a hash seed.
 */
function isRestDay(
	accountId: string,
	date: Date,
	restDaysPerWeek: number,
): boolean {
	if (restDaysPerWeek <= 0) return false;
	if (restDaysPerWeek >= 7) return true;
	const seed = simpleHash(
		`${accountId}:${date.getFullYear()}:${getISOWeek(date)}`,
	);
	const restDays = new Set<number>();
	for (let i = 0; restDays.size < restDaysPerWeek && i < 20; i++) {
		restDays.add(simpleHash(`${seed}:${i}`) % 7);
	}
	return restDays.has(date.getDay());
}

/**
 * Returns a random daily post count between min and max (inclusive).
 * Deterministic per account per day.
 */
function getDailyPostCount(
	accountId: string,
	dateKey: string,
	minPosts: number,
	maxPosts: number,
): number {
	if (minPosts >= maxPosts) return maxPosts;
	const hash = simpleHash(`${accountId}:daily:${dateKey}`);
	return minPosts + (hash % (maxPosts - minPosts + 1));
}

/**
 * Follower tier posting caps — smaller accounts get fewer posts per day.
 * Research: new/small accounts penalized for high-velocity posting.
 * Tier caps are maximums — actual cap is min(tierCap, groupConfig.posts_per_account_per_day).
 */
function getFollowerTierCap(account: AccountCandidate): number {
	const cohort = (account.sync_cohort || "").toLowerCase();

	// Cohort-based overrides: cold/dormant accounts get a softer ramp,
	// while warm/hot accounts can use the full 4/day group target.
	if (cohort === "cold" || cohort === "dormant") return 2;
	if (cohort === "warm" || cohort === "hot") return 4;

	const followers = account.followers_count ?? 0;
	if (followers < 1000) return 2;
	if (followers < 5000) return 3;
	return 4;
}

/**
 * Plan account assignments for a batch of queue items.
 *
 * 1. Loads all active accounts in the group
 * 2. Batch-checks smart timing (viral suppression, flop recovery, warming)
 * 3. Checks per-account eligibility (active hours, weekends, min_interval)
 * 4. Round-robins across eligible accounts
 *
 * Returns one PlannedSlot per requested count. If fewer accounts are
 * eligible than requested, slots wrap around (same account gets multiple).
 * Returns empty array if NO accounts are eligible.
 */
export async function planAccountSlots(
	groupId: string,
	workspaceId: string,
	ownerId: string,
	count: number,
	resolvedConfig?: import("./configResolver.js").ResolvedConfig,
): Promise<PlanResult> {
	if (count <= 0)
		return { slots: [], skipped: [], totalAccounts: 0, eligibleCount: 0 };

	// 1. Load group config (use resolved config if provided, else fetch)
	const groupConfig = resolvedConfig?.groupTimingConfig
		? {
				...resolvedConfig.groupTimingConfig,
				enabled: resolvedConfig.groupTimingConfig.enabled ?? true,
			}
		: (
				await db()
					.from("auto_post_group_config")
					.select(
						"enabled, timezone, active_hours_start, active_hours_end, post_on_weekends, min_interval_minutes, posts_per_account_per_day, min_posts_per_account_per_day, rest_days_per_week",
					)
					.eq("workspace_id", workspaceId)
					.eq("group_id", groupId)
					.maybeSingle()
			).data;

	if (!groupConfig?.enabled) {
		logger.info("[accountPlanner] Group disabled, no slots planned", {
			groupId,
		});
		return { slots: [], skipped: [], totalAccounts: 0, eligibleCount: 0 };
	}

	// 2. Load all active accounts in the group
	// Use account_groups.account_ids as source of truth (not accounts.group_id)
	// because accounts can be in sub-groups (feeders) while group_id points to their main group
	const groupAccountIds = resolvedConfig?.groupAccountIds?.length
		? resolvedConfig.groupAccountIds
		: (((
				await db()
					.from("account_groups")
					.select("account_ids")
					.eq("id", groupId)
					.maybeSingle()
			).data?.account_ids || []) as string[]);
	if (groupAccountIds.length === 0) {
		logger.info("[accountPlanner] No account_ids in group", { groupId });
		return { slots: [], skipped: [], totalAccounts: 0, eligibleCount: 0 };
	}

	const { data: accounts } = await db()
		.from("accounts")
		.select(
			"id, username, created_at, is_shadowbanned, is_retired, needs_reauth, is_active, status, followers_count, sync_cohort",
		)
		.eq("user_id", ownerId)
		.in("id", groupAccountIds)
		.not("threads_access_token_encrypted", "is", null)
		.or("status.is.null,status.neq.suspended");

	if (!accounts || accounts.length === 0) {
		logger.info("[accountPlanner] No accounts in group", { groupId });
		return { slots: [], skipped: [], totalAccounts: 0, eligibleCount: 0 };
	}

	// Filter out retired/reauth/inactive
	const active = accounts.filter(
		(a: Record<string, unknown>) =>
			!a.is_retired && !a.needs_reauth && a.is_active !== false,
	) as AccountCandidate[];

	if (active.length === 0) {
		logger.info("[accountPlanner] All accounts need reauth or inactive", {
			groupId,
		});
		return {
			slots: [],
			skipped: [],
			totalAccounts: accounts.length,
			eligibleCount: 0,
		};
	}

	// 3. Load per-account overrides (use resolved config if provided, else fetch)
	const overrideMap = new Map<string, Record<string, unknown>>();
	if (resolvedConfig?.accountOverrides) {
		// Convert ResolvedConfig's typed AccountOverride map to the blob format accountPlanner expects
		for (const [key, override] of resolvedConfig.accountOverrides) {
			overrideMap.set(key, {
				paused: override.paused,
				max_posts_per_day: override.max_posts_per_day,
				posts_per_account_per_day: override.max_posts_per_day,
				min_interval_minutes: override.min_interval_minutes,
				custom_voice: override.custom_voice,
			});
		}
	} else {
		const { data: overrides } = await db()
			.from("auto_post_account_overrides")
			.select("*")
			.eq("group_id", groupId);

		if (overrides) {
			for (const o of overrides) {
				const blob = (o as Record<string, unknown>).overrides as Record<
					string,
					unknown
				> | null;
				if (blob) {
					overrideMap.set(`${groupId}:${o.account_id}`, blob);
				}
			}
		}
	}

	// 4. Build GroupConfig for eligibility checks
	const gc: GroupConfig = {
		id: groupConfig.id || "",
		workspace_id: workspaceId,
		group_id: groupId,
		posts_per_account_per_day: groupConfig.posts_per_account_per_day ?? 1,
		min_interval_minutes: groupConfig.min_interval_minutes ?? 60,
		active_hours_start: groupConfig.active_hours_start ?? 8,
		active_hours_end: groupConfig.active_hours_end ?? 23,
		timezone: groupConfig.timezone ?? "UTC",
		post_on_weekends: groupConfig.post_on_weekends ?? true,
		enabled: true,
	};

	// 5. Get last post times per account (for min_interval check)
	const accountIds = active.map((a) => a.id);
	const lastPostByAccount = new Map<string, number>();
	const scheduleByAccount = new Map<string, AccountScheduleRow>();

	try {
		const { data: accountSchedules } = await db()
			.from("account_schedule")
			.select(
				"account_id, active_hours_start, active_hours_end, timezone, min_interval_minutes, paused, status, blocked_until",
			)
			.eq("group_id", groupId)
			.in("account_id", accountIds);
		for (const schedule of (accountSchedules ?? []) as AccountScheduleRow[]) {
			scheduleByAccount.set(schedule.account_id, schedule);
		}
	} catch (err) {
		logger.warn("[accountPlanner] Failed to load account schedules", {
			groupId,
			error: err instanceof Error ? err.message : String(err),
		});
	}

	const { data: lastPosts } = await db()
		.from("auto_post_queue")
		.select("account_id, posted_at")
		.in("account_id", accountIds)
		.in("status", ["published", "posted"])
		.not("posted_at", "is", null)
		.order("posted_at", { ascending: false });

	if (lastPosts) {
		for (const lp of lastPosts as Array<{
			account_id: string;
			posted_at: string;
		}>) {
			if (!lastPostByAccount.has(lp.account_id)) {
				lastPostByAccount.set(lp.account_id, new Date(lp.posted_at).getTime());
			}
		}
	}

	const now = new Date();

	// Count already-used posting capacity per account. This includes published,
	// publishing, queued/pending, retry, and pool rows planned for the account.
	// Warm-up/suppression caps are safety controls, so future ready rows reserve
	// capacity before they publish.
	let capacityRows: Awaited<ReturnType<typeof loadCapacityRowsForAccounts>> = [];
	try {
		capacityRows = await loadCapacityRowsForAccounts({
			workspaceId,
			groupId,
			accountIds,
			now,
		});
	} catch (err) {
		logger.warn("[accountPlanner] Failed to load warm-up capacity rows", {
			groupId,
			error: err instanceof Error ? err.message : String(err),
		});
		// Fail-open — the publish path still enforces caps before posting.
	}
	const eligibleAccounts: Array<{
		account: AccountCandidate;
		merged: GroupConfig;
	}> = [];
	const skippedAccounts: SkippedAccount[] = [];
	const probeAccountIds = new Set<string>();

	// Single batch DB read — replaces legacy 7 sequential Redis/DB checks
	const accountStates = await getGroupAccountStates(groupId);
	const stateMap = new Map<string, AccountAutoposterState>();
	for (const s of accountStates) stateMap.set(s.account_id, s);

	// Human-randomness config
	const restDaysPerWeek: number = groupConfig.rest_days_per_week ?? 0;
	const minPostsPerDay: number =
		groupConfig.min_posts_per_account_per_day ?? gc.posts_per_account_per_day;

	for (const account of active) {
		const accountOverride = overrideMap.get(`${groupId}:${account.id}`);
		if (accountOverride?.paused === true) {
			skippedAccounts.push({
				account_id: account.id,
				username: account.username,
				reason: "paused",
			});
			continue;
		}
		const accountSchedule = scheduleByAccount.get(account.id);
		if (accountSchedule?.paused === true) {
			skippedAccounts.push({
				account_id: account.id,
				username: account.username,
				reason: "account_schedule_paused",
			});
			continue;
		}
		if (
			accountSchedule?.status &&
			!["active", "enabled"].includes(accountSchedule.status)
		) {
			skippedAccounts.push({
				account_id: account.id,
				username: account.username,
				reason: `account_schedule_${accountSchedule.status}`,
			});
			continue;
		}
		if (
			accountSchedule?.blocked_until &&
			new Date(accountSchedule.blocked_until).getTime() > now.getTime()
		) {
			skippedAccounts.push({
				account_id: account.id,
				username: account.username,
				reason: "account_schedule_blocked",
			});
			continue;
		}

		// Rest day check — deterministic per account per week
		if (restDaysPerWeek > 0 && isRestDay(account.id, now, restDaysPerWeek)) {
			skippedAccounts.push({
				account_id: account.id,
				username: account.username,
				reason: "rest_day",
			});
			continue;
		}

		const state = stateMap.get(account.id);
		const healthScore = state?.account_health_score ?? null;
		const warmupPolicy = restartWarmupPolicyFromState(state);
		const effectiveCap = deriveEffectivePostingCap(state);
		if (isAutoposterHealthSuppressed(healthScore)) {
			skippedAccounts.push({
				account_id: account.id,
				username: account.username,
				reason: "account_health_suppressed",
			});
			continue;
		}
		if (warmupPolicy?.shouldSkipToday) {
			skippedAccounts.push({
				account_id: account.id,
				username: account.username,
				reason: `restart_warmup_${warmupPolicy.status}`,
			});
			continue;
		}
		if (effectiveCap.cap === 0) {
			skippedAccounts.push({
				account_id: account.id,
				username: account.username,
				reason: effectiveCap.reason,
			});
			continue;
		}
		const isProbeState = state?.status === "suppressed_probe";
		if (state?.recommended_strategy_mode === "suppress" && !isProbeState) {
			skippedAccounts.push({
				account_id: account.id,
				username: account.username,
				reason: "performance_suppressed",
			});
			continue;
		}

		// If state exists and account is blocked, skip with reason
		if (state && isBlocked(state)) {
			skippedAccounts.push({
				account_id: account.id,
				username: account.username,
				reason: state.status,
			});
			continue;
		}

		// Probe accounts (suppressed_probe status, not currently blocked)
		if (isProbeState) {
			probeAccountIds.add(account.id);
		}

		// Time-of-day eligibility (pure function)
		// skipActiveHours=true: planner assigns accounts for future scheduled times.
		// The publish worker re-checks active hours at actual publish time.
		const eligibility: EligibilityCheck = checkAccountEligibility(
			gc,
			account.id,
			overrideMap,
			lastPostByAccount,
			now,
			true, // skipActiveHours — publish worker enforces at publish time
		);
		if (!eligibility.eligible) {
			skippedAccounts.push({
				account_id: account.id,
				username: account.username,
				reason: "eligibility",
			});
			continue;
		}

		eligibleAccounts.push({
			account,
			merged: {
				...eligibility.merged,
				timezone:
					typeof accountSchedule?.timezone === "string" &&
					accountSchedule.timezone.trim()
						? accountSchedule.timezone
						: eligibility.merged.timezone,
				active_hours_start:
					typeof accountSchedule?.active_hours_start === "number"
						? accountSchedule.active_hours_start
						: eligibility.merged.active_hours_start,
				active_hours_end:
					typeof accountSchedule?.active_hours_end === "number"
						? accountSchedule.active_hours_end
						: eligibility.merged.active_hours_end,
				min_interval_minutes:
					typeof accountSchedule?.min_interval_minutes === "number"
						? accountSchedule.min_interval_minutes
						: eligibility.merged.min_interval_minutes,
			},
		});
	}

	// Prefer healthiest accounts first, then preserve the older warming priority as
	// a tie-breaker so recovery accounts still get motion when scores are equal.
	eligibleAccounts.sort((a, b) => {
		const scoreDelta =
			autoposterHealthSortValue(
				stateMap.get(b.account.id)?.account_health_score,
			) -
			autoposterHealthSortValue(
				stateMap.get(a.account.id)?.account_health_score,
			);
		if (scoreDelta !== 0) return scoreDelta;
		const performanceRank = (state: AccountAutoposterState | undefined) => {
			if (!state) return 0;
			const modeBoost: Record<string, number> = {
				scale: 300,
				clone_winners: 150,
				test_market: 50,
				reduce: -150,
				suppress: -1000,
			};
			return (
				(modeBoost[state.recommended_strategy_mode || ""] || 0) +
				Number(state.avg_views_24h_30d ?? state.last_14d_avg_views ?? 0) +
				Number(state.posts_above_100_views_rate ?? 0)
			);
		};
		const performanceDelta =
			performanceRank(stateMap.get(b.account.id)) -
			performanceRank(stateMap.get(a.account.id));
		if (performanceDelta !== 0) return performanceDelta;
		const aWarming =
			stateMap.get(a.account.id)?.status === "warming_limited" ? 0 : 1;
		const bWarming =
			stateMap.get(b.account.id)?.status === "warming_limited" ? 0 : 1;
		return aWarming - bWarming;
	});

	if (eligibleAccounts.length === 0) {
		logger.warn("[accountPlanner] No eligible accounts after checks", {
			groupId,
			totalAccounts: active.length,
			skipped: skippedAccounts.map((s) => `${s.reason}(@${s.username})`),
		});
		return {
			slots: [],
			skipped: skippedAccounts,
			totalAccounts: active.length,
			eligibleCount: 0,
		};
	}

	// 7. Get current round-robin index from group state
	const { data: groupState } = await db()
		.from("auto_post_group_state")
		.select("current_account_index")
		.eq("workspace_id", workspaceId)
		.eq("group_id", groupId)
		.maybeSingle();

	let rrIndex = groupState?.current_account_index ?? 0;

	// 8. Round-robin assignment — distribute slots across eligible accounts
	// Respects posts_per_account_per_day cap at plan time, with follower tier limits
	const groupDailyCap = gc.posts_per_account_per_day;
	const accountSlotCounts = new Map<string, number>();
	const slots: PlannedSlot[] = [];

	for (let i = 0; i < count; i++) {
		// Try each eligible account starting from current round-robin position
		let assigned = false;
		for (let attempt = 0; attempt < eligibleAccounts.length; attempt++) {
			const idx = (rrIndex + attempt) % eligibleAccounts.length;
			const { account, merged } = eligibleAccounts[idx]!;

			// Effective daily cap = min(randomized group cap, follower/cohort tier cap, health bonus)
			const tierCap = getFollowerTierCap(account);
			const acctState = stateMap.get(account.id);
			const avgViews = acctState?.last_14d_avg_views ?? 0;
			const accountDailyMax = merged.posts_per_account_per_day ?? groupDailyCap;
			const accountDailyMin = Math.min(minPostsPerDay, accountDailyMax);
			const accountDateKey = getDateKeyInTimezone(now, merged.timezone);
			// Randomized daily cap per account (deterministic for the day)
			const randomizedCap = getDailyPostCount(
				account.id,
				accountDateKey,
				accountDailyMin,
				accountDailyMax,
			);
			const healthCap =
				avgViews > 50 ? Math.max(randomizedCap, 2) : randomizedCap;
			const performanceCap =
				typeof acctState?.recommended_posts_per_day === "number"
					? Math.max(0, Math.floor(acctState.recommended_posts_per_day))
					: null;
			const warmupPolicy = restartWarmupPolicyFromState(acctState);
			const isProbeSlot = probeAccountIds.has(account.id);
			const strategyCap = isProbeSlot
				? Math.min(healthCap, 1)
				: acctState?.recommended_strategy_mode === "reduce"
					? Math.min(healthCap, 1)
					: performanceCap != null
						? Math.min(healthCap, performanceCap)
						: healthCap;
			const warmupCap =
				typeof warmupPolicy?.allowedPostsPerDay === "number"
					? Math.max(0, warmupPolicy.allowedPostsPerDay)
					: null;
			const dailyCapBase =
				acctState?.status === "warming_limited"
					? Math.min(strategyCap, tierCap, 1)
					: Math.min(strategyCap, tierCap);
			const dailyCap =
				warmupCap !== null ? Math.min(dailyCapBase, warmupCap) : dailyCapBase;

			// Check daily cap: already used capacity + planned in this batch.
			const alreadyUsed = countUsedPostingCapacityForAccount({
				accountId: account.id,
				timezone: merged.timezone,
				now,
				rows: capacityRows,
			});
			const plannedForAccount =
				(accountSlotCounts.get(account.id) ?? 0) + alreadyUsed;
			if (plannedForAccount >= dailyCap) continue;

			slots.push({
				accountId: account.id,
				roundRobinIndex: rrIndex + attempt,
				timezone: merged.timezone,
				activeHoursStart: merged.active_hours_start,
				activeHoursEnd: merged.active_hours_end,
				minIntervalMinutes: isProbeSlot
					? Math.max(merged.min_interval_minutes ?? 0, 1440)
					: merged.min_interval_minutes,
				...(isProbeSlot ? { isProbe: true } : {}),
				...(warmupPolicy ? { warmupPolicy } : {}),
			});
			accountSlotCounts.set(account.id, plannedForAccount + 1);
			rrIndex = (rrIndex + attempt + 1) % eligibleAccounts.length;
			assigned = true;
			break;
		}

		if (!assigned) {
			// All eligible accounts hit their daily cap — stop planning
			logger.info(
				"[accountPlanner] All accounts at daily cap (tier-aware), stopping",
				{
					groupId,
					planned: slots.length,
					requested: count,
					groupDailyCap,
				},
			);
			break;
		}
	}

	// 9. Update group state with new round-robin index
	if (slots.length > 0) {
		const lastSlot = slots[slots.length - 1];
		await db()
			.from("auto_post_group_state")
			.upsert(
				{
					workspace_id: workspaceId,
					group_id: groupId,
					current_account_index: lastSlot!.roundRobinIndex + 1,
					updated_at: now.toISOString(),
				} as Record<string, unknown>,
				{ onConflict: "workspace_id,group_id" },
			);
	}

	logger.info("[accountPlanner] Planned account slots", {
		groupId,
		requested: count,
		planned: slots.length,
		eligibleAccounts: eligibleAccounts.length,
		totalAccounts: active.length,
		skipped:
			skippedAccounts.length > 0
				? skippedAccounts.map((s) => `${s.reason}(@${s.username})`)
				: undefined,
		distribution: Object.fromEntries(accountSlotCounts),
	});

	return {
		slots,
		skipped: skippedAccounts,
		totalAccounts: active.length,
		eligibleCount: eligibleAccounts.length,
	};
}
