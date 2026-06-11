// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * State Evaluator — Unified account state evaluation.
 *
 * Phase 2 of the auto-poster simplification plan.
 * Consolidates the 7 checks from smartTiming.ts + accountPlanner.ts
 * into a single function that returns one status per account.
 *
 * Evaluation priority (highest wins):
 *   inactive > suppressed > suppressed_probe > view_cooldown >
 *   viral_suppress > flop_delay > shadowban_throttle >
 *   warming_silent > warming_limited > active
 *
 * This function is PURE w.r.t. external state — it takes all the data
 * it needs as arguments and returns a result. No Redis reads, no DB calls.
 * The cron endpoint handles data loading and DB writes.
 */

import type { AccountAutoposterStatus } from "./accountState.js";

// ============================================================================
// Input types — everything the evaluator needs, pre-fetched by the cron
// ============================================================================

export interface AccountEvalInput {
	account_id: string;
	group_id: string;
	workspace_id: string;
	username: string;
	/** From accounts table */
	is_active: boolean;
	is_retired: boolean;
	needs_reauth: boolean;
	is_shadowbanned: boolean;
	created_at: string | null;
	followers_count: number | null;
	/** Post history stats (pre-computed by cron) */
	posts_last_30d: PostViewRecord[];
	posts_last_14d: PostViewRecord[];
	/** Recent 3 posts for view decline check */
	recent_3_posts: PostViewRecord[];
	/** Recent posts in last 2h for viral check */
	posts_last_2h: PostWithVelocity[];
	/** Most recent post >2h old for flop check */
	latest_post_over_2h: PostViewRecord | null;
	/** Published posts count (for warming gate) */
	total_published_posts: number;
	/** Posts published in last 48h (for shadowban throttle) */
	posts_last_48h: number;
}

export interface PostViewRecord {
	id: string;
	views_count: number;
	published_at: string;
}

export interface PostWithVelocity {
	id: string;
	views_count: number;
	published_at: string;
	/** Views per hour since publish */
	velocity: number;
}

export interface EvalResult {
	status: AccountAutoposterStatus;
	status_reason: string;
	blocked_until: string | null;
	flop_proven_remaining: number;
	probe_posts_remaining: number;
	warming_posts_today: number;
	last_14d_avg_views: number | null;
	median_30d_views: number | null;
	max_30d_views: number | null;
	pct_under_5_views: number | null;
	/** Post ID that triggered the current flop_delay — prevents re-extending for same post */
	last_flop_post_id: string | null;
	/** When the current flop_delay was first triggered — enables max duration cap */
	flop_triggered_at: string | null;
	/** How many probe cycles completed (each cycle = 3 posts). After 2 cycles → permanently suppressed */
	probe_cycles_completed: number;
	/** Consecutive flop_delay triggers. After 3 → escalate to content_experiment or suppressed_probe */
	consecutive_flops: number;
	/** Whether to auto-retire this account (set by terminal suppression) */
	should_retire: boolean;
}

// ============================================================================
// Thresholds — same as smartTiming.ts, centralized here
// ============================================================================

/** Days since account connection for warming phases */
const WARMING_SILENT_DAYS = 3;
const WARMING_LIMITED_DAYS = 10;
/** Suppression: median ≤2, max <20, >90% under 5 */
const SUPPRESSION_MEDIAN_MAX = 2;
const SUPPRESSION_MAX_VIEWS = 20;
const SUPPRESSION_PCT_THRESHOLD = 90;
const SUPPRESSION_MIN_POSTS = 10;
/** Suppression: initial 3-day pause (was 14d — too long, accounts can't recover) */
const SUPPRESSION_PAUSE_DAYS = 3;
/** Suppression: probe post count */
const SUPPRESSION_PROBE_COUNT = 3;
/** Suppression: max probe cycles before giving up (3 posts × 2 cycles = 6 total probe posts) */
const SUPPRESSION_MAX_PROBE_CYCLES = 2;

// ============================================================================
// Core evaluation function
// ============================================================================

/**
 * Evaluate a single account's autoposter state.
 *
 * Returns the highest-priority status that applies.
 * All data is passed in — no external calls.
 */
