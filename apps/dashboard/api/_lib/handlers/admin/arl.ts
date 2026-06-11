// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * GET /api/admin/arl — Actioned Recommendation Lift (ARL) KPI
 *
 * Admin-only. Computes median % improvement in target metric
 * across all actioned Quick Wins with 14+ days of post-action data.
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAdminRole } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";

function median(arr: number[]): number {
	if (arr.length === 0) return 0;
	const sorted = [...arr].sort((a, b) => a - b);
	const mid = Math.floor(sorted.length / 2);
	return sorted.length % 2 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2;
}

export default withAdminRole(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		// #671: Rate limit admin endpoints
		const { checkRateLimit } = await import("../../rateLimiter.js");
		const rl = await checkRateLimit({
			key: `admin-arl:${user.id}`,
			limit: 30,
			windowSeconds: 60,
			failMode: "open",
		});
		if (!rl.allowed) return apiError(res, 429, "Rate limit exceeded");

		const supabase = getSupabase();

		const fourteenDaysAgo = new Date(
			Date.now() - 14 * 24 * 60 * 60 * 1000,
		).toISOString();

		// Get all actioned recommendations with 14+ days of post-action data
		// biome-ignore lint/suspicious/noExplicitAny: Supabase type instantiation depth
		const { data: actioned, error: fetchErr } = await (supabase as any)
			.from("recommendation_dismissals")
			.select("*")
			.eq("actioned", true)
			.lt("actioned_at", fourteenDaysAgo);

		if (fetchErr || !actioned || actioned.length === 0) {
			return apiSuccess(res, { arl: 0, sampleSize: 0, byCategory: {} });
		}

		const improvements: number[] = [];
		const byCategory: Record<string, number[]> = {};

		for (const rec of actioned) {
			const actionedAt = new Date(rec.actioned_at ?? "");
			const beforeStart = new Date(
				actionedAt.getTime() - 14 * 24 * 60 * 60 * 1000,
			).toISOString();
			const beforeEnd = rec.actioned_at;
			const afterStart = rec.actioned_at;
			const afterEnd = new Date(
				actionedAt.getTime() + 14 * 24 * 60 * 60 * 1000,
			).toISOString();

			// Query account_analytics for before/after periods
			const { data: beforeData } = await supabase
				.from("account_analytics")
				.select("engagement_rate, followers_count")
				.eq("account_id", rec.account_id)
				.gte("recorded_at", beforeStart)
				.lt("recorded_at", beforeEnd);

			const { data: afterData } = await supabase
				.from("account_analytics")
				.select("engagement_rate, followers_count")
				.eq("account_id", rec.account_id)
				.gte("recorded_at", afterStart)
				.lt("recorded_at", afterEnd);

			if (!beforeData?.length || !afterData?.length) continue;

			// Use engagement_rate as target metric
			const avgBefore =
				beforeData.reduce(
					(s: number, r: { engagement_rate: number | null }) =>
						s + (r.engagement_rate || 0),
					0,
				) / beforeData.length;
			const avgAfter =
				afterData.reduce(
					(s: number, r: { engagement_rate: number | null }) =>
						s + (r.engagement_rate || 0),
					0,
				) / afterData.length;

			if (avgBefore <= 0) continue;

			const pctImprovement = ((avgAfter - avgBefore) / avgBefore) * 100;
			improvements.push(pctImprovement);

			const cat = rec.category || "other";
			if (!byCategory[cat]) byCategory[cat] = [];
			byCategory[cat].push(pctImprovement);
		}

		const byCategoryMedian: Record<string, number> = {};
		for (const [cat, values] of Object.entries(byCategory)) {
			byCategoryMedian[cat] = Math.round(median(values) * 10) / 10;
		}

		return apiSuccess(res, {
			arl: Math.round(median(improvements) * 10) / 10,
			sampleSize: improvements.length,
			byCategory: byCategoryMedian,
		});
	},
);
