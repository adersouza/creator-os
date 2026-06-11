/**
 * Subscription Service
 * Handles all subscription-related operations with Stripe
 */

import { z } from "zod";
import { ApiHttpError, apiFetch } from "@/lib/apiFetch";
import { apiUrl } from "@/lib/apiUrl";
import { subscribe } from "@/services/realtimeManager";
import {
	ADDON_CONFIG,
	type BillingInterval,
	getEffectiveAccountLimit,
	PRICING,
	type SubscriptionTier,
	TIER_LIMITS,
	type Workspace,
	type WorkspaceSubscription,
} from "@/types/team";
import logger from "@/utils/logger";
import { supabase } from "./supabase";

// Helper to get current user ID for Supabase
const getSupabaseUserId = async (): Promise<string | null> => {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	return session?.user?.id || null;
};

async function requireSession(): Promise<void> {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	if (!session?.access_token) throw new Error("Not authenticated");
}

export interface CheckoutSessionResult {
	url: string;
	sessionId: string;
	trialGranted?: boolean | undefined;
}

export interface TrialStatus {
	eligible: boolean;
	reason?: string | undefined;
	hasUsedTrial?: boolean | undefined;
	emailBlocked?: boolean | undefined;
	ipRateLimited?: boolean | undefined;
}

export interface UsageStats {
	accountCount: number;
	accountLimit: number;
	memberCount: number;
	memberLimit: number;
	addOnsCount: number;
	tier: SubscriptionTier;
	isAtAccountLimit: boolean;
	isAtMemberLimit: boolean;
	canAddMoreAddons: boolean;
	percentAccountsUsed: number;
	percentMembersUsed: number;
}

export type StripePlanPriceKey =
	| "creator"
	| "pro"
	| "agency"
	| "white_label"
	| "empire";

export type StripePlanPrice = {
	priceId: string;
	amount: number | null;
	currency: string | null;
	display: string | null;
	recurringInterval: string | null;
	recurringIntervalCount: number | null;
	lookupSource: "stripe";
};

export type StripePlanPrices = Record<
	StripePlanPriceKey,
	Partial<Record<"monthly" | "yearly", StripePlanPrice>>
>;

const stripePlanPriceSchema = z.object({
	priceId: z.string(),
	amount: z.number().nullable(),
	currency: z.string().nullable(),
	display: z.string().nullable(),
	recurringInterval: z.string().nullable(),
	recurringIntervalCount: z.number().nullable(),
	lookupSource: z.literal("stripe"),
});

const planPriceIntervalsSchema = z.object({
	monthly: stripePlanPriceSchema.optional(),
	yearly: stripePlanPriceSchema.optional(),
});

const planPricesResponseSchema = z.object({
	success: z.boolean().optional(),
	prices: z
		.object({
			creator: planPriceIntervalsSchema.optional(),
			pro: planPriceIntervalsSchema.optional(),
			agency: planPriceIntervalsSchema.optional(),
			white_label: planPriceIntervalsSchema.optional(),
			empire: planPriceIntervalsSchema.optional(),
		})
		.nullable()
		.optional(),
});

const trialStatusSchema = z.object({
	success: z.boolean().optional(),
	eligible: z.boolean(),
	reason: z.string().optional(),
	hasUsedTrial: z.boolean().optional(),
	emailBlocked: z.boolean().optional(),
	ipRateLimited: z.boolean().optional(),
});

const checkoutSessionResponseSchema = z.object({
	success: z.boolean().optional(),
	url: z.string(),
	sessionId: z.string(),
	trialGranted: z.boolean().optional(),
});

const portalSessionResponseSchema = z.object({
	success: z.boolean().optional(),
	url: z.string(),
});

const okResponseSchema = z.object({
	success: z.boolean().optional(),
});

function apiErrorMessage(error: unknown, fallback: string): string {
	if (error instanceof ApiHttpError) {
		try {
			const body = JSON.parse(error.body) as { error?: unknown | undefined };
			if (typeof body.error === "string") return body.error;
		} catch {
			/* keep fallback */
		}
	}
	return error instanceof Error ? error.message : fallback;
}

