/**
 * Instagram Account Sync Endpoint
 * Receives QStash messages from sync-orchestrator (Phase 0 dispatch).
 * Syncs one Instagram account independently (60s budget).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	refreshInstagramAccountAnalytics,
	runPostSyncTasks,
} from "../../analyticsSync.js";
import { apiError, apiSuccess, getAuthUserOrError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { verifyQStashSignature } from "../../qstash.js";
import { getSupabase, getSupabaseAny } from "../../supabase.js";
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

	logger.info("Instagram account sync started", { accountId, syncType });

	const lock = await acquireSyncLock(accountId);
	if (!lock.acquired) {
		return apiSuccess(res, {
			skipped: true,
			reason: "Sync already in progress",
		});
	}

	try {
		// Fetch account from DB
		// follower_count & last_milestone_celebrated exist in DB but not in auto-generated TS types
		const { data: account, error } = (await db()
			.from("instagram_accounts")
			.select(
				"id, user_id, username, instagram_user_id, instagram_access_token_encrypted, login_type, follower_count, last_milestone_celebrated, last_synced_at",
			)
			.eq("id", accountId)
			.eq("user_id", userId)
			.maybeSingle()) as {
			data: {
				id: string;
				user_id: string;
				username: string;
				instagram_user_id: string;
				instagram_access_token_encrypted: string;
				login_type: string;
				follower_count: number | null;
				last_milestone_celebrated: number | null;
				last_synced_at: string | null;
			} | null;
			error: { message: string } | null;
		};

		if (error || !account) {
			logger.warn("IG account not found or error", {
				accountId,
				error: error?.message ?? JSON.stringify(error),
			});
			return apiSuccess(res, { skipped: true, reason: "Account not found" });
		}

		// Run sync
		const result = await refreshInstagramAccountAnalytics(
			account,
			syncType as "full" | "metrics",
			{ force: Boolean(force) },
		);

		// Post-sync tasks (non-fatal)
		if (result.success && !result.skipped) {
			try {
				await runPostSyncTasks(
					accountId,
					userId,
					"instagram",
					account.follower_count,
					account.last_milestone_celebrated ?? null,
				);
			} catch (postSyncErr) {
				logger.warn("Post-sync tasks failed", {
					accountId,
					error:
						postSyncErr instanceof Error
							? postSyncErr.message
							: String(postSyncErr),
				});
			}
		}

		logger.info("Instagram account sync complete", {
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
		// UUID/TEXT mismatch: IG-only accounts not in accounts table — skip gracefully
		// Still touch last_synced_at so health monitor doesn't flag as stale
		if (result.error === "Account not in accounts table") {
			await getSupabaseAny()
				.from("instagram_accounts")
				.update({ last_synced_at: new Date().toISOString() })
				.eq("id", accountId);
			return apiSuccess(res, { skipped: true, reason: result.error });
		}
		return apiError(res, 500, "Sync failed");
	} catch (err) {
		logger.error("Instagram account sync error", {
			accountId,
			error: err instanceof Error ? err.message : String(err),
		});
		// Report failure to job tracker before returning error
		if (jobId && userId) {
			try {
				await reportAccountSyncComplete(jobId, userId, false, accountId);
			} catch (_) {
				// Non-fatal
			}
		}
		return apiError(res, 500, "Sync failed");
	} finally {
		await lock.release();
	}
}
