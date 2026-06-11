// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * GET /api/user/annual-recap?year=2026
 *
 * Generates a "Your Growth Story" annual recap with CES journey,
 * archetype evolution, top wins, total stats, streaks, and more.
 * Cached in Redis for 24h (heavy query).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import type { DbContext } from "../../dbContext.js";
import { logger } from "../../logger.js";
import { withAuthDb } from "../../middleware.js";
import { cached } from "../../redisCache.js";

type UserDb = DbContext["userDb"];

const CACHE_TTL = 24 * 60 * 60; // 24h

interface MonthlyCES {
	month: number; // 1-12
	label: string;
	value: number | null;
}

interface ArchetypeChange {
	date: string;
	from: string;
	to: string;
}

interface TopWin {
	title: string;
	category: string;
	impact: number;
	completedAt: string;
}

interface TotalStats {
	postsPublished: number;
	followersGained: number;
	totalViews: number;
	totalEngagement: number;
}

interface Streaks {
	longestPostingStreak: number;
	longestCESGrowthStreak: number;
}

interface Milestone {
	type: "followers" | "engagement_rate" | "total_views";
	threshold: number;
	label: string;
	achievedAt: string | null;
}

interface AnnualRecapData {
	year: number;
	cesJourney: MonthlyCES[];
	archetypeEvolution: ArchetypeChange[];
	topWins: TopWin[];
	totalStats: TotalStats;
	topContentType: string | null;
	streaks: Streaks;
	milestones: Milestone[];
}

const MONTH_LABELS = [
	"Jan",
	"Feb",
	"Mar",
	"Apr",
	"May",
	"Jun",
	"Jul",
	"Aug",
	"Sep",
	"Oct",
	"Nov",
	"Dec",
];

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, context) => {
		const { user, userDb } = context;
		if (req.method !== "GET") {
			return apiError(res, 405, "Method not allowed");
		}

		const year = parseInt(
			String(req.query.year || new Date().getFullYear()),
			10,
		);
		if (Number.isNaN(year) || year < 2020 || year > 2100) {
			return apiError(res, 400, "Invalid year");
		}

		try {
			const data = await cached<AnnualRecapData>(
				`annual-recap:${user.id}:${year}`,
				CACHE_TTL,
				() => buildRecap(user.id, year, userDb),
			);
			return apiSuccess(res, data as unknown as Record<string, unknown>);
		} catch (err) {
			logger.error("[annual-recap] Failed", {
				userId: user.id,
				year,
				error: String(err),
			});
			return apiError(res, 500, "Failed to generate annual recap");
		}
	},
);

