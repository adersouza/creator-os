/**
 * Subscription Service
 * Handles all subscription-related operations with Stripe
 */

import { subscribe } from "@/services/realtimeManager.js";
import {
	ADDON_CONFIG,
	type BillingInterval,
	getEffectiveAccountLimit,
	PRICING,
	type SubscriptionTier,
	TIER_LIMITS,
	type WorkspaceSubscription,
} from "../types/team.js";
import logger from "@/utils/logger";
import { supabase } from "./supabase.js";

// Helper to get current user ID for Supabase
const getSupabaseUserId = async (): Promise<string | null> => {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	return session?.user?.id || null;
};

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

class SubscriptionService {
	/**
	 * Check if user is eligible for a free trial
	 * Returns eligibility status and reason if not eligible
	 */
	async checkTrialEligibility(): Promise<TrialStatus> {
		try {
			const {
				data: { session },
			} = await supabase.auth.getSession();
			if (!session) {
				return {
					eligible: false,
					reason: "Not authenticated",
				};
			}

			const response = await fetch("/api/subscription?action=check-trial", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${session.access_token}`,
				},
			});

			const data = await response.json();
			if (!response.ok) {
				throw new Error(data.error || "Failed to check trial status");
			}

			return data as TrialStatus;
		} catch (error: unknown) {
			logger.error("Failed to check trial status:", error);
			return {
				eligible: false,
				reason:
					error instanceof Error
						? error.message
						: "Unable to verify trial eligibility",
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
			const {
				data: { session },
			} = await supabase.auth.getSession();
			if (!session) {
				throw new Error("Not authenticated");
			}

			const response = await fetch("/api/subscription?action=create-checkout", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${session.access_token}`,
					"X-Idempotency-Key": `checkout-${workspaceId}-${tier}-${Math.floor(Date.now() / 60000)}`,
				},
				body: JSON.stringify({
					workspaceId,
					tier,
					interval: billing === "year" ? "yearly" : "monthly",
					trial: options?.requestTrial ?? true,
					successUrl:
						options?.successUrl ||
						`${window.location.origin}/welcome/success?session_id={CHECKOUT_SESSION_ID}`,
					cancelUrl: options?.cancelUrl || `${window.location.origin}/welcome`,
				}),
			});

			const data = await response.json();
			if (!response.ok) {
				throw new Error(data.error || "Failed to create checkout session");
			}

			return data as CheckoutSessionResult;
		} catch (error: unknown) {
			logger.error("Failed to create checkout session:", error);
			throw new Error(
				error instanceof Error ? error.message : "Failed to start checkout",
			);
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
			const {
				data: { session },
			} = await supabase.auth.getSession();
			if (!session) {
				throw new Error("Not authenticated");
			}

			const response = await fetch("/api/subscription?action=upgrade-empire", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${session.access_token}`,
				},
				body: JSON.stringify({
					workspaceId,
					tier: "empire",
					interval: billing === "year" ? "yearly" : "monthly",
					successUrl: `${window.location.origin}/settings?upgraded=empire`,
					cancelUrl: `${window.location.origin}/settings`,
				}),
			});

			const data = await response.json();
			if (!response.ok) {
				throw new Error(data.error || "Failed to upgrade to Empire");
			}

			return data as CheckoutSessionResult;
		} catch (error: unknown) {
			logger.error("Failed to upgrade to Empire:", error);
			throw new Error(
				error instanceof Error ? error.message : "Failed to upgrade to Empire",
			);
		}
	}

	/**
	 * Create a Stripe Customer Portal session for managing subscription
	 */
	async createPortalSession(workspaceId: string): Promise<string> {
		try {
			const {
				data: { session },
			} = await supabase.auth.getSession();
			if (!session) {
				throw new Error("Not authenticated");
			}

			const response = await fetch("/api/subscription?action=create-portal", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${session.access_token}`,
				},
				body: JSON.stringify({
					workspaceId,
					returnUrl: `${window.location.origin}/settings`,
				}),
			});

			const data = await response.json();
			if (!response.ok) {
				throw new Error(data.error || "Failed to create portal session");
			}

			return data.url;
		} catch (error: unknown) {
			logger.error("Failed to create portal session:", error);
			throw new Error(
				error instanceof Error
					? error.message
					: "Failed to open billing portal",
			);
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
			const {
				data: { session },
			} = await supabase.auth.getSession();
			if (!session) {
				throw new Error("Not authenticated");
			}

			const response = await fetch("/api/subscription?action=update-addons", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${session.access_token}`,
				},
				body: JSON.stringify({
					workspaceId,
					addOnsCount: newCount,
				}),
			});

			const data = await response.json();
			if (!response.ok) {
				throw new Error(data.error || "Failed to update add-ons");
			}
		} catch (error: unknown) {
			logger.error("Failed to update add-ons:", error);
			throw new Error(
				error instanceof Error ? error.message : "Failed to update add-ons",
			);
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

			const response = await fetch("/api/subscription?action=cancel", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${session.access_token}`,
				},
				body: JSON.stringify({ workspaceId }),
			});

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
	async getUsageStats(workspaceId: string): Promise<UsageStats> {
		try {
			const userId = await getSupabaseUserId();
			if (!userId) {
				throw new Error("Not authenticated");
			}

			// Get workspace data
			const { data: workspaceData, error: wsError } = await supabase
				.from("workspaces")
				.select("tier, subscription, account_count, member_count")
				.eq("id", workspaceId)
				.maybeSingle();

			if (wsError || !workspaceData) {
				throw new Error("Workspace not found");
			}

			// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
			const tier = ((workspaceData as any).tier || "free") as SubscriptionTier;
			// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
			const subscription = (workspaceData as any).subscription as Record<
				string,
				unknown
			> | null;
			const addOnsCount = (subscription?.add_ons_count as number) || 0;

			// Get actual account count from user's accounts
			let accountCount = 0;
			try {
				const { count, error: accError } = await supabase
					.from("accounts")
					.select("*", { count: "exact", head: true })
					.eq("user_id", userId);

				if (!accError) {
					accountCount = count || 0;
				}
			} catch (e) {
				logger.warn("Could not count accounts:", e);
				// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
				accountCount = ((workspaceData as any).account_count as number) || 0;
			}

			// Get member count from workspace_members
			let memberCount = 1;
			try {
				const { count, error: memError } = await supabase
					.from("workspace_members")
					.select("*", { count: "exact", head: true })
					.eq("workspace_id", workspaceId);

				if (!memError) {
					memberCount = count || 1;
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
