// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Funnel Correlation — Views to Follower Conversion
 *
 * GET /api/analytics/funnel-correlation?accountId=...&days=30
 * Correlates daily post views with daily follower changes to estimate
 * view-to-follower conversion rates.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { verifyAnyAccountOwnership } from "../helpers/verifyOwnership.js";
import { enforceAnalyticsSubRateLimit } from "./rateLimit.js";

const FunnelQuerySchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	days: z.coerce.number().int().min(1).max(90).optional().default(30),
});

const IG_FLEET_ACCOUNT_ID = "__ig_fleet__";

// biome-ignore lint/suspicious/noExplicitAny: table not yet in generated types
const db = (): any => getSupabase();

/**
 * Compute Pearson correlation coefficient between two arrays.
 * Returns 0 if either array has zero variance.
 */
function pearsonCorrelation(xs: number[], ys: number[]): number {
	const n = xs.length;
	if (n < 2) return 0;

	const meanX = xs.reduce((s, v) => s + v, 0) / n;
	const meanY = ys.reduce((s, v) => s + v, 0) / n;

	let sumXY = 0;
	let sumX2 = 0;
	let sumY2 = 0;

	for (let i = 0; i < n; i++) {
		const dx = xs[i]! - meanX;
		const dy = ys[i]! - meanY;
		sumXY += dx * dy;
		sumX2 += dx * dx;
		sumY2 += dy * dy;
	}

	const denom = Math.sqrt(sumX2 * sumY2);
	if (denom === 0) return 0;

	return sumXY / denom;
}

function correlationLabel(r: number): "strong" | "moderate" | "weak" | "none" {
	const absR = Math.abs(r);
	if (absR > 0.5) return "strong";
	if (absR > 0.3) return "moderate";
	if (absR > 0.1) return "weak";
	return "none";
}

type FunnelMetricKey =
	| "views"
	| "reach"
	| "follows"
	| "link_taps";

type FunnelStep = {
	key: FunnelMetricKey;
	label: string;
	value: number;
	rateFromPrevious: number | null;
	available: boolean;
	source: "account_analytics" | "follower_history" | "post_rollup";
};

type AccountAnalyticsFunnelRow = {
	total_views: number | null;
	ig_reach: number | null;
	total_reach: number | null;
	ig_website_clicks: number | null;
	total_clicks: number | null;
	follower_growth: number | null;
};

function toNumber(value: number | string | null | undefined): number {
	const n = Number(value ?? 0);
	return Number.isFinite(n) ? n : 0;
}

