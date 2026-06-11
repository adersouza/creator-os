/**
 * Tags API Route — Post tagging & campaign analytics
 *
 * GET/POST /api/tags?action=<action>
 *
 * Actions:
 *   list         — GET: list user's tag palette
 *   create       — POST: create/update tag in palette
 *   delete       — POST: remove from palette { id }
 *   assign       — POST: assign tag to posts { postIds[], tagName, tagColor? }
 *   unassign     — POST: remove tag from posts { postIds[], tagName }
 *   by-post      — GET: list tags on a post ?postId=X
 *   campaign     — GET: aggregate metrics for tagged posts ?tagName=X&periodDays=30
 */

import { apiError, apiSuccess, methodNotAllowed } from "./_lib/apiResponse.js";
import { withAuthDb } from "./_lib/middleware.js";
import { z, zEnum } from "./_lib/zodCompat.js";

const querySchema = z.object({
	action: zEnum([
		"list",
		"create",
		"delete",
		"assign",
		"unassign",
		"by-post",
		"campaign",
	]),
	postId: z.string().optional(),
	tagName: z.string().optional(),
	periodDays: z.coerce.number().int().min(1).max(365).optional().default(30),
	accountId: z.string().optional(),
});

type TagPostMetricRow = {
	views_count: number | null;
	likes_count: number | null;
	replies_count: number | null;
	reposts_count: number | null;
	shares_count: number | null;
	engagement_rate: number | null;
	ig_reach: number | null;
	ig_saved: number | null;
	ig_shares: number | null;
	published_at: string | null;
};

