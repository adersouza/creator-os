/**
 * POST /api/beta/claim
 *
 * Claims a beta spot for the authenticated user.
 * Sets is_beta_user=true, beta_joined_at=now() on profile.
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabaseAny } from "../../supabase.js";

const TOTAL_SPOTS = 50;
const db = () => getSupabaseAny();

export default withAuth(async (req, res, user) => {
	if (req.method !== "POST") return apiError(res, 405, "Method not allowed");

	try {
		const { data, error } = await db().rpc("claim_beta_spot", {
			p_user_id: user.id,
			p_total_spots: TOTAL_SPOTS,
		});

		if (error) {
			logger.error("[beta/claim] RPC error", { error: String(error) });
			return apiError(res, 500, "Failed to claim beta spot");
		}

		const result = data as {
			ok?: boolean | undefined;
			claimed?: boolean | undefined;
			already_beta?: boolean | undefined;
			spots_left?: number | undefined;
			reason?: string | undefined;
		} | null;

		if (result?.already_beta) {
			return apiSuccess(res, {
				success: true,
				message: "Already a beta user",
				spotsLeft: Math.max(0, result.spots_left ?? 0),
			});
		}

		if (result?.reason === "sold_out") {
			return apiError(res, 400, "All beta spots have been claimed");
		}

		if (result?.reason === "profile_not_found") {
			return apiError(res, 404, "Profile not found");
		}

		if (!result?.claimed) {
			logger.error("[beta/claim] Unexpected RPC result", {
				userId: user.id,
				result,
			});
			return apiError(res, 500, "Failed to claim beta spot");
		}

		const spotsLeft = Math.max(0, result.spots_left ?? 0);

		logger.info("[beta/claim] Beta spot claimed", {
			userId: user.id,
			spotsLeft,
		});

		return apiSuccess(res, {
			success: true,
			spotsLeft,
		});
	} catch (err) {
		logger.error("[beta/claim] Failed to claim beta spot", {
			error: String(err),
		});
		return apiError(res, 500, "Internal server error");
	}
});
