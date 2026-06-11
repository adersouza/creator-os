import {
	apiError,
	apiSuccess,
	badRequest,
	methodNotAllowed,
} from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabase, getSupabaseAny } from "../../supabase.js";
import { requireMinTier } from "../../tierGate.js";

/**
 * Evergreen post management
 *
 * POST action=toggle      — Mark/unmark a post as evergreen
 * POST action=update      — Update evergreen settings (interval, max recycles)
 * GET  action=list        — List evergreen posts with recycle status
 * GET  action=history     — Get recycle history for a post
 */
export default withAuth(async (req, res, user) => {
	const allowed = await requireMinTier(user.id, "pro", res);
	if (!allowed) return;

	const action = (
		req.method === "GET" ? req.query.action : req.body?.action
	) as string;
	const supabase = getSupabase();

	try {
		switch (action) {
			case "toggle": {
				if (req.method !== "POST") return methodNotAllowed(res);
				const { postId, isEvergreen } = req.body || {};
				if (!postId || typeof isEvergreen !== "boolean") {
					return badRequest(res, "postId and isEvergreen required");
				}

				// Verify ownership + published status
				const { data: post } = await supabase
					.from("posts")
					.select("id, status, engagement_rate")
					.eq("id", postId)
					.eq("user_id", user.id)
					.maybeSingle();
				if (!post) return apiError(res, 404, "Post not found");
				if (post.status !== "published") {
					return badRequest(
						res,
						"Only published posts can be marked as evergreen",
					);
				}

				const { data, error } = await supabase
					.from("posts")
					.update({
						is_evergreen: isEvergreen,
						updated_at: new Date().toISOString(),
					})
					.eq("id", postId)
					.eq("user_id", user.id)
					.select(
						"id, is_evergreen, evergreen_interval_days, recycle_count, max_recycles, last_recycled_at",
					)
					.single();

				if (error) {
					if (error.code === "PGRST116")
						return apiError(res, 404, "Post not found");
					throw error;
				}
				return apiSuccess(res, { post: data });
			}

			case "update": {
				if (req.method !== "POST") return methodNotAllowed(res);
				const { postId, intervalDays, maxRecycles, minEngagement } =
					req.body || {};
				if (!postId) return badRequest(res, "postId required");

				const updates: Record<string, string | number> = {
					updated_at: new Date().toISOString(),
				};
				if (typeof intervalDays === "number") {
					updates.evergreen_interval_days = Math.min(
						180,
						Math.max(7, intervalDays),
					);
				}
				if (typeof maxRecycles === "number") {
					updates.max_recycles = Math.min(50, Math.max(1, maxRecycles));
				}
				if (typeof minEngagement === "number") {
					updates.evergreen_min_engagement = Math.min(
						1,
						Math.max(0, minEngagement),
					);
				}

				const { data, error } = await getSupabaseAny()
					.from("posts")
					.update(updates)
					.eq("id", postId)
					.eq("user_id", user.id)
					.eq("is_evergreen", true)
					.select(
						"id, is_evergreen, evergreen_interval_days, recycle_count, max_recycles, evergreen_min_engagement, last_recycled_at",
					)
					.single();

				if (error) {
					if (error.code === "PGRST116")
						return apiError(res, 404, "Evergreen post not found");
					throw error;
				}
				if (!data) return apiError(res, 404, "Evergreen post not found");
				return apiSuccess(res, { post: data });
			}

			case "list": {
				const accountId = req.query.accountId as string;
				let query = supabase
					.from("posts")
					.select(
						"id, content, platform, account_id, instagram_account_id, published_at, views_count, likes_count, replies_count, engagement_rate, is_evergreen, evergreen_interval_days, recycle_count, max_recycles, last_recycled_at, evergreen_min_engagement",
					)
					.eq("user_id", user.id)
					.eq("is_evergreen", true)
					.eq("status", "published")
					.order("published_at", { ascending: false });

				if (accountId) query = query.eq("account_id", accountId);

				const { data, error } = await query.limit(100);
				if (error) throw error;

				// Compute next recycle date for each
				const posts = (data || []).map(
					(p: {
						last_recycled_at: string | null;
						published_at: string | null;
						evergreen_interval_days: number | null;
						max_recycles: number | null;
						recycle_count: number | null;
						[key: string]: unknown;
					}) => {
						const lastRecycled = p.last_recycled_at || p.published_at;
						const nextRecycleDate = lastRecycled
							? new Date(
									new Date(lastRecycled).getTime() +
										(p.evergreen_interval_days || 30) * 86400000,
								).toISOString()
							: null;
						const isDue =
							nextRecycleDate && new Date(nextRecycleDate) <= new Date();
						const recyclesRemaining =
							(p.max_recycles || 5) - (p.recycle_count || 0);

						return {
							...p,
							nextRecycleDate,
							isDue: isDue && recyclesRemaining > 0,
							recyclesRemaining,
						};
					},
				);

				return apiSuccess(res, { posts });
			}

			case "history": {
				const postId = (req.query.postId || req.body?.postId) as string;
				if (!postId) return badRequest(res, "postId required");

				const { data: sourcePost, error: sourceError } = await supabase
					.from("posts")
					.select("id")
					.eq("id", postId)
					.eq("user_id", user.id)
					.maybeSingle();

				if (sourceError) throw sourceError;
				if (!sourcePost) return apiError(res, 404, "Post not found");

				const { data, error } = await supabase
					.from("posts")
					.select(
						"id, content, published_at, views_count, likes_count, engagement_rate, recycled_from_id",
					)
					.eq("recycled_from_id", postId)
					.eq("user_id", user.id)
					.order("published_at", { ascending: false })
					.limit(20);

				if (error) throw error;
				return apiSuccess(res, { recycledPosts: data || [] });
			}

			default:
				return badRequest(res, `Unknown action: ${action}`);
		}
	} catch (err: unknown) {
		const errMsg =
			err instanceof Error ? err.message : (JSON.stringify(err) ?? String(err));
		logger.error("[evergreen] API error", { error: errMsg });
		return apiError(res, 500, "Internal server error");
	}
});