function buildFunnelSteps({
	analyticsRows,
	totalViews,
	totalFollowerChange,
}: {
	analyticsRows: AccountAnalyticsFunnelRow[];
	totalViews: number;
	totalFollowerChange: number;
}): FunnelStep[] {
	const sum = (selector: (row: AccountAnalyticsFunnelRow) => number | null) =>
		analyticsRows.reduce(
			(total, row) => total + Math.max(0, toNumber(selector(row))),
			0,
		);
	const has = (selector: (row: AccountAnalyticsFunnelRow) => number | null) =>
		analyticsRows.some(
			(row) => selector(row) !== null && toNumber(selector(row)) > 0,
		);

	const viewsFromAnalytics = sum((row) => row.total_views);
	const reach = sum((row) => row.ig_reach ?? row.total_reach);
	const profileLinkTaps = sum((row) => row.ig_website_clicks ?? row.total_clicks);
	const positiveFollows = sum((row) => {
		const growth = toNumber(row.follower_growth);
		return growth > 0 ? growth : 0;
	});

	const steps: Array<Omit<FunnelStep, "rateFromPrevious">> = [
		{
			key: "views",
			label: "Views",
			value: viewsFromAnalytics > 0 ? viewsFromAnalytics : totalViews,
			available: viewsFromAnalytics > 0 || totalViews > 0,
			source: viewsFromAnalytics > 0 ? "account_analytics" : "post_rollup",
		},
		{
			key: "reach",
			label: "Reach",
			value: reach,
			available: has((row) => row.ig_reach ?? row.total_reach),
			source: "account_analytics",
		},
		{
			key: "follows",
			label: "Follows",
			value:
				positiveFollows > 0
					? positiveFollows
					: Math.max(0, totalFollowerChange),
			available: positiveFollows > 0 || totalFollowerChange > 0,
			source: positiveFollows > 0 ? "account_analytics" : "follower_history",
		},
		{
			key: "link_taps",
			label: "Profile link taps",
			value: profileLinkTaps,
			available: has((row) => row.ig_website_clicks ?? row.total_clicks),
			source: "account_analytics",
		},
	];

	let previous: number | null = null;
	return steps.map((step) => {
		const rateFromPrevious =
			previous != null && previous > 0 && step.available
				? Math.round((step.value / previous) * 10_000) / 100
				: null;
		if (step.available && step.value > 0) previous = step.value;
		return { ...step, rateFromPrevious };
	});
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") {
			return apiError(res, 405, "Method not allowed");
		}

		const userId = user.id;
		const allowed = await enforceAnalyticsSubRateLimit(res, {
			userId,
			action: "funnel-correlation",
			limit: 20,
		});
		if (!allowed) return;

		const parsed = parseQueryOrError(res, FunnelQuerySchema, req.query);
		if (!parsed) return;
		const { accountId, days } = parsed;

		let accountColumn = "account_id";
		let viewsColumn = "views_count";
		let postAccountIds = [accountId];
		let analyticsAccountIds = [accountId];

		if (accountId === IG_FLEET_ACCOUNT_ID) {
			accountColumn = "instagram_account_id";
			viewsColumn = "ig_views";

			const [igAccountsResult, legacyAccountsResult] = await Promise.all([
				db()
					.from("instagram_accounts")
					.select("id, username")
					.eq("user_id", userId)
					.eq("is_active", true),
				db()
					.from("accounts")
					.select("id, username")
					.eq("user_id", userId)
					.eq("is_active", true),
			]);

			if (igAccountsResult.error) {
				return apiError(res, 500, "Failed to fetch Instagram accounts", {
					details: igAccountsResult.error.message,
				});
			}
			if (legacyAccountsResult.error) {
				return apiError(
					res,
					500,
					"Failed to fetch Instagram analytics accounts",
					{
						details: legacyAccountsResult.error.message,
					},
				);
			}

			const igRows = (igAccountsResult.data ?? []) as Array<{
				id: string;
				username: string | null;
			}>;
			const igUsernames = new Set(
				igRows
					.map((row) => (row.username ?? "").replace(/^@/, ""))
					.filter(Boolean),
			);
			postAccountIds = igRows.map((row) => row.id);
			analyticsAccountIds = Array.from(
				new Set([
					...postAccountIds,
					...(
						(legacyAccountsResult.data ?? []) as Array<{
							id: string;
							username: string | null;
						}>
					)
						.filter((row) =>
							igUsernames.has((row.username ?? "").replace(/^@/, "")),
						)
						.map((row) => row.id),
				]),
			);
		} else {
			// Verify account belongs to user and resolve which account column the
			// posts table uses for this platform.
			const ownership = await verifyAnyAccountOwnership(res, accountId, userId);
			if (!ownership) return;
			accountColumn =
				ownership.platform === "instagram"
					? "instagram_account_id"
					: "account_id";
			viewsColumn =
				ownership.platform === "instagram" ? "ig_views" : "views_count";

			if (ownership.platform === "instagram") {
				const { data: igAccount } = await db()
					.from("instagram_accounts")
					.select("username")
					.eq("id", accountId)
					.eq("user_id", userId)
					.maybeSingle();

				const username =
					typeof igAccount?.username === "string"
						? igAccount.username.replace(/^@/, "")
						: null;

				if (username) {
					const { data: legacyAccount } = await db()
						.from("accounts")
						.select("id")
						.eq("user_id", userId)
						.eq("is_active", true)
						.eq("username", username)
						.maybeSingle();

					if (typeof legacyAccount?.id === "string") {
						analyticsAccountIds = Array.from(
							new Set([accountId, legacyAccount.id]),
						);
					}
				}
			}
		}

		if (postAccountIds.length === 0 && analyticsAccountIds.length === 0) {
			return apiSuccess(res, {
				accountId,
				periodDays: days,
				dailyCorrelation: [],
				funnelSteps: [],
				summary: {
					avgDailyViews: 0,
					avgDailyFollowerChange: 0,
					overallConversionRate: 0,
					bestConversionDay: null,
					correlationStrength: "none",
				},
				topConverterPosts: [],
			});
		}

		const cutoffDate = new Date(Date.now() - days * 86_400_000)
			.toISOString()
			.split("T")[0]!;
		const cutoffTimestamp = new Date(
			Date.now() - days * 86_400_000,
		).toISOString();

		// Parallel queries: follower history + published posts. The richer IG
		// funnel comes from account_analytics below after we resolve which ID that
		// table uses for the selected Instagram account.
		const [metricsResult, postsResult] = await Promise.all([
			db()
				.from("account_metrics_history")
				.select("date, followers_count, account_id")
				.in("account_id", analyticsAccountIds)
				.gte("date", cutoffDate)
				.order("date", { ascending: true }),

			db()
				.from("posts")
				.select("id, content, views_count, ig_views, published_at, permalink")
				.in(
					accountColumn,
					postAccountIds.length > 0 ? postAccountIds : analyticsAccountIds,
				)
				.eq("user_id", userId)
				.eq("status", "published")
				.not("published_at", "is", null)
				.gte("published_at", cutoffTimestamp)
				.order("published_at", { ascending: false }),
		]);

		if (metricsResult.error)
			return apiError(res, 500, "Failed to fetch metrics history", {
				details: metricsResult.error.message,
			});
		if (postsResult.error)
			return apiError(res, 500, "Failed to fetch posts", {
				details: postsResult.error.message,
			});

		const metricsRows: Array<{
			date: string;
			followers_count: number;
			account_id?: string | undefined;
		}> = metricsResult.data ?? [];
		const allPosts: Array<{
			id: string;
			content: string | null;
			views_count: number;
			ig_views: number | null;
			published_at: string;
			permalink: string | null;
		}> = postsResult.data ?? [];

		// Build follower-count-by-date map
		const followerByDate = new Map<string, number>();
		for (const row of metricsRows) {
			followerByDate.set(
				row.date,
				(followerByDate.get(row.date) ?? 0) + (row.followers_count ?? 0),
			);
		}

		// Build posts-by-date map
		const postsByDate = new Map<
			string,
			Array<{
				id: string;
				content: string | null;
				views_count: number;
				ig_views: number | null;
				published_at: string;
				permalink: string | null;
			}>
		>();
		for (const post of allPosts) {
			const date = post.published_at.split("T")[0]!;
			if (!postsByDate.has(date!)) {
				postsByDate.set(date!, []);
			}
			postsByDate.get(date!)?.push(post);
		}

		// Collect all unique dates across both sources, sorted
		const allDatesSet = new Set<string>();
		for (const d of followerByDate.keys()) allDatesSet.add(d);
		for (const d of postsByDate.keys()) allDatesSet.add(d);
		const sortedDates = Array.from(allDatesSet).sort();

		// Build daily correlation array
		const dailyCorrelation: Array<{
			date: string;
			views: number;
			postsPublished: number;
			followerChange: number;
			estimatedConversionRate: number;
		}> = [];

		let prevFollowers: number | null = null;

		for (const date of sortedDates) {
			const followers = followerByDate.get(date) ?? null;
			const dayPosts = postsByDate.get(date) ?? [];

			const views = dayPosts.reduce(
				(sum, p) =>
					sum +
					((viewsColumn === "ig_views" ? p.ig_views : p.views_count) ?? 0),
				0,
			);
			const postsPublished = dayPosts.length;

			let followerChange = 0;
			if (followers !== null && prevFollowers !== null) {
				followerChange = followers - prevFollowers;
			}

			const estimatedConversionRate =
				views > 0 ? Math.round((followerChange / views) * 10000) / 10000 : 0;

			dailyCorrelation.push({
				date,
				views,
				postsPublished,
				followerChange,
				estimatedConversionRate,
			});

			if (followers !== null) {
				prevFollowers = followers;
			}
		}

		// Compute summary stats
		const daysWithData = dailyCorrelation.length;
		const totalViews = dailyCorrelation.reduce((s, d) => s + d.views, 0);
		const totalFollowerChange = dailyCorrelation.reduce(
			(s, d) => s + d.followerChange,
			0,
		);

		const avgDailyViews =
			daysWithData > 0 ? Math.round((totalViews / daysWithData) * 10) / 10 : 0;
		const avgDailyFollowerChange =
			daysWithData > 0
				? Math.round((totalFollowerChange / daysWithData) * 100) / 100
				: 0;
		const overallConversionRate =
			totalViews > 0
				? Math.round((totalFollowerChange / totalViews) * 10000) / 10000
				: 0;

		// Find best conversion day (only days with views > 0 and positive follower change)
		let bestConversionDay: {
			date: string;
			rate: number;
			views: number;
			followerChange: number;
		} | null = null;

		for (const day of dailyCorrelation) {
			if (day.views > 0 && day.followerChange > 0) {
				const rate = day.estimatedConversionRate;
				if (bestConversionDay === null || rate > bestConversionDay.rate) {
					bestConversionDay = {
						date: day.date,
						rate,
						views: day.views,
						followerChange: day.followerChange,
					};
				}
			}
		}

		// Pearson correlation between daily views and daily follower changes
		const viewsArr = dailyCorrelation.map((d) => d.views);
		const changesArr = dailyCorrelation.map((d) => d.followerChange);
		const r = pearsonCorrelation(viewsArr, changesArr);
		const correlationStrength = correlationLabel(r);

		// Top converter posts: posts from the days with highest follower gains
		const daysByFollowerGain = [...dailyCorrelation]
			.filter((d) => d.followerChange > 0 && d.postsPublished > 0)
			.sort((a, b) => b.followerChange - a.followerChange)
			.slice(0, 5);

		const topConverterPosts: Array<{
			id: string;
			content: string;
			views: number;
			dayFollowerChange: number;
			publishedAt: string;
			permalink: string | null;
		}> = [];

		for (const day of daysByFollowerGain) {
			const dayPosts = postsByDate.get(day.date) ?? [];
			for (const p of dayPosts) {
				topConverterPosts.push({
					id: p.id,
					content: (p.content ?? "").slice(0, 100),
					views: (viewsColumn === "ig_views" ? p.ig_views : p.views_count) ?? 0,
					dayFollowerChange: day.followerChange,
					publishedAt: p.published_at,
					permalink: p.permalink,
				});
			}
			if (topConverterPosts.length >= 5) break;
		}

		const { data: analyticsRows, error: analyticsError } = await db()
			.from("account_analytics")
			.select(
				"total_views, ig_reach, total_reach, ig_website_clicks, total_clicks, follower_growth",
			)
			.in("account_id", analyticsAccountIds)
			.gte("date", cutoffDate);

		if (analyticsError) {
			return apiError(res, 500, "Failed to fetch funnel analytics", {
				details: analyticsError.message,
			});
		}

		const funnelSteps = buildFunnelSteps({
			analyticsRows: (analyticsRows ?? []) as AccountAnalyticsFunnelRow[],
			totalViews,
			totalFollowerChange,
		});

		return apiSuccess(res, {
			accountId,
			periodDays: days,
			dailyCorrelation,
			funnelSteps,
			summary: {
				avgDailyViews,
				avgDailyFollowerChange,
				overallConversionRate,
				bestConversionDay,
				correlationStrength,
			},
			topConverterPosts: topConverterPosts.slice(0, 5),
		});
	},
);