export function evaluateAccountState(
	input: AccountEvalInput,
	now: Date = new Date(),
	/** Previous state for continuity (probe counter, flop counter, flop post tracking) */
	previousState?:
		| (Omit<Partial<EvalResult>, "status_reason"> & {
				status_reason?: string | null | undefined;
		  })
		| null,
): EvalResult {
	// Pre-compute performance stats used across multiple checks
	const stats = computePerformanceStats(input);

	// Priority 1: Inactive (retired, needs reauth, deactivated)
	if (input.is_retired || input.needs_reauth || !input.is_active) {
		const reasons: string[] = [];
		if (input.is_retired) reasons.push("retired");
		if (input.needs_reauth) reasons.push("needs reauth");
		if (!input.is_active) reasons.push("deactivated");
		return result("inactive", reasons.join(", "), null, stats);
	}

	// Priority 2: Suppressed (near-zero distribution)
	const suppression = checkSuppression(input, stats, now);
	if (suppression) {
		const prevCycles = previousState?.probe_cycles_completed ?? 0;
		const previousBlockedUntil = previousState?.blocked_until
			? new Date(previousState.blocked_until).getTime()
			: null;
		const suppressionPauseElapsed =
			previousState?.status === "suppressed" &&
			previousBlockedUntil !== null &&
			Number.isFinite(previousBlockedUntil) &&
			previousBlockedUntil <= now.getTime();

		// Terminal state: after N failed probe cycles, auto-retire the account
		if (prevCycles >= SUPPRESSION_MAX_PROBE_CYCLES) {
			return {
				...result(
					"inactive",
					`Auto-retired: ${prevCycles} probe cycles failed — account shadowbanned`,
					null,
					stats,
				),
				probe_cycles_completed: prevCycles,
				should_retire: true,
			};
		}

		if (suppressionPauseElapsed) {
			return {
				...result(
					"suppressed_probe",
					`Suppression pause elapsed — probing with ${SUPPRESSION_PROBE_COUNT} conservative winner-clone text post(s)`,
					null,
					stats,
				),
				probe_posts_remaining:
					previousState?.probe_posts_remaining &&
					previousState.probe_posts_remaining > 0
						? previousState.probe_posts_remaining
						: SUPPRESSION_PROBE_COUNT,
				probe_cycles_completed: prevCycles,
			};
		}

		if (
			previousState?.status === "suppressed_probe" &&
			(previousState.probe_posts_remaining ?? 0) > 0
		) {
			const probePostsRemaining =
				previousState.probe_posts_remaining ?? SUPPRESSION_PROBE_COUNT;
			return {
				...result(
					"suppressed_probe",
					`Probe cycle active — ${probePostsRemaining} probe post(s) remaining`,
					null,
					stats,
				),
				probe_posts_remaining: probePostsRemaining,
				probe_cycles_completed: prevCycles,
			};
		}

		// Track probe cycle completion: if was probing and now re-suppressed, increment cycle count
		const newCycles =
			previousState?.status === "suppressed_probe" &&
			suppression.status === "suppressed"
				? prevCycles + 1
				: prevCycles;

		// If previously in probe mode, preserve probe counter
		if (
			previousState?.status === "suppressed_probe" ||
			suppression.status === "suppressed_probe"
		) {
			return {
				...result(
					suppression.status,
					suppression.reason,
					suppression.blocked_until,
					stats,
				),
				probe_posts_remaining:
					suppression.probe_posts_remaining ??
					previousState?.probe_posts_remaining ??
					SUPPRESSION_PROBE_COUNT,
				probe_cycles_completed: newCycles,
			};
		}
		return {
			...result(
				suppression.status,
				suppression.reason,
				suppression.blocked_until,
				stats,
			),
			probe_cycles_completed: newCycles,
		};
	}

	// Priority 3: View decline cooldown — REMOVED
	// Blocked accounts for 12h after 3 recent posts dipped below 40% of baseline.
	// Same problem as flop_delay — punishes normal Threads variance on healthy accounts.

	// Priority 4: Viral suppression — REMOVED
	// Blocked accounts for 3-6h when a post was getting high velocity (>5x baseline).
	// This was actively harmful — stopping an account while it's going viral is the
	// opposite of what you want. Let viral posts ride.

	// Priority 5: Flop delay — REMOVED
	// Single-post flops are normal Threads variance. Blocking accounts for 48-72h
	// after one bad post killed 20% of the fleet. The suppression check (Priority 2)
	// already catches accounts with structurally bad distribution (median ≤2, >90% under 5).

	// Priority 6: Shadowban throttle (1 post/48h)
	if (input.is_shadowbanned && input.posts_last_48h > 0) {
		const blocked_until = new Date(
			now.getTime() + 48 * 60 * 60 * 1000,
		).toISOString();
		return result(
			"shadowban_throttle",
			`Shadowbanned — ${input.posts_last_48h} post(s) in last 48h, max 1 allowed`,
			blocked_until,
			stats,
		);
	}

	// Priority 7-8: Warming phases
	const warming = checkWarming(input, now);
	if (warming) {
		return result(warming.status, warming.reason, null, stats);
	}

	// All clear
	return result("active", "All checks passed", null, stats);
}

// ============================================================================
// Individual check functions (pure, no side effects)
// ============================================================================

interface CheckResult {
	status: AccountAutoposterStatus;
	reason: string;
	blocked_until: string | null;
	probe_posts_remaining?: number | undefined;
	proven_remaining?: number | undefined;
}