class SubscriptionService {
	/**
	 * Fetch live Stripe Price objects for the billing page. Missing env-backed
	 * prices are omitted so the UI can avoid displaying stale hardcoded prices.
	 */
	async getPlanPrices(): Promise<StripePlanPrices | null> {
		try {
			try {
				await requireSession();
			} catch {
				return null;
			}

			const data = await apiFetch(
				"/api/subscription?action=plan-prices",
				planPricesResponseSchema,
				{ method: "POST" },
			);

			return (data.prices ?? null) as StripePlanPrices | null;
		} catch (error: unknown) {
			logger.warn("Failed to load Stripe plan prices", {
				error: error instanceof Error ? error.message : String(error),
			});
			return null;
		}
	}

	/**
	 * Check if user is eligible for a free trial
	 * Returns eligibility status and reason if not eligible
	 */
	async checkTrialEligibility(): Promise<TrialStatus> {
		try {
			try {
				await requireSession();
			} catch {
				return {
					eligible: false,
					reason: "Not authenticated",
				};
			}

			const data = await apiFetch(
				"/api/subscription?action=check-trial",
				trialStatusSchema,
				{ method: "POST" },
			);

			return data;
		} catch (error: unknown) {
			logger.error("Failed to check trial status:", error);
			return {
				eligible: false,
				reason: apiErrorMessage(error, "Unable to verify trial eligibility"),
			};
		}
	}

	/**
	 * Create a Stripe Checkout session for upgrading
	 * @param requestTrial - Whether to request trial (will be verified server-side)
	 */
	async createCheckoutSession(
		workspaceId: string,
		tier: "pro" | "agency" | "empire",
		billing: BillingInterval,
		options?: {
			requestTrial?: boolean | undefined;
			successUrl?: string | undefined;
			cancelUrl?: string | undefined;
		},
	): Promise<CheckoutSessionResult> {
		try {
			await requireSession();

			return await apiFetch(
				"/api/subscription?action=create-checkout",
				checkoutSessionResponseSchema,
				{
					method: "POST",
					headers: {
						"X-Idempotency-Key": `checkout-${workspaceId}-${tier}-${Math.floor(Date.now() / 60000)}`,
					},
					json: {
						workspaceId,
						tier,
						interval: billing === "year" ? "yearly" : "monthly",
						trial: options?.requestTrial ?? true,
						successUrl:
							options?.successUrl ||
							`${window.location.origin}/welcome/success?session_id={CHECKOUT_SESSION_ID}`,
						cancelUrl: options?.cancelUrl || `${window.location.origin}/welcome`,
					},
				},
			);
		} catch (error: unknown) {
			logger.error("Failed to create checkout session:", error);
			throw new Error(apiErrorMessage(error, "Failed to start checkout"));
		}
	}

	/**
	 * Upgrade from Agency to Empire tier
	 * Uses proration for fair billing
	 */
	async upgradeToEmpire(
		workspaceId: string,
		billing: BillingInterval,
	): Promise<CheckoutSessionResult> {
		try {
			await requireSession();

			return await apiFetch(
				"/api/subscription?action=upgrade-empire",
				checkoutSessionResponseSchema,
				{
					method: "POST",
					json: {
						workspaceId,
						tier: "empire",
						interval: billing === "year" ? "yearly" : "monthly",
						successUrl: `${window.location.origin}/settings?upgraded=empire`,
						cancelUrl: `${window.location.origin}/settings`,
					},
				},
			);
		} catch (error: unknown) {
			logger.error("Failed to upgrade to Empire:", error);
			throw new Error(apiErrorMessage(error, "Failed to upgrade to Empire"));
		}
	}

	/**
	 * Create a Stripe Customer Portal session for managing subscription
	 */
	async createPortalSession(workspaceId: string): Promise<string> {
		try {
			await requireSession();

			const data = await apiFetch(
				"/api/subscription?action=create-portal",
				portalSessionResponseSchema,
				{
					method: "POST",
					json: {
						workspaceId,
						returnUrl: `${window.location.origin}/settings`,
					},
				},
			);

			return data.url;
		} catch (error: unknown) {
			logger.error("Failed to create portal session:", error);
			throw new Error(apiErrorMessage(error, "Failed to open billing portal"));
		}
	}

