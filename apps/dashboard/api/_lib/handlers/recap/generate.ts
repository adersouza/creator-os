// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * GET /api/recap/generate?account_id=X&period=7d|30d|all
 *
 * Generates a personalized growth recap for sharing.
 * Returns stats, highlights, and a headline for the recap card.
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { resolveAccount } from "../../resolveAccount.js";
import { getSupabaseAny } from "../../supabase.js";

const db = () => getSupabaseAny();

const DAYS = [
	"Sunday",
	"Monday",
	"Tuesday",
	"Wednesday",
	"Thursday",
	"Friday",
	"Saturday",
];

interface GrowthRecap {
	period: string;
	periodDays: number;
	accountHandle: string;
	platform: string;
	totalPosts: number;
	totalViews: number;
	totalEngagement: number;
	followerChange: number;
	avgEngagementRate: number;
	cesScore: number;
	cesTrend: "up" | "down" | "stable";
	cesChange: number;
	bestPost: {
		content: string;
		views: number;
		viralScore: number;
		thumbnail?: string | undefined;
	} | null;
	quickWinsSolved: number;
	bestDay: string;
	bestHour: string;
	topWord: string;
	streak: number;
	headline: string;
}

function generateHeadline(recap: GrowthRecap): string {
	if (recap.followerChange > 100)
		return `You gained ${recap.followerChange} followers this week`;
	if (recap.totalViews > 10000)
		return `${(recap.totalViews / 1000).toFixed(1)}K people saw your content`;
	if (recap.quickWinsSolved > 0)
		return `${recap.quickWinsSolved} Quick Wins solved — your strategy is working`;
	if (recap.cesChange > 5)
		return `Your CES jumped ${recap.cesChange} points — you're leveling up`;
	if (recap.streak > 5)
		return `${recap.streak}-day posting streak — consistency wins`;
	return `${recap.totalPosts} posts, ${recap.totalEngagement} engagements — keep building`;
}

function formatPeriod(start: Date, end: Date): string {
	const opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
	const y = end.getFullYear();
	return `${start.toLocaleDateString("en-US", opts)}-${end.toLocaleDateString("en-US", opts)}, ${y}`;
}

function getMostCommonWord(texts: string[]): string {
	const stopWords = new Set([
		"the",
		"a",
		"an",
		"and",
		"or",
		"but",
		"in",
		"on",
		"at",
		"to",
		"for",
		"of",
		"is",
		"it",
		"i",
		"my",
		"me",
		"you",
		"your",
		"this",
		"that",
		"with",
		"from",
		"be",
		"was",
		"are",
		"have",
		"has",
		"had",
		"do",
		"does",
		"did",
		"will",
		"would",
		"can",
		"could",
		"not",
		"no",
		"so",
		"if",
		"just",
		"about",
		"up",
		"out",
		"all",
		"its",
		"been",
		"were",
		"they",
		"their",
		"what",
		"when",
		"how",
		"who",
		"which",
		"more",
		"some",
		"than",
	]);
	const freq: Record<string, number> = {};
	for (const text of texts) {
		const words = (text || "")
			.toLowerCase()
			.replace(/[^a-z\s]/g, "")
			.split(/\s+/)
			.filter((w) => w.length > 2 && !stopWords.has(w));
		for (const w of words) freq[w] = (freq[w] || 0) + 1;
	}
	let topWord = "content";
	let topCount = 0;
	for (const [word, count] of Object.entries(freq)) {
		if (count > topCount) {
			topWord = word;
			topCount = count;
		}
	}
	return topWord;
}

