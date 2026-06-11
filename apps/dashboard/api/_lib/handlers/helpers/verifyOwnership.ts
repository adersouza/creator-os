/**
 * Shared Ownership Verification Helpers
 *
 * Eliminates the repeated pattern of verifying that an account, competitor,
 * or other entity belongs to the authenticated user before proceeding.
 *
 * Usage:
 *   const account = await verifyAccountOwnership(res, accountId, userId);
 *   if (!account) return; // 404 already sent
 *
 *   const competitor = await verifyCompetitorOwnership(res, competitorId, userId);
 *   if (!competitor) return; // 404 already sent
 */

import type { VercelResponse } from "@vercel/node";
import { apiError } from "../../apiResponse.js";
import { getSupabase, type TypedSupabaseClient } from "../../supabase.js";

type OwnershipDb = TypedSupabaseClient;

const db = (): OwnershipDb => getSupabase();

// ============================================================================
// Account Ownership
// ============================================================================

/**
 * Verify that a Threads account belongs to the given user.
 * Returns the account row (with at least `id`) or null if not found.
 * Sends apiError(404) automatically when the account is missing.
 *
 * @param select - Columns to select (default: "id")
 */
export async function verifyAccountOwnership(
	res: VercelResponse,
	accountId: string,
	userId: string,
	select = "id",
	client: OwnershipDb = db(),
): Promise<Record<string, unknown> | null> {
	const { data: account, error } = await client
		.from("accounts")
		.select(select)
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle();

	if (error) {
		apiError(res, 500, "Failed to verify account", {
			details: error.message,
		});
		return null;
	}
	if (!account) {
		apiError(res, 404, "Account not found");
		return null;
	}

	return account as unknown as Record<string, unknown>;
}

// ============================================================================
// Instagram Account Ownership
// ============================================================================

/**
 * Verify that an Instagram account belongs to the given user.
 * Returns the account row or null. Sends apiError(404) automatically.
 *
 * @param select - Columns to select (default: "id")
 */
export async function verifyIgAccountOwnership(
	res: VercelResponse,
	accountId: string,
	userId: string,
	select = "id",
	client: OwnershipDb = db(),
): Promise<Record<string, unknown> | null> {
	const { data: account, error } = await client
		.from("instagram_accounts")
		.select(select)
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle();

	if (error) {
		apiError(res, 500, "Failed to verify Instagram account", {
			details: error.message,
		});
		return null;
	}
	if (!account) {
		apiError(res, 404, "Instagram account not found");
		return null;
	}

	return account as unknown as Record<string, unknown>;
}

// ============================================================================
// Any Account (Threads OR Instagram)
// ============================================================================

/**
 * Verify that an account (either Threads or Instagram) belongs to the user.
 * Checks Threads first, then Instagram. Returns { account, platform } or null.
 * Sends apiError(404) only if both lookups fail.
 */
export async function verifyAnyAccountOwnership(
	res: VercelResponse,
	accountId: string,
	userId: string,
	client: OwnershipDb = db(),
): Promise<{
	account: Record<string, unknown>;
	platform: "threads" | "instagram";
} | null> {
	// Check Threads first
	const { data: threadAccount } = await client
		.from("accounts")
		.select("id")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle();

	if (threadAccount) {
		return {
			account: threadAccount as unknown as Record<string, unknown>,
			platform: "threads",
		};
	}

	// Check Instagram
	const { data: igAccount } = await client
		.from("instagram_accounts")
		.select("id")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle();

	if (igAccount) {
		return {
			account: igAccount as unknown as Record<string, unknown>,
			platform: "instagram",
		};
	}

	apiError(res, 404, "Account not found");
	return null;
}

// ============================================================================
// Competitor Ownership
// ============================================================================

/**
 * Verify that a competitor belongs to the given user.
 * Returns the competitor row or null. Sends apiError(404) automatically.
 *
 * @param select - Columns to select (default: "id, username, platform")
 */
export async function verifyCompetitorOwnership(
	res: VercelResponse,
	competitorId: string,
	userId: string,
	select = "id, username, platform",
): Promise<Record<string, unknown> | null> {
	const { data: competitor, error } = await db()
		.from("competitors")
		.select(select)
		.eq("id", competitorId)
		.eq("user_id", userId)
		.maybeSingle();

	if (error) {
		apiError(res, 500, "Failed to verify competitor", {
			details: error.message,
		});
		return null;
	}
	if (!competitor) {
		apiError(res, 404, "Competitor not found");
		return null;
	}

	return competitor as unknown as Record<string, unknown>;
}
