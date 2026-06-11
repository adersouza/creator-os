/**
 * Consolidated Subscription API Route
 *
 * POST /api/subscription?action=create-checkout|create-portal|cancel|update-addons|check-trial|plan-prices
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import type Stripe from "stripe";

// ============================================================================
// Row / API Types
// ============================================================================

interface ProfileCheckoutRow {
	stripe_customer_id?: string | undefined;
	stripe_subscription_id?: string | undefined;
	subscription_status?: string | undefined;
	email?: string | undefined;
	display_name?: string | undefined;
	has_used_trial?: boolean | undefined;
	is_beta_user?: boolean | undefined;
	beta_discount_code?: string | undefined;
}

interface ProfilePortalRow {
	stripe_customer_id?: string | undefined;
}

interface ProfileCancelRow {
	stripe_subscription_id?: string | undefined;
}

interface ProfileTrialRow {
	has_used_trial?: boolean | undefined;
	trial_started_at?: string | undefined;
	trial_ends_at?: string | undefined;
}

interface ProfileAddonsRow {
	stripe_subscription_id?: string | undefined;
	extra_accounts?: number | undefined;
	extra_team_members?: number | undefined;
}

import { apiError, apiSuccess } from "../../apiResponse.js";
import { logAudit } from "../../auditLog.js";
import { enforceAccountLimits } from "../../billing.js";
import { logger } from "../../logger.js";
import { requireStepUp, withAuth } from "../../middleware.js";
import {
	getPrivilegedSupabase,
	PRIVILEGED_DB_REASONS,
} from "../../privilegedDb.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { getStripe } from "../../stripeClient.js";
import { z, zEnum } from "../../zodCompat.js";

/**
 * Resolve a Stripe price ID from env. Throws a clear error if the env var
 * is missing — prevents silent empty-string failures during checkout.
 */
function requirePriceId(envVar: string): string {
	const val = process.env[envVar];
	if (!val) {
		throw new Error(`[subscription] Missing Stripe price: ${envVar}`);
	}
	return val;
}

// Addon price IDs are genuinely optional — empty string means DB-only tracking
const ADDON_PRICE_IDS: Record<string, string> = {
	extra_account: process.env.STRIPE_PRICE_EXTRA_ACCOUNT || "",
	extra_team_member: process.env.STRIPE_PRICE_EXTRA_TEAM_MEMBER || "",
};
const db = () =>
	getPrivilegedSupabase(PRIVILEGED_DB_REASONS.subscriptionManagement);

const CheckoutSchema = z.object({
	tier: zEnum(["pro", "agency", "empire"], {
		message: "tier must be pro, agency or empire",
	}),
	interval: zEnum(["monthly", "yearly"], {
		message: "interval must be monthly or yearly",
	}),
	workspaceId: z.string().optional(),
	successUrl: z.string().optional(),
	cancelUrl: z.string().optional(),
	trial: z.boolean().optional(),
});

const LIVE_STRIPE_SUBSCRIPTION_STATUSES = new Set([
	"active",
	"trialing",
	"past_due",
	"unpaid",
	"incomplete",
]);

const PLAN_PRICE_KEYS = [
	"creator",
	"pro",
	"agency",
	"white_label",
	"empire",
] as const;

type PlanPriceKey = (typeof PLAN_PRICE_KEYS)[number];
type PlanPriceInterval = "monthly" | "yearly";

function priceEnvKey(plan: PlanPriceKey, interval: PlanPriceInterval): string {
	return `STRIPE_PRICE_${plan.toUpperCase()}_${interval.toUpperCase()}`;
}

function formatStripeAmount(
	unitAmount: number | null,
	currency: string | null,
): string | null {
	if (unitAmount == null || !currency) return null;
	return new Intl.NumberFormat("en-US", {
		style: "currency",
		currency: currency.toUpperCase(),
		maximumFractionDigits: unitAmount % 100 === 0 ? 0 : 2,
	}).format(unitAmount / 100);
}

const CancelSchema = z.object({
	immediate: z.boolean().optional().default(false),
});

const MAX_EXTRA_ACCOUNTS = 5;
const MAX_EXTRA_TEAM_MEMBERS = 10;

const UpdateAddonsSchema = z.object({
	extraAccounts: z
		.number()
		.int()
		.min(0)
		.max(MAX_EXTRA_ACCOUNTS)
		.optional()
		.default(0),
	extraTeamMembers: z
		.number()
		.int()
		.min(0)
		.max(MAX_EXTRA_TEAM_MEMBERS)
		.optional()
		.default(0),
});

