/**
 * Tier Gating Utility
 *
 * Enforces subscription tier requirements on API endpoints.
 * Prevents premium features from being accessed by free-tier users
 * who bypass the UI gating.
 */

import type { VercelResponse } from "@vercel/node";
import { apiError } from "./apiResponse.js";
import { getSupabase } from "./supabase.js";

export type Tier = "free" | "pro" | "agency" | "empire";
const TIER_RANK: Record<Tier, number> = {
	free: 0,
	pro: 1,
	agency: 2,
	empire: 3,
};

// Per-invocation cache (Vercel functions are short-lived, so this is per-request)
const tierCache = new Map<string, { tier: Tier; ts: number }>();
const TIER_CACHE_TTL = 60_000; // 1 minute

export async function getUserTier(userId: string): Promise<Tier> {
	const cached = tierCache.get(userId);
	if (cached && Date.now() - cached.ts < TIER_CACHE_TTL) {
		return cached.tier;
	}

	const { data } = await getSupabase()
		.from("profiles")
		.select("subscription_tier")
		.eq("id", userId)
		.maybeSingle();
	const tier = (
		(data as { subscription_tier?: string | undefined })?.subscription_tier || "free"
	).toLowerCase();
	const result = (tier in TIER_RANK ? tier : "free") as Tier;

	tierCache.set(userId, { tier: result, ts: Date.now() });
	return result;
}

/**
 * Invalidate the in-memory tier cache for a specific user.
 * Call this from webhook handlers when a subscription changes
 * so the user doesn't retain stale premium access.
 */
export function invalidateTierCache(userId: string): void {
	tierCache.delete(userId);
}

export async function requireMinTier(
	userId: string,
	minTier: Tier,
	res: VercelResponse,
): Promise<boolean> {
	const userTier = await getUserTier(userId);
	if (TIER_RANK[userTier] < TIER_RANK[minTier]) {
		apiError(res, 403, `This feature requires ${minTier} tier or higher`, {
			code: "TIER_REQUIRED",
			details: `current: ${userTier}, required: ${minTier}`,
		});
		return false;
	}
	return true;
}
