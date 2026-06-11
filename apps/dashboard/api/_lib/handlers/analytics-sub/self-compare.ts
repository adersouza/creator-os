// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { verifyAccountOwnership } from "../helpers/verifyOwnership.js";

const db = () => getSupabase();
const MAX_RANGE_DAYS = 90;
const DAY_MS = 86_400_000;

function parseDate(s: string): Date | null {
	const d = new Date(`${s}T00:00:00Z`);
	return Number.isNaN(d.getTime()) ? null : d;
}

function daysBetween(a: Date, b: Date): number {
	return Math.abs(b.getTime() - a.getTime()) / DAY_MS;
}

interface PeriodMetrics {
	ces: number;
	avgEngagementRate: number;
	postsPerWeek: number;
	totalViews: number;
	followerChange: number;
	topContentType: string;
	quickWinsActioned: number;
}

async function fetchPeriodMetrics(
	accountId: string,
	userId: string,
	start: string,
	end: string,
): Promise<PeriodMetrics> {
	const supabase = db();

	// Fetch account_analytics for the period
	const { data: analytics } = await supabase
		.from("account_analytics")
		.select("followers_count, engagement_rate, total_views, date")
		.eq("account_id", accountId)
		.gte("date", start)
		.lte("date", end)
		.order("date", { ascending: true });

	interface AnalyticsRow {
		followers_count: number | null;
		engagement_rate: number | null;
		total_views: number | null;
		date: string;
	}
	const rows = (analytics || []) as AnalyticsRow[];

	// Follower change: last - first
	const followerChange =
		rows.length >= 2
			? (rows[rows.length - 1]!.followers_count || 0) -
				(rows[0]!.followers_count || 0)
			: 0;

	// Avg engagement rate
	const engRates = rows
		.filter((r) => r.engagement_rate != null)
		.map((r) => r.engagement_rate as number);
	const avgEngagementRate =
		engRates.length > 0
			? engRates.reduce((a: number, b: number) => a + b, 0) / engRates.length
			: 0;

	// Total views: sum
	const totalViews = rows.reduce(
		(sum: number, r) => sum + (r.total_views || 0),
		0,
	);

	// Fetch posts for the period
	const { data: posts } = await supabase
		.from("posts")
		.select(
			"likes, replies, reposts, shares, comments, saves, quotes, published_at, media_type",
		)
		.eq("account_id", accountId)
		.eq("user_id", userId)
		.gte("published_at", start)
		.lte("published_at", `${end}T23:59:59Z`);

	interface PostRow {
		likes: number | null;
		replies: number | null;
		reposts: number | null;
		shares: number | null;
		comments: number | null;
		saves: number | null;
		quotes: number | null;
		published_at: string | null;
		media_type: string | null;
	}
	const postRows = (posts || []) as unknown as PostRow[];

	// Posts per week
	const startD = new Date(start);
	const endD = new Date(end);
	const weeks = Math.max(daysBetween(startD, endD) / 7, 1);
	const postsPerWeek = postRows.length / weeks;

	// CES: (totalEngagement / postCount) / (followers / 1000), normalized
	const latestFollowers =
		rows.length > 0 ? rows[rows.length - 1]!.followers_count || 1 : 1;
	let ces = 0;
	if (postRows.length > 0 && latestFollowers > 0) {
		const totalEng = postRows.reduce(
			(sum: number, p) =>
				sum +
				(p.likes || 0) +
				(p.replies || 0) +
				(p.reposts || 0) +
				(p.shares || 0) +
				(p.comments || 0) +
				(p.saves || 0) +
				(p.quotes || 0),
			0,
		);
		const avgEng = totalEng / postRows.length;
		const raw = avgEng / (latestFollowers / 1000);
		// Normalize using same bands as contentEfficiencyScore.ts
		const bands: [number, number, number, number][] = [
			[0, 2, 1, 20],
			[2, 5, 20, 40],
			[5, 15, 40, 60],
			[15, 40, 60, 80],
			[40, 200, 80, 100],
		];
		ces = 100;
		for (const [rMin, rMax, sMin, sMax] of bands) {
			if (raw <= rMax) {
				const t = (raw - rMin) / (rMax - rMin);
				ces = Math.round(sMin + t * (sMax - sMin));
				break;
			}
		}
		if (raw <= 0) ces = 1;
	}

	// Top content type
	const typeCounts: Record<string, number> = {};
	for (const p of postRows) {
		const t = (p.media_type || "text").toUpperCase();
		typeCounts[t] = (typeCounts[t] || 0) + 1;
	}
	const topContentType =
		Object.entries(typeCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || "N/A";

	// Quick wins actioned
	const { count: quickWinsActioned } = await supabase
		.from("feature_usage")
		.select("id", { count: "exact", head: true })
		.eq("user_id", userId)
		.in("feature_name", [
			"QuickWins",
			"quick_win_applied",
			"recommendation_applied",
		])
		.gte("used_at", start)
		.lte("used_at", `${end}T23:59:59Z`);

	return {
		ces,
		avgEngagementRate: Math.round(avgEngagementRate * 100) / 100,
		postsPerWeek: Math.round(postsPerWeek * 10) / 10,
		totalViews,
		followerChange,
		topContentType,
		quickWinsActioned: quickWinsActioned || 0,
	};
}

export default withAuth(async (req, res, user) => {
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	const { accountId, startA, endA, startB, endB } = req.query as Record<
		string,
		string
	>;

	if (!accountId || !startA || !endA || !startB || !endB) {
		return apiError(
			res,
			400,
			"Missing required params: accountId, startA, endA, startB, endB",
		);
	}

	const dStartA = parseDate(startA);
	const dEndA = parseDate(endA);
	const dStartB = parseDate(startB);
	const dEndB = parseDate(endB);

	if (!dStartA || !dEndA || !dStartB || !dEndB) {
		return apiError(res, 400, "Invalid date format. Use YYYY-MM-DD.");
	}

	if (
		daysBetween(dStartA, dEndA) > MAX_RANGE_DAYS ||
		daysBetween(dStartB, dEndB) > MAX_RANGE_DAYS
	) {
		return apiError(
			res,
			400,
			`Each period must be ${MAX_RANGE_DAYS} days or less.`,
		);
	}

	if (dEndA >= dStartB) {
		return apiError(res, 400, "Period A must end before Period B starts.");
	}

	// Verify account ownership (IDOR prevention)
	const ownedAccount = await verifyAccountOwnership(res, accountId, user.id);
	if (!ownedAccount) return;

	try {
		const [periodA, periodB] = await Promise.all([
			fetchPeriodMetrics(accountId, user.id, startA, endA),
			fetchPeriodMetrics(accountId, user.id, startB, endB),
		]);

		return apiSuccess(res, { periodA, periodB });
	} catch (err: unknown) {
		logger.error("Self-compare error", { error: String(err) });
		return apiError(res, 500, "Failed to compute self-comparison");
	}
});