/**
 * Check if this Stripe customer already had a trial on a previous subscription.
 * Catches the scenario where a user cancels, creates a new workspace, and
 * tries to get another trial. The UNIQUE constraints on threads_user_id /
 * instagram_user_id prevent simultaneous cross-user linking at DB level;
 * this check adds Stripe-level dedup for the same customer identity.
 *
 * Returns a reason string if abuse detected, null if clean.
 */
async function checkCrossUserTrialAbuse(
	userId: string,
): Promise<string | null> {
	try {
		const { data: profile } = await db()
			.from("profiles")
			.select("stripe_customer_id")
			.eq("id", userId)
			.maybeSingle();

		if (!profile?.stripe_customer_id) return null;

		// Ask Stripe if this customer ever had a subscription with a trial
		const subs = await getStripe().subscriptions.list({
			customer: profile.stripe_customer_id,
			limit: 10,
			status: "all",
		});

		const hadTrial = subs.data.some((s) => s.trial_end !== null);
		if (hadTrial) return "stripe_customer_had_prior_trial";

		return null;
	} catch (err) {
		// Fail open — don't block legitimate checkouts if this check errors
		logger.warn("[subscription] Cross-user trial check failed, allowing", {
			userId,
			error: err instanceof Error ? err.message : String(err),
		});
		return null;
	}
}

async function handlePlanPrices(_req: VercelRequest, res: VercelResponse) {
	const stripe = getStripe();
	const prices: Record<
		PlanPriceKey,
		Partial<
			Record<
				PlanPriceInterval,
				{
					priceId: string;
					amount: number | null;
					currency: string | null;
					display: string | null;
					recurringInterval: string | null;
					recurringIntervalCount: number | null;
					lookupSource: "stripe";
				}
			>
		>
	> = {
		creator: {},
		pro: {},
		agency: {},
		white_label: {},
		empire: {},
	};

	await Promise.all(
		PLAN_PRICE_KEYS.flatMap((plan) =>
			(["monthly", "yearly"] as const).map(async (interval) => {
				const envKey = priceEnvKey(plan, interval);
				const priceId = process.env[envKey];
				if (!priceId) return;
				try {
					const price = await stripe.prices.retrieve(priceId);
					prices[plan][interval] = {
						priceId,
						amount: price.unit_amount,
						currency: price.currency,
						display: formatStripeAmount(price.unit_amount, price.currency),
						recurringInterval: price.recurring?.interval ?? null,
						recurringIntervalCount: price.recurring?.interval_count ?? null,
						lookupSource: "stripe",
					};
				} catch (err) {
					logger.warn("[subscription] Stripe price lookup failed", {
						envKey,
						priceId,
						error: err instanceof Error ? err.message : String(err),
					});
				}
			}),
		),
	);

	return apiSuccess(res, { prices });
}

