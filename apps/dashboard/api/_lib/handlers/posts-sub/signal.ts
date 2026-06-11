/**
 * POST /api/posts/signal — Store post-success signal ("Why did this work?")
 * Body: { postId: string, signal: string }
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuthDb } from "../../middleware.js";
import { requireMinTier } from "../../tierGate.js";

const VALID_SIGNALS = [
	"great_media",
	"trending_topic",
	"perfect_timing",
	"strong_hook",
	"got_lucky",
] as const;

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, context) => {
		const { user, userDb } = context;
		const allowed = await requireMinTier(user.id, "pro", res);
		if (!allowed) return;

		if (req.method !== "POST") return apiError(res, 405, "Method not allowed");

		const { postId, signal } = req.body || {};
		if (!postId || typeof postId !== "string") {
			return apiError(res, 400, "postId is required");
		}
		if (!signal || !VALID_SIGNALS.includes(signal)) {
			return apiError(
				res,
				400,
				`signal must be one of: ${VALID_SIGNALS.join(", ")}`,
			);
		}

		// #630: Verify post ownership before allowing signal
		const { data: post } = await userDb
			.from("posts")
			.select("id")
			.eq("id", postId)
			.eq("user_id", user.id)
			.maybeSingle();

		if (!post) {
			// Also check IG posts
			const { data: igPost } = await userDb
				.from("instagram_posts")
				.select("id")
				.eq("id", postId)
				.eq("user_id", user.id)
				.maybeSingle();
			if (!igPost) {
				return apiError(res, 404, "Post not found");
			}
		}

		const { error } = await userDb
			.from("post_success_signals")
			.upsert(
				{ user_id: user.id, post_id: postId, signal },
				{ onConflict: "user_id,post_id" },
			);

		if (error) {
			return apiError(res, 500, "Failed to store signal");
		}

		return apiSuccess(res, { stored: true });
	},
);
