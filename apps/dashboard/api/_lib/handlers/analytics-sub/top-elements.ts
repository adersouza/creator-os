// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Top Content Elements Analysis
 *
 * GET /api/analytics/top-elements?accountId=...&days=30
 * Analyzes hashtags, CTAs, caption lengths, and media types.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { verifyAccountOwnership } from "../helpers/verifyOwnership.js";

const TopElementsQuerySchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	days: z.coerce.number().int().min(1).max(90).optional().default(30),
});

// biome-ignore lint/suspicious/noExplicitAny: table not yet in generated types
const db = (): any => getSupabase();

const CTA_PATTERNS: Record<string, RegExp> = {
	link_in_bio: /link\s*(in|on)\s*(my\s+)?bio/i,
	follow_me: /follow\s+(me|us|@)/i,
	comment_below: /comment\s*(below|down|here|your)/i,
	share_this: /share\s*(this|it|with)/i,
	question: /\?\s*$/m,
	save_this: /save\s*(this|it|for)/i,
};

function extractHashtags(text: string): string[] {
	const matches = text.match(/#[a-zA-Z0-9_]+/g);
	return matches ? matches.map((t) => t.toLowerCase()) : [];
}

function getCaptionBucket(length: number): string {
	if (length <= 50) return "short";
	if (length <= 150) return "medium";
	if (length <= 300) return "long";
	return "very_long";
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") {
			return apiError(res, 405, "Method not allowed");
		}

		const userId = user.id;
		const parsed = parseQueryOrError(res, TopElementsQuerySchema, req.query);
		if (!parsed) return;
		const { accountId, days } = parsed;

		// Verify account
		const account = await verifyAccountOwnership(res, accountId, userId);
		if (!account) return;

		const cutoff = new Date(Date.now() - days * 86_400_000).toISOString();

		const { data: posts, error: postsError } = await db()
			.from("posts")
			.select(
				"id, content, views_count, likes_count, replies_count, media_type, created_at",
			)
			.eq("account_id", accountId)
			.eq("user_id", userId)
			.eq("status", "published")
			.gte("created_at", cutoff)
			.order("created_at", { ascending: false });

		if (postsError)
			return apiError(res, 500, "Failed to fetch posts", {
				details: postsError.message,
			});

		const allPosts = posts ?? [];

		if (allPosts.length === 0) {
			return apiSuccess(res, {
				periodDays: days,
				totalPosts: 0,
				hashtags: [],
				ctas: [],
				captionLengths: [],
				mediaTypes: [],
			});
		}

		// Hashtag analysis
		const hashtagStats: Record<
			string,
			{ uses: number; totalEngagement: number }
		> = {};

		// CTA analysis
		const ctaStats: Record<string, { uses: number; totalEngagement: number }> =
			{};

		// Caption length buckets
		const lengthBuckets: Record<
			string,
			{ count: number; totalEngagement: number }
		> = {
			short: { count: 0, totalEngagement: 0 },
			medium: { count: 0, totalEngagement: 0 },
			long: { count: 0, totalEngagement: 0 },
			very_long: { count: 0, totalEngagement: 0 },
		};

		// Media type analysis
		const mediaStats: Record<
			string,
			{ count: number; totalEngagement: number; totalReach: number }
		> = {};

		for (const p of allPosts) {
			const content = p.content ?? "";
			const engagement = (p.likes_count ?? 0) + (p.replies_count ?? 0);
			const reach = p.views_count ?? 0;

			// Hashtags
			const tags = extractHashtags(content);
			for (const tag of tags) {
				if (!hashtagStats[tag])
					hashtagStats[tag] = { uses: 0, totalEngagement: 0 };
				hashtagStats[tag].uses++;
				hashtagStats[tag].totalEngagement += engagement;
			}

			// CTAs
			for (const [ctaName, pattern] of Object.entries(CTA_PATTERNS)) {
				if (pattern.test(content)) {
					if (!ctaStats[ctaName])
						ctaStats[ctaName] = { uses: 0, totalEngagement: 0 };
					ctaStats[ctaName].uses++;
					ctaStats[ctaName].totalEngagement += engagement;
				}
			}

			// Caption length
			const bucket = getCaptionBucket(content.length);
			lengthBuckets[bucket]!.count++;
			lengthBuckets[bucket]!.totalEngagement += engagement;

			// Media type
			const mediaType = p.media_type ?? "text";
			if (!mediaStats[mediaType])
				mediaStats[mediaType] = { count: 0, totalEngagement: 0, totalReach: 0 };
			mediaStats[mediaType].count++;
			mediaStats[mediaType].totalEngagement += engagement;
			mediaStats[mediaType].totalReach += reach;
		}

		// Format results
		const hashtags = Object.entries(hashtagStats)
			.filter(([_, s]) => s.uses >= 2)
			.map(([tag, s]) => ({
				tag,
				uses: s.uses,
				avgEngagement: Math.round((s.totalEngagement / s.uses) * 10) / 10,
			}))
			.sort((a, b) => b.avgEngagement - a.avgEngagement)
			.slice(0, 10);

		const ctas = Object.entries(ctaStats)
			.map(([name, s]) => ({
				name,
				uses: s.uses,
				avgEngagement: Math.round((s.totalEngagement / s.uses) * 10) / 10,
			}))
			.sort((a, b) => b.avgEngagement - a.avgEngagement);

		const captionLengths = Object.entries(lengthBuckets)
			.filter(([_, s]) => s.count > 0)
			.map(([bucket, s]) => ({
				bucket,
				range:
					bucket === "short"
						? "0-50"
						: bucket === "medium"
							? "50-150"
							: bucket === "long"
								? "150-300"
								: "300+",
				count: s.count,
				avgEngagement: Math.round((s.totalEngagement / s.count) * 10) / 10,
			}));

		const mediaTypes = Object.entries(mediaStats)
			.map(([type, s]) => ({
				type,
				count: s.count,
				avgEngagement: Math.round((s.totalEngagement / s.count) * 10) / 10,
				avgReach: Math.round(s.totalReach / s.count),
			}))
			.sort((a, b) => b.avgEngagement - a.avgEngagement);

		return apiSuccess(res, {
			periodDays: days,
			totalPosts: allPosts.length,
			hashtags,
			ctas,
			captionLengths,
			mediaTypes,
		});
	},
);
