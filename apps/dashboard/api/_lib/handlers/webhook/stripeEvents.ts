import type { SupabaseClient } from "@supabase/supabase-js";
import type Stripe from "stripe";
import { logAudit } from "../../auditLog.js";
import { enforceAccountLimits } from "../../billing.js";
import {
	sendPaymentFailed,
	sendSubscriptionCancelled,
	sendSubscriptionConfirmation,
	sendTrialEndingSoon,
} from "../../emailService.js";
import { invalidateTierCache } from "../../tierGate.js";

interface StripeSubscriptionExt {
	current_period_start?: number | undefined;
	current_period_end?: number | undefined;
}

interface StripeInvoiceExt {
	subscription?: string | undefined;
	attempt_count?: number | undefined;
}

type Logger = {
	error: (message: string, meta?: Record<string, unknown>) => void;
	warn: (message: string, meta?: Record<string, unknown>) => void;
	info: (message: string, meta?: Record<string, unknown>) => void;
};

export interface StripeWebhookDeps {
	stripe: Stripe;
	// biome-ignore lint/suspicious/noExplicitAny: webhook updates heterogeneous typed tables and JSON payloads.
	supabase: SupabaseClient<any>;
	logger: Logger;
}

type StripeEventHandler = (
	event: Stripe.Event,
	deps: StripeWebhookDeps,
) => Promise<void>;

function toIsoFromUnixTimestamp(value?: number | null): string | null {
	return typeof value === "number"
		? new Date(value * 1000).toISOString()
		: null;
}

function formatUnixDate(value?: number | null): string | null {
	return typeof value === "number"
		? new Date(value * 1000).toLocaleDateString("en-US", {
				month: "long",
				day: "numeric",
				year: "numeric",
			})
		: null;
}

/**
 * Map a Stripe price ID to our internal tier. Returns null when the price
 * is unrecognized so callers fail closed instead of silently downgrading a
 * paying customer to free.
 */