// Create checkout session
async function handleCreateCheckout(
	req: VercelRequest,
	res: VercelResponse,
	user: { id: string; email?: string | undefined },
) {
	const parsed = CheckoutSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const { tier, interval, workspaceId, successUrl, cancelUrl, trial } =
		parsed.data;

	if (workspaceId) {
		const { data: workspace, error: workspaceError } = await db()
			.from("workspaces")
			.select("id, owner_id")
			.eq("id", workspaceId)
			.maybeSingle();
		if (workspaceError) {
			logger.error("[subscription] Workspace ownership lookup failed", {
				userId: user.id,
				workspaceId,
				error: String(workspaceError),
			});
			return apiError(res, 500, "Failed to verify workspace");
		}
		if (!workspace || workspace.owner_id !== user.id) {
			return apiError(res, 403, "You do not have billing access to this workspace", {
				code: "WORKSPACE_BILLING_ACCESS_DENIED",
			});
		}
	}

	const { data: profile } = (await db()
		.from("profiles")
		.select(
			"stripe_customer_id, stripe_subscription_id, subscription_status, email, display_name, has_used_trial, is_beta_user, beta_discount_code",
		)
		.eq("id", user.id)
		.maybeSingle()) as { data: ProfileCheckoutRow | null; error: unknown };

	let stripeCustomerId = profile?.stripe_customer_id;

	if (!stripeCustomerId) {
		const customerParams: Stripe.CustomerCreateParams = {
			metadata: { supabase_user_id: user.id },
		};
		const customerEmail = user.email || profile?.email;
		if (customerEmail) customerParams.email = customerEmail;
		if (profile?.display_name) customerParams.name = profile.display_name;
		const customer = await getStripe().customers.create(customerParams);
		stripeCustomerId = customer.id;
		await db()
			.from("profiles")
			.update({ stripe_customer_id: customer.id })
			.eq("id", user.id);
	}

	if (profile?.stripe_subscription_id) {
		let existingSubscription: Stripe.Subscription;
		try {
			existingSubscription = await getStripe().subscriptions.retrieve(
				profile.stripe_subscription_id,
			);
		} catch (error) {
			logger.error("[subscription] Failed to verify existing subscription", {
				userId: user.id,
				subscriptionId: profile.stripe_subscription_id,
				error: String(error),
			});
			return apiError(
				res,
				502,
				"Could not verify your current subscription. Please try again.",
			);
		}
		if (LIVE_STRIPE_SUBSCRIPTION_STATUSES.has(existingSubscription.status)) {
			const baseUrl = process.env.APP_URL || "https://juno33.com";
			const portal = await getStripe().billingPortal.sessions.create({
				customer: stripeCustomerId,
				return_url:
					successUrl || `${baseUrl}/settings?tab=subscription&subscription=true`,
			});
			return apiSuccess(res, {
				url: portal.url,
				mode: "billing_portal",
				reason: "active_subscription_exists",
			});
		}
	}

	const priceEnvVar = `STRIPE_PRICE_${tier.toUpperCase()}_${interval.toUpperCase()}`;
	let priceId: string;
	try {
		priceId = requirePriceId(priceEnvVar);
	} catch {
		return apiError(
			res,
			500,
			`Stripe price not configured for ${tier}_${interval}`,
		);
	}

	let trialPeriodDays: number | undefined;
	if (trial && !profile?.has_used_trial) {
		// Cross-user trial abuse check: verify that none of this user's Meta
		// accounts were previously linked to a profile that already used a trial.
		// The UNIQUE constraints on threads_user_id / instagram_user_id prevent
		// simultaneous linking, but a user could unlink from profile A, create
		// profile B, re-link the same Meta account, and request a new trial.
		const trialAbuse = await checkCrossUserTrialAbuse(user.id);
		if (!trialAbuse) {
			trialPeriodDays = 14;
		} else {
			logger.info("[subscription] Trial blocked — cross-user abuse detected", {
				userId: user.id,
				reason: trialAbuse,
			});
		}
	}

	const baseUrl = process.env.APP_URL || "https://juno33.com";

	// Apply beta discount coupon if user is a beta tester
	// v22 reshuffled types: Checkout.SessionCreateParams is now a type alias,
	// so nested namespace access (.Discount) no longer propagates. Reach the
	// element type via indexed-access on the params interface instead.
	const discounts: NonNullable<
		Stripe.Checkout.SessionCreateParams["discounts"]
	> = [];
	if (profile?.is_beta_user && profile?.beta_discount_code === "BETA30") {
		// Use the BETA30 coupon configured in Stripe for 30% lifetime discount
		const betaCouponId = process.env.STRIPE_BETA_COUPON_ID;
		if (betaCouponId) {
			discounts.push({ coupon: betaCouponId });
		} else {
			logger.warn(
				"[subscription] Beta user but STRIPE_BETA_COUPON_ID not configured",
				{ userId: user.id },
			);
		}
	}

	const idempotencyHeader =
		typeof req.headers["idempotency-key"] === "string"
			? req.headers["idempotency-key"]
			: undefined;
	const stripeRequestOptions: Stripe.RequestOptions | undefined = idempotencyHeader
		? {
				idempotencyKey: `checkout:${user.id}:${tier}:${interval}:${idempotencyHeader}`.slice(
					0,
					255,
				),
			}
		: undefined;
	const session = await getStripe().checkout.sessions.create({
		customer: stripeCustomerId,
		mode: "subscription",
		payment_method_types: ["card"],
		line_items: [{ price: priceId, quantity: 1 }],
		subscription_data: {
			...(trialPeriodDays ? { trial_period_days: trialPeriodDays } : {}),
			metadata: {
				supabase_user_id: user.id,
				workspace_id: workspaceId || "",
				tier,
			},
		},
		success_url:
			successUrl || `${baseUrl}/settings?tab=subscription&success=true`,
		cancel_url:
			cancelUrl || `${baseUrl}/settings?tab=subscription&canceled=true`,
		metadata: {
			supabase_user_id: user.id,
			workspace_id: workspaceId || "",
			tier,
		},
		// Apply beta discount if available, otherwise allow manual promo codes
		...(discounts.length > 0 ? { discounts } : { allow_promotion_codes: true }),
	}, stripeRequestOptions);

	// NOTE: Trial fields (has_used_trial, trial_started_at, trial_ends_at, subscription_tier)
	// are set in the Stripe webhook handler (checkout.session.completed) — NOT here.
	// Setting them before payment completes would prevent retry if payment fails.

	// Store billing interval
	const billingInterval =
		parsed.data.interval === "yearly" ? "annual" : "monthly";
	await db()
		.from("profiles")
		.update({ billing_interval: billingInterval })
		.eq("id", user.id);

	return apiSuccess(res, { sessionId: session.id, url: session.url });
}

