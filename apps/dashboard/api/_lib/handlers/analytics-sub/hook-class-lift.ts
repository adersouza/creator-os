/**
 * First-line hook lift — which opening-line archetypes drive the most reach.
 *
 * GET /api/analytics?action=hook-class-lift&periodDays=30
 *
 * Mockup: dashboard-research-validated-2026.html R6 ("First-line hook NLP").
 *
 * Reads posts.hook_class (populated by hookClassifier in the analytics-pipeline
 * Phase 4). Returns per-class avg reach + post count + a "lift" multiplier
 * (class avg ÷ overall avg). Filters thin samples (<minPosts).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z, zEnum } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { getAccountIdsForContext } from "../../workspaceAccounts.js";

const QuerySchema = z.object({
	accountId: z.string().optional(),
	accountIds: z.string().optional(),
	periodDays: z.coerce.number().int().min(1).max(90).optional().default(30),
	minPosts: z.coerce.number().int().min(1).max(50).optional().default(3),
	minConfidence: z.coerce.number().min(0).max(1).optional().default(0.5),
	platform: zEnum(["all", "instagram", "threads"]).optional().default("all"),
	workspaceId: z.string().optional(),
});

// biome-ignore lint/suspicious/noExplicitAny: posts columns aren't all in generated types
const db = (): any => getSupabase();

interface HookRow {
	hookClass: string;
	postCount: number;
	totalReach: number;
	avgReach: number;
	lift: number; // 1.0 = class avg matches overall fleet avg
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, accountIds, periodDays, minPosts, minConfidence, platform, workspaceId } = parsed;

		let candidateIds: string[] = accountIds
			? accountIds.split(",").map((s) => s.trim()).filter(Boolean)
			: accountId && accountId !== "ALL"
				? [accountId]
				: await getAccountIdsForContext(
						user.id,
						workspaceId ?? null,
						platform === "all" ? undefined : platform,
					);
		if (candidateIds.length > 0) {
			const allowed = new Set(
				await getAccountIdsForContext(
					user.id,
					workspaceId ?? null,
					platform === "all" ? undefined : platform,
				),
			);
			candidateIds = candidateIds.filter((id) => allowed.has(id));
		}

		if (candidateIds.length === 0) {
			return apiSuccess(res, { hooks: [], periodDays, fleetAvgReach: 0, platform });
		}

		const cutoff = new Date(Date.now() - periodDays * 86_400_000).toISOString();

		let query = db()
			.from("posts")
			.select(
				"platform, hook_class, hook_class_confidence, ig_reach, views_count",
			)
			.eq("user_id", user.id)
			.eq("status", "published")
			.not("hook_class", "is", null)
			.gte("hook_class_confidence", minConfidence)
			.gte("published_at", cutoff);

		if (platform === "instagram") {
			query = query.eq("platform", "instagram").in("instagram_account_id", candidateIds);
		} else if (platform === "threads") {
			query = query.eq("platform", "threads").in("account_id", candidateIds);
		} else {
			query = query.or(
				`account_id.in.(${candidateIds.join(",")}),instagram_account_id.in.(${candidateIds.join(",")})`,
			);
		}

		const { data: rows, error } = await query;
		if (error) {
			return apiError(res, 500, "Failed to load hook lift", {
				details: error.message,
			});
		}

		const buckets = new Map<string, { count: number; sumReach: number }>();
		let fleetReach = 0;
		let fleetCount = 0;
		for (const r of (rows || []) as Array<{
			platform: string;
			hook_class: string | null;
			ig_reach: number | null;
			views_count: number | null;
		}>) {
			if (!r.hook_class) continue;
			const reach =
				r.platform === "instagram" ? r.ig_reach || 0 : r.views_count || 0;
			fleetReach += reach;
			fleetCount += 1;
			const b = buckets.get(r.hook_class) ?? { count: 0, sumReach: 0 };
			b.count += 1;
			b.sumReach += reach;
			buckets.set(r.hook_class, b);
		}
		const fleetAvg = fleetCount > 0 ? fleetReach / fleetCount : 0;

		const hooks: HookRow[] = [];
		for (const [hookClass, b] of buckets.entries()) {
			if (b.count < minPosts) continue;
			const avgReach = b.sumReach / b.count;
			hooks.push({
				hookClass,
				postCount: b.count,
				totalReach: b.sumReach,
				avgReach,
				lift: fleetAvg > 0 ? avgReach / fleetAvg : 0,
			});
		}
		hooks.sort((a, b) => b.lift - a.lift);

		return apiSuccess(res, {
			hooks,
			fleetAvgReach: fleetAvg,
			fleetPostCount: fleetCount,
			periodDays,
			platform,
			thresholdMinPosts: minPosts,
			thresholdMinConfidence: minConfidence,
			notes: {
				reachField:
					"IG: ig_reach. Threads: views_count (closest reach proxy — Threads API does not expose distinct reach).",
			},
		});
	},
);
