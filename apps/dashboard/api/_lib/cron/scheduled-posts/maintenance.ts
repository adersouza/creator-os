/**
 * Maintenance tasks for scheduled post processing.
 * Handles cleanup of old rejected queue items, retrying failed posts,
 * cleaning up orphaned publishing posts, and rescuing stuck posts
 * assigned to inactive accounts.
 */

import {
	isAccountPublishable,
	publishableAccountFilters,
} from "../../accountEligibility.js";
import { deliverNotification } from "../../deliverNotification.js";
import { logger } from "../../logger.js";
import type { ProcessingStats } from "./shared.js";
import { db, isTransientError } from "./shared.js";

function assertNoDbError(
	context: string,
	error: { message?: string } | null,
): void {
	if (!error) return;
	logger.error(`[scheduled-posts] ${context} failed`, {
		error: error.message || String(error),
	});
	throw new Error(`${context} failed: ${error.message || String(error)}`);
}

/**
 * STEP 0a: Clean up old rejected rows from auto_post_queue (>7 days)
 */
export async function cleanupRejectedQueue(): Promise<void> {
	const { error } = await db()
		.from("auto_post_queue")
		.delete()
		.eq("status", "rejected")
		.lt(
			"created_at",
			new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
		);
	assertNoDbError("cleanup rejected queue", error);
}

/**
 * STEP 0b: Retry recently failed posts with transient errors (Threads + IG)
 */
export async function retryFailedPosts(stats: ProcessingStats): Promise<void> {
	const retryWindow = new Date(Date.now() - 30 * 60 * 1000).toISOString(); // last 30 min
	const { data: failedRetryPosts, error: failedRetryPostsError } = await db()
		.from("posts")
		.select("id, platform, retry_count, error_message")
		.eq("status", "failed")
		.in("platform", ["threads", "instagram"])
		.gte("updated_at", retryWindow)
		.lt("retry_count", 3) // max 3 retries
		.limit(10);
	assertNoDbError("load retryable failed posts", failedRetryPostsError);

	if (failedRetryPosts && failedRetryPosts.length > 0) {
		for (const rp of failedRetryPosts as {
			id: string;
			platform: string;
			retry_count: number;
			error_message: string | null;
		}[]) {
			if (rp.error_message && isTransientError(rp.error_message)) {
				// Re-queue for publishing by setting status back to scheduled
				// Status guard prevents overwriting a post changed between SELECT and UPDATE
				const { error: retryUpdateError } = await db()
					.from("posts")
					.update({
						status: "scheduled",
						retry_count: (rp.retry_count || 0) + 1,
						error_message: null,
						updated_at: new Date().toISOString(),
					})
					.eq("id", rp.id)
					.eq("status", "failed");
				assertNoDbError("re-queue failed post", retryUpdateError);
				stats.retried++;
				logger.info("Re-queued failed post for retry", {
					postId: rp.id,
					platform: rp.platform,
					retryCount: (rp.retry_count || 0) + 1,
				});
			}
		}
	}
}

/**
 * STEP 0.5: Cleanup orphaned "publishing" posts (stuck > 30 min)
 * If a cron run crashes or times out, posts can get stuck in
 * "publishing" status forever. Reset them to "failed" so users
 * can see what happened and retry manually.
 */
