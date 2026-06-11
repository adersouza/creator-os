/**
 * Story profile activity — IG posts/stories ranked by profile lifts.
 *
 * GET /api/analytics?action=story-profile-activity&accountId=X&periodDays=7
 *
 * Reads posts.ig_post_profile_activity — a JSONB breakdown of action_types
 * Meta returns (profile_visits, follows, bio_link_taps, email_contacts, etc.).
 * Summed per post, ranked by profile_visits+follows since those are the two
 * actions users actively care about.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";

const QuerySchema = z.object({
	accountId: z.string().optional(),
	accountIds: z.string().optional(),
	periodDays: z.coerce.number().int().min(1).max(90).optional().default(7),
	limit: z.coerce.number().int().min(1).max(20).optional().default(5),
});

// biome-ignore lint/suspicious/noExplicitAny: JSONB column
const db = (): any => getSupabase();

type ProfileActivity =
	| Record<string, number>
	| Array<{ action_type?: string | null | undefined; value?: number | null | undefined }>;

interface ActivityTotals {
	profileVisits: number;
	follows: number;
	bioLinkTaps: number;
}

function addAction(total: ActivityTotals, key: string, value: number): void {
	const normalized = key.toLowerCase().replace(/[^a-z0-9]+/g, "_");
	if (normalized === "profile_visits" || normalized === "profile_visit") {
		total.profileVisits += value;
	} else if (normalized === "follows" || normalized === "follow") {
		total.follows += value;
	} else if (
		normalized === "bio_link_taps" ||
		normalized === "bio_link_tap" ||
		normalized === "bio_link_clicks" ||
		normalized === "website_clicks"
	) {
		total.bioLinkTaps += value;
	}
}

function normalizeActivity(
	activity: ProfileActivity | null,
	directProfileVisits = 0,
	directFollows = 0,
): ActivityTotals {
	const total: ActivityTotals = {
		profileVisits: Number(directProfileVisits) || 0,
		follows: Number(directFollows) || 0,
		bioLinkTaps: 0,
	};
	if (Array.isArray(activity)) {
		for (const item of activity) {
			addAction(total, item.action_type || "", Number(item.value) || 0);
		}
	} else if (activity && typeof activity === "object") {
		for (const [key, value] of Object.entries(activity)) {
			addAction(total, key, Number(value) || 0);
		}
	}
	return total;
}

function scoreActivity(a: ActivityTotals): number {
	return a.profileVisits + a.follows * 3; // weight follows more heavily — higher intent.
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, accountIds: accountIdsStr, periodDays, limit } = parsed;

		let targetAccountIds: string[] = [];
		if (accountIdsStr) {
			targetAccountIds = accountIdsStr.split(",").filter(Boolean);
		} else if (accountId && accountId !== "ALL") {
			targetAccountIds = [accountId];
		}

		if (targetAccountIds.length === 0) {
			const { data: igAccounts } = await db()
				.from("instagram_accounts")
				.select("id")
				.eq("user_id", user.id);
			targetAccountIds = (igAccounts || []).map((a: { id: string }) => a.id);
		} else {
			const { data: owned } = await db()
				.from("instagram_accounts")
				.select("id")
				.eq("user_id", user.id)
				.in("id", targetAccountIds);
			targetAccountIds = (owned || []).map((a: { id: string }) => a.id);
		}

		if (targetAccountIds.length === 0) {
			return apiSuccess(res, { posts: [], periodDays });
		}

		const cutoff = new Date();
		cutoff.setDate(cutoff.getDate() - periodDays);

		const { data: rows } = await db()
			.from("posts")
			.select(
				"id, content, published_at, permalink, ig_post_profile_activity, ig_profile_visits, ig_follows_count, media_type",
			)
			.in("instagram_account_id", targetAccountIds)
			.eq("user_id", user.id)
			.eq("status", "published")
			.gte("published_at", cutoff.toISOString());

		const scored = ((rows || []) as Array<{
			id: string;
			content: string | null;
			published_at: string;
			permalink: string | null;
			ig_post_profile_activity: ProfileActivity | null;
			ig_profile_visits: number | null;
			ig_follows_count: number | null;
			media_type: string | null;
		}>)
			.map((r) => {
				const activity = normalizeActivity(
					r.ig_post_profile_activity,
					r.ig_profile_visits || 0,
					r.ig_follows_count || 0,
				);
				return {
					id: r.id,
					content: r.content,
					publishedAt: r.published_at,
					permalink: r.permalink,
					mediaType: r.media_type,
					profileVisits: activity.profileVisits,
					follows: activity.follows,
					bioLinkTaps: activity.bioLinkTaps,
					score: scoreActivity(activity),
				};
			})
			.filter((p) => p.score > 0)
			.sort((a, b) => b.score - a.score)
			.slice(0, limit);

		return apiSuccess(res, { posts: scored, periodDays });
	},
);
