// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Handler: POST /api/competitors?action=ig-sync
 *
 * Sync an Instagram competitor's profile and posts.
 */

import { apiError, apiSuccess } from "../../../apiResponse.js";
import { logger } from "../../../logger.js";
import { getSupabaseAny } from "../../../supabase.js";
import { CompetitorIgSyncSchema } from "../../../validation.js";
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

export const handleIgSync = withAuthAndBody(
	CompetitorIgSyncSchema,
	async (user, parsed, _req, res) => {
		const { competitorId, accountId } = parsed;

		const { data: competitor } = await db()
			.from("competitors")
			.select("*")
			.eq("id", competitorId)
			.eq("user_id", user.id)
			.eq("platform", "instagram")
			.maybeSingle();

		if (!competitor) return apiError(res, 404, "Competitor not found");

		const account = await getIgAccount(user.id, accountId);
		if (!account) return apiError(res, 404, "Instagram account not found");

		const { getBusinessDiscovery } = await import("../../../instagramApi.js");
		const result = await getBusinessDiscovery(
			account.instagram_access_token_encrypted as string,
			account.instagram_user_id as string,
			competitor.username,
			12,
		);

		if (!result.success) {
			return apiError(res, 500, result.error || "Failed to sync");
		}

		const profile = result.profile as unknown as IgProfile;
		const media = profile.media?.data || [];
		const { avgLikes, avgComments, engagementRate } = calculateIgMetrics(
			media,
			profile.followers_count || 0,
		);

		// Update competitor
		const { error: compErr } = await db()
			.from("competitors")
			.update({
				display_name: profile.name || profile.username,
				avatar_url: profile.profile_picture_url || "",
				bio: profile.biography || "",
				follower_count: profile.followers_count || 0,
				media_count: profile.media_count || 0,
				avg_likes: avgLikes,
				avg_comments: avgComments,
				engagement_rate: engagementRate,
				website: profile.website || "",
				last_synced_at: new Date().toISOString(),
			})
			.eq("id", competitorId);
		if (compErr) {
			logger.warn("[ig-sync] Failed to update competitor", {
				competitorId,
				error: compErr.message,
			});
		}

		// Create snapshot
		const today = new Date().toISOString().split("T")[0]!;
		const { error: snapErr } = await db()
			.from("competitor_snapshots")
			.upsert(
				{
					competitor_id: competitorId,
					user_id: user.id,
					snapshot_date: today,
					follower_count: profile.followers_count || 0,
					// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert
				} as any,
				{ onConflict: "competitor_id,snapshot_date" },
			);
		if (snapErr) {
			logger.warn("[ig-sync] Failed to upsert competitor_snapshots", {
				competitorId,
				error: snapErr.message,
			});
		}

		// Upsert top posts
		if (media.length > 0) {
			// Delete old posts and insert fresh
			const { error: delErr } = await db()
				.from("competitor_top_posts")
				.delete()
				.eq("competitor_id", competitorId)
				.eq("platform", "instagram");
			if (delErr) {
				logger.warn("[ig-sync] Failed to delete old competitor_top_posts", {
					competitorId,
					error: delErr.message,
				});
			}

			const topPosts = (media as IgMediaPost[])
				.sort(
					(a: IgMediaPost, b: IgMediaPost) =>
						(b.like_count || 0) +
						(b.comments_count || 0) -
						((a.like_count || 0) + (a.comments_count || 0)),
				)
				.slice(0, 10)
				.map((post: IgMediaPost) => ({
					competitor_id: competitorId,
					user_id: user.id,
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

			const { error: insertErr } = await getSupabaseAny()
				.from("competitor_top_posts")
				.insert(topPosts);
			if (insertErr) {
				logger.warn("[ig-sync] Failed to insert competitor_top_posts", {
					competitorId,
					count: topPosts.length,
					error: insertErr.message,
				});
			}
		}

		return apiSuccess(res);
	},
);