async function buildRecap(
	userId: string,
	year: number,
	db: UserDb,
): Promise<AnnualRecapData> {
	const startDate = `${year}-01-01`;
	const endDate = `${year}-12-31`;

	// Get user's accounts
	const { data: accounts } = await db
		.from("accounts")
		.select("id")
		.eq("user_id", userId);
	const accountIds = (accounts ?? []).map((a) => a.id);

	// 1. Account analytics for the year
	let analyticsRows: Array<{
		date: string;
		followers_count: number | null;
		total_views: number | null;
		engagement_rate: number | null;
	}> = [];
	if (accountIds.length > 0) {
		const { data } = await db
			.from("account_analytics")
			.select("date, followers_count, total_views, engagement_rate")
			.in("account_id", accountIds)
			.gte("date", startDate)
			.lte("date", endDate)
			.order("date", { ascending: true });
		analyticsRows = data ?? [];
	}

	// 2. Posts for the year
	let posts: Array<{
		id: string;
		created_at: string;
		media_type: string | null;
		likes_count: number | null;
		replies_count: number | null;
		reposts_count: number | null;
		views_count: number | null;
	}> = [];
	if (accountIds.length > 0) {
		const { data } = await db
			.from("posts")
			.select(
				"id, created_at, media_type, likes_count, replies_count, reposts_count, views_count",
			)
			.in("account_id", accountIds)
			.gte("created_at", `${startDate}T00:00:00Z`)
			.lte("created_at", `${endDate}T23:59:59Z`)
			.order("created_at", { ascending: true });
		posts = (data ?? []).map((p) => ({ ...p, created_at: p.created_at ?? "" }));
	}

	// 3. Quick wins (solved)
	const { data: quickWins } = await db
		.from("quick_wins")
		.select("title, category, measured_impact, completed_at")
		.eq("user_id", userId)
		.eq("status", "completed")
		.gte("completed_at", `${startDate}T00:00:00Z`)
		.lte("completed_at", `${endDate}T23:59:59Z`)
		.order("measured_impact", { ascending: false })
		.limit(5);

	// 4. Archetype changes from creator_events
	const { data: archetypeEvents } = await db
		.from("creator_events")
		.select("event_date, metrics_snapshot")
		.eq("user_id", userId)
		.eq("event_type", "archetype_changed")
		.gte("event_date", startDate)
		.lte("event_date", endDate)
		.order("event_date", { ascending: true });

	// --- Build engagement rate journey (monthly averages) ---
	const cesJourney: MonthlyCES[] = MONTH_LABELS.map((label, i) => {
		const month = i + 1;
		const monthStr = String(month).padStart(2, "0");
		const monthRows = analyticsRows.filter((r) => {
			const d = String(r.date);
			return d.startsWith(`${year}-${monthStr}`);
		});
		const erValues = monthRows
			.map((r) => r.engagement_rate)
			.filter((v): v is number => v != null);
		const avg =
			erValues.length > 0
				? erValues.reduce((a: number, b: number) => a + b, 0) / erValues.length
				: null;
		return {
			month,
			label,
			value: avg !== null ? Math.round(avg * 100) / 100 : null,
		};
	});

	// --- Archetype evolution ---
	const archetypeEvolution: ArchetypeChange[] = (archetypeEvents ?? []).map(
		(e) => {
			const snap = e.metrics_snapshot as {
				old_archetype?: string | undefined;
				new_archetype?: string | undefined;
			} | null;
			return {
				date: e.event_date,
				from: snap?.old_archetype ?? "Unknown",
				to: snap?.new_archetype ?? "Unknown",
			};
		},
	);

	// --- Top wins ---
	const topWins: TopWin[] = (quickWins ?? []).map((w) => ({
		title: w.title,
		category: (w.category as string | null) ?? "general",
		impact: w.measured_impact ?? 0,
		completedAt: (w.completed_at as string | null) ?? "",
	}));

	// --- Total stats ---
	const postsPublished = posts.length;
	const totalEngagement = posts.reduce(
		(sum: number, p) =>
			sum +
			(p.likes_count ?? 0) +
			(p.replies_count ?? 0) +
			(p.reposts_count ?? 0),
		0,
	);
	const totalViews = posts.reduce(
		(sum: number, p) => sum + (p.views_count ?? 0),
		0,
	);

	let followersGained = 0;
	if (analyticsRows.length >= 2) {
		const first = analyticsRows[0]?.followers_count ?? 0;
		const last = analyticsRows[analyticsRows.length - 1]?.followers_count ?? 0;
		followersGained = last - first;
	}

	const totalStats: TotalStats = {
		postsPublished,
		followersGained,
		totalViews,
		totalEngagement,
	};

	// --- Top content type ---
	const typeEngagement: Record<string, number> = {};
	for (const p of posts) {
		const t = p.media_type || "text";
		typeEngagement[t] =
			(typeEngagement[t] || 0) +
			(p.likes_count ?? 0) +
			(p.replies_count ?? 0) +
			(p.reposts_count ?? 0);
	}
	const topContentType =
		Object.entries(typeEngagement).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;

	// --- Streaks ---
	const postDates = [
		...new Set(posts.map((p) => p.created_at?.slice(0, 10))),
	].sort();
	const longestPostingStreak = computeConsecutiveDayStreak(postDates);

	const monthlyCESValues = cesJourney
		.map((c) => c.value)
		.filter((v): v is number => v !== null);
	const longestCESGrowthStreak = computeGrowthStreak(monthlyCESValues);

	// --- Milestones ---
	const milestones: Milestone[] = [];

	// Follower milestones (existing pattern — kept for completeness)
	const followerThresholds = [100, 500, 1000, 5000, 10000, 50000, 100000];
	for (const threshold of followerThresholds) {
		const row = analyticsRows.find(
			(r) => (r.followers_count ?? 0) >= threshold,
		);
		milestones.push({
			type: "followers",
			threshold,
			label: `${threshold >= 1000 ? `${threshold / 1000}K` : threshold} followers`,
			achievedAt: row?.date ?? null,
		});
	}

	// Engagement rate milestones: first time reaching 5%, 10%, 15%, 20%
	const engagementRateThresholds = [5, 10, 15, 20];
	// Compute daily engagement rates from posts grouped by date
	const postsByDate: Record<string, { engagement: number; views: number }> = {};
	for (const p of posts) {
		const dateKey = p.created_at?.slice(0, 10);
		if (!dateKey) continue;
		if (!postsByDate[dateKey])
			postsByDate[dateKey] = { engagement: 0, views: 0 };
		postsByDate[dateKey].engagement +=
			(p.likes_count ?? 0) + (p.replies_count ?? 0) + (p.reposts_count ?? 0);
		postsByDate[dateKey].views += p.views_count ?? 0;
	}
	const sortedDates = Object.keys(postsByDate).sort();
		for (const threshold of engagementRateThresholds) {
			let achievedDate: string | null = null;
			for (const dateKey of sortedDates) {
				const { engagement, views } = postsByDate[dateKey]!;
			if (views > 0) {
				const rate = (engagement / views) * 100;
				if (rate >= threshold) {
					achievedDate = dateKey;
					break;
				}
			}
		}
		milestones.push({
			type: "engagement_rate",
			threshold,
			label: `${threshold}% engagement rate`,
			achievedAt: achievedDate,
		});
	}

	// Total views milestones: cumulative views crossing thresholds
	const viewsThresholds = [1000, 10000, 100000, 1000000];
	let cumulativeViews = 0;
	const viewsMilestoneAchieved: Record<number, string | null> = {};
	for (const t of viewsThresholds) viewsMilestoneAchieved[t] = null;
	for (const dateKey of sortedDates) {
		cumulativeViews += postsByDate[dateKey]!.views;
		for (const threshold of viewsThresholds) {
			if (
				viewsMilestoneAchieved[threshold] === null &&
				cumulativeViews >= threshold
			) {
				viewsMilestoneAchieved[threshold] = dateKey;
			}
		}
	}
	for (const threshold of viewsThresholds) {
		const label =
			threshold >= 1000000
				? `${threshold / 1000000}M`
				: threshold >= 1000
					? `${threshold / 1000}K`
					: String(threshold);
		milestones.push({
			type: "total_views",
			threshold,
			label: `${label} total views`,
			achievedAt: viewsMilestoneAchieved[threshold]!,
		});
	}

	return {
		year,
		cesJourney,
		archetypeEvolution,
		topWins,
		totalStats,
		topContentType,
		streaks: { longestPostingStreak, longestCESGrowthStreak },
		milestones,
	};
}

function computeConsecutiveDayStreak(sortedDates: string[]): number {
	if (sortedDates.length === 0) return 0;
	let maxStreak = 1;
	let current = 1;
	for (let i = 1; i < sortedDates.length; i++) {
		const prev = new Date(sortedDates[i - 1]!);
		const curr = new Date(sortedDates[i]!);
		const diffDays = (curr.getTime() - prev.getTime()) / (1000 * 60 * 60 * 24);
		if (diffDays === 1) {
			current++;
			maxStreak = Math.max(maxStreak, current);
		} else {
			current = 1;
		}
	}
	return maxStreak;
}

function computeGrowthStreak(values: number[]): number {
	if (values.length < 2) return 0;
	let maxStreak = 0;
	let current = 0;
	for (let i = 1; i < values.length; i++) {
		if (values[i]! > values[i - 1]!) {
			current++;
			maxStreak = Math.max(maxStreak, current);
		} else {
			current = 0;
		}
	}
	return maxStreak;
}