export async function cleanupOrphanedPosts(): Promise<void> {
	const orphanThreshold = new Date(Date.now() - 30 * 60 * 1000).toISOString();
	const { data: orphanedPosts, error: orphanedPostsError } = await db()
		.from("posts")
		.select("id, platform, user_id")
		.eq("status", "publishing")
		.lt("updated_at", orphanThreshold)
		.limit(20);
	assertNoDbError("load orphaned publishing posts", orphanedPostsError);

	if (orphanedPosts && orphanedPosts.length > 0) {
		const orphanMsg =
			"Publishing timed out — post was stuck in 'publishing' status for over 30 minutes. This usually means the previous publish attempt crashed. Please retry.";

		// Mark all orphaned posts as failed
		for (const op of orphanedPosts as {
			id: string;
			platform: string;
			user_id: string;
		}[]) {
			const { error: orphanErr } = await db()
				.from("posts")
				.update({
					status: "failed",
					error_message: orphanMsg,
					updated_at: new Date().toISOString(),
				})
				.eq("id", op.id)
				.eq("status", "publishing");
			if (orphanErr) {
				logger.error(
					"[scheduled-posts] Failed to mark orphaned post as failed",
					{
						postId: op.id,
						error: orphanErr.message,
					},
				);
			}
			logger.warn("Cleaned up orphaned publishing post", {
				postId: op.id,
				platform: op.platform,
			});
		}

		// Send ONE batched notification per user (not per post)
		const orphansByUser = new Map<string, string[]>();
		for (const op of orphanedPosts as { id: string; user_id: string }[]) {
			const list = orphansByUser.get(op.user_id) || [];
			list.push(op.id);
			orphansByUser.set(op.user_id, list);
		}

		for (const [userId, postIds] of Array.from(orphansByUser)) {
			const batchMsg =
				postIds.length === 1
					? orphanMsg
					: `${postIds.length} scheduled posts timed out — they were stuck in 'publishing' status for over 30 minutes. This usually means the previous publish attempt crashed. Please retry from the scheduled posts page.`;
			const { error: notificationError } = await db()
				.from("notifications")
				.insert({
					user_id: userId,
					type: "post_failed",
					title:
						postIds.length === 1
							? "Scheduled post timed out"
							: `${postIds.length} scheduled posts timed out`,
					message: batchMsg,
					read: false,
					data: { postIds },
				});
			if (notificationError) {
				logger.warn("[scheduled-posts] Failed to persist orphan notification", {
					userId,
					postIds,
					error: notificationError.message,
				});
			}
			deliverNotification({
				userId,
				type: "post_failed",
				title:
					postIds.length === 1
						? "Scheduled post timed out"
						: `${postIds.length} scheduled posts timed out`,
				message: batchMsg,
				data: { postIds },
			}).catch((err) =>
				logger.warn("[scheduled-posts] Notification delivery failed", {
					error: String(err),
				}),
			);
		}

		logger.info(`Cleaned up ${orphanedPosts.length} orphaned publishing posts`);
	}
}

/**
 * STEP 0.6: Rescue stuck Threads scheduled posts (overdue > 30 min)
 * Posts assigned to accounts that became inactive/needs_reauth
 * are invisible to the main query (which filters is_active=true).
 * Attempt to reassign to another active account in the same group,
 * or mark as failed with a clear reason.
 */
