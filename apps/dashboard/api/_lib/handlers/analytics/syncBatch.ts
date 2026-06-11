// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Analytics Handler: sync-batch
 *
 * Batch-syncs multiple Threads + Instagram accounts sequentially.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { syncInstagramAccount, syncThreadsAccount } from "../../accountSync.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getSupabase } from "../../supabase.js";
import { parseBodyOrError } from "../../validation.js";
import { z } from "../../zodCompat.js";

const db = () => getSupabase();

// ============================================================================
// Zod Schema
// ============================================================================

const SyncBatchSchema = z
	.object({
		accountIds: z.array(z.string()).optional(),
		igAccountIds: z.array(z.string()).optional(),
		delayMs: z.number().int().min(0).max(10000).optional().default(1500),
	})
	.refine(
		(data) =>
			(data.accountIds && data.accountIds.length > 0) ||
			(data.igAccountIds && data.igAccountIds.length > 0),
		{ message: "accountIds or igAccountIds array is required" },
	);

// ============================================================================
// Internal helpers
// ============================================================================

/** Delegates to shared syncThreadsAccount from accountSync module */
async function syncSingleAccount(
	accountId: string,
	userId: string,
): Promise<{
	accountId: string;
	username?: string | undefined;
	success: boolean;
	suspended?: boolean | undefined;
	reactivated?: boolean | undefined;
	error?: string | undefined;
	data?: Record<string, unknown> | undefined;
}> {
	const result = await syncThreadsAccount(accountId, userId);
	return {
		accountId: result.accountId,
		username: result.username,
		success: result.success,
		suspended: result.suspended,
		reactivated: result.reactivated,
		error: result.error,
		data: result.data
			? {
					followersCount: result.data.followersCount,
					postsCount: result.data.postsCount,
					postsUpdated: result.data.syncedPosts,
					postsImported: result.data.importedPosts,
				}
			: undefined,
	};
}

/** Delegates to shared syncInstagramAccount from accountSync module */
async function syncSingleIgAccount(
	igAccountId: string,
	userId: string,
): Promise<{
	accountId: string;
	username?: string | undefined;
	success: boolean;
	error?: string | undefined;
}> {
	const result = await syncInstagramAccount(igAccountId, userId);
	return {
		accountId: result.accountId,
		username: result.username,
		success: result.success,
		error: result.error,
	};
}

// ============================================================================
// Handler
// ============================================================================

/**
 * POST /api/analytics?action=sync-batch
 * Batch-sync multiple accounts sequentially, server-side.
 */
export async function handleSyncBatch(req: VercelRequest, res: VercelResponse) {
	logger.info("handleSyncBatch called");

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

	const userId = user.id;

	const parsed = parseBodyOrError(res, SyncBatchSchema, req.body);
	if (!parsed) return;

	const { accountIds, igAccountIds, delayMs } = parsed;

	const hasThreads = accountIds && accountIds.length > 0;
	const hasIg = igAccountIds && igAccountIds.length > 0;

	// Verify ownership — only sync accounts belonging to this user
	let ownedAccountIds: string[] = [];
	let ownedIgAccountIds: string[] = [];

	if (hasThreads) {
		const { data: ownedAccounts } = await db()
			.from("accounts")
			.select("id")
			.eq("user_id", userId)
			.in("id", accountIds ?? []);
		ownedAccountIds = (ownedAccounts || []).map((a: { id: string }) => a.id);
	}

	if (hasIg) {
		const { data: ownedIgAccounts } = await db()
			.from("instagram_accounts")
			.select("id")
			.eq("user_id", userId)
			.in("id", igAccountIds ?? []);
		ownedIgAccountIds = (ownedIgAccounts || []).map(
			(a: { id: string }) => a.id,
		);
	}

	if (ownedAccountIds.length === 0 && ownedIgAccountIds.length === 0) {
		return apiError(res, 404, "No owned accounts found in the provided IDs");
	}

	// Limit to 100 accounts max per batch
	const limitedAccountIds = ownedAccountIds.slice(0, 100);
	const limitedIgAccountIds = ownedIgAccountIds.slice(0, 100);
	const totalCount = limitedAccountIds.length + limitedIgAccountIds.length;
	logger.info("Batch processing started", {
		totalCount,
		threadsCount: limitedAccountIds.length,
		igCount: limitedIgAccountIds.length,
		delayMs,
	});

	const results: Array<{
		accountId: string;
		username?: string | undefined;
		success: boolean;
		suspended?: boolean | undefined;
		reactivated?: boolean | undefined;
		error?: string | undefined;
		platform?: string | undefined;
	}> = [];

	const startTime = Date.now();

	// Process Threads accounts
	for (let i = 0; i < limitedAccountIds.length; i++) {
		const accountId = limitedAccountIds[i];
		logger.info("Processing Threads account", {
			index: i + 1,
			total: limitedAccountIds.length,
			accountId,
		});

		const result = await syncSingleAccount(accountId!, userId);
		results.push({ ...result, platform: "threads" });

		// Log progress
		if (result.success) {
			logger.info("Threads account synced", {
				username: result.username || accountId,
			});
		} else if (result.suspended) {
			logger.warn("Threads account suspended", {
				username: result.username || accountId,
			});
		} else {
			logger.error("Threads account sync failed", {
				username: result.username || accountId,
				error: result.error,
			});
		}

		// Delay between accounts (except for the last one)
		if (i < limitedAccountIds.length - 1 || limitedIgAccountIds.length > 0) {
			await new Promise((resolve) => setTimeout(resolve, delayMs));
		}
	}

	// Process Instagram accounts
	for (let i = 0; i < limitedIgAccountIds.length; i++) {
		const igAccountId = limitedIgAccountIds[i];
		logger.info("Processing IG account", {
			index: i + 1,
			total: limitedIgAccountIds.length,
			igAccountId,
		});

		const result = await syncSingleIgAccount(igAccountId!, userId);
		results.push({ ...result, platform: "instagram" });

		if (result.success) {
			logger.info("IG account synced", {
				username: result.username || igAccountId,
			});
		} else {
			logger.error("IG account sync failed", {
				username: result.username || igAccountId,
				error: result.error,
			});
		}

		if (i < limitedIgAccountIds.length - 1) {
			await new Promise((resolve) => setTimeout(resolve, delayMs));
		}
	}

	const duration = Date.now() - startTime;
	const successCount = results.filter((r) => r.success).length;
	const suspendedCount = results.filter((r) => r.suspended).length;
	const failedCount = results.filter((r) => !r.success && !r.suspended).length;

	logger.info("Batch processing complete", {
		durationMs: duration,
		successCount,
		suspendedCount,
		failedCount,
	});

	return apiSuccess(res, {
		summary: {
			total: totalCount,
			success: successCount,
			suspended: suspendedCount,
			failed: failedCount,
			durationMs: duration,
		},
		results,
		// Include lists for UI notifications
		suspendedAccounts: results
			.filter((r) => r.suspended)
			.map((r) => r.username || r.accountId),
		reactivatedAccounts: results
			.filter((r) => r.reactivated)
			.map((r) => r.username || r.accountId),
	});
}
