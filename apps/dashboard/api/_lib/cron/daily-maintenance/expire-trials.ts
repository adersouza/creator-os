/**
 * Phase 1: Expire Trials
 * Downgrades expired trial profiles to free tier.
 */

import type { Logger, PhaseMetadata, TypedSupabaseClient } from "./shared.js";

export async function phaseExpireTrials(
	supabase: TypedSupabaseClient,
	logger: Logger,
): Promise<PhaseMetadata["expireTrials"]> {
	const { expireTrial } = await import("../../trialManager.js");
	const now = new Date().toISOString();

	const { data: expiredProfiles, error } = await supabase
		.from("profiles")
		.select("id")
		.lt("trial_ends_at", now)
		.eq("trial_used", false)
		.not("trial_ends_at", "is", null);

	if (error) {
		logger.error("[daily-maintenance] Failed to query expired trials", {
			error: error.message,
		});
		throw new Error("Failed to query expired trials");
	}

	if (!expiredProfiles || expiredProfiles.length === 0) {
		return { count: 0 };
	}

	let expired = 0;
	for (const profile of expiredProfiles) {
		try {
			await expireTrial(profile.id);
			expired++;
		} catch (err) {
			logger.error("[daily-maintenance] Failed to expire trial", {
				userId: profile.id,
				error: String(err),
			});
		}
	}

	logger.info("[daily-maintenance] Trial expiry complete", {
		expired,
		total: expiredProfiles.length,
	});
	return { count: expired };
}
