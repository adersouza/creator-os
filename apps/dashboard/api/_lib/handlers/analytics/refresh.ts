/**
 * Analytics Handlers: refresh + ig-refresh
 *
 * Single-account sync for Threads and Instagram.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { syncInstagramAccount, syncThreadsAccount } from "../../accountSync.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { invalidateDashboard } from "../../dashboardCache.js";
import { logger } from "../../logger.js";
import { invalidateCachePattern } from "../../redisCache.js";
import { getSupabase } from "../../supabase.js";
import { parseBodyOrError } from "../../validation.js";
import { z } from "../../zodCompat.js";

const db = () => getSupabase();

// ============================================================================
// Zod Schemas
// ============================================================================

const RefreshSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
});

const IgRefreshSchema = z.object({
	igAccountId: z.string().min(1, "igAccountId is required"),
});

// ============================================================================
// Handlers
// ============================================================================

/**
 * POST /api/analytics?action=refresh
 * Sync a single Threads account.
 */
export async function handleRefresh(req: VercelRequest, res: VercelResponse) {
	logger.info("handleRefresh called");

	try {
		const parsed = parseBodyOrError(res, RefreshSchema, req.body);
		if (!parsed) return;
		const { accountId } = parsed;
		logger.info("Refresh request", { accountId });

		// Get user ID from Authorization header
		const authHeader = req.headers.authorization;
		if (!authHeader?.startsWith("Bearer ")) {
			logger.warn("Missing auth header");
			return apiError(res, 401, "Missing or invalid authorization header");
		}

		const authToken = authHeader.replace("Bearer ", "");
		const {
			data: { user },
			error: authError,
		} = await db().auth.getUser(authToken);

		if (authError || !user) {
			return apiError(res, 401, "Invalid or expired token");
		}

		// Verify account ownership (IDOR protection) — also fetch group_id for cache invalidation
		const { data: ownedAccount } = await db()
			.from("accounts")
			.select("id, group_id")
			.eq("id", accountId)
			.eq("user_id", user.id)
			.maybeSingle();
		if (!ownedAccount) {
			return apiError(res, 403, "Account not found or not authorized");
		}

		const result = await syncThreadsAccount(accountId, user.id);

		if (!result.success && result.suspended) {
			return apiSuccess(res, {
				success: false,
				suspended: true,
				accountId: result.accountId,
				username: result.username,
				message: result.error,
				error: result.error,
			});
		}

		if (!result.success) {
			// Map specific errors to appropriate status codes
			if (result.error === "Account not found") {
				return apiError(res, 404, result.error);
			}
			if (
				result.error === "No OAuth credentials" ||
				result.error?.startsWith("Failed to fetch profile:")
			) {
				return apiError(res, 400, result.error ?? "Unknown error");
			}
			if (result.error?.includes("Token decryption failed")) {
				return apiError(res, 500, result.error ?? "Unknown error");
			}
			if (result.error?.startsWith("Profile fetch error:")) {
				return apiError(res, 500, "Failed to fetch profile from Threads API");
			}
			return apiError(res, 500, "Internal server error");
		}

		// Invalidate dashboard and group analytics caches after successful sync
		invalidateDashboard(accountId).catch(() => {});
		if (ownedAccount.group_id) {
			invalidateCachePattern(
				`group-analytics:${ownedAccount.group_id}:*`,
			).catch(() => {});
		}

		return apiSuccess(res, {
			reactivated: result.reactivated,
			username: result.username,
			lastSyncedAt: new Date().toISOString(),
			data: {
				followersCount: result.data?.followersCount,
				postsCount: result.data?.postsCount,
				postsUpdated: result.data?.syncedPosts,
				postsImported: result.data?.importedPosts,
				engagementRate: result.data?.engagementRate,
			},
		});
	} catch (error: unknown) {
		logger.error("Uncaught error in handleRefresh", {
			error: error instanceof Error ? error.message : String(error),
		});
		return apiError(res, 500, "Internal server error");
	}
}

/**
 * POST /api/analytics?action=ig-refresh
 * Sync a single Instagram account.
 */
export async function handleIgRefresh(req: VercelRequest, res: VercelResponse) {
	logger.info("handleIgRefresh called");

	try {
		const parsed = parseBodyOrError(res, IgRefreshSchema, req.body);
		if (!parsed) return;
		const { igAccountId } = parsed;
		logger.info("IG refresh request", { igAccountId });

		// Auth
		const authHeader = req.headers.authorization;
		if (!authHeader?.startsWith("Bearer ")) {
			return apiError(res, 401, "Missing or invalid authorization header");
		}

		const authToken = authHeader.replace("Bearer ", "");
		const {
			data: { user },
			error: authError,
		} = await db().auth.getUser(authToken);

		if (authError || !user) {
			return apiError(res, 401, "Invalid or expired token");
		}

		// Verify account ownership (IDOR protection) — also fetch group_id for cache invalidation
		const { data: ownedIgAccount } = await db()
			.from("instagram_accounts")
			.select("id, group_id")
			.eq("id", igAccountId)
			.eq("user_id", user.id)
			.maybeSingle();
		if (!ownedIgAccount) {
			return apiError(res, 403, "Account not found or not authorized");
		}

		const result = await syncInstagramAccount(igAccountId, user.id);

		if (!result.success) {
			if (result.error === "Instagram account not found") {
				return apiError(res, 400, "Instagram account not found", {
					details: `igAccountId=${igAccountId}, userId=${user.id}`,
				});
			}
			if (result.error === "Missing OAuth credentials") {
				return apiError(
					res,
					400,
					"Instagram account missing OAuth credentials",
				);
			}
			if (result.error?.startsWith("Failed to fetch IG media:")) {
				return apiError(res, 400, result.error ?? "Unknown error");
			}
			return apiError(
				res,
				500,
				"Internal server error during IG analytics refresh",
			);
		}

		// Invalidate dashboard and group analytics caches after successful IG sync
		invalidateDashboard(igAccountId).catch(() => {});
		if (ownedIgAccount.group_id) {
			invalidateCachePattern(
				`group-analytics:${ownedIgAccount.group_id}:*`,
			).catch(() => {});
		}

		return apiSuccess(res, {
			username: result.username,
			lastSyncedAt: new Date().toISOString(),
			data: {
				followersCount: result.data?.followersCount,
				postsCount: result.data?.postsCount,
				postsUpdated: result.data?.syncedPosts,
				postsImported: result.data?.importedPosts,
				engagementRate: result.data?.engagementRate,
			},
		});
	} catch (error: unknown) {
		logger.error("Uncaught error in handleIgRefresh", {
			error: error instanceof Error ? error.message : String(error),
		});
		return apiError(
			res,
			500,
			"Internal server error during IG analytics refresh",
		);
	}
}