function checkSuppression(
	input: AccountEvalInput,
	stats: PerformanceStats,
	now: Date,
): CheckResult | null {
	const posts30d = input.posts_last_30d;
	if (posts30d.length < SUPPRESSION_MIN_POSTS) return null;

	const { medianViews, maxViews, pctUnder5 } = stats;
	if (medianViews === null || maxViews === null || pctUnder5 === null)
		return null;

	if (
		medianViews > SUPPRESSION_MEDIAN_MAX ||
		maxViews >= SUPPRESSION_MAX_VIEWS ||
		pctUnder5 <= SUPPRESSION_PCT_THRESHOLD
	) {
		return null;
	}

	// Account is suppressed
	const pauseUntil = new Date(
		now.getTime() + SUPPRESSION_PAUSE_DAYS * 24 * 60 * 60 * 1000,
	).toISOString();

	return {
		status: "suppressed",
		reason: `Near-zero distribution: median ${medianViews} views, max ${maxViews}, ${pctUnder5}% under 5 views (${posts30d.length} posts)`,
		blocked_until: pauseUntil,
		probe_posts_remaining: SUPPRESSION_PROBE_COUNT,
	};
}

function checkWarming(input: AccountEvalInput, now: Date): CheckResult | null {
	if (!input.created_at) return null;

	const connectedDate = new Date(input.created_at);
	if (Number.isNaN(connectedDate.getTime())) return null;

	const daysSinceConnection =
		(now.getTime() - connectedDate.getTime()) / (1000 * 60 * 60 * 24);

	// Silent phase (0-3 days)
	if (daysSinceConnection < WARMING_SILENT_DAYS) {
		return {
			status: "warming_silent",
			reason: `Account ${Math.round(daysSinceConnection * 10) / 10}d old — silent phase (0-${WARMING_SILENT_DAYS}d)`,
			blocked_until: new Date(
				connectedDate.getTime() + WARMING_SILENT_DAYS * 24 * 60 * 60 * 1000,
			).toISOString(),
		};
	}

	// Limited phase (3-10 days, or gate not met)
	if (daysSinceConnection < WARMING_LIMITED_DAYS) {
		return {
			status: "warming_limited",
			reason: `Account ${Math.round(daysSinceConnection)}d old — limited phase (${WARMING_SILENT_DAYS}-${WARMING_LIMITED_DAYS}d), max 1 post/day`,
			blocked_until: null, // Not time-blocked, just rate-limited
		};
	}

	// Past the limited phase = warming complete. The automation gate (total_published_posts
	// < 10) was removed because the count query hits Supabase's 1000-row default limit
	// on large fleets, causing established accounts (25-89 posts) to show as 0 posts.
	// Accounts older than 10 days have had enough organic activity to be safe.
	return null; // Warming complete
}

// ============================================================================
// Performance stats (computed once, reused across checks)
// ============================================================================

interface PerformanceStats {
	last14dAvgViews: number | null;
	medianViews: number | null;
	maxViews: number | null;
	pctUnder5: number | null;
}

function computePerformanceStats(input: AccountEvalInput): PerformanceStats {
	const posts14d = input.posts_last_14d;
	const posts30d = input.posts_last_30d;

	const last14dAvgViews =
		posts14d.length > 0
			? posts14d.reduce((s, p) => s + (p.views_count ?? 0), 0) / posts14d.length
			: null;

	if (posts30d.length === 0) {
		return {
			last14dAvgViews,
			medianViews: null,
			maxViews: null,
			pctUnder5: null,
		};
	}

	const views = posts30d.map((p) => p.views_count ?? 0).sort((a, b) => a - b);
	const medianViews = views[Math.floor(views.length / 2)];
	const maxViews = views[views.length - 1];
	const under5 = views.filter((v) => v <= 5).length;
	const pctUnder5 = Math.round((under5 / views.length) * 100);

	return {
		last14dAvgViews,
		medianViews: medianViews!,
		maxViews: maxViews!,
		pctUnder5,
	};
}

// ============================================================================
// Helper to build EvalResult
// ============================================================================

function result(
	status: AccountAutoposterStatus,
	reason: string,
	blocked_until: string | null,
	stats: PerformanceStats,
): EvalResult {
	return {
		status,
		status_reason: reason,
		blocked_until,
		flop_proven_remaining: 0,
		probe_posts_remaining: 0,
		warming_posts_today: 0,
		last_14d_avg_views:
			stats.last14dAvgViews !== null ? Math.round(stats.last14dAvgViews) : null,
		median_30d_views: stats.medianViews,
		max_30d_views: stats.maxViews,
		pct_under_5_views: stats.pctUnder5,
		last_flop_post_id: null,
		flop_triggered_at: null,
		probe_cycles_completed: 0,
		consecutive_flops: 0,
		should_retire: false,
	};
}
