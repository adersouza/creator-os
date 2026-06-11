import { apiError, apiSuccess } from "../_lib/apiResponse.js";
import { logger } from "../_lib/logger.js";
import { withAuth } from "../_lib/middleware.js";
import {
	enforceRouteRateLimit,
	getClientIp,
} from "../_lib/routeRateLimit.js";
import {
	getPrivilegedSupabase,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";

export default withAuth(async (req, res, user) => {
	if (req.method !== "POST") return apiError(res, 405, "Method not allowed");

	const ipAllowed = await enforceRouteRateLimit(res, {
		key: `auth-ip:apply-referral:ip:${getClientIp(req)}:minute`,
		limit: 5,
		windowSeconds: 60,
		failMode: "closed",
		message: "Too many auth requests. Try again shortly.",
	});
	if (!ipAllowed) return;

	const { code } = req.body || {};
	if (!code || typeof code !== "string") {
		return apiError(res, 400, "Missing referral code");
	}

	const supabase = getPrivilegedSupabase(
		PRIVILEGED_DB_REASONS.referralManagement,
	);
	const userId = user.id;

	try {
		// Check if user already has a referral
		const { data: existing } = await supabase
			.from("referrals")
			.select("id")
			.eq("referred_id", userId)
			.limit(1);

		if (existing && existing.length > 0) {
			return apiSuccess(res, { applied: false, reason: "already_referred" });
		}

		// Look up code
		const { data: referralCode } = await supabase
			.from("referral_codes")
			.select("*")
			.eq("code", code.toUpperCase())
			.eq("is_active", true)
			.maybeSingle();

		if (!referralCode) {
			return apiError(res, 404, "Invalid or expired referral code");
		}

		if (referralCode.user_id === userId) {
			return apiError(res, 400, "Cannot use your own referral code");
		}

		if (
			referralCode.max_uses > 0 &&
			referralCode.uses >= referralCode.max_uses
		) {
			return apiError(res, 400, "Referral code has reached its limit");
		}

		// #638: Atomic increment to prevent TOCTOU race condition
		// Increment uses atomically — only succeeds if uses < max_uses
		// biome-ignore lint/suspicious/noExplicitAny: increment_referral_uses not yet in RPC type enum
		const { data: updatedCode, error: incrError } = await (supabase as any).rpc(
			"increment_referral_uses",
			{ code_id: referralCode.id, max_limit: referralCode.max_uses || 999999 },
		);

		// Fallback: if RPC doesn't exist, use standard update
		if (incrError?.code === "42883") {
			// Function not found — use legacy path
			await supabase
				.from("referral_codes")
				.update({ uses: (referralCode.uses ?? 0) + 1 })
				.eq("id", referralCode.id);
		} else if (incrError) {
			logger.error("[apply-referral] Atomic increment failed", {
				error: incrError.message,
			});
			return apiError(res, 500, "Failed to apply referral");
		} else if (updatedCode === false || updatedCode === 0) {
			return apiError(res, 400, "Referral code has reached its limit");
		}

		// Create referral link
		const { error } = await supabase.from("referrals").insert({
			referrer_id: referralCode.user_id,
			referred_id: userId,
			referral_code_id: referralCode.id,
			status: "completed",
		});

		if (error) {
			if (error.code === "23505") {
				return apiSuccess(res, { applied: false, reason: "already_referred" });
			}
			logger.error("[apply-referral] Insert failed", { error: error.message });
			return apiError(res, 500, "Failed to apply referral");
		}

		return apiSuccess(res, { applied: true });
	} catch (error) {
		logger.error("[apply-referral] Error", { error: String(error) });
		return apiError(res, 500, "Failed to apply referral");
	}
});