export async function rescueStuckThreadsPosts(
	stats: ProcessingStats,
): Promise<void> {
	const rescueThreshold = new Date(Date.now() - 30 * 60 * 1000).toISOString();

	// Find Threads posts that are overdue and joined to inactive/reauth accounts
	const { data: stuckPosts, error: stuckPostsError } = await db()
		.from("posts")
		.select(
			"id, user_id, account_id, platform, scheduled_for, retry_count, accounts!inner (id, group_id, is_active, needs_reauth, status, token_expires_at)",
		)
		.eq("status", "scheduled")
		.lt("scheduled_for", rescueThreshold)
		.or("platform.is.null,platform.eq.threads")
		.limit(20);
	assertNoDbError("load stuck Threads posts", stuckPostsError);

	if (stuckPosts && stuckPosts.length > 0) {
		for (const sp of stuckPosts as {
			id: string;
			user_id: string;
			account_id: string;
			platform: string;
			scheduled_for: string;
			retry_count: number | null;
			accounts: {
				id: string;
				group_id: string | null;
				is_active: boolean;
				needs_reauth: boolean | null;
				status: string | null;
				token_expires_at: string | null;
			};
		}[]) {
			const acct = sp.accounts;
			const eligibility = isAccountPublishable(acct);
			if (eligibility.eligible) continue; // Not stuck due to account — skip (may be rate-limited, will resolve next cycle)

			const ineligibleReason = eligibility.reason || "unknown";

			// Try to reassign to another active account in the same group
			let reassigned = false;
			if (acct.group_id) {
				const altQuery = db()
					.from("accounts")
					.select("id")
					.eq("user_id", sp.user_id)
					.eq("group_id", acct.group_id)
					.neq("id", sp.account_id)
					.limit(5);
				const { data: altAccounts, error: altAccountsError } =
					await publishableAccountFilters(altQuery);
				assertNoDbError("load alternate Threads accounts", altAccountsError);

				if (altAccounts && altAccounts.length > 0) {
					const newAccountId = (altAccounts[0] as { id: string }).id;
					const { error: reassignErr } = await db()
						.from("posts")
						.update({
							account_id: newAccountId,
							metadata: {
								original_account_id: sp.account_id,
								reassign_reason: ineligibleReason,
								reassigned_at: new Date().toISOString(),
							},
							updated_at: new Date().toISOString(),
						})
						.eq("id", sp.id)
						.eq("status", "scheduled");

					if (!reassignErr) {
						reassigned = true;
						stats.retried++;
						logger.info("[rescue] Reassigned stuck post to active account", {
							postId: sp.id,
							fromAccount: sp.account_id,
							toAccount: newAccountId,
							reason: ineligibleReason,
						});
					}
				}
			}

			// No reassignment possible — fail with clear error
			if (!reassigned) {
				const { error: failUpdateError } = await db()
					.from("posts")
					.update({
						status: "failed",
						error_message: `Post could not publish: ${ineligibleReason}. No other active accounts available in the group. Please reconnect the account or reassign manually.`,
						updated_at: new Date().toISOString(),
					})
					.eq("id", sp.id)
					.eq("status", "scheduled");
				assertNoDbError("fail stuck Threads post", failUpdateError);

				const { error: notificationError } = await db()
					.from("notifications")
					.insert({
						user_id: sp.user_id,
						type: "post_failed",
						title: "Scheduled post failed — account unavailable",
						message: `A scheduled post couldn't publish because the account is ${ineligibleReason.replace("_", " ")}. No other active accounts were available for reassignment.`,
						read: false,
						data: {
							postId: sp.id,
							accountId: sp.account_id,
							reason: ineligibleReason,
						},
					});
				if (notificationError) {
					logger.warn(
						"[scheduled-posts] Failed to persist stuck post notification",
						{
							userId: sp.user_id,
							postId: sp.id,
							error: notificationError.message,
						},
					);
				}

				deliverNotification({
					userId: sp.user_id,
					type: "post_failed",
					title: "Scheduled post failed — account unavailable",
					message: `A scheduled post couldn't publish because the account is ${ineligibleReason.replace("_", " ")}. No other active accounts were available for reassignment.`,
					data: {
						postId: sp.id,
						accountId: sp.account_id,
						reason: ineligibleReason,
					},
				}).catch((err) =>
					logger.warn("[scheduled-posts] Notification delivery failed", {
						error: String(err),
					}),
				);

				logger.warn(
					"[rescue] Failed stuck post — no active accounts in group",
					{
						postId: sp.id,
						accountId: sp.account_id,
						reason: ineligibleReason,
					},
				);
			}
		}
	}
}

/**
 * STEP 1.5: Rescue stuck IG scheduled posts (overdue > 30 min, inactive account)
 */
