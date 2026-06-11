/**
 * Threads Account Sync Endpoint
 * Receives QStash messages from sync-orchestrator (Phase 0 dispatch).
 * Syncs one Threads account independently (60s budget).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	refreshThreadsAccountAnalytics,
	runPostSyncTasks,
} from "../../analyticsSync.js";
import { apiError, apiSuccess, getAuthUserOrError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { verifyQStashSignature } from "../../qstash.js";
import { getSupabase } from "../../supabase.js";
import { acquireSyncLock } from "../../syncLock.js";
import { reportAccountSyncComplete } from "../../syncProgress.js";

const db = () => getSupabase();

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	// Dual-auth: accepts either a QStash signature (from sync-orchestrator cron) or
	// a Bearer JWT (from MCP / direct API calls). withAuth would reject QStash-signed
	// requests because they carry no Bearer token, so this route intentionally uses
	// getAuthUserOrError directly for the JWT path.
	const hasQStashSignature =
		typeof req.headers["upstash-signature"] === "string";
	let jwtUserId: string | undefined;
	if (hasQStashSignature) {
		if (!(await verifyQStashSignature(req, res))) return;
	} else {
		const user = await getAuthUserOrError(req, res);
		if (!user) return;
		jwtUserId = user.id;
	}

	const {
		accountId,
		userId: bodyUserId,
		syncType = "metrics",
		jobId,
		force,
	} = req.body || {};
	const userId = jwtUserId ?? bodyUserId;

	if (!accountId || !userId) {
		return apiSuccess(res, {
			error: "Missing accountId or userId",
			skipped: true,
		});
	}

	logger.info("Threads account sync started", { accountId, syncType });

	const lock = await acquireSyncLock(accountId);
	if (!lock.acquired) {
		return apiSuccess(res, {
			skipped: true,
			reason: "Sync already in progress",
		});
	}

	try {
		// Fetch account from DB
		const { data: account, error } = await db()
			.from("accounts")
			.select(
				"id, user_id, username, threads_user_id, threads_access_token_encrypted, followers_count, last_milestone_celebrated, last_synced_at",
			)
			.eq("id", accountId)
			.eq("user_id", userId)
			.maybeSingle();

		if (error || !account) {
			logger.warn("Account not found or error", {
				accountId,
				error: String(error),
			});
			// Return 200 so QStash doesn't retry for missing accounts
			return apiSuccess(res, { skipped: true, reason: "Account not found" });
		}

		// Run sync
		const result = await refreshThreadsAccountAnalytics(
			account,
			syncType as "full" | "metrics" | "recent",
			{ force: Boolean(force) },
		);

		// Post-sync tasks (non-fatal)
		if (result.success && !result.skipped) {
			try {
				await runPostSyncTasks(
					accountId,
					userId,
					"threads",
					account.followers_count,
					account.last_milestone_celebrated ?? null,
				);
			} catch (postSyncErr) {
				logger.warn("Post-sync tasks failed", {
					accountId,
					error: String(postSyncErr),
				});
			}
		}

		logger.info("Threads account sync complete", {
			accountId,
			username: account.username,
			postsUpdated: result.postsUpdated,
			skipped: result.skipped,
		});

		// Report progress to job tracker (if this was dispatched as part of a user-triggered sync)
		if (jobId && userId) {
			try {
				await reportAccountSyncComplete(
					jobId,
					userId,
					result.success,
					accountId,
				);
			} catch (progressErr) {
				logger.warn("Failed to report sync progress", {
					jobId,
					accountId,
					error: String(progressErr),
				});
			}
		}

		if (result.success) {
			return apiSuccess(res, result as unknown as Record<string, unknown>);
		}
		return apiError(res, 500, "Sync failed");
	} catch (err) {
		logger.error("Threads account sync error", {
			accountId,
			error: String(err),
		});
		// Report failure to job tracker before returning error
		if (jobId && userId) {
			try {
				await reportAccountSyncComplete(jobId, userId, false, accountId);
			} catch (_) {
				// Non-fatal
			}
		}
		// 500 → QStash will retry
		return apiError(res, 500, "Sync failed");
	} finally {
		await lock.release();
	}
}
