// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Handler: POST /api/competitors?action=ig-add
 *
 * Add an Instagram competitor via business discovery.
 */

import { apiError, apiSuccess } from "../../../apiResponse.js";
import { logger } from "../../../logger.js";
import { CompetitorIgAddSchema } from "../../../validation.js";
import { withAuthAndBody } from "../../helpers/withAuthAndBody.js";
import { calculateIgMetrics, db, getIgAccount } from "../shared.js";

interface IgMediaPost {
	id: string;
	caption?: string | null | undefined;
	like_count?: number | null | undefined;
	comments_count?: number | null | undefined;
	media_url?: string | null | undefined;
	media_type?: string | null | undefined;
	permalink?: string | null | undefined;
	timestamp?: string | null | undefined;
}

interface IgProfile {
	username: string;
	name?: string | undefined;
	biography?: string | undefined;
	followers_count?: number | undefined;
	media_count?: number | undefined;
	profile_picture_url?: string | undefined;
	website?: string | undefined;
	media?: { data?: IgMediaPost[] | undefined } | undefined;
}

export const handleIgAdd = withAuthAndBody(
	CompetitorIgAddSchema,
	async (user, parsed, _req, res) => {
		const { accountId, targetUsername } = parsed;

		const account = await getIgAccount(user.id, accountId);
		if (!account) return apiError(res, 404, "Instagram account not found");

		const cleanUsername = targetUsername.replace(/^@/, "").trim();

		const { getBusinessDiscovery } = await import("../../../instagramApi.js");
		const result = await getBusinessDiscovery(
			account.instagram_access_token_encrypted as string,
			account.instagram_user_id as string,
			cleanUsername,
			12,
		);

		if (!result.success) {
			return apiError(res, 404, result.error || `@${cleanUsername} not found`);
		}

		const profile = result.profile as unknown as IgProfile;

		// Check if already exists
		const { data: existing } = await db()
			.from("competitors")
			.select("id")
			.eq("user_id", user.id)
			.eq("platform", "instagram")
			.eq("username", profile.username)
			.maybeSingle();

		if (existing) {
			return apiError(res, 400, "Competitor already tracked");
		}

		const media = profile.media?.data || [];
		const { avgLikes, avgComments, engagementRate } = calculateIgMetrics(
			media,
			profile.followers_count || 0,
		);

		// Insert competitor
		const { data: competitor, error: insertError } = await db()
			.from("competitors")
			.insert({
				user_id: user.id,
				platform: "instagram",
				threads_user_id: profile.username, // reuse column for identifier
				instagram_user_id: profile.username,
				username: profile.username,
				display_name: profile.name || profile.username,
				avatar_url: profile.profile_picture_url || "",
				bio: profile.biography || "",
				follower_count: profile.followers_count || 0,
				media_count: profile.media_count || 0,
				avg_likes: avgLikes,
				avg_comments: avgComments,
				engagement_rate: engagementRate,
				website: profile.website || "",
				is_verified: false,
				added_at: new Date().toISOString(),
				last_synced_at: new Date().toISOString(),
				// biome-ignore lint/suspicious/noExplicitAny: Supabase insert missing columns in generated types
			} as any)
			.select()
			.maybeSingle();

		if (insertError) {
			logger.error("IG competitor insert error", {
				error: String(insertError),
			});
			return apiError(res, 500, "Failed to add competitor");
		}
		if (!competitor) return apiError(res, 500, "Failed to add competitor");

		// Store initial snapshot
		const today = new Date().toISOString().split("T")[0]!;
		await db()
			.from("competitor_snapshots")
			.upsert(
				{
					competitor_id: competitor.id,
					snapshot_date: today,
					follower_count: profile.followers_count || 0,
					// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert missing columns in generated types
				} as any,
				{ onConflict: "competitor_id,snapshot_date" },
			);

		// Store top posts
		if (media.length > 0) {
			const topPosts = (media as IgMediaPost[])
				.sort(
					(a: IgMediaPost, b: IgMediaPost) =>
						(b.like_count || 0) +
						(b.comments_count || 0) -
						((a.like_count || 0) + (a.comments_count || 0)),
				)
				.slice(0, 10)
				.map((post: IgMediaPost) => ({
					competitor_id: competitor.id,
					platform: "instagram",
					threads_post_id: post.id,
					content: post.caption || "",
					like_count: post.like_count || 0,
					comments_count: post.comments_count || 0,
					engagement_score:
						(post.like_count || 0) + (post.comments_count || 0) * 3,
					media_url: post.media_url || "",
					media_type: post.media_type || "IMAGE",
					permalink: post.permalink || "",
					published_at: post.timestamp,
					fetched_at: new Date().toISOString(),
				}));

			await db()
				.from("competitor_top_posts")
				// biome-ignore lint/suspicious/noExplicitAny: Supabase insert
				.insert(topPosts as any);
		}

		return apiSuccess(res, { competitor });
	},
);
