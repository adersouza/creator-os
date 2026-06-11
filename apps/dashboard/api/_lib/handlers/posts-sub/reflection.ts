/**
 * /api/posts/reflection
 * POST — Store a post-publish reflection (👍/👎)
 * GET  — Check if user already reflected on a post
 *
 * Called from posts.ts router (already wrapped with withAuth).
 * Uses getAuthUserOrError directly to avoid double-wrapping.
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, getAuthUserOrError } from "../../apiResponse.js";
import { getSupabase } from "../../supabase.js";
import { requireMinTier } from "../../tierGate.js";

export default async function handleReflection(
	req: VercelRequest,
	res: VercelResponse,
) {
	const user = await getAuthUserOrError(req, res);
	if (!user) return;

	const allowed = await requireMinTier(user.id, "pro", res);
	if (!allowed) return;

	const supabase = getSupabase();

	if (req.method === "GET") {
		const postId = req.query.postId as string;
		const postIds = req.query.postIds as string; // comma-separated batch

		// Batch mode: check multiple posts in one request
		if (postIds) {
			const ids = postIds.split(",").slice(0, 100); // cap at 100
			const { data, error } = await supabase
				.from("post_reflections")
				.select("post_id, met_expectations")
				.eq("user_id", user.id)
				.in("post_id", ids);

			if (error) return apiError(res, 500, "Failed to check reflections");
			const reflected = new Set(
				(data || []).map((r: { post_id: string }) => r.post_id),
			);
			const results: Record<
				string,
				{ reflected: boolean; metExpectations: boolean | null }
			> = {};
			for (const id of ids) {
				const row = (data || []).find(
					(r: { post_id: string }) => r.post_id === id,
				) as { met_expectations?: boolean | undefined } | undefined;
				results[id] = {
					reflected: reflected.has(id),
					metExpectations: row?.met_expectations ?? null,
				};
			}
			return apiSuccess(res, { batch: results });
		}

		// Single mode (legacy)
		if (!postId)
			return apiError(res, 400, "postId or postIds query param required");

		const { data, error } = await supabase
			.from("post_reflections")
			.select("id, met_expectations")
			.eq("user_id", user.id)
			.eq("post_id", postId)
			.maybeSingle();

		if (error) return apiError(res, 500, "Failed to check reflection");
		return apiSuccess(res, {
			reflected: !!data,
			metExpectations: data?.met_expectations ?? null,
		});
	}

	if (req.method === "POST") {
		const { postId, metExpectations } = req.body || {};
		if (!postId || typeof postId !== "string")
			return apiError(res, 400, "postId is required");
		if (typeof metExpectations !== "boolean")
			return apiError(res, 400, "metExpectations (boolean) is required");

		// #630: Verify post ownership before allowing reflection
		const { data: ownedPost } = await supabase
			.from("posts")
			.select("id")
			.eq("id", postId)
			.eq("user_id", user.id)
			.maybeSingle();
		if (!ownedPost) {
			// biome-ignore lint/suspicious/noExplicitAny: instagram_posts.user_id not in generated types
			const { data: igPost } = await (supabase as any)
				.from("instagram_posts")
				.select("id")
				.eq("id", postId)
				.eq("user_id", user.id)
				.maybeSingle();
			if (!igPost) {
				return apiError(res, 404, "Post not found");
			}
		}

		const { error } = await supabase.from("post_reflections").upsert(
			{
				user_id: user.id,
				post_id: postId,
				met_expectations: metExpectations,
			},
			{ onConflict: "user_id,post_id" },
		);

		if (error) return apiError(res, 500, "Failed to store reflection");
		return apiSuccess(res, { stored: true });
	}

	return apiError(res, 405, "Method not allowed");
}
