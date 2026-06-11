/**
 * Cross-account patterns — topics lifting across multiple accounts.
 *
 * GET /api/analytics?action=cross-account-patterns&periodDays=30&minAccounts=2
 *
 * Groups the user's published posts by topic_tag. Surfaces tags where
 * ≥ minAccounts accounts have posted AND fleet avg reach for that tag
 * exceeds the fleet baseline (avg reach across all tags). The lift
 * multiplier ranks the patterns.
 *
 * This is the cheap MVP of widget #16 — no cluster-on-audio, no
 * hook-fingerprint. Just the cross-account overlap signal. A future pass
 * can expand to audio_id when that capture lands.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";

const QuerySchema = z.object({
	periodDays: z.coerce.number().int().min(7).max(180).optional().default(30),
	minAccounts: z.coerce.number().int().min(2).max(20).optional().default(2),
	minPosts: z.coerce.number().int().min(1).max(50).optional().default(3),
	limit: z.coerce.number().int().min(1).max(20).optional().default(6),
});

// biome-ignore lint/suspicious/noExplicitAny: posts columns aren't fully in generated types
const db = (): any => getSupabase();

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { periodDays, minAccounts, minPosts, limit } = parsed;

		const { data: accounts } = await db()
			.from("accounts")
			.select("id")
			.eq("user_id", user.id);
		const accountIds = (accounts || []).map((a: { id: string }) => a.id);
		if (accountIds.length < minAccounts) {
			return apiSuccess(res, { patterns: [], periodDays, reason: "not-enough-accounts" });
		}

		const cutoff = new Date();
		cutoff.setDate(cutoff.getDate() - periodDays);

		// `posts` has no bare `reach` column — past code selected a phantom
		// column so the endpoint silently returned empty for everyone. Use
		// `ig_reach` for Instagram and `views_count` for Threads (per memory:
		// Threads reach uses views as the closest API-backed proxy).
		const { data: posts } = await db()
			.from("posts")
			.select("topic_tag, ig_reach, views_count, account_id")
			.in("account_id", accountIds)
			.eq("user_id", user.id)
			.eq("status", "published")
			.not("topic_tag", "is", null)
			.gte("published_at", cutoff.toISOString());

		if (!posts || posts.length === 0) {
			return apiSuccess(res, { patterns: [], periodDays });
		}

		type Row = {
			topic_tag: string | null;
			ig_reach: number | null;
			views_count: number | null;
			account_id: string;
		};
		// Per-tag aggregation: account set, post count, total reach.
		const byTag = new Map<
			string,
			{ accounts: Set<string>; posts: number; totalReach: number }
		>();
		let fleetReach = 0;
		let fleetPosts = 0;
		for (const p of posts as Row[]) {
			if (!p.topic_tag) continue;
			const reach = p.ig_reach ?? p.views_count ?? 0;
			if (reach <= 0) continue;
			fleetReach += reach;
			fleetPosts += 1;
			const bucket = byTag.get(p.topic_tag) || {
				accounts: new Set<string>(),
				posts: 0,
				totalReach: 0,
			};
			bucket.accounts.add(p.account_id);
			bucket.posts += 1;
			bucket.totalReach += reach;
			byTag.set(p.topic_tag, bucket);
		}

		const fleetAvgReach = fleetPosts > 0 ? fleetReach / fleetPosts : 0;
		if (fleetAvgReach === 0) {
			return apiSuccess(res, { patterns: [], periodDays });
		}

		const patterns = Array.from(byTag.entries())
			.filter(
				([, b]) => b.accounts.size >= minAccounts && b.posts >= minPosts,
			)
			.map(([tag, b]) => {
				const tagAvgReach = b.totalReach / b.posts;
				return {
					topic: tag,
					accountCount: b.accounts.size,
					posts: b.posts,
					avgReach: tagAvgReach,
					lift: fleetAvgReach > 0 ? tagAvgReach / fleetAvgReach : 1,
				};
			})
			.filter((p) => p.lift > 1)
			.sort((a, b) => b.lift - a.lift)
			.slice(0, limit);

		return apiSuccess(res, {
			patterns,
			periodDays,
			fleetAvgReach,
		});
	},
);
