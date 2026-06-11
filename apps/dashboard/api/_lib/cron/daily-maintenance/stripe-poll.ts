/**
 * Phase 9: Stripe Subscription Status Poll
 * Safety net for missed Stripe webhooks: queries all users with an active
 * Stripe subscription and verifies DB status matches Stripe's truth.
 * Read-only from Stripe, write-only to local DB.
 */

import type { Logger, PhaseMetadata, TypedSupabaseClient } from "./shared.js";

export async function phaseStripeSubscriptionPoll(
	supabase: TypedSupabaseClient,
	logger: Logger,
): Promise<PhaseMetadata["stripeSubscriptionPoll"]> {
	let checked = 0;
	let corrected = 0;

	// Only import Stripe when this phase runs (lazy import for Vercel)
	const Stripe = (await import("stripe")).default;
	const stripeKey = process.env.STRIPE_SECRET_KEY;
	if (!stripeKey) {
		logger.warn(
			"[daily-maintenance] STRIPE_SECRET_KEY not set, skipping subscription poll",
		);
		return { checked: 0, corrected: 0 };
	}
	const stripeClient = new Stripe(stripeKey, {
		// @ts-expect-error — holding wire-format on clover to keep SDK majors no-op against prod; SDK only types LatestApiVersion (dahlia).
		apiVersion: "2026-02-25.clover",
	});

	// Query all profiles that have a Stripe subscription we should verify.
	// Includes active, past_due, and trialing — these are the states where
	// a missed webhook could cause the DB to drift from Stripe's truth.
	const { data: profiles, error } = await supabase
		.from("profiles")
		.select(
			"id, subscription_tier, subscription_status, stripe_subscription_id",
		)
		.not("stripe_subscription_id", "is", null)
		.in("subscription_status", ["active", "past_due", "trialing"]);

	if (error) {
		logger.error(
			"[daily-maintenance] Failed to query profiles for subscription poll",
			{ error: error.message },
		);
		return { checked: 0, corrected: 0, error: error.message };
	}

	if (!profiles?.length) {
		logger.info("[daily-maintenance] No active subscriptions to verify");
		return { checked: 0, corrected: 0 };
	}

	const { logAudit } = await import("../../auditLog.js");
	const { enforceAccountLimits } = await import("../../billing.js");
	const { invalidateTierCache } = await import("../../tierGate.js");

	// Price → tier mapping (mirrors webhook.ts getTierFromPriceId)
	const proPrices = new Set(
		[
			process.env.STRIPE_PRICE_PRO_MONTHLY,
			process.env.STRIPE_PRICE_PRO_YEARLY,
			"price_1SccE83aFLVx4e2SeU9eXSDd",
			"price_1SccFt3aFLVx4e2SCKQlBLmR",
		].filter(Boolean),
	);
	const empirePrices = new Set(
		[
			process.env.STRIPE_PRICE_EMPIRE_MONTHLY,
			process.env.STRIPE_PRICE_EMPIRE_YEARLY,
		].filter(Boolean),
	);
	const agencyPrices = new Set(
		[
			process.env.STRIPE_PRICE_AGENCY_MONTHLY,
			process.env.STRIPE_PRICE_AGENCY_YEARLY,
		].filter(Boolean),
	);
	function getTierFromPriceId(
		priceId: string,
	): "free" | "pro" | "agency" | "empire" {
		if (proPrices.has(priceId)) return "pro";
		if (agencyPrices.has(priceId)) return "agency";
		if (empirePrices.has(priceId)) return "empire";
		return "free";
	}

	// Process sequentially — Stripe rate limit is 25 req/s, we have few paid users
	for (const profile of profiles) {
		const subId = (profile as unknown as { stripe_subscription_id: string })
			.stripe_subscription_id;

		try {
			const stripeSub = await stripeClient.subscriptions.retrieve(subId);
			checked++;

			const stripeStatus = stripeSub.status; // active | past_due | unpaid | canceled | incomplete | incomplete_expired | trialing | paused
			const dbStatus = (profile as unknown as { subscription_status: string })
				.subscription_status;
			const dbTier = (profile as unknown as { subscription_tier: string })
				.subscription_tier;

			// Determine what tier the Stripe subscription actually corresponds to
			const priceId = stripeSub.items.data[0]?.price?.id;
			const stripeTier = priceId ? getTierFromPriceId(priceId) : "free";

			// Check if DB is out of sync with Stripe
			const statusMismatch = stripeStatus !== dbStatus;
			const tierMismatch = ["active", "past_due", "trialing"].includes(
				stripeStatus,
			)
				? stripeTier !== dbTier
				: dbTier !== "free"; // canceled/unpaid → should be free

			if (!statusMismatch && !tierMismatch) continue;

			// Determine corrective action based on Stripe's truth
			let newTier: string;
			let newStatus: string;

			if (["active", "trialing"].includes(stripeStatus)) {
				// Stripe says active/trialing — restore the correct tier
				newTier = stripeTier;
				newStatus = stripeStatus;
			} else if (stripeStatus === "past_due") {
				// Stripe says past_due — keep tier but mark status
				newTier = stripeTier;
				newStatus = "past_due";
			} else {
				// canceled, unpaid, incomplete_expired, paused → downgrade to free
				newTier = "free";
				newStatus = stripeStatus === "canceled" ? "canceled" : stripeStatus;
			}

			// Apply correction
			const profileUpdate: Record<string, unknown> = {
				subscription_status: newStatus,
				subscription_tier: newTier,
				updated_at: new Date().toISOString(),
			};
			// Clear subscription ID if Stripe says it's fully gone
			if (["canceled", "incomplete_expired"].includes(stripeStatus)) {
				profileUpdate.stripe_subscription_id = null;
			}

			await supabase
				.from("profiles")
				.update(profileUpdate as never)
				.eq("id", profile.id);

			// Invalidate tier cache so stale data isn't served
			invalidateTierCache(profile.id);

			// Enforce account limits if tier was corrected downward
			if (newTier !== dbTier && newTier !== "empire" && newTier !== "agency") {
				await enforceAccountLimits(profile.id, newTier);
			}

			logAudit(profile.id, "billing.subscription_poll_correction", {
				metadata: {
					stripeSubscriptionId: subId,
					stripeStatus,
					stripeTier,
					dbStatus,
					dbTier,
					correctedTo: { tier: newTier, status: newStatus },
				},
			});

			logger.warn(
				"[daily-maintenance] Subscription status corrected via Stripe poll",
				{
					userId: profile.id,
					stripeStatus,
					stripeTier,
					dbStatus,
					dbTier,
					correctedTo: { tier: newTier, status: newStatus },
				},
			);
			corrected++;
		} catch (err) {
			// Stripe API error for this specific subscription — log and continue
			const errMsg = err instanceof Error ? err.message : String(err);

			// If subscription doesn't exist in Stripe (deleted), clean up DB
			if (errMsg.includes("No such subscription")) {
				await supabase
					.from("profiles")
					.update({
						subscription_tier: "free",
						subscription_status: "canceled",
						stripe_subscription_id: null,
						updated_at: new Date().toISOString(),
					})
					.eq("id", profile.id);

				invalidateTierCache(profile.id);
				await enforceAccountLimits(profile.id, "free");

				logAudit(profile.id, "billing.subscription_poll_correction", {
					metadata: {
						stripeSubscriptionId: subId,
						reason: "subscription_not_found_in_stripe",
						correctedTo: { tier: "free", status: "canceled" },
					},
				});

				logger.warn(
					"[daily-maintenance] Subscription not found in Stripe — downgraded to free",
					{ userId: profile.id, subscriptionId: subId },
				);
				corrected++;
			} else {
				logger.error(
					"[daily-maintenance] Failed to verify subscription with Stripe",
					{ userId: profile.id, subscriptionId: subId, error: errMsg },
				);
			}
		}
	}

	logger.info("[daily-maintenance] Stripe subscription poll complete", {
		checked,
		corrected,
	});
	return { checked, corrected };
}
