// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Account Health Scorer — computes 0-100 health score per account
 *
 * Runs daily via health-monitor cron (every 4 hours, but scoring runs once/day).
 *
 * Scoring breakdown:
 *   - Views per post (7d avg)    40% — 0 views = 0, 50+ = 100
 *   - Reply rate (7d)            20% — 0% = 0, 2%+ = 100
 *   - Follower growth (7d)       15% — 0 = 0, 5+/day = 100
 *   - Days since last 0-view     10% — 0 days = 0, 7+ = 100
 *   - Account age                 5% — <7d = 20, 7-30 = 60, 30+ = 100
 *   - Shadowban signals          10% — 0 views + engagement synced = instant 0
 *
 * Health tiers drive dynamic post allocation:
 *   80-100 (star):       5 posts/day
 *   50-79 (healthy):     3 posts/day
 *   20-49 (struggling):  2 posts/day
 *   0-19 (dead):         1 post/day
 *
 * Auto-disable: 0 health for 7 consecutive days → disable
 * Recovery: Every 14 days, re-enable for 48h test (1 post/day)
 */

import { AlertLevel, alert } from "../alerting.js";
import { logger, serializeError } from "../logger.js";
import { getSupabase } from "../supabase.js";

// biome-ignore lint/suspicious/noExplicitAny: new columns not in generated types
const db = (): any => getSupabase();

const LOG_PREFIX = "[account-health-scorer]";

// ============================================================================
// Tier Definitions
// ============================================================================

interface HealthTier {
	name: string;
	minScore: number;
	postsPerDay: number;
}

const TIERS: HealthTier[] = [
	{ name: "star", minScore: 80, postsPerDay: 5 },
	{ name: "healthy", minScore: 50, postsPerDay: 3 },
	{ name: "struggling", minScore: 20, postsPerDay: 2 },
	{ name: "dead", minScore: 0, postsPerDay: 1 },
];

function getTier(score: number): HealthTier {
	for (const tier of TIERS) {
		if (score >= tier.minScore) return tier;
	}
	return TIERS[TIERS.length - 1]!;
}

// ============================================================================
// Configuration
// ============================================================================

const AUTO_DISABLE_THRESHOLD_DAYS = 7;
const RECOVERY_INTERVAL_DAYS = 14;

// ============================================================================
// Types
// ============================================================================

interface AccountWithMetrics {
	id: string;
	user_id: string;
	username: string;
	group_id: string | null;
	is_active: boolean;
	created_at: string;
	followers_count: number;
}

interface HealthResult {
	accountsScored: number;
	tiersChanged: number;
	autoDisabled: number;
	recoveryStarted: number;
}

// ============================================================================
// Main Orchestrator
// ============================================================================

export async function computeAccountHealthScores(): Promise<number> {
	const result: HealthResult = {
		accountsScored: 0,
		tiersChanged: 0,
		autoDisabled: 0,
		recoveryStarted: 0,
	};

	try {
		// Fetch all Threads accounts
		const { data: accounts, error: accError } = await db()
			.from("accounts")
			.select(
				"id, user_id, username, group_id, is_active, created_at, followers_count",
			)
			.order("user_id");

		if (accError || !accounts) {
			logger.error(`${LOG_PREFIX} Failed to fetch accounts`, {
				error: String(accError),
			});
			return 0;
		}

		logger.info(`${LOG_PREFIX} Scoring ${accounts.length} accounts`);

		// Process in batches by user
		const byUser = new Map<string, AccountWithMetrics[]>();
		for (const acc of accounts) {
			if (!byUser.has(acc.user_id)) byUser.set(acc.user_id, []);
			byUser.get(acc.user_id)?.push(acc);
		}

		for (const [userId, userAccounts] of byUser) {
			try {
				await scoreUserAccounts(userId, userAccounts, result);
			} catch (err) {
				logger.error(`${LOG_PREFIX} Failed to score user`, {
					userId,
					error: serializeError(err),
				});
			}
		}

		// Handle auto-disable and recovery
		await processAutoDisableAndRecovery(result);

		logger.info(`${LOG_PREFIX} Complete`, { ...result });

		// Discord alert if significant changes
		if (result.autoDisabled > 0 || result.recoveryStarted > 0) {
			await alert(AlertLevel.INFO, "Account health update", {
				scored: String(result.accountsScored),
				tiersChanged: String(result.tiersChanged),
				autoDisabled: String(result.autoDisabled),
				recoveryStarted: String(result.recoveryStarted),
			});
		}
	} catch (err) {
		logger.error(`${LOG_PREFIX} Fatal error`, { error: serializeError(err) });
	}

	return result.accountsScored;
}

