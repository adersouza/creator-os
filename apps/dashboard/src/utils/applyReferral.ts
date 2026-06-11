/**
 * Apply Referral Code — checks localStorage for a stored referral code
 * and calls POST /api/auth/apply-referral. Fire-and-forget: errors are
 * silently swallowed so they never block signup/login.
 */

import { apiUrl } from "@/lib/apiUrl";
import { appToast } from "@/lib/toast";
import { supabase } from "@/services/supabase";
import logger from "@/utils/logger";

export async function applyStoredReferralCode(): Promise<void> {
	try {
		const code =
			localStorage.getItem("juno33_referral_code") ||
			localStorage.getItem("threadsdash_referral_code");

		if (!code) return;

		const { data: sessionData } = await supabase.auth.getSession();
		const token = sessionData?.session?.access_token;
		if (!token) return;

		const res = await fetch(apiUrl("/api/auth/apply-referral"), {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${token}`,
			},
			body: JSON.stringify({ code }),
		});

		// Clean up localStorage regardless of outcome
		localStorage.removeItem("juno33_referral_code");
		localStorage.removeItem("threadsdash_referral_code");

		if (!res.ok) {
			logger.error("[referral] Server error:", res.status);
			return;
		}

		const data = await res.json();
		if (data?.data?.applied) {
			appToast.success("Referral applied! You and your friend both benefit.");
		}
	} catch (err) {
		logger.error("[referral] Failed to apply referral code:", err);
		try {
			localStorage.removeItem("juno33_referral_code");
			localStorage.removeItem("threadsdash_referral_code");
		} catch (e) {
			logger.error("[referral] Cleanup failed:", e);
		}
	}
}
