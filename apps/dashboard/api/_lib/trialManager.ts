/**
 * Trial Manager — 14-day Pro trial lifecycle
 */

import { createNotification } from "./createNotification.js";
import { logger } from "./logger.js";
import { getSupabase } from "./supabase.js";

const db = () => getSupabase();

interface ProfileWithTrial {
	id?: string | undefined;
	trial_started_at?: string | null | undefined;
	trial_ends_at?: string | null | undefined;
	trial_used?: boolean | undefined;
	has_used_trial?: boolean | undefined;
	subscription_tier?: string | undefined;
}

/**
 * Check if the user's trial is currently active.
 */
export function isTrialActive(profile: ProfileWithTrial): boolean {
	if (!profile.trial_ends_at) return false;
	if (profile.trial_used || profile.has_used_trial) return false;
	return new Date(profile.trial_ends_at) > new Date();
}

/**
 * Get how many days remain in the trial.
 */
export function getTrialDaysRemaining(profile: ProfileWithTrial): number {
	if (!profile.trial_ends_at) return 0;
	const diff = new Date(profile.trial_ends_at).getTime() - Date.now();
	return Math.max(0, Math.ceil(diff / (1000 * 60 * 60 * 24)));
}

/**
 * Expire a trial — downgrade to free, mark used, notify user.
 */
export async function expireTrial(userId: string): Promise<void> {
	try {
		// Fetch usage stats for personalized message
		let aiQueries = 0;
		let scheduledPosts = 0;
		const followerGrowth = 0;

		try {
			const { count: aiCount } = await db()
				.from("feature_usage")
				.select("id", { count: "exact", head: true })
				.eq("user_id", userId)
				.in("feature_name", ["ai_advisor", "ai_generate", "ai_copilot"]);
			aiQueries = aiCount || 0;
		} catch (err) {
			logger.debug("skip", { error: String(err) });
		}

		try {
			const { count: postCount } = await db()
				.from("posts")
				.select("id", { count: "exact", head: true })
				.eq("user_id", userId)
				.eq("status", "scheduled");
			scheduledPosts = postCount || 0;
		} catch (err) {
			logger.debug("skip", { error: String(err) });
		}

		// #697: Atomic downgrade — only update if trial hasn't already been expired
		// Prevents race condition where concurrent calls both read trial_used=false
		const { data: updated } = await db()
			.from("profiles")
			.update({
				subscription_tier: "free",
				trial_used: true,
				has_used_trial: true,
				updated_at: new Date().toISOString(),
			})
			.eq("id", userId)
			.eq("trial_used", false)
			.select("id");

		// If no rows matched, trial was already expired by another call
		if (!updated || updated.length === 0) {
			logger.info("Trial already expired (no-op)", { userId });
			return;
		}

		// Personalized notification
		const usageParts: string[] = [];
		if (aiQueries > 0)
			usageParts.push(`You used AI insights ${aiQueries} times`);
		if (scheduledPosts > 0)
			usageParts.push(`scheduled ${scheduledPosts} posts`);

		const usageSummary =
			usageParts.length > 0
				? `During your 14-day trial: ${usageParts.join(", ")}. Keep the momentum → `
				: "";

		await createNotification({
			userId,
			type: "trial_expired",
			title: "Your Pro trial has ended",
			message: `${usageSummary}Upgrade to Pro to keep your AI insights and advanced analytics.`,
			data: { aiQueries, scheduledPosts, followerGrowth },
		});

		logger.info("Trial expired", { userId, aiQueries, scheduledPosts });
	} catch (err) {
		logger.error("Failed to expire trial", { userId, error: String(err) });
		throw err;
	}
}

/**
 * Start a 14-day Pro trial for a new user.
 */
export async function startTrial(userId: string): Promise<void> {
	const now = new Date();
	const trialEnd = new Date(now.getTime() + 14 * 24 * 60 * 60 * 1000);

	await db()
		.from("profiles")
		.update({
			subscription_tier: "pro",
			trial_started_at: now.toISOString(),
			trial_ends_at: trialEnd.toISOString(),
			trial_used: false,
			has_used_trial: true,
			updated_at: now.toISOString(),
		})
		.eq("id", userId);

	logger.info("Trial started", { userId, trialEndsAt: trialEnd.toISOString() });
}
