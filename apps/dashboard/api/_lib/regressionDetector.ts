// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Regression Detector for Quick Wins
 *
 * After a Quick Win is marked "solved", monitors the target metric for 21 days.
 * If the metric regresses >15% from post-optimization level for 7+ consecutive days,
 * marks the recommendation as "regressed" and optionally re-queues a new rec.
 */

import { createNotification } from "./createNotification.js";
import { logger } from "./logger.js";
import { getRedis } from "./redis.js";
import { getSupabase, getSupabaseAny } from "./supabase.js";

const db = () => getSupabase();
const dbAny = () => getSupabaseAny();

export interface RegressionEvent {
	accountId: string;
	platform: string;
	recId: string;
	category: string;
	baselineValue: number;
	postOptValue: number;
	currentValue: number;
	regressionPct: number;
	consecutiveDays: number;
	status: "regressed" | "faded";
}

/**
 * Check all solved baselines for regression.
 * Called from the quickwin-monitor cron.
 */
export async function checkRegressions(): Promise<RegressionEvent[]> {
	const events: RegressionEvent[] = [];

	try {
		// Get all baselines that were marked solved (threshold reached)
		const { data: baselines } = await db()
			.from("recommendation_baselines")
			.select(
				"account_id, platform, rec_id, category, baseline_value, post_opt_value, solved_at",
			)
			.eq("solved", true)
			.is("regression_expired", null); // not yet expired

		if (!baselines || baselines.length === 0) return events;

		for (const baseline of baselines) {
			try {
				const event = await checkSingleRegression(
					baseline as unknown as BaselineRow,
				);
				if (event) events.push(event);
			} catch (err) {
				logger.warn("[regression] Check failed for baseline", {
					recId: baseline.rec_id,
					error: String(err),
				});
			}
		}
	} catch (err) {
		logger.error("[regression] Fatal error in checkRegressions", {
			error: String(err),
		});
	}

	return events;
}

interface BaselineRow {
	account_id: string;
	platform: string;
	rec_id: string;
	category: string;
	baseline_value: number;
	post_opt_value: number;
	solved_at: string | null;
}

async function checkSingleRegression(
	baseline: BaselineRow,
): Promise<RegressionEvent | null> {
	const { account_id, platform, rec_id, category, post_opt_value, solved_at } =
		baseline;

	if (!solved_at || !post_opt_value) return null;

	const solvedDate = new Date(solved_at);
	const daysSinceSolved =
		(Date.now() - solvedDate.getTime()) / (1000 * 60 * 60 * 24);

	// Only monitor for 21 days after solving
	if (daysSinceSolved > 21) {
		// Check if still regressed after 21 days → mark as "faded"
		const redis = getRedis();
		const regKey = `rec:regression:${account_id}:${rec_id}`;
		const regDays = parseInt((await redis.get(regKey)) || "0", 10);

		if (regDays >= 7) {
			// Mark as faded — expire the monitoring and re-queue
			await db()
				.from("recommendation_baselines")
				.update({ regression_expired: true, regression_status: "faded" })
				.eq("account_id", account_id)
				.eq("platform", platform)
				.eq("rec_id", rec_id);

			await redis.del(regKey);

			return {
				accountId: account_id,
				platform,
				recId: rec_id,
				category,
				baselineValue: baseline.baseline_value,
				postOptValue: post_opt_value,
				currentValue: 0, // unknown at expiry
				regressionPct: 0,
				consecutiveDays: regDays,
				status: "faded",
			};
		}

		// 21 days passed, no regression → expire monitoring
		await db()
			.from("recommendation_baselines")
			.update({ regression_expired: true, regression_status: "stable" })
			.eq("account_id", account_id)
			.eq("platform", platform)
			.eq("rec_id", rec_id);

		return null;
	}

	// Get current metric value from recent analytics
	const currentValue = await getCurrentMetricValue(
		account_id,
		platform,
		category,
	);
	if (currentValue === null) return null;

	// Check for >15% regression from post-optimization level
	const regressionPct =
		((post_opt_value - currentValue) / post_opt_value) * 100;
	const redis = getRedis();
	const regKey = `rec:regression:${account_id}:${rec_id}`;

	if (regressionPct > 15) {
		// #703: Use atomic INCR to prevent race condition on consecutive days counter
		const newDays = await redis.incr(regKey);
		if (newDays === 1) {
			await redis.expire(regKey, 30 * 24 * 60 * 60); // 30 day TTL on first set
		}

		if (newDays >= 7) {
			// Mark as regressed
			await db()
				.from("recommendation_baselines")
				.update({
					regression_status: "regressed",
					regression_pct: Math.round(regressionPct),
					regression_detected_at: new Date().toISOString(),
				})
				.eq("account_id", account_id)
				.eq("platform", platform)
				.eq("rec_id", rec_id);

			return {
				accountId: account_id,
				platform,
				recId: rec_id,
				category,
				baselineValue: baseline.baseline_value,
				postOptValue: post_opt_value,
				currentValue,
				regressionPct: Math.round(regressionPct),
				consecutiveDays: newDays,
				status: "regressed",
			};
		}
	} else {
		// Reset consecutive days counter
		await redis.del(regKey);
	}

	return null;
}