// Create portal session
async function handleCreatePortal(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { returnUrl } = req.body || {};

	const { data: profile } = (await db()
		.from("profiles")
		.select("stripe_customer_id")
		.eq("id", userId)
		.maybeSingle()) as { data: ProfilePortalRow | null; error: unknown };

	if (!profile?.stripe_customer_id) {
		return apiError(res, 400, "No billing account found");
	}

	const baseUrl = process.env.APP_URL || "https://juno33.com";

	const session = await getStripe().billingPortal.sessions.create({
		customer: profile?.stripe_customer_id,
		return_url: returnUrl || `${baseUrl}/settings?tab=subscription`,
	});

	return apiSuccess(res, { url: session.url });
}

// Cancel subscription
async function handleCancel(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = CancelSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const { immediate } = parsed.data;

	const { data: profile } = (await db()
		.from("profiles")
		.select("stripe_subscription_id")
		.eq("id", userId)
		.maybeSingle()) as { data: ProfileCancelRow | null; error: unknown };

	if (!profile?.stripe_subscription_id) {
		return apiError(res, 400, "No active subscription found");
	}

	if (immediate) {
		await getStripe().subscriptions.cancel(profile?.stripe_subscription_id);
		await db()
			.from("profiles")
			.update({
				subscription_tier: "free",
				subscription_status: "canceled",
				stripe_subscription_id: null,
				updated_at: new Date().toISOString(),
			})
			.eq("id", userId);

		// Enforce account limits — free tier allows only 1 account
		await enforceAccountLimits(userId, "free");
	} else {
		await getStripe().subscriptions.update(profile?.stripe_subscription_id, {
			cancel_at_period_end: true,
		});
		await db()
			.from("profiles")
			.update({
				subscription_status: "canceling",
				updated_at: new Date().toISOString(),
			})
			.eq("id", userId);
	}

	return apiSuccess(res, { immediate });
}

// Check trial eligibility
async function handleCheckTrial(
	_req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { data: profile } = (await db()
		.from("profiles")
		.select("has_used_trial, trial_started_at, trial_ends_at")
		.eq("id", userId)
		.maybeSingle()) as { data: ProfileTrialRow | null; error: unknown };

	const eligible = !profile?.has_used_trial;
	let daysRemaining = 0;

	if (profile?.trial_ends_at) {
		const endDate = new Date(profile?.trial_ends_at);
		const now = new Date();
		daysRemaining = Math.max(
			0,
			Math.ceil((endDate.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)),
		);
	}

	return apiSuccess(res, {
		eligible,
		hasUsedTrial: profile?.has_used_trial || false,
		trialStartedAt: profile?.trial_started_at,
		trialEndsAt: profile?.trial_ends_at,
		daysRemaining,
	});
}

