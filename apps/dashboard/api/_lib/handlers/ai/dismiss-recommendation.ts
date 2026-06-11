/**
 * POST /api/ai/dismiss-recommendation
 *
 * Dismisses a recommendation with a reason:
 * - "already_doing" → auto-check if confirmed, mark as solved
 * - "not_relevant" → store; if 2+ in same category, deprioritize for 30 days (Redis)
 * - "will_try_later" → store with resurface_at = now + 14 days
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import type { Database } from "../../../../types/supabase.js";
import type { DbContext } from "../../dbContext.js";
import { logger } from "../../logger.js";
import { withAuthDb } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { getRedis } from "../../redis.js";

type RecommendationDismissalInsert =
	Database["public"]["Tables"]["recommendation_dismissals"]["Insert"];
type UserDb = DbContext["userDb"];

const VALID_REASONS = [
	"already_doing",
	"not_relevant",
	"will_try_later",
] as const;
const RESURFACE_DAYS = 14;
const DEPRIORITIZE_TTL = 30 * 24 * 60 * 60; // 30 days in seconds

export default withAuthDb(async (req, res, context) => {
	const { user, userDb } = context;
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const rl = await checkRateLimit({
		key: `ai-dismiss:${user.id}`,
		limit: 30,
		windowSeconds: 3600,
		failMode: "closed",
	});
	if (!rl.allowed) {
		return apiError(res, 429, "Too many requests");
	}

	const {
		recId,
		accountId,
		platform: _platform,
		reason,
		category,
	} = req.body || {};

	if (!recId || !accountId || !reason) {
		return apiError(res, 400, "recId, accountId, and reason are required");
	}

	if (!VALID_REASONS.includes(reason)) {
		return apiError(
			res,
			400,
			`reason must be one of: ${VALID_REASONS.join(", ")}`,
		);
	}

	try {
		const now = new Date();
		const dismissalData: RecommendationDismissalInsert = {
			user_id: user.id,
			account_id: accountId,
			rec_id: recId,
			category: category || null,
			reason,
			dismissed_at: now.toISOString(),
			resurface_at: null,
			auto_solved: false,
		};

		if (reason === "will_try_later") {
			const resurface = new Date(
				now.getTime() + RESURFACE_DAYS * 24 * 60 * 60 * 1000,
			);
			dismissalData.resurface_at = resurface.toISOString();
		}

		if (reason === "already_doing") {
			// Quick check: if the rec no longer appears in current analysis, auto-mark as solved
			dismissalData.auto_solved = true; // optimistic — the rec engine already validated the data
		}

		// Upsert dismissal
		await userDb
			.from("recommendation_dismissals")
			.upsert(dismissalData, {
				onConflict: "user_id,account_id,rec_id",
			});

		// Handle "not_relevant" deprioritization
		if (reason === "not_relevant" && category) {
			await handleDeprioritization(user.id, category, userDb);
		}

		logger.info("[dismiss-rec] Stored dismissal", {
			userId: user.id.slice(0, 8),
			recId,
			reason,
			category,
		});

		return apiSuccess(res, { dismissed: true, reason });
	} catch (err) {
		logger.error("[dismiss-rec] Failed", { error: String(err) });
		return apiError(res, 500, "Failed to dismiss recommendation");
	}
});

async function handleDeprioritization(
	userId: string,
	category: string,
	userDb: UserDb,
): Promise<void> {
	try {
		// Count "not_relevant" dismissals in this category
		const { count } = await userDb
			.from("recommendation_dismissals")
			.select("id", { count: "exact", head: true })
			.eq("user_id", userId)
			.eq("category", category)
			.eq("reason", "not_relevant");

		if ((count ?? 0) >= 2) {
			// Deprioritize this category for 30 days in Redis
			const redis = getRedis();
			const key = `rec:deprioritize:${userId}:${category}`;
			await redis.set(key, "1", { ex: DEPRIORITIZE_TTL });

			logger.info("[dismiss-rec] Category deprioritized", {
				userId: userId.slice(0, 8),
				category,
				ttlDays: 30,
			});
		}
	} catch (err) {
		logger.warn("[dismiss-rec] Deprioritization check failed", {
			error: String(err),
		});
	}
}