// ============================================================================
// Score Calculation
// ============================================================================

async function scoreUserAccounts(
	userId: string,
	accounts: AccountWithMetrics[],
	result: HealthResult,
): Promise<void> {
	const accountIds = accounts.map((a) => a.id);
	const now = new Date();
	const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);

	// Fetch 7-day post metrics for all accounts
	const { data: recentPosts } = await db()
		.from("posts")
		.select(
			"account_id, views_count, replies_count, published_at, engagement_fetched_at",
		)
		.in("account_id", accountIds)
		.eq("platform", "threads")
		.eq("status", "published")
		.gte("published_at", sevenDaysAgo.toISOString());

	// Group posts by account
	const postsByAccount = new Map<string, typeof recentPosts>();
	for (const post of recentPosts || []) {
		if (!postsByAccount.has(post.account_id))
			postsByAccount.set(post.account_id, []);
		postsByAccount.get(post.account_id)?.push(post);
	}

	// Resolve workspace
	const { data: ws } = await db()
		.from("workspaces")
		.select("id")
		.eq("owner_id", userId)
		.maybeSingle();
	const workspaceId = ws?.id || "";

	// Fetch previous health snapshots for delta comparison
	const { data: prevSnapshots } = await db()
		.from("account_health_snapshots")
		.select("account_id, health_score, health_tier, consecutive_dead_days")
		.eq("account_table", "accounts")
		.in("account_id", accountIds)
		.eq("period_days", 7);

	const prevMap = new Map<
		string,
		{ health_score: number; health_tier: string; consecutive_dead_days: number }
	>();
	for (const snap of prevSnapshots || []) {
		prevMap.set(snap.account_id, snap);
	}

	// Score each account
	for (const account of accounts) {
		const posts = postsByAccount.get(account.id) || [];
		const syncedPosts = posts.filter(
			(p: Record<string, unknown>) => p.engagement_fetched_at,
		);

		// --- Views per post (40%) ---
		let viewsScore = 0;
		if (syncedPosts.length > 0) {
			const totalViews = syncedPosts.reduce(
				(sum: number, p: Record<string, unknown>) =>
					sum + ((p.views_count as number) || 0),
				0,
			);
			const avgViews = totalViews / syncedPosts.length;
			viewsScore = Math.min(100, (avgViews / 50) * 100);
		}

		// --- Reply rate (20%) ---
		let replyScore = 0;
		if (syncedPosts.length > 0) {
			const totalViews = syncedPosts.reduce(
				(sum: number, p: Record<string, unknown>) =>
					sum + ((p.views_count as number) || 0),
				0,
			);
			const totalReplies = syncedPosts.reduce(
				(sum: number, p: Record<string, unknown>) =>
					sum + ((p.replies_count as number) || 0),
				0,
			);
			const replyRate = totalViews > 0 ? (totalReplies / totalViews) * 100 : 0;
			replyScore = Math.min(100, (replyRate / 2) * 100);
		}

		// --- Follower growth (15%) ---
		// Compute actual 7-day follower delta from account_analytics
		let followerGrowth7d = 0;
		try {
			const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
				.toISOString()
				.split("T")[0]!;
			const { data: analyticsRows } = await db()
				.from("account_analytics")
				.select("followers_count, date")
				.eq("account_id", account.id)
				.gte("date", sevenDaysAgo)
				.order("date", { ascending: true })
				.limit(2);
			if (analyticsRows && analyticsRows.length >= 2) {
				const oldest =
					((analyticsRows[0] as Record<string, unknown>)
						.followers_count as number) || 0;
				const newest =
					((analyticsRows[analyticsRows.length - 1] as Record<string, unknown>)
						.followers_count as number) || 0;
				followerGrowth7d = Math.max(0, newest - oldest);
			}
		} catch {
			// Fallback to 0 if no analytics data available
		}
		const growthScore = Math.min(100, (followerGrowth7d / 5) * 100);

		// --- Days since last 0-view post (10%) ---
		let daysSinceZeroView = 999;
		const zeroViewPosts = syncedPosts
			.filter((p: Record<string, unknown>) => (p.views_count as number) === 0)
			.sort(
				(a: Record<string, unknown>, b: Record<string, unknown>) =>
					new Date(b.published_at as string).getTime() -
					new Date(a.published_at as string).getTime(),
			);

		if (zeroViewPosts.length > 0) {
			const lastZero = new Date(zeroViewPosts[0].published_at as string);
			daysSinceZeroView = Math.floor(
				(now.getTime() - lastZero.getTime()) / (24 * 60 * 60 * 1000),
			);
		}
		const zeroViewScore = Math.min(100, (daysSinceZeroView / 7) * 100);

		// --- Account age (5%) ---
		const ageMs = now.getTime() - new Date(account.created_at).getTime();
		const ageDays = Math.floor(ageMs / (24 * 60 * 60 * 1000));
		let ageScore = 100;
		if (ageDays < 7) ageScore = 20;
		else if (ageDays < 30) ageScore = 60;

		// --- Shadowban signals (10%) ---
		let shadowbanScore = 100;
		const isShadowbanned =
			syncedPosts.length >= 5 &&
			syncedPosts.every(
				(p: Record<string, unknown>) => ((p.views_count as number) || 0) === 0,
			);
		if (isShadowbanned) shadowbanScore = 0;

		// --- Composite score ---
		const healthScore = Math.round(
			viewsScore * 0.4 +
				replyScore * 0.2 +
				growthScore * 0.15 +
				zeroViewScore * 0.1 +
				ageScore * 0.05 +
				shadowbanScore * 0.1,
		);

		const tier = getTier(healthScore);
		const prev = prevMap.get(account.id);
		const prevTier = prev?.health_tier || "healthy";
		const tierChanged = prevTier !== tier.name;

		// Consecutive dead days tracking
		let consecutiveDeadDays = prev?.consecutive_dead_days || 0;
		if (healthScore === 0) {
			consecutiveDeadDays++;
		} else {
			consecutiveDeadDays = 0;
		}

		const avgViews =
			syncedPosts.length > 0
				? syncedPosts.reduce(
						(sum: number, p: Record<string, unknown>) =>
							sum + ((p.views_count as number) || 0),
						0,
					) / syncedPosts.length
				: 0;

		const totalViews = syncedPosts.reduce(
			(sum: number, p: Record<string, unknown>) =>
				sum + ((p.views_count as number) || 0),
			0,
		);
		const totalReplies = syncedPosts.reduce(
			(sum: number, p: Record<string, unknown>) =>
				sum + ((p.replies_count as number) || 0),
			0,
		);
		const replyRate = totalViews > 0 ? totalReplies / totalViews : 0;

		// Upsert health snapshot
		const { error: upsertError } = await db()
			.from("account_health_snapshots")
			.upsert(
				{
					user_id: userId,
					workspace_id: workspaceId,
					account_table: "accounts",
					account_id: account.id,
					account_name: account.username,
					platform: "threads",
					period_days: 7,
					health_score: healthScore,
					health_tier: tier.name,
					posts_per_day_override: tier.postsPerDay,
					views_per_post_7d: avgViews,
					reply_rate_7d: replyRate,
					follower_growth_7d: followerGrowth7d,
					days_since_zero_views: daysSinceZeroView,
					account_age_days: ageDays,
					is_shadowbanned: isShadowbanned,
					consecutive_dead_days: consecutiveDeadDays,
					followers_current: account.followers_count || 0,
					reach_3day: 0, // Will be populated by separate reach calc
					computed_at: now.toISOString(),
				},
				{ onConflict: "user_id,account_table,account_id,period_days" },
			);

		if (upsertError) {
			logger.error(`${LOG_PREFIX} Upsert failed`, {
				accountId: account.id,
				error: String(upsertError),
			});
			continue;
		}

		result.accountsScored++;
		if (tierChanged) {
			result.tiersChanged++;
			logger.info(`${LOG_PREFIX} Tier changed`, {
				account: account.username,
				from: prevTier,
				to: tier.name,
				score: healthScore,
			});
		}

		// Health scoring is for reporting only — never gates or throttles posting.
	}
}

