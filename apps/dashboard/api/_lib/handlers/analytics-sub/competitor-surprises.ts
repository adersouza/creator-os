// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Competitor surprises — competitor posts outperforming their own baseline.
 *
 * GET /api/analytics?action=competitor-surprises&windowHours=48&baselineDays=30&minMultiplier=3
 *
 * Pulls competitor_top_posts with rankable engagement metrics for the user's watched competitors. For each
 * competitor, computes the median engagement_score across their baseline
 * window, then flags posts in the recent window that hit ≥ minMultiplier
 * × median. Surfaces the format/hook worth reverse-engineering.
 *
 * Rows with stats_unavailable and partial_engagement are excluded; they belong
 * in pattern benchmarks, not performance surprise reporting.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";

const QuerySchema = z.object({
	windowHours: z.coerce.number().int().min(1).max(168).optional().default(48),
	baselineDays: z.coerce.number().int().min(7).max(365).optional().default(30),
	minMultiplier: z.coerce.number().min(1.5).max(20).optional().default(3),
	minBaselinePosts: z.coerce.number().int().min(1).max(100).optional().default(5),
	limit: z.coerce.number().int().min(1).max(20).optional().default(5),
});

// biome-ignore lint/suspicious/noExplicitAny: JOINs across competitor tables
const db = (): any => getSupabase();

function median(values: number[]): number {
	if (values.length === 0) return 0;
	const sorted = [...values].sort((a, b) => a - b);
	const mid = Math.floor(sorted.length / 2);
	if (sorted.length % 2 === 0) return (sorted[mid - 1]! + sorted[mid]!) / 2;
	return sorted[mid]!;
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const {
			windowHours,
			baselineDays,
			minMultiplier,
			minBaselinePosts,
			limit,
		} = parsed;

		const now = Date.now();
		const windowStart = new Date(now - windowHours * 60 * 60 * 1000);
		const baselineStart = new Date(now - baselineDays * 24 * 60 * 60 * 1000);

		// Pull all competitor posts in the baseline window for this user.
		// competitor_top_posts has user_id, so RLS + scoping stays direct.
		const { data: posts } = await db()
			.from("competitor_top_posts")
			.select(
				"id, competitor_id, competitor_username, content, published_at, permalink, engagement_score, like_count, reply_count, repost_count, view_count, metric_quality",
			)
			.eq("user_id", user.id)
			.in("metric_quality", ["valid_engagement", "scraper_estimated"])
			.gte("published_at", baselineStart.toISOString())
			.not("published_at", "is", null)
			.not("engagement_score", "is", null);

		if (!posts || posts.length === 0) {
			return apiSuccess(res, {
				surprises: [],
				windowHours,
				baselineDays,
				metricQuality: "valid_engagement_or_scraper_estimated_required",
				message:
					"No competitor posts have rankable engagement metrics; use competitor pattern benchmarks instead.",
			});
		}

		// Bucket by competitor so median is per-account, not fleet-wide.
		type Row = {
			id: string;
			competitor_id: string;
			competitor_username: string | null;
			content: string | null;
			published_at: string;
			permalink: string | null;
			engagement_score: number | null;
			like_count: number | null;
			reply_count: number | null;
			repost_count: number | null;
			view_count: number | null;
			metric_quality: string | null;
		};

		const byCompetitor = new Map<string, Row[]>();
		for (const p of posts as Row[]) {
			const arr = byCompetitor.get(p.competitor_id) || [];
			arr.push(p);
			byCompetitor.set(p.competitor_id, arr);
		}

		const surprises = [];
		for (const [, rows] of byCompetitor) {
			if (rows.length < minBaselinePosts) continue;
			const scores = rows
				.map((r) => r.engagement_score || 0)
				.filter((s) => s > 0);
			if (scores.length < minBaselinePosts) continue;
			const medianScore = median(scores);
			if (medianScore <= 0) continue;

			for (const r of rows) {
				const pubDate = new Date(r.published_at);
				if (pubDate < windowStart) continue;
				const score = r.engagement_score || 0;
				if (score <= 0) continue;
				const multiplier = score / medianScore;
				if (multiplier < minMultiplier) continue;
				surprises.push({
					id: r.id,
					competitorId: r.competitor_id,
					competitorUsername: r.competitor_username,
					content: r.content,
					permalink: r.permalink,
					publishedAt: r.published_at,
					engagementScore: score,
					medianScore,
					multiplier,
					likes: r.like_count || 0,
					replies: r.reply_count || 0,
					reposts: r.repost_count || 0,
					views: r.view_count || 0,
					metricQuality: r.metric_quality,
				});
			}
		}

		surprises.sort((a, b) => b.multiplier - a.multiplier);
		return apiSuccess(res, {
			surprises: surprises.slice(0, limit),
			windowHours,
			baselineDays,
		});
	},
);