	/**
	 * Update add-ons count for Pro tier
	 */
	async updateAddOns(workspaceId: string, newCount: number): Promise<void> {
		if (newCount < 0 || newCount > ADDON_CONFIG.maxAddons) {
			throw new Error(
				`Add-ons must be between 0 and ${ADDON_CONFIG.maxAddons}`,
			);
		}

		try {
			await requireSession();

			await apiFetch(
				"/api/subscription?action=update-addons",
				okResponseSchema,
				{
					method: "POST",
					json: {
						workspaceId,
						addOnsCount: newCount,
					},
				},
			);
		} catch (error: unknown) {
			logger.error("Failed to update add-ons:", error);
			throw new Error(apiErrorMessage(error, "Failed to update add-ons"));
		}
	}

	/**
	 * Cancel subscription (with grace period)
	 */
	async cancelSubscription(workspaceId: string): Promise<void> {
		try {
			const {
				data: { session },
			} = await supabase.auth.getSession();
			if (!session) {
				throw new Error("Not authenticated");
			}

			const response = await fetch(apiUrl("/api/subscription?action=cancel"), {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${session.access_token}`,
				},
				body: JSON.stringify({ workspaceId }),
			});

			const { handleMfaStepUp } = await import("@/lib/authErrors");
			if (await handleMfaStepUp(response)) {
				throw new Error("MFA step-up required");
			}

			const data = await response.json();
			if (!response.ok) {
				throw new Error(data.error || "Failed to cancel subscription");
			}
		} catch (error: unknown) {
			logger.error("Failed to cancel subscription:", error);
			throw new Error(
				error instanceof Error
					? error.message
					: "Failed to cancel subscription",
			);
		}
	}

	/**
	 * Get current subscription for a workspace
	 */
	async getSubscription(
		workspaceId: string,
	): Promise<WorkspaceSubscription | null> {
		try {
			const { data, error } = await supabase
				.from("workspaces")
				.select("tier, subscription")
				.eq("id", workspaceId)
				.maybeSingle();

			if (error || !data) return null;

			// Parse subscription data from Supabase
			// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
			const subscription = (data as any).subscription;
			if (!subscription) return null;

			return {
				// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
				tier: subscription.tier || (data as any).tier || "free",
				status: subscription.status || "active",
				currentPeriodStart: subscription.current_period_start
					? new Date(subscription.current_period_start)
					: undefined,
				currentPeriodEnd: subscription.current_period_end
					? new Date(subscription.current_period_end)
					: undefined,
				cancelAtPeriodEnd: subscription.cancel_at_period_end || false,
				billingInterval: subscription.billing_interval,
				addOnsCount: subscription.add_ons_count || 0,
				trialEndAt: subscription.trial_end_date
					? new Date(subscription.trial_end_date)
					: undefined,
			} as WorkspaceSubscription;
		} catch (error) {
			logger.error("Failed to get subscription:", error);
			return null;
		}
	}

	/**
	 * Subscribe to subscription changes in real-time
	 */
	subscribeToSubscription(
		workspaceId: string,
		callback: (subscription: WorkspaceSubscription | null) => void,
	): () => void {
		// Initial fetch
		this.getSubscription(workspaceId).then(callback);

		return subscribe(
			`workspace-subscription:${workspaceId}`,
			() =>
				supabase
					.channel(`workspace-subscription-${workspaceId}`)
					.on(
						"postgres_changes",
						{
							event: "*",
							schema: "public",
							table: "workspaces",
							filter: `id=eq.${workspaceId}`,
						},
						(payload) => {
							const data = payload.new as Record<string, unknown>;
							if (data) {
								const subscription = data.subscription as Record<
									string,
									unknown
								> | null;
								if (subscription) {
									callback({
										tier:
											(subscription.tier as SubscriptionTier) ||
											(data.tier as SubscriptionTier) ||
											"free",
										status: (subscription.status as string) || "active",
										currentPeriodStart: subscription.current_period_start
											? new Date(subscription.current_period_start as string)
											: undefined,
										currentPeriodEnd: subscription.current_period_end
											? new Date(subscription.current_period_end as string)
											: undefined,
										cancelAtPeriodEnd:
											(subscription.cancel_at_period_end as boolean) || false,
										billingInterval: subscription.billing_interval as
											| "month"
											| "year",
										addOnsCount: (subscription.add_ons_count as number) || 0,
										trialEndAt: subscription.trial_end_date
											? new Date(subscription.trial_end_date as string)
											: undefined,
									} as WorkspaceSubscription);
								} else {
									callback(null);
								}
							} else {
								callback(null);
							}
						},
					)
					.subscribe(),
			() => {
				this.getSubscription(workspaceId).then(callback);
			},
		);
	}

	/**
	 * Calculate usage stats for a workspace
	 */
	async getUsageStats(
		workspaceId: string,
		options?: {
			workspace?: Workspace | null | undefined;
			memberCount?: number | undefined;
		},
	): Promise<UsageStats> {
		try {
			const userId = await getSupabaseUserId();
			if (!userId) {
				throw new Error("Not authenticated");
			}

			let workspaceData: {
				tier?: string | null | undefined;
				subscription?: Record<string, unknown> | null | undefined;
				account_count?: number | null | undefined;
				member_count?: number | null | undefined;
			} | null = null;
			if (options?.workspace) {
				workspaceData = {
					tier: options.workspace.subscriptionTier,
					subscription: options.workspace.subscription
						? {
								...options.workspace.subscription,
								add_ons_count: options.workspace.subscription.addOnsCount,
							}
						: null,
					account_count: options.workspace.accountCount ?? null,
					member_count: options.workspace.memberCount ?? null,
				};
			} else {
				// Get workspace data
				const { data, error: wsError } = await supabase
					.from("workspaces")
					.select("tier, subscription, account_count, member_count")
					.eq("id", workspaceId)
					.maybeSingle();

				if (wsError || !data) {
					throw new Error("Workspace not found");
				}
				workspaceData = data;
			}

			// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
			const tier = ((workspaceData as any).tier || "free") as SubscriptionTier;
			// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
			const subscription = (workspaceData as any).subscription as Record<
				string,
				unknown
			> | null;
			const addOnsCount = (subscription?.add_ons_count as number) || 0;

			// Prefer the denormalized workspace count. The shell calls this on app
			// boot for every route, so avoiding a fresh HEAD count keeps navigation
			// from surfacing aborted Supabase requests during reload-style smoke tests.
			// Fall back to a narrow count only when the workspace row has not been
			// backfilled yet.
			// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
			let accountCount = (workspaceData as any).account_count as number | null;
			if (typeof accountCount !== "number") {
				try {
					const { count, error: accError } = await supabase
						.from("accounts")
						.select("id", { count: "exact", head: true })
						.eq("user_id", userId);

					if (!accError) {
						accountCount = count || 0;
					}
				} catch (e) {
					logger.warn("Could not count accounts:", e);
					accountCount = 0;
				}
			}
			accountCount = accountCount ?? 0;

			// Get member count from workspace_members
			let memberCount = options?.memberCount ?? 1;
			try {
				if (options?.memberCount === undefined) {
					const { count, error: memError } = await supabase
						.from("workspace_members")
						.select("*", { count: "exact", head: true })
						.eq("workspace_id", workspaceId);

					if (!memError) {
						memberCount = count || 1;
					}
				}
			} catch (e) {
				logger.warn("Could not count members:", e);
				// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
				memberCount = ((workspaceData as any).member_count as number) || 1;
			}

			const accountLimit = getEffectiveAccountLimit(tier, addOnsCount);
			const memberLimit = TIER_LIMITS[tier].maxMembers;

			return {
				accountCount,
				accountLimit,
				memberCount,
				memberLimit,
				addOnsCount,
				tier,
				isAtAccountLimit: accountCount >= accountLimit,
				isAtMemberLimit: memberCount >= memberLimit,
				canAddMoreAddons:
					tier === "pro" && addOnsCount < ADDON_CONFIG.maxAddons,
				percentAccountsUsed:
					accountLimit === Infinity
						? 0
						: Math.round((accountCount / accountLimit) * 100),
				percentMembersUsed:
					memberLimit === Infinity
						? 0
						: Math.round((memberCount / memberLimit) * 100),
			};
		} catch (error) {
			logger.error("Failed to get usage stats:", error);
			throw error;
		}
	}

	/**
	 * Check if user can add a new account
	 */
	async canAddAccount(workspaceId: string): Promise<{
		allowed: boolean;
		reason?: string | undefined;
		upsellTier?: SubscriptionTier | undefined;
	}> {
		try {
			const stats = await this.getUsageStats(workspaceId);

			if (!stats.isAtAccountLimit) {
				return { allowed: true };
			}

			// At limit - determine upsell path
			if (stats.tier === "free") {
				return {
					allowed: false,
					reason: "Free plan limited to 1 account",
					upsellTier: "pro",
				};
			}

			if (stats.tier === "pro") {
				if (stats.canAddMoreAddons) {
					return {
						allowed: false,
						reason: `You've used all ${stats.accountLimit} accounts. Add more for $8/mo each.`,
						upsellTier: "pro", // Show add-on purchase
					};
				} else {
					return {
						allowed: false,
						reason:
							"Maximum 10 accounts on Pro. Upgrade to Agency for unlimited.",
						upsellTier: "agency",
					};
				}
			}

			// Agency should never hit this
			return { allowed: true };
		} catch (error) {
			logger.error("Failed to check account limit:", error);
			return { allowed: false, reason: "Failed to check limits" };
		}
	}

	/**
	 * Check if user can invite more members
	 */
	async canInviteMember(workspaceId: string): Promise<{
		allowed: boolean;
		reason?: string | undefined;
		upsellTier?: SubscriptionTier | undefined;
	}> {
		try {
			const stats = await this.getUsageStats(workspaceId);

			if (!stats.isAtMemberLimit) {
				return { allowed: true };
			}

			if (stats.tier === "free") {
				return {
					allowed: false,
					reason: "Free plan is solo only",
					upsellTier: "pro",
				};
			}

			if (stats.tier === "pro") {
				return {
					allowed: false,
					reason:
						"Pro plan limited to 4 team members. Upgrade to Agency for unlimited.",
					upsellTier: "agency",
				};
			}

			return { allowed: true };
		} catch (error) {
			logger.error("Failed to check member limit:", error);
			return { allowed: false, reason: "Failed to check limits" };
		}
	}

	/**
	 * Format price for display
	 */
	formatPrice(cents: number, showCents = false): string {
		const dollars = cents / 100;
		if (showCents || dollars % 1 !== 0) {
			return `$${dollars.toFixed(2)}`;
		}
		return `$${Math.round(dollars)}`;
	}

	/**
	 * Get savings percentage for yearly billing
	 */
	getYearlySavings(tier: "pro" | "agency"): number {
		const monthlyTotal = PRICING[tier].month * 12;
		const yearlyTotal = PRICING[tier].year;
		return Math.round(((monthlyTotal - yearlyTotal) / monthlyTotal) * 100);
	}

	/**
	 * Calculate add-on cost preview
	 */
	getAddOnCostPreview(
		currentAddOns: number,
		newAddOns: number,
	): {
		monthlyCost: number;
		difference: number;
	} {
		const currentCost = currentAddOns * ADDON_CONFIG.pricePerAccount;
		const newCost = newAddOns * ADDON_CONFIG.pricePerAccount;
		return {
			monthlyCost: newCost,
			difference: newCost - currentCost,
		};
	}

	/**
	 * Check if should show Agency upsell (Pro with 4+ add-ons)
	 */
	shouldShowAgencyUpsell(tier: SubscriptionTier, addOnsCount: number): boolean {
		return tier === "pro" && addOnsCount >= 4;
	}

	/**
	 * Calculate Agency savings vs Pro with add-ons
	 */
	getAgencySavingsOverPro(addOnsCount: number): number {
		const proWithAddons =
			PRICING.pro.month + addOnsCount * ADDON_CONFIG.pricePerAccount;
		return proWithAddons - PRICING.agency.month;
	}
}

export const subscriptionService = new SubscriptionService();
