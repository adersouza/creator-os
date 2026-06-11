// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * POST /api/ai/growth-simulator — Follower growth projection & scenario modeling
 *
 * Uses linear regression on historical follower data to project milestones.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { getSupabase } from "../../supabase.js";
import { requireMinTier } from "../../tierGate.js";

/** Simple linear regression: y = slope * x + intercept */
function linearRegression(points: { x: number; y: number }[]): {
	slope: number;
	intercept: number;
	r2: number;
} {
	const n = points.length;
	if (n === 0) return { slope: 0, intercept: 0, r2: 0 };
	if (n === 1) return { slope: 0, intercept: points[0]!.y, r2: 0 };

	let sumX = 0,
		sumY = 0,
		sumXY = 0,
		sumX2 = 0;
	for (const p of points) {
		sumX += p.x;
		sumY += p.y;
		sumXY += p.x * p.y;
		sumX2 += p.x * p.x;
	}

	const denom = n * sumX2 - sumX * sumX;
	if (denom === 0) return { slope: 0, intercept: sumY / n, r2: 0 };

	const slope = (n * sumXY - sumX * sumY) / denom;
	const intercept = (sumY - slope * sumX) / n;
	const meanY = sumY / n;
	let ssTot = 0;
	let ssRes = 0;
	for (const p of points) {
		const predicted = slope * p.x + intercept;
		ssTot += (p.y - meanY) ** 2;
		ssRes += (p.y - predicted) ** 2;
	}
	const r2 = ssTot > 0 ? Math.max(0, 1 - ssRes / ssTot) : 0;
	return { slope, intercept, r2 };
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}

		// Tier gate — Growth Simulator requires Pro or higher
		if (!(await requireMinTier(user.id, "pro", res))) return;

		// Rate limit: 20 requests/hour per user
		const rl = await checkRateLimit({
			key: `growth-sim:${user.id}`,
			limit: 20,
			windowSeconds: 3600,
			failMode: "closed",
		});
		if (!rl.allowed) {
			return apiError(res, 429, "Rate limit exceeded. Please wait a moment.");
		}

		const { accountId, platform } = req.body || {};
		if (!accountId || !platform) {
			return apiError(res, 400, "accountId and platform are required");
		}

		const supabase = getSupabase();

		try {
			// Verify ownership — check both accounts (Threads) and instagram_accounts
			let account: { id: string; followers_count: number | null } | null = null;

			if (platform === "instagram") {
				const { data } = await supabase
					.from("instagram_accounts")
					.select("id, follower_count")
					.eq("id", accountId)
					.eq("user_id", user.id)
					.maybeSingle();
				// Normalize column name
				const igRow = data as {
					id: string;
					followers_count?: number | null | undefined;
					follower_count?: number | null | undefined;
				} | null;
				account = igRow
					? { id: igRow.id, followers_count: igRow.follower_count ?? null }
					: null;
			} else {
				const { data } = await supabase
					.from("accounts")
					.select("id, followers_count")
					.eq("id", accountId)
					.eq("user_id", user.id)
					.maybeSingle();
				account = data as { id: string; followers_count: number | null } | null;
			}

			if (!account) {
				return apiError(res, 404, "Account not found");
			}

			// Fetch last 90 days of follower data
			const ninetyDaysAgo = new Date();
			ninetyDaysAgo.setDate(ninetyDaysAgo.getDate() - 90);

			const { data: analytics } = await supabase
				.from("account_analytics")
				.select("date, followers_count")
				.eq("account_id", accountId)
				.gte("date", ninetyDaysAgo.toISOString().split("T")[0]!)
				.order("date", { ascending: true });

			const rows = (analytics || []).filter(
				(r: { date: string; followers_count: number | null }) =>
					r.followers_count != null && r.followers_count > 0,
			);
			const currentFollowers: number =
				account.followers_count ||
				(rows.length > 0 ? rows[rows.length - 1]!.followers_count : 0) ||
				0;

			const firstDate = rows[0]?.date ? new Date(rows[0].date).getTime() : 0;
			const lastDate = rows[rows.length - 1]?.date
				? new Date(rows[rows.length - 1]!.date).getTime()
				: 0;
			const historySpanDays =
				firstDate && lastDate ? Math.round((lastDate - firstDate) / 86400000) : 0;

			if (rows.length < 14 || historySpanDays < 21) {
				return apiSuccess(res, {
					currentFollowers,
					avgDailyGrowth: 0,
					projections: [],
					scenarios: [],
					dataPoints: rows.length,
					confidence: "low",
					message:
						"Not enough historical data for a reliable projection. Need at least 14 data points across 21 days.",
				});
			}

			// Convert dates to day offsets for regression
			const baseDate = new Date(rows[0]!.date).getTime();
			const msPerDay = 86400000;
			const points = rows.map((r) => ({
				x: (new Date(r.date).getTime() - baseDate) / msPerDay,
				y: r.followers_count as number,
			}));

			const { slope: avgDailyGrowth, r2 } = linearRegression(points);
			const forecastable = avgDailyGrowth > 0 && r2 >= 0.35;

			// Generate projections for milestones
			const milestones = [
				1000, 5000, 10000, 25000, 50000, 100000, 500000, 1000000,
			];
			const relevantMilestones = milestones.filter((m) => m > currentFollowers);

			const projections = forecastable
				? relevantMilestones.slice(0, 4).map((target) => {
				const daysToTarget =
					avgDailyGrowth > 0
						? (target - currentFollowers) / avgDailyGrowth
						: null;
				const estimatedDate =
					daysToTarget != null && daysToTarget > 0
						? new Date(Date.now() + daysToTarget * msPerDay)
								.toISOString()
								.split("T")[0]!
						: null;
				return {
					target,
					estimatedDate,
					daysToTarget: daysToTarget != null ? Math.ceil(daysToTarget) : null,
				};
			})
				: [];

			// Scenario modeling: benchmark estimate for increased posting frequency.
			const boostedGrowth = avgDailyGrowth * 1.3;
			const scenarios = [
				{
					label: "Illustrative scenario, not a forecast: increase posting by 50%",
					estimatedDailyGrowth: Math.round(boostedGrowth * 100) / 100,
					description: `Illustrative scenario, not a forecast: the benchmark multiplier models growth at +${boostedGrowth.toFixed(1)}/day if posting rises 50%. Validate against this account's next 30 days.`,
					source: "benchmark_multiplier",
					multiplier: 1.3,
				},
			];

			// Historical data for chart
			const history = rows.map((r) => ({
				date: r.date,
				followers: r.followers_count,
			}));

			// --- Strategy suggestions from analytics (non-fatal, Threads only) ---
			type StrategySuggestion = {
				pillar: string;
				change: string;
				confidence: number;
				reason: string;
			};
			const suggestions: StrategySuggestion[] = [];

			if (platform === "threads" || platform === "instagram") {
				try {
					// Look up group_id from the correct table based on platform
					const table =
						platform === "instagram" ? "instagram_accounts" : "accounts";
					const { data: acctData } = await supabase
						.from(table)
						.select("group_id")
						.eq("id", accountId)
						.eq("user_id", user.id)
						.maybeSingle();
					const groupId = (acctData as { group_id?: string | null | undefined } | null)
						?.group_id;

					if (groupId) {
						const { data: groupData } = await supabase
							.from("account_groups")
							.select("content_strategy")
							.eq("id", groupId)
							.maybeSingle();
						const strategy = (
							groupData as { content_strategy?: { pillars?: string[] | undefined } | undefined } | null
						)?.content_strategy;
						const pillars = strategy?.pillars;

						if (pillars && pillars.length > 0) {
							const sixtyDaysAgo = new Date();
							sixtyDaysAgo.setDate(sixtyDaysAgo.getDate() - 60);

							const { data: recentPosts } = await supabase
								.from("posts")
								.select(
									"content, likes_count, replies_count, reposts_count, views_count",
								)
								.eq(
									platform === "instagram"
										? "instagram_account_id"
										: "account_id",
									accountId,
								)
								.eq("user_id", user.id)
								.eq("status", "published")
								.gte("published_at", sixtyDaysAgo.toISOString())
								.not("content", "is", null)
								.limit(100);

							type PostRow = {
								content: string | null;
								likes_count: number | null;
								replies_count: number | null;
								reposts_count: number | null;
								views_count: number | null;
							};
							const posts = (recentPosts ?? []) as PostRow[];

							if (posts.length >= 5) {
								const PILLAR_KEYWORDS: Record<string, string[]> = {
									"everyday life": [
										"today",
										"morning",
										"tonight",
										"yesterday",
										"woke",
										"weekend",
										"week",
										"last night",
									],
									"nerdy interests": [
										"game",
										"gaming",
										"anime",
										"coding",
										"code",
										"tech",
										"science",
										"space",
										"book",
										"movie",
										"show",
										"series",
										"nerd",
										"geek",
										"computer",
										"stream",
									],
									"random thoughts": [
										"honestly",
										"thought",
										"lowkey",
										"real talk",
										"just realized",
										"imo",
										"idk",
										"randomly",
										"kinda",
									],
									"relatable moments": [
										"anyone else",
										"who else",
										"same",
										"every time",
										"always",
										"literally",
										"never fails",
										"every single",
									],
								};

								const scored = posts.map((p) => {
									const likes = p.likes_count ?? 0;
									const replies = p.replies_count ?? 0;
									const reposts = p.reposts_count ?? 0;
									const views = p.views_count ?? 0;
									return {
										text: (p.content ?? "").toLowerCase(),
										score: likes * 3 + replies * 5 + reposts * 4 + views * 0.01,
									};
								});

								const avgOverall =
									scored.reduce((s, p) => s + p.score, 0) / scored.length;

								for (const pillar of pillars) {
									const key = pillar.toLowerCase();
									const keywords =
										PILLAR_KEYWORDS[key] ??
										key.split(" ").filter((w) => w.length > 3);
									const matching = scored.filter((p) =>
										keywords.some((kw) => p.text.includes(kw)),
									);

									if (matching.length < 2) continue;

									const avgPillar =
										matching.reduce((s, p) => s + p.score, 0) / matching.length;
									const ratio = avgOverall > 0 ? avgPillar / avgOverall : 1;
									const sampleFactor = Math.min(matching.length / 10, 1);

									if (ratio >= 1.15) {
										const pct = Math.round((ratio - 1) * 100);
										suggestions.push({
											pillar,
											change: `Prioritize '${pillar}' content`,
											confidence: Math.min(
												Math.round(sampleFactor * (0.55 + ratio * 0.2) * 100) /
													100,
												0.95,
											),
											reason: `${matching.length} '${pillar}' posts averaged ${pct}% higher engagement than overall average`,
										});
									} else if (ratio < 0.8 && matching.length >= 3) {
										const pct = Math.round((1 - ratio) * 100);
										suggestions.push({
											pillar,
											change: `Reduce '${pillar}' posting frequency`,
											confidence: Math.min(
												Math.round(sampleFactor * 0.65 * 100) / 100,
												0.85,
											),
											reason: `'${pillar}' posts averaged ${pct}% lower engagement than overall average (${matching.length} posts sampled)`,
										});
									}
								}

								suggestions.sort((a, b) => b.confidence - a.confidence);
							}
						}
					}
				} catch {
					// Non-fatal — suggestions unavailable if data is missing
				}
			}

			return apiSuccess(res, {
				currentFollowers,
				avgDailyGrowth: Math.round(avgDailyGrowth * 100) / 100,
				projections,
				scenarios,
				history,
				dataPoints: rows.length,
				historySpanDays,
				r2: Math.round(r2 * 100) / 100,
				confidence: forecastable ? (r2 >= 0.65 ? "medium" : "low") : "low",
				message: forecastable
					? undefined
					: "Follower history is too volatile or flat for a reliable milestone forecast. Use the chart as history, not a prediction.",
				suggestions,
				method: "statistical_regression",
				aiGenerated: false,
			});
		} catch (err: unknown) {
			logger.error("[ai/growth-simulator] Failed", {
				userId: user.id,
				error: err instanceof Error ? err.message : String(err),
			});
			return apiError(res, 500, "Growth simulation failed");
		}
	},
);