export default withAuthDb(async (req, res, context) => {
	const { user, userDb } = context;
	if (req.method !== "POST" && req.method !== "GET") {
		return methodNotAllowed(res);
	}

	const parsed = querySchema.safeParse(req.query);
	if (!parsed.success) {
		return apiError(res, 400, `Invalid action: ${req.query.action ?? ""}`);
	}
	const { action } = parsed.data;

	try {
		switch (action) {
			// ── List tag palette ──
			case "list": {
				const { data, error } = await userDb
					.from("user_tag_palette")
					.select("*")
					.eq("user_id", user.id)
					.order("tag_name", { ascending: true });
				if (error) return apiError(res, 500, "Failed to fetch tags");
				return apiSuccess(res, { tags: data || [] });
			}

			// ── Create/update tag in palette ──
			case "create": {
				if (req.method !== "POST") return methodNotAllowed(res);
				const { tagName, tagColor } = req.body || {};
				if (!tagName) return apiError(res, 400, "tagName required");

				const { data, error } = await userDb
					.from("user_tag_palette")
					.upsert(
						{
							user_id: user.id,
							tag_name: tagName.slice(0, 50),
							tag_color: tagColor || "#38bdf8",
						},
						{ onConflict: "user_id,tag_name" },
				)
					.select()
					.maybeSingle();
				if (error) return apiError(res, 500, "Failed to create tag");
				return apiSuccess(res, data ?? {});
			}

			// ── Delete from palette ──
			case "delete": {
				if (req.method !== "POST") return methodNotAllowed(res);
				const { id } = req.body || {};
				if (!id) return apiError(res, 400, "id required");

				const { data, error } = await userDb
					.from("user_tag_palette")
					.delete()
					.eq("id", id)
					.eq("user_id", user.id)
					.select("id")
					.maybeSingle();
				if (error) return apiError(res, 500, "Failed to delete tag");
				if (!data) return apiError(res, 404, "Tag not found");
				return apiSuccess(res, { deleted: true });
			}

			// ── Assign tag to posts ──
			case "assign": {
				if (req.method !== "POST") return methodNotAllowed(res);
				const { postIds, tagName, tagColor } = req.body || {};
				if (!postIds?.length || !tagName)
					return apiError(res, 400, "postIds[] and tagName required");

				const uniquePostIds = [...new Set(postIds as string[])];
				const { data: ownedPosts } = await userDb
					.from("posts")
					.select("id")
					.in("id", uniquePostIds)
					.eq("user_id", user.id);

				const ownedSet = new Set(
					((ownedPosts ?? []) as Array<{ id: string }>).map((p) => p.id),
				);
				const missingIds = uniquePostIds.filter(
					(id: string) => !ownedSet.has(id),
				);
				if (missingIds.length > 0) {
					return apiError(
						res,
						404,
						`${missingIds.length} post(s) not found or not owned by user`,
					);
				}

				const rows = uniquePostIds.map((pid: string) => ({
					post_id: pid,
					tag_name: tagName.slice(0, 50),
					tag_color: tagColor || "#38bdf8",
					user_id: user.id,
				}));

				const { data, error } = await userDb
					.from("post_tags")
					.upsert(rows, { onConflict: "post_id,tag_name,user_id" })
					.select();
				if (error) return apiError(res, 500, "Failed to assign tags");
				return apiSuccess(res, { tags: data || [] });
			}

			// ── Unassign tag from posts ──
			case "unassign": {
				if (req.method !== "POST") return methodNotAllowed(res);
				const { postIds: removeIds, tagName: removeTag } = req.body || {};
				if (!removeIds?.length || !removeTag)
					return apiError(res, 400, "postIds[] and tagName required");

				const uniqueRemoveIds = [...new Set(removeIds as string[])];
				const { data: ownedPosts } = await userDb
					.from("posts")
					.select("id")
					.in("id", uniqueRemoveIds)
					.eq("user_id", user.id);

				const ownedSet = new Set(
					((ownedPosts ?? []) as Array<{ id: string }>).map((p) => p.id),
				);
				const missingIds = uniqueRemoveIds.filter(
					(id: string) => !ownedSet.has(id),
				);
				if (missingIds.length > 0) {
					return apiError(
						res,
						404,
						`${missingIds.length} post(s) not found or not owned by user`,
					);
				}

				const { error } = await userDb
					.from("post_tags")
					.delete()
					.in("post_id", uniqueRemoveIds)
					.eq("tag_name", removeTag)
					.eq("user_id", user.id);
				if (error) return apiError(res, 500, "Failed to unassign tags");
				return apiSuccess(res, { removed: true });
			}

			// ── Tags on a specific post ──
			case "by-post": {
				const postId = parsed.data.postId;
				if (!postId) return apiError(res, 400, "postId required");

				const { data, error } = await userDb
					.from("post_tags")
					.select("*")
					.eq("post_id", postId)
					.eq("user_id", user.id);
				if (error) return apiError(res, 500, "Failed to fetch post tags");
				const { data: ownedPost } = await userDb
					.from("posts")
					.select("id")
					.eq("id", postId)
					.eq("user_id", user.id)
					.maybeSingle();
				if (!ownedPost) return apiError(res, 404, "Post not found");
				return apiSuccess(res, { tags: data || [] });
			}

			// ── Campaign analytics (aggregate metrics for tagged posts) ──
			case "campaign": {
				const tagName = parsed.data.tagName;
				if (!tagName) return apiError(res, 400, "tagName required");

				const cutoff = new Date();
				cutoff.setDate(cutoff.getDate() - parsed.data.periodDays);
				const cutoffStr = cutoff.toISOString();

				// Get post IDs with this tag
				const { data: taggedPosts } = await userDb
					.from("post_tags")
					.select("post_id")
					.eq("user_id", user.id)
					.eq("tag_name", tagName);

				if (!taggedPosts?.length)
					return apiSuccess(res, {
						tagName,
						postCount: 0,
						metrics: null,
					});

				const postIds = taggedPosts.map((t: { post_id: string }) => t.post_id);

				// Get post metrics
				const { data: posts } = await userDb
					.from("posts")
					.select(
						"views_count, likes_count, replies_count, reposts_count, shares_count, engagement_rate, ig_reach, ig_saved, ig_shares, published_at",
					)
					.in("id", postIds)
					.gte("published_at", cutoffStr);

				if (!posts?.length)
					return apiSuccess(res, {
						tagName,
						postCount: 0,
						metrics: null,
					});

				// Aggregate
				const metrics = {
					postCount: posts.length,
					totalViews: 0,
					totalLikes: 0,
					totalReplies: 0,
					totalReposts: 0,
					totalShares: 0,
					totalReach: 0,
					totalSaved: 0,
					avgEngagementRate: 0,
				};

				for (const p of posts as TagPostMetricRow[]) {
					metrics.totalViews += p.views_count ?? 0;
					metrics.totalLikes += p.likes_count ?? 0;
					metrics.totalReplies += p.replies_count ?? 0;
					metrics.totalReposts += p.reposts_count ?? 0;
					metrics.totalShares += p.shares_count ?? 0;
					metrics.totalReach += p.ig_reach ?? 0;
					metrics.totalSaved += p.ig_saved ?? 0;
					metrics.avgEngagementRate += p.engagement_rate ?? 0;
				}

				metrics.avgEngagementRate = Number.parseFloat(
					(metrics.avgEngagementRate / posts.length).toFixed(2),
				);

				return apiSuccess(res, { tagName, ...metrics });
			}

			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (_error) {
		return apiError(res, 500, "Internal server error");
	}
});
