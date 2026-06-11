/**
 * Referral System API
 * POST /api/referrals?action=create-code|validate-code|apply-code|stats
 */

import { apiError, apiSuccess } from "./_lib/apiResponse.js";
import { logger } from "./_lib/logger.js";
import { withAuth } from "./_lib/middleware.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "./_lib/privilegedDb.js";
import { z, zEnum } from "./_lib/zodCompat.js";

interface ReferralRow {
	status: string;
}

// ============================================================================
// Query schema
// ============================================================================

const postQuerySchema = z.object({
	action: zEnum([
		"create-code",
		"validate-code",
		"apply-code",
		"stats",
	]).optional(),
});

export default withAuth(async (req, res, user) => {
	const userId = user.id;
	const baseUrl =
		process.env.APP_URL ||
		(process.env.VERCEL_URL
			? `https://${process.env.VERCEL_URL}`
			: "https://juno33.com");
	const { action } =
		req.method === "POST" ? postQuerySchema.parse(req.query) : req.query;
	// Referral validation intentionally crosses user boundaries to look up a
	// referrer's active code before creating the referred user's row.
	const supabase = getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.referralManagement,
	);

	// GET — return user's referral code, link, and stats
	if (req.method === "GET") {
		const { data: codes } = await supabase
			.from("referral_codes")
			.select("*")
			.eq("user_id", userId)
			.eq("is_active", true)
			.limit(1);

		const { data: referrals } = await supabase
			.from("referrals")
			.select("*")
			.eq("referrer_id", userId);

		const code = codes?.[0]?.code || null;
		return apiSuccess(res, {
			referralCode: code,
			referralLink: code ? `${baseUrl}/ref/${code}` : null,
			totalReferrals: referrals?.length || 0,
			completedReferrals:
				referrals?.filter(
					(r: ReferralRow) =>
						r.status === "completed" || r.status === "rewarded",
				).length || 0,
		});
	}

	if (req.method !== "POST") return apiError(res, 405, "Method not allowed");

	try {
		switch (action) {
			case "create-code": {
				// #564: Validate that the user's profile exists before creating a referral code
				const { data: profile } = await supabase
					.from("profiles")
					.select("display_name, email")
					.eq("id", userId)
					.maybeSingle();

				if (!profile) {
					return apiError(
						res,
						404,
						"User profile not found. Please complete your profile setup first.",
					);
				}

				const username =
					// #695: Use display_name only — never leak email prefix in referral codes
					profile?.display_name || "USER";

				const { data: existing } = await supabase
					.from("referral_codes")
					.select("*")
					.eq("user_id", userId)
					.eq("is_active", true)
					.limit(1);

				if (existing && existing.length > 0) {
					return apiSuccess(res, { code: existing[0] });
				}

				const { data: codeResult } = await supabase.rpc(
					"generate_referral_code",
					{ username },
				);
				const code =
					codeResult ||
					`${username.slice(0, 4).toUpperCase()}${Math.floor(Math.random() * 10000)}`;

				const { data: newCode, error } = await supabase
					.from("referral_codes")
					.insert({
						user_id: userId,
						code,
						reward_type: "extra_account",
						reward_value: 1,
					})
					.select()
					.maybeSingle();

				if (error) {
					logger.error("Failed to create referral code", {
						error: String(error.message),
					});
					return apiError(res, 500, "Failed to create referral code");
				}

				return apiSuccess(res, { code: newCode });
			}

			case "validate-code": {
				const { code } = req.body || {};
				if (!code) return apiError(res, 400, "Missing code");

				const { data: referralCode } = await supabase
					.from("referral_codes")
					.select("*, profiles!referral_codes_user_id_fkey(display_name)")
					.eq("code", (code as string).toUpperCase())
					.eq("is_active", true)
					.maybeSingle();

				if (!referralCode)
					return apiError(res, 404, "Invalid or expired referral code");

				const { data: existingReferral } = await supabase
					.from("referrals")
					.select("id")
					.eq("referred_id", userId)
					.limit(1);

				if (existingReferral && existingReferral.length > 0) {
					return apiError(res, 400, "You've already used a referral code");
				}

				if (referralCode.user_id === userId) {
					return apiError(res, 400, "You can't use your own referral code");
				}

				return apiSuccess(res, {
					valid: true,
					referrerName: referralCode.profiles?.display_name || "A friend",
					rewardType: referralCode.reward_type,
				});
			}

			case "apply-code": {
				const { code } = req.body || {};
				if (!code) return apiError(res, 400, "Missing code");

				const { data: existingReferral } = await supabase
					.from("referrals")
					.select("id")
					.eq("referred_id", userId)
					.limit(1);

				if (existingReferral && existingReferral.length > 0) {
					return apiError(res, 400, "You've already used a referral code");
				}

				const { data: referralCode } = await supabase
					.from("referral_codes")
					.select("*")
					.eq("code", (code as string).toUpperCase())
					.eq("is_active", true)
					.maybeSingle();

				if (!referralCode) return apiError(res, 404, "Invalid referral code");
				if (referralCode.user_id === userId)
					return apiError(res, 400, "Can't use your own code");

				let usageIncremented = false;

				// Atomic increment — prevents TOCTOU race on max_uses
				const { data: incremented, error: rpcError } = await supabase.rpc(
					"increment_referral_uses",
					{
						p_code_id: referralCode.id,
						p_max_limit: referralCode.max_uses ?? 0,
					},
				);

				if (rpcError) {
					// Fallback for environments where RPC isn't deployed yet
					if (rpcError.code === "42883") {
						if (
							referralCode.max_uses > 0 &&
							referralCode.uses >= referralCode.max_uses
						) {
							return apiError(
								res,
								400,
								"This referral code has reached its limit",
							);
						}

						const currentUses = referralCode.uses ?? 0;
						const { data: updatedCode, error: updateError } = await supabase
							.from("referral_codes")
							.update({ uses: currentUses + 1 })
							.eq("id", referralCode.id)
							.eq("uses", currentUses)
							.select("id")
							.maybeSingle();

						if (updateError) {
							logger.error("Fallback referral use increment failed", {
								error: updateError.message,
							});
							return apiError(res, 500, "Failed to apply referral code");
						}
						if (!updatedCode) {
							return apiError(
								res,
								409,
								"Referral code was updated concurrently. Please retry.",
							);
						}
						usageIncremented = true;
					} else {
						logger.error("increment_referral_uses RPC failed", {
							error: rpcError.message,
						});
						return apiError(res, 500, "Failed to apply referral code");
					}
				} else if (incremented === false) {
					return apiError(res, 400, "This referral code has reached its limit");
				} else {
					usageIncremented = true;
				}

				const { error: refError } = await supabase.from("referrals").insert({
					referrer_id: referralCode.user_id,
					referred_id: userId,
					referral_code_id: referralCode.id,
					status: "completed",
				});

				if (refError) {
					if (refError.code === "23505")
						return apiError(res, 400, "You've already used a referral code");
					logger.error("Referral insert failed after usage increment", {
						referralCodeId: referralCode.id,
						usageIncremented,
						error: refError.message,
					});
					logger.error("Failed to apply referral", {
						error: String(refError.message),
					});
					return apiError(res, 500, "Failed to apply referral code");
				}

				return apiSuccess(res, {
					applied: true,
					rewardType: referralCode.reward_type,
				});
			}

			case "stats": {
				const { data: codes } = await supabase
					.from("referral_codes")
					.select("*")
					.eq("user_id", userId)
					.eq("is_active", true);

				const { data: referrals } = await supabase
					.from("referrals")
					.select("*, profiles!referrals_referred_id_fkey(display_name)")
					.eq("referrer_id", userId)
					.order("created_at", { ascending: false });

				const { data: profile } = await supabase
					.from("profiles")
					.select(
						"referral_reward_months_earned, referral_reward_months_used, referral_trial_ends_at",
					)
					.eq("id", userId)
					.maybeSingle();

				const totalReferrals = referrals?.length || 0;
				const completedReferrals =
					referrals?.filter(
						(r: ReferralRow) =>
							r.status === "completed" || r.status === "rewarded",
					).length || 0;
				const rewardMonthsEarned = profile?.referral_reward_months_earned || 0;
				const rewardMonthsUsed = profile?.referral_reward_months_used || 0;
				const rewardMonthsAvailable = rewardMonthsEarned - rewardMonthsUsed;
				const maxRewardMonths = 12;

				return apiSuccess(res, {
					codes: codes || [],
					referrals: referrals || [],
					totalReferrals,
					completedReferrals,
					rewards: {
						monthsEarned: rewardMonthsEarned,
						monthsUsed: rewardMonthsUsed,
						monthsAvailable: rewardMonthsAvailable,
						maxMonths: maxRewardMonths,
						referralTrialEndsAt: profile?.referral_trial_ends_at || null,
					},
				});
			}

			default:
				return apiError(
					res,
					400,
					"Invalid action. Use: create-code, validate-code, apply-code, stats",
				);
		}
	} catch (error: unknown) {
		logger.error("Referrals API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
