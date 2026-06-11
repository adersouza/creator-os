/**
 * GET /api/beta/status
 *
 * Returns beta spot count (public) and personal beta status (if authed).
 * No auth required for spot count — auth optional for personal status.
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withCors } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";

const TOTAL_SPOTS = 50;
const db = () => getSupabase();

const BETA_PERKS = [
	"30-day Pro trial (instead of 14)",
	"Lifetime 30% off any paid plan",
	"Beta Tester badge on profile",
	"Personal onboarding support",
];

const BETA_FEATURES = [
	"early_access_analytics",
	"ai_sandbox",
	"advanced_scheduling",
];

export default withCors(async (req, res) => {
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	try {
		// Count current beta users
		const { count } = await db()
			.from("profiles")
			.select("*", { count: "exact", head: true })
			.eq("is_beta_user", true);

		const betaCount = count || 0;
		const spotsLeft = Math.max(0, TOTAL_SPOTS - betaCount);
		const isOpen = spotsLeft > 0;

		// Check personal status if authenticated
		let isBetaUser = false;
		const authHeader = req.headers.authorization;
		if (authHeader?.startsWith("Bearer ")) {
			try {
				const token = authHeader.slice(7);
				const {
					data: { user },
				} = await db().auth.getUser(token);
				if (user) {
					const { data: profile } = await db()
						.from("profiles")
						.select("is_beta_user")
						.eq("id", user.id)
						.maybeSingle();
					isBetaUser = profile?.is_beta_user || false;
				}
			} catch (err) {
				logger.debug("Failed to verify auth token for beta status check", {
					error: String(err),
				});
				// Auth check failed, continue without personal status
			}
		}

		return apiSuccess(res, {
			spotsLeft,
			totalSpots: TOTAL_SPOTS,
			isOpen,
			isBetaUser,
			perks: BETA_PERKS,
			features: isBetaUser ? BETA_FEATURES : [],
		});
	} catch (err) {
		logger.error("[beta/status] Error", { error: String(err) });
		return apiError(res, 500, "Internal server error");
	}
});
