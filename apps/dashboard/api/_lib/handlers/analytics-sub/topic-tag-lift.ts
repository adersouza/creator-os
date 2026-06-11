/**
 * Topic-tag lift — which topics are over-performing this window.
 *
 * GET /api/analytics?action=topic-tag-lift&accountId=X&periodDays=30&baselineDays=90&platform=threads
 *
 * Groups published posts by `topic_tag` and computes avg reach per topic for
 * the window vs. a longer baseline. IG uses `ig_reach`; Threads uses
 * `views_count` as the reach proxy. Lift = windowAvg / baselineAvg.
 * Surfaces tags punching above their own weight so operators know what to
 * double down on.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { getAccountIdsForContext } from "../../workspaceAccounts.js";
import { z, zEnum } from "../../zodCompat.js";

const QuerySchema = z.object({
	accountId: z.string().optional(),
	accountIds: z.string().optional(),
	platform: zEnum(["all", "instagram", "threads"]).optional().default("all"),
	periodDays: z.coerce.number().int().min(1).max(90).optional().default(30),
	baselineDays: z.coerce.number().int().min(7).max(365).optional().default(90),
	minPosts: z.coerce.number().int().min(1).max(50).optional().default(2),
	limit: z.coerce.number().int().min(1).max(20).optional().default(6),
	workspaceId: z.string().optional(),
});

// biome-ignore lint/suspicious/noExplicitAny: posts columns aren't fully in generated types
const db = (): any => getSupabase();

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const {
			accountId,
			accountIds: accountIdsStr,
			platform,
			periodDays,
			baselineDays,
			minPosts,
			limit,
			workspaceId,
		} = parsed;

		let targetAccountIds: string[] = [];
		if (accountIdsStr) {
			targetAccountIds = accountIdsStr.split(",").filter(Boolean);
		} else if (accountId && accountId !== "ALL") {
			targetAccountIds = [accountId];
		}

		if (targetAccountIds.length === 0) {
			targetAccountIds = await getAccountIdsForContext(
				user.id,
				workspaceId ?? null,
				platform === "all" ? undefined : platform,
			);
		} else {
			const allowed = new Set(
				await getAccountIdsForContext(
					user.id,
					workspaceId ?? null,
					platform === "all" ? undefined : platform,
				),
			);
			targetAccountIds = targetAccountIds.filter((id) => allowed.has(id));
		}

		if (targetAccountIds.length === 0) {
			return apiSuccess(res, { topics: [], periodDays, baselineDays });
		}

		const now = new Date();
		const windowStart = new Date(now);
		windowStart.setDate(windowStart.getDate() - periodDays);
		const baselineStart = new Date(now);
		baselineStart.setDate(baselineStart.getDate() - baselineDays);

		// One query for the full baseline — window overlaps baseline, so we
		// partition in memory rather than running two DB queries.
		let query = db()
			.from("posts")
			.select("platform, topic_tag, ig_reach, views_count, published_at")
			.eq("user_id", user.id)
			.eq("status", "published")
			.not("topic_tag", "is", null)
			.gte("published_at", baselineStart.toISOString());

		if (platform === "instagram") {
			query = query
				.eq("platform", "instagram")
				.in("instagram_account_id", targetAccountIds);
		} else if (platform === "threads") {
			query = query.eq("platform", "threads").in("account_id", targetAccountIds);
		} else {
			query = query.or(
				`account_id.in.(${targetAccountIds.join(",")}),instagram_account_id.in.(${targetAccountIds.join(",")})`,
			);
		}

		const { data: posts, error } = await query;
		if (error) {
			return apiError(res, 500, "Failed to load topic-tag lift", {
				details: error.message,
			});
		}

		interface Bucket {
			windowPosts: number;
			windowReach: number;
			baselinePosts: number;
			baselineReach: number;
		}
		const byTopic = new Map<string, Bucket>();

		for (const p of (posts || []) as Array<{
			platform: string | null;
			topic_tag: string | null;
			ig_reach: number | null;
			views_count: number | null;
			published_at: string;
		}>) {
			if (!p.topic_tag) continue;
			const reach =
				p.platform === "instagram" ? p.ig_reach || 0 : p.views_count || 0;
			if (reach <= 0) continue;
			const pubDate = new Date(p.published_at);
			const b = byTopic.get(p.topic_tag) || {
				windowPosts: 0,
				windowReach: 0,
				baselinePosts: 0,
				baselineReach: 0,
			};
			// Always count into baseline (baseline is the full period queried).
			b.baselinePosts += 1;
			b.baselineReach += reach;
			if (pubDate >= windowStart) {
				b.windowPosts += 1;
				b.windowReach += reach;
			}
			byTopic.set(p.topic_tag, b);
		}

		const topics = Array.from(byTopic.entries())
			.filter(([, b]) => b.windowPosts >= minPosts && b.baselinePosts >= minPosts)
			.map(([tag, b]) => {
				const windowAvg = b.windowReach / b.windowPosts;
				const baselineAvg = b.baselineReach / b.baselinePosts;
				const lift = baselineAvg > 0 ? windowAvg / baselineAvg : null;
				return {
					topic: tag,
					windowAvgReach: windowAvg,
					baselineAvgReach: baselineAvg,
					lift,
					windowPosts: b.windowPosts,
				};
			})
			.sort((a, b) => {
				if (a.lift == null && b.lift == null) return 0;
				if (a.lift == null) return 1;
				if (b.lift == null) return -1;
				return b.lift - a.lift;
			})
			.slice(0, limit);

		return apiSuccess(res, { topics, periodDays, baselineDays });
	},
);