export async function rescueStuckIGPosts(): Promise<void> {
	const igRescueThreshold = new Date(Date.now() - 30 * 60 * 1000).toISOString();
	const { data: stuckIgPosts, error: stuckIgPostsError } = await db()
		.from("posts")
		.select(
			"id, user_id, instagram_account_id, scheduled_for, instagram_accounts!inner (id, group_id, is_active, needs_reauth, status, token_expires_at)",
		)
		.eq("status", "scheduled")
		.eq("platform", "instagram")
		.lt("scheduled_for", igRescueThreshold)
		.limit(20);
	assertNoDbError("load stuck Instagram posts", stuckIgPostsError);

	if (stuckIgPosts && stuckIgPosts.length > 0) {
		for (const sip of stuckIgPosts as {
			id: string;
			user_id: string;
			instagram_account_id: string;
			scheduled_for: string;
			instagram_accounts: {
				id: string;
				group_id: string | null;
				is_active: boolean;
				needs_reauth: boolean | null;
				status: string | null;
				token_expires_at: string | null;
			};
		}[]) {
			const igAcct = sip.instagram_accounts;
			const igElig = isAccountPublishable(igAcct);
			if (igElig.eligible) continue;

			const reason = igElig.reason || "unknown";

			// Try reassignment to another active IG account in same group
			let reassigned = false;
			if (igAcct.group_id) {
				const altIgQuery = db()
					.from("instagram_accounts")
					.select("id")
					.eq("user_id", sip.user_id)
					.eq("group_id", igAcct.group_id)
					.neq("id", sip.instagram_account_id)
					.limit(5);
				const { data: altIg, error: altIgError } =
					await publishableAccountFilters(altIgQuery);
				assertNoDbError("load alternate Instagram accounts", altIgError);

				if (altIg && altIg.length > 0) {
					const newId = (altIg[0] as { id: string }).id;
					const { error: reErr } = await db()
						.from("posts")
						.update({
							instagram_account_id: newId,
							metadata: {
								original_instagram_account_id: sip.instagram_account_id,
								reassign_reason: reason,
								reassigned_at: new Date().toISOString(),
							},
							updated_at: new Date().toISOString(),
						})
						.eq("id", sip.id)
						.eq("status", "scheduled");

					if (!reErr) {
						reassigned = true;
						logger.info("[rescue-ig] Reassigned stuck IG post", {
							postId: sip.id,
							from: sip.instagram_account_id,
							to: newId,
							reason,
						});
					}
				}
			}

			if (!reassigned) {
				const { error: failUpdateError } = await db()
					.from("posts")
					.update({
						status: "failed",
						error_message: `Post could not publish: ${reason}. No other active Instagram accounts available in the group.`,
						updated_at: new Date().toISOString(),
					})
					.eq("id", sip.id)
					.eq("status", "scheduled");
				assertNoDbError("fail stuck Instagram post", failUpdateError);

				const { error: notificationError } = await db()
					.from("notifications")
					.insert({
						user_id: sip.user_id,
						type: "post_failed",
						title: "Scheduled IG post failed — account unavailable",
						message: `A scheduled Instagram post couldn't publish because the account is ${reason.replace("_", " ")}.`,
						read: false,
						data: {
							postId: sip.id,
							accountId: sip.instagram_account_id,
							reason,
						},
					});
				if (notificationError) {
					logger.warn(
						"[scheduled-posts] Failed to persist stuck IG notification",
						{
							userId: sip.user_id,
							postId: sip.id,
							error: notificationError.message,
						},
					);
				}

				deliverNotification({
					userId: sip.user_id,
					type: "post_failed",
					title: "Scheduled IG post failed — account unavailable",
					message: `A scheduled Instagram post couldn't publish because the account is ${reason.replace("_", " ")}.`,
					data: { postId: sip.id, accountId: sip.instagram_account_id, reason },
				}).catch((err) =>
					logger.warn("[scheduled-posts] Notification delivery failed", {
						error: String(err),
					}),
				);

				logger.warn("[rescue-ig] Failed stuck IG post", {
					postId: sip.id,
					accountId: sip.instagram_account_id,
					reason,
				});
			}
		}
	}
}
