/**
 * Quality-weighted engagement by content pillar.
 *
 * GET /api/analytics?action=quality-by-pillar&periodDays=30
 *
 * Mockup: new-widgets-2026.html #6 ("Quality-weighted engagement · by content
 * pillar"). Surfaces which pillars (content_category) are punching above their
 * weight on quality signals (saves + sends ÷ reach), the Mosseri-validated
 * "real engagement" metric.
 *
 * Source columns:
 *   - posts.content_category (already populated by the AI classifier — 744
 *     rows in prod with values like "engagement-bait", "entertainment",
 *     "inspirational", "educational", etc.)
 *   - posts.ig_saved + posts.ig_shares + posts.ig_reach (per-post IG signals)
 *   - posts.shares_count + posts.reposts_count + posts.views_count (Threads)
 *
 * Returns ranked pillars with QWE = (saves+sends) / reach × 100, post counts,
 * and reach. Filters out pillars with < minPosts (default 2) so a single hit
 * doesn't define a category.
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
	minPosts: z.coerce.number().int().min(1).max(50).optional().default(2),
	platform: zEnum(["all", "instagram", "threads"]).optional().default("all"),
	workspaceId: z.string().optional(),
});

// biome-ignore lint/suspicious/noExplicitAny: posts columns aren't all in generated types
const db = (): any => getSupabase();

interface PillarRow {
	pillar: string;
	postCount: number;
	totalReach: number;
	totalSaves: number;
	totalSends: number;
	qwe: number; // 0-100 percent
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, accountIds, periodDays, minPosts, platform, workspaceId } =
			parsed;

		// Scope: explicit accountIds list, single accountId, or every account
		// in the user's context (workspace-aware).
		let candidateIds: string[] = accountIds
			? accountIds
					.split(",")
					.map((s) => s.trim())
					.filter(Boolean)
			: accountId && accountId !== "ALL"
				? [accountId]
				: await getAccountIdsForContext(
						user.id,
						workspaceId ?? null,
						platform === "all" ? undefined : platform,
					);

		// Always re-scope through the workspace allow-list — never trust client
		// IDs without checking ownership.
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
			return apiSuccess(res, { pillars: [], periodDays, platform });
		}

		const cutoff = new Date(Date.now() - periodDays * 86_400_000).toISOString();

		// One query covering both platforms — IG account_id and Threads
		// account_id share the same column; instagram_account_id is the
		// platform-specific FK on IG rows.
		let query = db()
			.from("posts")
			.select(
				"platform, content_category, ig_reach, ig_saved, ig_shares, views_count, shares_count, reposts_count",
			)
			.eq("user_id", user.id)
			.eq("status", "published")
			.not("content_category", "is", null)
			.gte("published_at", cutoff);

		if (platform === "instagram") {
			query = query.eq("platform", "instagram").in("instagram_account_id", candidateIds);
		} else if (platform === "threads") {
			query = query.eq("platform", "threads").in("account_id", candidateIds);
		} else {
			// All view: union via .or() on the FK columns. This is the same
			// pattern the follower-attribution handler uses.
			query = query.or(
				`account_id.in.(${candidateIds.join(",")}),instagram_account_id.in.(${candidateIds.join(",")})`,
			);
		}

		const { data: rows, error } = await query;

		if (error) {
			return apiError(res, 500, "Failed to load pillar data", {
				details: error.message,
			});
		}

		const byPillar = new Map<string, PillarRow>();
		for (const r of (rows || []) as Array<{
			platform: string;
			content_category: string | null;
			ig_reach: number | null;
			ig_saved: number | null;
			ig_shares: number | null;
			views_count: number | null;
			shares_count: number | null;
			reposts_count: number | null;
		}>) {
			if (!r.content_category) continue;
			const isIg = r.platform === "instagram";
			const reach = isIg
				? r.ig_reach || 0
				: // Threads doesn't expose reach distinct from views — views_count is
					// the closest proxy. Document it on the response so the tile can
					// label accordingly.
					r.views_count || 0;
			const saves = isIg ? r.ig_saved || 0 : 0; // Threads has no save-equivalent
			// Sends = IG shares + Threads reposts/shares (any "amplify" action)
			const sends = isIg
				? r.ig_shares || 0
				: (r.shares_count || 0) + (r.reposts_count || 0);

			const existing = byPillar.get(r.content_category) ?? {
				pillar: r.content_category,
				postCount: 0,
				totalReach: 0,
				totalSaves: 0,
				totalSends: 0,
				qwe: 0,
			};
			existing.postCount += 1;
			existing.totalReach += reach;
			existing.totalSaves += saves;
			existing.totalSends += sends;
			byPillar.set(r.content_category, existing);
		}

		// Filter thin samples + compute QWE.
		const pillars: PillarRow[] = [];
		for (const p of byPillar.values()) {
			if (p.postCount < minPosts) continue;
			p.qwe =
				p.totalReach > 0
					? ((p.totalSaves + p.totalSends) / p.totalReach) * 100
					: 0;
			pillars.push(p);
		}

		pillars.sort((a, b) => b.qwe - a.qwe);

		return apiSuccess(res, {
			pillars,
			periodDays,
			platform,
			thresholdMinPosts: minPosts,
			// Threads contribution to "reach" uses views_count as a proxy. The
			// frontend tile should label that in the legend.
			notes: {
				threadsReachProxy: "views_count",
				igReachField: "ig_reach",
				sendsFormula:
					"IG: ig_shares; Threads: shares_count + reposts_count",
				savesFormula: "IG: ig_saved; Threads: 0 (no save equivalent)",
			},
		});
	},
);