export default withAuth(async (req, res, user) => {
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	const accountId = req.query.account_id as string;
	const period = (req.query.period as string) || "7d";

	if (!accountId) return apiError(res, 400, "account_id is required");

	try {
		// Calculate date range
		const now = new Date();
		let periodDays = 7;
		if (period === "30d") periodDays = 30;
		else if (period === "all") periodDays = 365;
		const startDate = new Date(now.getTime() - periodDays * 86400000);

		// Fetch account (Threads or Instagram) — verifies ownership
		const resolved = await resolveAccount(accountId, user.id);

		if (!resolved) {
			return apiError(res, 403, "Account not found or not authorized");
		}

		const handle = resolved.username || "user";
		const platform = resolved.platform || "threads";

		// Fetch posts in period — for IG accounts, match on instagram_account_id
		const isIG = platform === "instagram";
		let postsQuery = db()
			.from("posts")
			.select(
				"id, content, text, views, reach, likes, like_count, replies_count, replies, comments_count, reposts, shares, saved, saves, media_url, thumbnail_url, published_at",
			);

		if (isIG) {
			postsQuery = postsQuery.eq("instagram_account_id", accountId);
		} else {
			postsQuery = postsQuery.eq("account_id", accountId);
		}

		const { data: posts } = await postsQuery
			.gte("published_at", startDate.toISOString())
			.not("published_at", "is", null)
			.order("published_at", { ascending: false })
			.limit(500);

		const postList: Record<string, unknown>[] = posts || [];
		const totalPosts = postList.length;

		// Calculate metrics
		let totalViews = 0;
		let totalEngagement = 0;
		let bestPost = null;
		let bestViews = -1;
		const dayEngagement: Record<string, number> = {};
		const hourEngagement: Record<number, number> = {};
		const publishDates = new Set<string>();

		for (const post of postList) {
			const views = (post.views as number) || (post.reach as number) || 0;
			const likes = (post.likes as number) || (post.like_count as number) || 0;
			const replies =
				(post.replies_count as number) ||
				(post.replies as number) ||
				(post.comments_count as number) ||
				0;
			const reposts = (post.reposts as number) || (post.shares as number) || 0;
			const saves = (post.saved as number) || (post.saves as number) || 0;
			const eng = likes + replies + reposts + saves;

			totalViews += views;
			totalEngagement += eng;

			if (views > bestViews) {
				bestViews = views;
				bestPost = {
					content: (post.content as string) || (post.text as string) || "",
					views,
					viralScore: Math.min(
						10,
						Math.round((eng / Math.max(views, 1)) * 100 * 10) / 10,
					),
					thumbnail:
						(post.media_url as string | undefined) ||
						(post.thumbnail_url as string | undefined) ||
						undefined,
				};
			}

			if (post.published_at) {
				const d = new Date(post.published_at as string);
				const dayName = DAYS[d.getDay()];
				dayEngagement[dayName!] = (dayEngagement[dayName!] || 0) + eng;
				hourEngagement[d.getHours()] =
					(hourEngagement[d.getHours()] || 0) + eng;
				publishDates.add(d.toISOString().slice(0, 10));
			}
		}

		const avgEngagementRate =
			totalViews > 0
				? Math.round((totalEngagement / totalViews) * 10000) / 100
				: 0;

		// Best day/hour
		let bestDay = "Monday";
		let bestDayEng = -1;
		for (const [day, eng] of Object.entries(dayEngagement)) {
			if (eng > bestDayEng) {
				bestDay = day;
				bestDayEng = eng;
			}
		}

		let bestHour = "9 AM";
		let bestHourEng = -1;
		for (const [hour, eng] of Object.entries(hourEngagement)) {
			if (eng > bestHourEng) {
				bestHourEng = eng;
				const h = parseInt(hour, 10);
				bestHour =
					h === 0
						? "12 AM"
						: h === 12
							? "12 PM"
							: h < 12
								? `${h} AM`
								: `${h - 12} PM`;
			}
		}

		// Streak calculation
		let streak = 0;
		const sortedDates = Array.from(publishDates).sort().reverse();
		if (sortedDates.length > 0) {
			streak = 1;
			for (let i = 1; i < sortedDates.length; i++) {
				const prev = new Date(sortedDates[i - 1]!);
				const curr = new Date(sortedDates[i]!);
				const diff = (prev.getTime() - curr.getTime()) / 86400000;
				if (diff <= 1.5) streak++;
				else break;
			}
		}

		// Top word
		const topWord = getMostCommonWord(
			postList.map(
				(p: Record<string, unknown>) => (p.content || p.text || "") as string,
			),
		);

		// CES (simplified)
		const cesScore =
			totalViews > 0
				? Math.round((totalEngagement / totalViews) * 1000) / 10
				: 0;

		// Quick wins solved
		let quickWinsSolved = 0;
		try {
			const { count } = await db()
				.from("quick_wins")
				.select("*", { count: "exact", head: true })
				.eq("account_id", accountId)
				.eq("status", "completed")
				.gte("completed_at", startDate.toISOString());
			quickWinsSolved = count || 0;
		} catch (err) {
			logger.debug("Failed to fetch quick_wins count for recap", {
				accountId,
				error: String(err),
			});
			// Table may not exist yet
		}

		// Follower change — check both account_analytics and ig_account_analytics
		let followerChange = 0;
		try {
			const analyticsTable = isIG
				? "ig_account_analytics"
				: "account_analytics";
			const accountCol = isIG ? "instagram_account_id" : "account_id";
			const { data: snapshots } = await db()
				.from(analyticsTable)
				.select("followers_count, recorded_at")
				.eq(accountCol, accountId)
				.gte("recorded_at", startDate.toISOString())
				.order("recorded_at", { ascending: true })
				.limit(2);
			if (snapshots && snapshots.length >= 2) {
				followerChange =
					(snapshots[snapshots.length - 1]!.followers_count || 0) -
					(snapshots[0]!.followers_count || 0);
			}
		} catch (err) {
			logger.debug("Failed to fetch follower change from analytics", {
				accountId,
				platform,
				error: String(err),
			});
			// Table may not exist
		}

		const recap: GrowthRecap = {
			period: formatPeriod(startDate, now),
			periodDays,
			accountHandle: handle,
			platform,
			totalPosts,
			totalViews,
			totalEngagement,
			followerChange,
			avgEngagementRate,
			cesScore,
			cesTrend: "stable",
			cesChange: 0,
			bestPost,
			quickWinsSolved,
			bestDay,
			bestHour,
			topWord,
			streak,
			headline: "",
		};

		recap.headline = generateHeadline(recap);

		return apiSuccess(res, { data: recap });
	} catch (err) {
		logger.error("[recap/generate] Error", { error: String(err) });
		return apiError(res, 500, "Internal server error");
	}
});
