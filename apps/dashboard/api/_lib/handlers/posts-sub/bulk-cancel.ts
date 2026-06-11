/**
 * Bulk Cancel Scheduled/Draft Posts
 *
 * POST /api/posts/bulk-cancel
 * Body: { postIds: string[], dryRun?: boolean (default true) }
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logAudit } from "../../auditLog.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";

// biome-ignore lint/suspicious/noExplicitAny: table not yet in generated types
const db = (): any => getSupabase();

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}

		const userId = user.id;
		const { postIds, dryRun = true } = req.body ?? {};

		if (!Array.isArray(postIds) || postIds.length === 0) {
			return apiError(res, 400, "postIds must be a non-empty array");
		}
		if (postIds.length > 50) {
			return apiError(res, 400, "Maximum 50 posts per request");
		}

		// Fetch matching posts that are scheduled or draft and belong to the user
		const { data: matchingPosts, error: fetchError } = await db()
			.from("posts")
			.select("id, content, status, scheduled_for, account_id, platform")
			.in("id", postIds)
			.eq("user_id", userId)
			.in("status", ["scheduled", "draft"]);

		if (fetchError) {
			return apiError(res, 500, "Failed to fetch posts", {
				details: fetchError.message,
			});
		}

		const posts = matchingPosts ?? [];
		const matchedIds = posts.map((p: { id: string }) => p.id);
		const skippedIds = postIds.filter((id: string) => !matchedIds.includes(id));

		if (dryRun) {
			return apiSuccess(res, {
				dryRun: true,
				willCancel: posts,
				willCancelCount: posts.length,
				skippedIds,
				skippedCount: skippedIds.length,
			});
		}

		// Actually delete them
		const { error: deleteError } = await db()
			.from("posts")
			.delete()
			.in("id", matchedIds)
			.eq("user_id", userId);

		if (deleteError) {
			return apiError(res, 500, "Failed to cancel posts", {
				details: deleteError.message,
			});
		}

		void logAudit(userId, "post.bulk-cancel", {
			metadata: {
				cancelledCount: posts.length,
				cancelledIds: matchedIds,
				skippedCount: skippedIds.length,
			},
		});

		return apiSuccess(res, {
			dryRun: false,
			cancelledCount: posts.length,
			cancelledIds: matchedIds,
			skippedIds,
			skippedCount: skippedIds.length,
		});
	},
);
