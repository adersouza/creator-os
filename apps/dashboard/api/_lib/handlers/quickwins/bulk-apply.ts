/**
 * POST /api/quickwins/bulk-apply — Bulk Quick Win Actions
 *
 * Actions:
 * - apply-timing: Updates scheduled_for on next 5 upcoming posts to recommended time window
 * - snooze: Stores snooze in Redis with 30-day TTL
 *
 * Body: { category: string, action: "apply-timing" | "snooze", accountId: string, platform: string, recommendedHours?: number[] }
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getRedis } from "../../redis.js";
import { getSupabase } from "../../supabase.js";

const SNOOZE_TTL_SECONDS = 30 * 24 * 60 * 60; // 30 days

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") return apiError(res, 405, "Method not allowed");

		const { category, action, accountId, platform, recommendedHours } =
			req.body || {};

		if (!category || !action || !accountId) {
			return apiError(
				res,
				400,
				"Missing required fields: category, action, accountId",
			);
		}

		if (!["apply-timing", "snooze"].includes(action)) {
			return apiError(
				res,
				400,
				"Invalid action. Must be 'apply-timing' or 'snooze'",
			);
		}

		const supabase = getSupabase();

		const resolvedPlatform = platform === "instagram" ? "instagram" : "threads";
		const accountTable =
			resolvedPlatform === "instagram" ? "instagram_accounts" : "accounts";
		const accountColumn =
			resolvedPlatform === "instagram" ? "instagram_account_id" : "account_id";

		// Verify user owns this account
		const { data: account } = await supabase
			.from(accountTable)
			.select("id, user_id")
			.eq("id", accountId)
			.maybeSingle();

		if (!account || account.user_id !== user.id) {
			return apiError(res, 403, "Not your account");
		}

		if (action === "snooze") {
			const redis = getRedis();
			const key = `rec:snooze:${user.id}:${category}`;
			await redis.set(key, "1", { ex: SNOOZE_TTL_SECONDS });
			return apiSuccess(res, { snoozed: true, category, expiresIn: "30 days" });
		}

		if (action === "apply-timing") {
			if (
				!recommendedHours ||
				!Array.isArray(recommendedHours) ||
				recommendedHours.length === 0
			) {
				return apiError(
					res,
					400,
					"recommendedHours required for apply-timing action",
				);
			}

			if (
				!recommendedHours.every(
					(h: unknown) =>
						typeof h === "number" && Number.isInteger(h) && h >= 0 && h < 24,
				)
			) {
				return apiError(
					res,
					400,
					"recommendedHours must contain integers 0-23",
				);
			}

			// Get next 5 upcoming scheduled posts from the posts table
			const now = new Date().toISOString();
			const { data: scheduledPosts, error: fetchErr } = await supabase
				.from("posts")
				.select("id, scheduled_for")
				.eq(accountColumn, accountId)
				.eq("status", "scheduled")
				.gt("scheduled_for", now)
				.order("scheduled_for", { ascending: true })
				.limit(5);

			if (fetchErr) {
				return apiError(res, 500, "Failed to fetch scheduled posts");
			}

			if (!scheduledPosts || scheduledPosts.length === 0) {
				return apiSuccess(res, {
					updated: 0,
					message: "No upcoming scheduled posts found",
				});
			}

			// Update each post's scheduled_for to the nearest recommended hour
			let updated = 0;
			for (const post of scheduledPosts) {
				const dt = new Date(post.scheduled_for ?? "");
				// Find the nearest recommended hour on the same day
				const currentHour = dt.getUTCHours();
				let bestHour = recommendedHours[0];
				let minDist = Math.abs(currentHour - bestHour);
				for (const h of recommendedHours) {
					const dist = Math.abs(currentHour - h);
					if (dist < minDist) {
						minDist = dist;
						bestHour = h;
					}
				}
				dt.setUTCHours(bestHour, 0, 0, 0);

				const { error: updateErr } = await supabase
					.from("posts")
					.update({ scheduled_for: dt.toISOString() })
					.eq("id", post.id)
					.eq(accountColumn, accountId);

				if (!updateErr) updated++;
			}

			return apiSuccess(res, { updated, total: scheduledPosts.length });
		}
	},
);