export function getTierFromPriceId(
	priceId: string,
): "pro" | "agency" | "empire" | null {
	const proPrices = new Set(
		[
			process.env.STRIPE_PRICE_PRO_MONTHLY,
			process.env.STRIPE_PRICE_PRO_YEARLY,
			// Legacy ThreadsDash Pro prices (still active on some subscriptions)
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

	if (proPrices.has(priceId)) return "pro";
	if (agencyPrices.has(priceId)) return "agency";
	if (empirePrices.has(priceId)) return "empire";
	return null;
}

async function handleCheckoutSessionCompleted(
	event: Stripe.Event,
	{ stripe, supabase, logger }: StripeWebhookDeps,
) {
	const session = event.data.object as Stripe.Checkout.Session;
	const userId = session.metadata?.supabase_user_id;
	const workspaceId = session.metadata?.workspace_id;
	const tier = session.metadata?.tier as "pro" | "agency" | "empire";

	if (!userId || !session.subscription) return;

	invalidateTierCache(userId);

	const subscription = await stripe.subscriptions.retrieve(
		session.subscription as string,
	);
	const subscriptionExt = subscription as Stripe.Subscription &
		StripeSubscriptionExt;

	const profileUpdate: Record<string, unknown> = {
		subscription_tier: tier,
		subscription_status: subscription.status,
		stripe_subscription_id: subscription.id,
		updated_at: new Date().toISOString(),
	};

	if (subscription.trial_end) {
		profileUpdate.has_used_trial = true;
		profileUpdate.trial_started_at = new Date().toISOString();
		profileUpdate.trial_ends_at = new Date(
			subscription.trial_end * 1000,
		).toISOString();
	}

	const { error: profileErr } = await supabase
		.from("profiles")
		.update(profileUpdate)
		.eq("id", userId);

	if (profileErr) {
		logger.error("[webhook] Critical: failed to update profile on checkout", {
			userId,
			error: profileErr.message,
			eventId: event.id,
		});
		throw new Error(`Profile update failed: ${profileErr.message}`);
	}

	if (workspaceId) {
		const { error: wsErr } = await supabase
			.from("workspaces")
			.update({
				tier,
				subscription: {
					tier,
					status: subscription.status,
					stripe_customer_id: session.customer,
					stripe_subscription_id: subscription.id,
					billing_interval:
						subscription.items.data[0]?.price?.recurring?.interval || "month",
					current_period_start: toIsoFromUnixTimestamp(
						subscriptionExt.current_period_start,
					),
					current_period_end: toIsoFromUnixTimestamp(
						subscriptionExt.current_period_end,
					),
					cancel_at_period_end: subscription.cancel_at_period_end || false,
					trial_end_date: subscription.trial_end
						? new Date(subscription.trial_end * 1000).toISOString()
						: null,
				},
				updated_at: new Date().toISOString(),
			})
			.eq("id", workspaceId);

		if (wsErr) {
			logger.warn("[webhook] Non-critical: failed to update workspace on checkout", {
				workspaceId,
				error: wsErr.message,
			});
		}
	}

	logAudit(userId, "billing.subscription_created", {
		metadata: {
			tier,
			subscriptionId: subscription.id,
			status: subscription.status,
		},
	});

	try {
		const { data: profile } = await supabase
			.from("profiles")
			.select("email")
			.eq("id", userId)
			.maybeSingle();
		if (profile?.email) {
			const interval =
				subscription.items.data[0]?.price?.recurring?.interval === "year"
					? "yearly"
					: "monthly";
			await sendSubscriptionConfirmation(
				profile.email,
				tier,
				interval as "monthly" | "yearly",
			);
		}
	} catch (emailErr) {
		logger.warn("Failed to send subscription confirmation email", {
			error: String(emailErr),
		});
	}
}

async function handleCustomerSubscriptionChanged(
	event: Stripe.Event,
	{ supabase, logger }: StripeWebhookDeps,
) {
	// Treat created and updated identically — both carry the full
	// subscription object with metadata + price. Stripe fires created for
	// API-initiated subscriptions where checkout.session.completed never fires.
	const subscription = event.data.object as Stripe.Subscription;
	const subscriptionExt = subscription as Stripe.Subscription &
		StripeSubscriptionExt;
	const userId = subscription.metadata?.supabase_user_id;

	if (!userId) return;

	invalidateTierCache(userId);

	const priceId = subscription.items.data[0]?.price?.id;
	const tier = priceId ? getTierFromPriceId(priceId) : null;

	if (priceId && tier === null) {
		logger.error("[webhook] Unknown Stripe priceId — refusing to update tier", {
			userId,
			priceId,
			subscriptionId: subscription.id,
		});
		throw new Error(`unknown_price_id:${priceId}`);
	}

	const keepTier = ["active", "past_due", "trialing"].includes(
		subscription.status,
	);
	const newTier = keepTier && tier ? tier : "free";

	const { error: profileErr } = await supabase
		.from("profiles")
		.update({
			subscription_tier: newTier,
			subscription_status: subscription.status,
			stripe_subscription_id: subscription.id,
			updated_at: new Date().toISOString(),
		})
		.eq("id", userId);

	if (profileErr) {
		logger.error(
			"[webhook] Critical: failed to update profile on subscription change",
			{
				userId,
				error: profileErr.message,
				eventId: event.id,
			},
		);
		throw new Error(`Profile update failed: ${profileErr.message}`);
	}

	const workspaceId = subscription.metadata?.workspace_id;
	if (workspaceId) {
		const { error: wsErr } = await supabase
			.from("workspaces")
			.update({
				tier: keepTier ? tier : "free",
				subscription: {
					tier: keepTier ? tier : "free",
					status: subscription.status,
					stripe_subscription_id: subscription.id,
					billing_interval:
						subscription.items.data[0]?.price?.recurring?.interval || "month",
					current_period_start: toIsoFromUnixTimestamp(
						subscriptionExt.current_period_start,
					),
					current_period_end: toIsoFromUnixTimestamp(
						subscriptionExt.current_period_end,
					),
					cancel_at_period_end: subscription.cancel_at_period_end || false,
					trial_end_date: subscription.trial_end
						? new Date(subscription.trial_end * 1000).toISOString()
						: null,
				},
				updated_at: new Date().toISOString(),
			})
			.eq("id", workspaceId);

		if (wsErr) {
			logger.warn(
				"[webhook] Non-critical: failed to update workspace on subscription change",
				{
					workspaceId,
					error: wsErr.message,
				},
			);
		}
	}

	const effectiveTier = keepTier && tier ? tier : "free";
	await enforceAccountLimits(userId, effectiveTier);

	logAudit(userId, "billing.tier_change", {
		metadata: {
			tier: effectiveTier,
			status: subscription.status,
			subscriptionId: subscription.id,
		},
	});
}

async function handleCustomerSubscriptionDeleted(
	event: Stripe.Event,
	{ supabase, logger }: StripeWebhookDeps,
) {
	const subscription = event.data.object as Stripe.Subscription;
	const subscriptionExt = subscription as Stripe.Subscription &
		StripeSubscriptionExt;
	const userId = subscription.metadata?.supabase_user_id;

	if (!userId) return;

	invalidateTierCache(userId);

	const { error: profileErr } = await supabase
		.from("profiles")
		.update({
			subscription_tier: "free",
			subscription_status: "canceled",
			stripe_subscription_id: null,
			updated_at: new Date().toISOString(),
		})
		.eq("id", userId);

	if (profileErr) {
		logger.error(
			"[webhook] Critical: failed to downgrade profile on subscription deletion",
			{
				userId,
				error: profileErr.message,
				eventId: event.id,
			},
		);
		throw new Error(`Profile update failed: ${profileErr.message}`);
	}

	const workspaceId = subscription.metadata?.workspace_id;
	if (workspaceId) {
		const { error: wsErr } = await supabase
			.from("workspaces")
			.update({
				tier: "free",
				subscription: {
					tier: "free",
					status: "canceled",
					stripe_subscription_id: null,
					cancel_at_period_end: false,
				},
				updated_at: new Date().toISOString(),
			})
			.eq("id", workspaceId);

		if (wsErr) {
			logger.warn(
				"[webhook] Non-critical: failed to update workspace on subscription deletion",
				{
					workspaceId,
					error: wsErr.message,
				},
			);
		}
	}

	await enforceAccountLimits(userId, "free");

	logAudit(userId, "billing.subscription_canceled", {
		metadata: { subscriptionId: subscription.id },
	});

	try {
		const { data: profile } = await supabase
			.from("profiles")
			.select("email")
			.eq("id", userId)
			.maybeSingle();
		if (profile?.email) {
			const endDate = formatUnixDate(subscriptionExt.current_period_end) || "soon";
			await sendSubscriptionCancelled(profile.email, endDate);
		}
	} catch (emailErr) {
		logger.warn("Failed to send cancellation email", {
			error: String(emailErr),
		});
	}
}

async function handleInvoicePaymentFailed(
	event: Stripe.Event,
	{ stripe, supabase, logger }: StripeWebhookDeps,
) {
	const invoice = event.data.object as Stripe.Invoice;
	const subscriptionId = (invoice as unknown as StripeInvoiceExt)
		.subscription as string;

	if (!subscriptionId) return;

	const subscription = await stripe.subscriptions.retrieve(subscriptionId);
	const userId = subscription.metadata?.supabase_user_id;

	if (!userId) return;

	const { error: profileErr } = await supabase
		.from("profiles")
		.update({
			subscription_status: "past_due",
			updated_at: new Date().toISOString(),
		})
		.eq("id", userId);

	if (profileErr) {
		logger.error("[webhook] Critical: failed to set past_due on payment failure", {
			userId,
			error: profileErr.message,
			eventId: event.id,
		});
		throw new Error(`Profile update failed: ${profileErr.message}`);
	}

	logAudit(userId, "billing.payment_failed", {
		metadata: {
			invoiceId: invoice.id,
			attemptCount: (invoice as unknown as StripeInvoiceExt).attempt_count || 1,
		},
	});

	try {
		const { data: profile } = await supabase
			.from("profiles")
			.select("email")
			.eq("id", userId)
			.maybeSingle();
		if (profile?.email) {
			await sendPaymentFailed(
				profile.email,
				(invoice as unknown as StripeInvoiceExt).attempt_count || 1,
			);
		}
	} catch (emailErr) {
		logger.warn("Failed to send payment failed email", {
			error: String(emailErr),
		});
	}
}

async function handleInvoicePaymentSucceeded(
	event: Stripe.Event,
	{ stripe, supabase, logger }: StripeWebhookDeps,
) {
	const invoice = event.data.object as Stripe.Invoice;
	const subscriptionId = (invoice as unknown as StripeInvoiceExt)
		.subscription as string;

	if (!subscriptionId) return;

	const subscription = await stripe.subscriptions.retrieve(subscriptionId);
	const userId = subscription.metadata?.supabase_user_id;

	if (!userId) return;

	invalidateTierCache(userId);

	const priceId = subscription.items.data[0]?.price?.id;
	const tier = priceId ? getTierFromPriceId(priceId) : null;
	if (priceId && tier === null) {
		logger.error("[webhook] Unknown Stripe priceId on invoice.payment_succeeded", {
			userId,
			priceId,
			subscriptionId: subscription.id,
		});
	}

	const update: Record<string, unknown> = {
		subscription_status: "active",
		updated_at: new Date().toISOString(),
	};
	if (tier) update.subscription_tier = tier;

	const { error: profileErr } = await supabase
		.from("profiles")
		.update(update)
		.eq("id", userId);

	if (profileErr) {
		logger.error(
			"[webhook] Critical: failed to restore profile on payment success",
			{
				userId,
				error: profileErr.message,
				eventId: event.id,
			},
		);
		throw new Error(`Profile update failed: ${profileErr.message}`);
	}

	logAudit(userId, "billing.payment_succeeded", {
		metadata: { invoiceId: invoice.id, tier },
	});

	const workspaceId = subscription.metadata?.workspace_id;
	if (workspaceId && tier) {
		const { error: wsErr } = await supabase
			.from("workspaces")
			.update({
				tier,
				subscription: {
					id: subscription.id,
					status: "active",
					current_period_end: (subscription as unknown as StripeSubscriptionExt)
						.current_period_end,
					cancel_at_period_end: subscription.cancel_at_period_end,
				},
				updated_at: new Date().toISOString(),
			})
			.eq("id", workspaceId);

		if (wsErr) {
			logger.warn(
				"[webhook] Non-critical: failed to update workspace on payment success",
				{
					workspaceId,
					error: wsErr.message,
				},
			);
		}
	}
}

async function handleCustomerSubscriptionTrialWillEnd(
	event: Stripe.Event,
	{ supabase, logger }: StripeWebhookDeps,
) {
	const subscription = event.data.object as Stripe.Subscription;
	const userId = subscription.metadata?.supabase_user_id;

	if (!userId || !subscription.trial_end) return;

	const trialEndDate = new Date(subscription.trial_end * 1000);
	const { error: notifErr } = await supabase.from("notifications").upsert(
		{
			user_id: userId,
			type: "trial_ending",
			title: "Your trial is ending soon",
			message: `Your free trial will end on ${trialEndDate.toLocaleDateString()}. Subscribe now to keep your features.`,
			read: false,
			data: {
				subscription_id: subscription.id,
				trial_end: trialEndDate.toISOString(),
			},
		},
		{
			onConflict: "user_id,type,(data->>subscription_id)",
			ignoreDuplicates: true,
		},
	);

	if (notifErr) {
		logger.warn(
			"[webhook] Non-critical: failed to insert trial ending notification",
			{
				userId,
				error: notifErr.message,
			},
		);
	}

	try {
		const { data: profile } = await supabase
			.from("profiles")
			.select("email")
			.eq("id", userId)
			.maybeSingle();
		if (profile?.email) {
			const daysLeft = Math.max(
				1,
				Math.ceil(
					(subscription.trial_end * 1000 - Date.now()) /
						(1000 * 60 * 60 * 24),
				),
			);
			await sendTrialEndingSoon(profile.email, daysLeft);
		}
	} catch (emailErr) {
		logger.warn("Failed to send trial ending email", {
			error: String(emailErr),
		});
	}
}

export const STRIPE_EVENT_HANDLER_MAP: Partial<
	Record<Stripe.Event["type"], StripeEventHandler>
> = {
	"checkout.session.completed": handleCheckoutSessionCompleted,
	"customer.subscription.created": handleCustomerSubscriptionChanged,
	"customer.subscription.updated": handleCustomerSubscriptionChanged,
	"customer.subscription.deleted": handleCustomerSubscriptionDeleted,
	"invoice.payment_failed": handleInvoicePaymentFailed,
	"invoice.payment_succeeded": handleInvoicePaymentSucceeded,
	"customer.subscription.trial_will_end":
		handleCustomerSubscriptionTrialWillEnd,
};