// Update addons
async function handleUpdateAddons(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = UpdateAddonsSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const { extraAccounts, extraTeamMembers } = parsed.data;
	const newExtraAccounts = extraAccounts;
	const newExtraTeamMembers = extraTeamMembers;

	const { data: profile } = (await db()
		.from("profiles")
		.select("stripe_subscription_id, extra_accounts, extra_team_members")
		.eq("id", userId)
		.maybeSingle()) as { data: ProfileAddonsRow | null; error: unknown };

	if (!profile?.stripe_subscription_id) {
		return apiError(res, 400, "No active subscription found");
	}

	let stripeUpdated = false;

	// Update Stripe if addon price IDs are configured
	if (ADDON_PRICE_IDS.extra_account || ADDON_PRICE_IDS.extra_team_member) {
		try {
			const subscription = await getStripe().subscriptions.retrieve(
				profile?.stripe_subscription_id,
			);

			const updates: Stripe.SubscriptionUpdateParams = { items: [] };

			// Handle extra accounts addon
			if (
				ADDON_PRICE_IDS.extra_account &&
				newExtraAccounts !== (profile?.extra_accounts || 0)
			) {
				const existingItem = subscription.items.data.find(
					(item) => item.price.id === ADDON_PRICE_IDS.extra_account,
				);

				if (existingItem) {
					// Update existing item quantity — cap as defense-in-depth
					updates.items?.push({
						id: existingItem.id,
						quantity: Math.min(newExtraAccounts, MAX_EXTRA_ACCOUNTS),
					});
				} else if (newExtraAccounts > 0) {
					// Add new item — cap as defense-in-depth
					updates.items?.push({
						price: ADDON_PRICE_IDS.extra_account,
						quantity: Math.min(newExtraAccounts, MAX_EXTRA_ACCOUNTS),
					});
				}
			}

			// Handle extra team members addon
			if (
				ADDON_PRICE_IDS.extra_team_member &&
				newExtraTeamMembers !== (profile?.extra_team_members || 0)
			) {
				const existingItem = subscription.items.data.find(
					(item) => item.price.id === ADDON_PRICE_IDS.extra_team_member,
				);

				if (existingItem) {
					updates.items?.push({
						id: existingItem.id,
						quantity: Math.min(newExtraTeamMembers, MAX_EXTRA_TEAM_MEMBERS),
					});
				} else if (newExtraTeamMembers > 0) {
					updates.items?.push({
						price: ADDON_PRICE_IDS.extra_team_member,
						quantity: Math.min(newExtraTeamMembers, MAX_EXTRA_TEAM_MEMBERS),
					});
				}
			}

			// Apply Stripe updates if there are any
			if (updates.items && updates.items.length > 0) {
				await getStripe().subscriptions.update(
					profile?.stripe_subscription_id,
					updates,
				);
				stripeUpdated = true;
				logger.info("Updated Stripe addons", {
					extraAccounts: newExtraAccounts,
					extraTeamMembers: newExtraTeamMembers,
				});
			}
		} catch (stripeError: unknown) {
			logger.error("Failed to update Stripe addons", {
				error:
					stripeError instanceof Error
						? stripeError.message
						: String(stripeError),
			});
			return apiError(
				res,
				502,
				"Failed to update billing. Your plan was not changed. Please try again.",
			);
		}
	}

	// Update database only after Stripe succeeds (or if Stripe price IDs not configured)
	await db()
		.from("profiles")
		.update({
			extra_accounts: newExtraAccounts,
			extra_team_members: newExtraTeamMembers,
			updated_at: new Date().toISOString(),
		})
		.eq("id", userId);

	// If add-on slots were reduced, deactivate any accounts now over the new limit
	const oldExtraAccounts = profile?.extra_accounts || 0;
	if (newExtraAccounts < oldExtraAccounts) {
		await enforceAccountLimits(userId, "pro", newExtraAccounts);
	}

	return apiSuccess(res, {
		stripeUpdated,
		extraAccounts: newExtraAccounts,
		extraTeamMembers: newExtraTeamMembers,
	});
}

export default withAuth(async (req, res, user) => {
	const userId = user.id;

	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	// Rate limit billing operations: 10 requests/min per user
	const rl = await checkRateLimit({
		key: `subscription:${userId}`,
		limit: 10,
		windowSeconds: 60,
		failMode: "closed",
	});
	if (!rl.allowed) {
		return apiError(res, 429, "Too many requests. Please wait a moment.");
	}

	const action = req.query.action as string;

	try {
		switch (action) {
			case "create-checkout":
				logAudit(userId, "subscription.create-checkout", { req });
				return handleCreateCheckout(req, res, user);
			case "plan-prices":
				return handlePlanPrices(req, res);
			case "create-portal":
				return handleCreatePortal(req, res, userId);
			case "cancel": {
				// Cancelling affects revenue + grace periods; force step-up if
				// the user has TOTP enrolled so a stolen session alone can't do it.
				const stepUp = await requireStepUp(req, res, userId);
				if (stepUp) return stepUp;
				logAudit(userId, "subscription.cancel", { req });
				return handleCancel(req, res, userId);
			}
			case "check-trial":
				return handleCheckTrial(req, res, userId);
			case "update-addons":
				return handleUpdateAddons(req, res, userId);
			case "upgrade-empire":
				// Alias: upgrade-empire is just create-checkout with tier=empire
				return handleCreateCheckout(req, res, user);
			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("Subscription API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