// ============================================================================
// Health-Based Interval Overrides
// ============================================================================

// ============================================================================
// Auto-Disable & Recovery
// ============================================================================

async function processAutoDisableAndRecovery(
	result: HealthResult,
): Promise<void> {
	const now = new Date();

	// Auto-disable: accounts with 0 health for 7+ consecutive days
	const { data: deadAccounts } = await db()
		.from("account_health_snapshots")
		.select("account_id, user_id, account_name, consecutive_dead_days")
		.eq("account_table", "accounts")
		.gte("consecutive_dead_days", AUTO_DISABLE_THRESHOLD_DAYS)
		.or("auto_disabled.is.null,auto_disabled.eq.false")
		.eq("period_days", 7);

	for (const dead of deadAccounts || []) {
		// Set auto_disabled flag
		await db()
			.from("account_health_snapshots")
			.update({
				auto_disabled: true,
				auto_disabled_at: now.toISOString(),
			})
			.eq("account_id", dead.account_id)
			.eq("period_days", 7);

		// Disable the actual account
		await db()
			.from("accounts")
			.update({
				is_active: false,
				status: "deactivated",
				updated_at: new Date().toISOString(),
			})
			.eq("id", dead.account_id);

		result.autoDisabled++;
		logger.warn(`${LOG_PREFIX} Auto-disabled dead account`, {
			account: dead.account_name,
			deadDays: dead.consecutive_dead_days,
		});
	}

	// Recovery: re-enable disabled accounts every 14 days for 48h test
	const recoveryThreshold = new Date(
		now.getTime() - RECOVERY_INTERVAL_DAYS * 24 * 60 * 60 * 1000,
	);

	const { data: recoverable } = await db()
		.from("account_health_snapshots")
		.select(
			"account_id, user_id, account_name, last_recovery_attempt, recovery_attempts",
		)
		.eq("account_table", "accounts")
		.eq("auto_disabled", true)
		.eq("period_days", 7)
		.or(
			`last_recovery_attempt.is.null,last_recovery_attempt.lte.${recoveryThreshold.toISOString()}`,
		);

	for (const acc of recoverable || []) {
		// Re-enable the account
		await db()
			.from("accounts")
			.update({
				is_active: true,
				status: "active",
				updated_at: new Date().toISOString(),
			})
			.eq("id", acc.account_id);

		// Update recovery tracking
		await db()
			.from("account_health_snapshots")
			.update({
				last_recovery_attempt: now.toISOString(),
				recovery_attempts: (acc.recovery_attempts || 0) + 1,
				posts_per_day_override: 1, // 1 post/day during recovery test
			})
			.eq("account_id", acc.account_id)
			.eq("period_days", 7);

		result.recoveryStarted++;
		logger.info(`${LOG_PREFIX} Recovery test started`, {
			account: acc.account_name,
			attempt: (acc.recovery_attempts || 0) + 1,
		});
	}
}

// ============================================================================
// Dynamic Allocation — called by auto-post-worker before publishing
// ============================================================================

/**
 * Get the health-based posts-per-day allocation for an account.
 * Returns the override value, or null if no health data exists.
 */
export async function getHealthBasedAllocation(
	accountId: string,
): Promise<number | null> {
	const { data } = await db()
		.from("account_health_snapshots")
		.select("posts_per_day_override, health_tier")
		.eq("account_table", "accounts")
		.eq("account_id", accountId)
		.eq("period_days", 7)
		.maybeSingle();

	return data?.posts_per_day_override || null;
}

/**
 * Get health tier for content quality routing.
 * Star accounts get first pick from the queue.
 */
export async function getHealthTier(accountId: string): Promise<string | null> {
	const { data } = await db()
		.from("account_health_snapshots")
		.select("health_tier")
		.eq("account_table", "accounts")
		.eq("account_id", accountId)
		.eq("period_days", 7)
		.maybeSingle();

	return data?.health_tier || null;
}