/**
 * Get current metric value for a category from recent analytics data.
 */
async function getCurrentMetricValue(
	accountId: string,
	platform: string,
	category: string,
): Promise<number | null> {
	try {
		const postsTable = platform === "instagram" ? "instagram_posts" : "posts";
		const accountCol =
			platform === "instagram" ? "instagram_account_id" : "account_id";
		const sevenDaysAgo = new Date(
			Date.now() - 7 * 24 * 60 * 60 * 1000,
		).toISOString();

		const { data: recentPosts } = await dbAny()
			.from(postsTable)
			.select(
				"published_at, likes_count, replies_count, reposts_count, shares_count, content, views_count",
			)
			.eq(accountCol, accountId)
			.gte("published_at", sevenDaysAgo)
			.not("published_at", "is", null)
			.order("published_at", { ascending: false })
			.limit(50);

		if (!recentPosts || recentPosts.length < 3) return null;

		switch (category) {
			case "timing": {
				// Ratio of posts in best hours (simplified: use engagement-weighted hours)
				const engByHour: Record<number, { total: number; count: number }> = {};
				for (const p of recentPosts) {
					if (!p.published_at) continue;
					const hour = new Date(p.published_at).getUTCHours();
					const eng =
						(p.likes_count || 0) +
						(p.replies_count || 0) +
						(p.reposts_count || p.shares_count || 0);
					if (!engByHour[hour]) engByHour[hour] = { total: 0, count: 0 };
					engByHour[hour].total += eng;
					engByHour[hour].count++;
				}
				const hourlyAvg = Object.entries(engByHour)
					.map(([h, v]) => ({ hour: parseInt(h, 10), avg: v.total / v.count }))
					.sort((a, b) => b.avg - a.avg);
				if (hourlyAvg.length < 3) return null;
				const bestHours = new Set(hourlyAvg.slice(0, 3).map((h) => h.hour));
				const inBest = recentPosts.filter(
					(p: { published_at?: string | null | undefined }) =>
						p.published_at &&
						bestHours.has(new Date(p.published_at).getUTCHours()),
				).length;
				return inBest / recentPosts.length;
			}
			case "content": {
				// Hashtag overlap ratio
				const tagSets: string[][] = [];
				for (const p of recentPosts) {
					const text = p.content || "";
					const tags = (text.match(/#\w+/g) || []).map((t: string) =>
						t.toLowerCase(),
					);
					if (tags.length > 0) tagSets.push(tags);
				}
				if (tagSets.length < 3) return null;
				let overlap = 0;
				const totalPairs = (tagSets.length * (tagSets.length - 1)) / 2;
				for (let i = 0; i < tagSets.length; i++) {
					for (let j = i + 1; j < tagSets.length; j++) {
						const a = new Set(tagSets[i]);
						const b = new Set(tagSets[j]);
						const inter = [...a].filter((t) => b.has(t)).length;
						const union = new Set([...a, ...b]).size;
						if (union > 0 && inter / union > 0.7) overlap++;
					}
				}
				return totalPairs > 0 ? overlap / totalPairs : null;
			}
			case "frequency": {
				const now = Date.now();
				const weekCounts = [0, 0, 0, 0];
				for (const p of recentPosts) {
					if (!p.published_at) continue;
					const age = now - new Date(p.published_at).getTime();
					const wi = Math.floor(age / (7 * 24 * 60 * 60 * 1000));
					if (wi >= 0 && wi < 4) weekCounts[wi]!++;
				}
				const mean = weekCounts.reduce((a, b) => a + b, 0) / 4;
				if (mean < 1) return null;
				const variance =
					weekCounts.reduce((s, c) => s + (c - mean) ** 2, 0) / 4;
				return Math.sqrt(variance) / mean; // coefficient of variation
			}
			case "engagement": {
				const { data } = await dbAny()
					.from("reply_response_times")
					.select("avg_response_mins")
					.eq("account_id", accountId)
					.eq("platform", platform)
					.order("computed_at", { ascending: false })
					.limit(1)
					.maybeSingle();
				return data ? data.avg_response_mins / 60 : null;
			}
			default:
				return null;
		}
	} catch (err) {
		logger.debug("[regression] Failed to fetch current metric value", {
			error: String(err),
		});
		return null;
	}
}

/**
 * Check for Quick Wins actioned ~48h ago and send result nudge notifications.
 */
export async function checkResultReminders(): Promise<number> {
	let sent = 0;

	try {
		// Find dismissals with reason "already_doing" from ~48h ago that haven't been notified
		const twoDaysAgo = new Date(Date.now() - 48 * 60 * 60 * 1000);
		const threeDaysAgo = new Date(Date.now() - 72 * 60 * 60 * 1000);

		const { data: actionedRecs } = await dbAny()
			.from("recommendation_dismissals")
			.select(
				"*, recommendation_baselines!inner(title, icon, category, baseline_value, threshold)",
			)
			.eq("reason", "already_doing")
			.is("result_notified", null)
			.gte("dismissed_at", threeDaysAgo.toISOString())
			.lte("dismissed_at", twoDaysAgo.toISOString());

		if (!actionedRecs || actionedRecs.length === 0) return 0;

		for (const rec of actionedRecs) {
			try {
				// Get user timezone for quiet hours
				const { data: profile } = await db()
					.from("profiles")
					.select("timezone")
					.eq("id", rec.user_id)
					.maybeSingle();

				const tz = profile?.timezone || "UTC";
				const userHour = new Date().toLocaleString("en-US", {
					timeZone: tz,
					hour: "numeric",
					hour12: false,
				});
				const hour = parseInt(userHour, 10);

				// Respect quiet hours: 11PM - 8AM
				if (hour >= 23 || hour < 8) continue;

				// Get first post metrics since the action date
				const postsTable =
					rec.platform === "instagram" ? "instagram_posts" : "posts";
				const accountCol =
					rec.platform === "instagram" ? "instagram_account_id" : "account_id";

				const { data: recentPost } = await dbAny()
					.from(postsTable)
					.select(
						"likes_count, replies_count, reposts_count, shares_count, views_count, published_at",
					)
					.eq(accountCol, rec.account_id)
					.gte("published_at", rec.dismissed_at)
					.not("published_at", "is", null)
					.order("published_at", { ascending: true })
					.limit(1)
					.maybeSingle();

				if (!recentPost) continue;

				// Get average engagement for comparison
				const thirtyDaysAgo = new Date(
					Date.now() - 30 * 24 * 60 * 60 * 1000,
				).toISOString();
				const { data: avgPosts } = await dbAny()
					.from(postsTable)
					.select(
						"likes_count, replies_count, reposts_count, shares_count, views_count",
					)
					.eq(accountCol, rec.account_id)
					.gte("published_at", thirtyDaysAgo)
					.not("published_at", "is", null);

				if (!avgPosts || avgPosts.length < 5) continue;

				const getEng = (p: {
					likes_count?: number | null | undefined;
					replies_count?: number | null | undefined;
					reposts_count?: number | null | undefined;
					shares_count?: number | null | undefined;
				}) =>
					(p.likes_count || 0) +
					(p.replies_count || 0) +
					(p.reposts_count || p.shares_count || 0);

				const postEng = getEng(recentPost);
				const avgEng =
					avgPosts.reduce(
						(
							s: number,
							p: {
								likes_count?: number | null | undefined;
								replies_count?: number | null | undefined;
								reposts_count?: number | null | undefined;
								shares_count?: number | null | undefined;
							},
						) => s + getEng(p),
						0,
					) / avgPosts.length;
				const delta =
					avgEng > 0 ? Math.round(((postEng - avgEng) / avgEng) * 100) : 0;

				const baseline = rec.recommendation_baselines;
				const actionVerb = getActionVerb(baseline?.category || "");
				const metricLabel = getMetricLabel(baseline?.category || "");
				const deltaStr = delta >= 0 ? `+${delta}%` : `${delta}%`;

				await createNotification({
					userId: rec.user_id,
					type: "quick_win_result",
					title: "📊 Quick Win Result",
					message: `Quick update: Since you ${actionVerb} 2 days ago, your first post saw ${postEng} ${metricLabel} (${deltaStr} vs your average). Early signal: ${deltaStr}.`,
					data: {
						recId: rec.rec_id,
						category: baseline?.category,
						delta,
						postEngagement: postEng,
						avgEngagement: Math.round(avgEng),
					},
				});

				// Mark as notified
				await dbAny()
					.from("recommendation_dismissals")
					.update({ result_notified: true })
					.eq("user_id", rec.user_id)
					.eq("account_id", rec.account_id)
					.eq("rec_id", rec.rec_id);

				sent++;
			} catch (err) {
				logger.warn("[result-reminder] Failed for rec", {
					recId: rec.rec_id,
					error: String(err),
				});
			}
		}
	} catch (err) {
		logger.error("[result-reminder] Fatal error", { error: String(err) });
	}

	return sent;
}

function getActionVerb(category: string): string {
	switch (category) {
		case "timing":
			return "shifted your posting times";
		case "content":
			return "diversified your hashtags";
		case "format":
			return "switched up your content format";
		case "engagement":
			return "started replying faster";
		case "frequency":
			return "tightened your posting cadence";
		case "accessibility":
			return "added alt text";
		default:
			return "made the change";
	}
}

function getMetricLabel(category: string): string {
	switch (category) {
		case "timing":
			return "engagements";
		case "content":
			return "engagements";
		case "format":
			return "engagements";
		case "engagement":
			return "replies";
		case "frequency":
			return "engagements";
		case "accessibility":
			return "impressions";
		default:
			return "engagements";
	}
}
