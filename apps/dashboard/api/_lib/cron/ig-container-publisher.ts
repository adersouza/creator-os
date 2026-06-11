/**
 * Instagram Container Publisher Cron Job
 *
 * Runs every 5 minutes (staggered +3 offset) to check and publish pending Instagram containers.
 *
 * Flow:
 * 1. Query ig_pending_containers WHERE status = 'pending'
 * 2. For each, check container status (single API call, no polling)
 * 3. If ready, publish and update post record
 * 4. If error after 10 checks, mark failed
 *
 * Schedule: 3,8,13,18,23,28,33,38,43,48,53,58 * * * * (every 5 min, offset +3)
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { alertCronFailure } from "../alerting.js";
import { trackCronRun, withCronLock } from "../cronUtils.js";
import { logger, serializeError } from "../logger.js";
import { isRetryableMetaError, withRetry } from "../retryUtils.js";
import { getSupabase, type TypedSupabaseClient } from "../supabase.js";

export const config = {
	maxDuration: 60,
};

const MAX_CHECK_ATTEMPTS = 10;

export default async function handler(req: VercelRequest, res: VercelResponse) {
	// Strict cron secret check — no x-vercel-cron fallback (spoofable header)
	const { verifyCronAuth } = await import("../apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const supabase = getSupabase();

	const lockResult = await withCronLock(
		supabase,
		"ig-container-publisher",
		async () => {
			return trackCronRun(supabase, "ig-container-publisher", async () => {
				const count = await processPendingContainers(supabase);
				return { itemsProcessed: count };
			});
		},
	);

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}

	return res.status(200).json({ success: true });
}

export async function processPendingContainers(
	supabase: TypedSupabaseClient,
): Promise<number> {
	// Lazy import to avoid module crashes
	const { checkContainerReady, publishContainer } = await import(
		"../instagramApi.js"
	);
	const { decrypt } = await import("../encryption.js");

	// Orphan recovery: reset items stuck in processing for >15 minutes back to pending.
	// This happens when a previous cron run crashed or timed out mid-publish.
	const orphanThreshold = new Date(Date.now() - 15 * 60 * 1000).toISOString();
	await supabase
		.from("ig_pending_containers")
		.update({ status: "pending", updated_at: new Date().toISOString() })
		.eq("status", "processing")
		.lt("updated_at", orphanThreshold);

	// Atomic claim: move pending → processing to prevent double-publish on crash recovery
	const { data: containers, error } = await supabase
		.from("ig_pending_containers")
		.update({
			status: "processing",
			last_checked_at: new Date().toISOString(),
			updated_at: new Date().toISOString(),
		})
		.eq("status", "pending")
		.order("id", { ascending: true })
		.limit(10)
		.select("id, post_id, container_id, account_id, check_count, login_type");

	if (error) {
		logger.error("IG Container Publisher query error", {
			error: serializeError(error),
		});
		try {
			const { captureServerException } = await import("../sentryServer.js");
			await captureServerException(error, {
				cronJob: "ig-container-publisher",
			});
		} catch (_sentryErr) {
			logger.warn("[ig-container-publisher] Sentry capture failed", {
				error: String(_sentryErr),
			});
		}
		alertCronFailure("ig-container-publisher", serializeError(error));
		throw error;
	}

	if (!containers || containers.length === 0) {
		logger.info("No pending IG containers");
		return 0;
	}

	logger.info("Processing pending IG containers", { count: containers.length });

	let published = 0;

	for (const container of containers) {
		// Fetch the instagram account for this container
		const { data: igAccount, error: acctErr } = await supabase
			.from("instagram_accounts")
			.select(
				"instagram_user_id, instagram_access_token_encrypted, is_active, needs_reauth",
			)
			.eq("id", container.account_id)
			.maybeSingle();

		if (acctErr || !igAccount?.instagram_access_token_encrypted) {
			logger.warn("IG container has no valid account", {
				containerId: container.id,
				error: acctErr ? serializeError(acctErr) : "missing_token",
			});
			await supabase
				.from("ig_pending_containers")
				.update({
					status: "error",
					error: acctErr
						? "Account lookup failed"
						: "Account not properly configured",
					last_checked_at: new Date().toISOString(),
					updated_at: new Date().toISOString(),
				})
				.eq("id", container.id);
			continue;
		}

		// Skip inactive or reauth-needed accounts
		if (!igAccount.is_active || igAccount.needs_reauth) {
			const reason = !igAccount.is_active
				? "Account is inactive"
				: "Account needs re-authentication";
			logger.warn("IG container skipped — account ineligible", {
				containerId: container.id,
				reason,
			});
			await supabase
				.from("ig_pending_containers")
				.update({
					status: "error",
					error: reason,
					last_checked_at: new Date().toISOString(),
					updated_at: new Date().toISOString(),
				})
				.eq("id", container.id);
			await supabase
				.from("posts")
				.update({
					status: "failed",
					error_message: reason,
					updated_at: new Date().toISOString(),
				})
				.eq("id", container.post_id ?? container.id);
			continue;
		}

		try {
			const token = decrypt(igAccount.instagram_access_token_encrypted);

			// Quick single-check (no polling) with retry wrapper
			const statusResult = await withRetry<{
				status: "pending" | "ready" | "error";
				error?: string | undefined;
			}>(
				() =>
					checkContainerReady(
						token,
						container.container_id ?? "",
						container.login_type ?? undefined,
					),
				{
					maxRetries: 2,
					baseDelayMs: 1000,
					maxDelayMs: 5000,
					shouldRetry: (err) =>
						isRetryableMetaError(
							(err as { status?: number | undefined })?.status || 0,
							err,
						),
				},
			);

			logger.info("IG container status check", {
				containerId: container.container_id,
				status: statusResult.status,
				checkNumber: (container.check_count || 0) + 1,
			});

			if (statusResult.status === "ready") {
				// Publish! with retry wrapper
				const publishResult = await withRetry<
					import("../instagramApi.js").IGPostingResult
				>(
					() =>
						publishContainer(
							token,
							igAccount.instagram_user_id,
							container.container_id ?? "",
							container.login_type ?? undefined,
						),
					{
						maxRetries: 2,
						baseDelayMs: 1000,
						maxDelayMs: 5000,
						shouldRetry: (err) =>
							isRetryableMetaError(
								(err as { status?: number | undefined })?.status || 0,
								err,
							),
					},
				);

				if (publishResult.success && publishResult.mediaId) {
					// Update container record
					await supabase
						.from("ig_pending_containers")
						.update({
							status: "published",
							last_checked_at: new Date().toISOString(),
							updated_at: new Date().toISOString(),
							check_count: (container.check_count || 0) + 1,
						})
						.eq("id", container.id);

					// Update the post record
					await supabase
						.from("posts")
						.update({
							status: "published",
							instagram_post_id: publishResult.mediaId,
							permalink: publishResult.permalink || null,
							published_at: new Date().toISOString(),
							ig_container_status: "PUBLISHED",
							updated_at: new Date().toISOString(),
						})
						.eq("id", container.post_id ?? container.id);

					published++;
					logger.info("IG container published", {
						postId: container.post_id,
						mediaId: publishResult.mediaId,
						permalink: publishResult.permalink,
					});

					// Schedule engagement syncs at 1h, 6h, 24h (fire-and-forget)
					import("../qstashSchedule.js").then(({ schedulePostPublishSyncs }) =>
						schedulePostPublishSyncs(
							container.post_id ?? "",
							container.account_id,
							undefined,
							"instagram",
							"container",
						),
					);

					// Notify user of successful IG publish
					try {
						const { data: postOwner } = await supabase
							.from("posts")
							.select("user_id")
							.eq("id", container.post_id ?? "")
							.maybeSingle();
						if (postOwner?.user_id) {
							await supabase.from("notifications").insert({
								user_id: postOwner.user_id,
								type: "post_published",
								title: "Instagram post published",
								message: "Your scheduled Instagram post has been published.",
								read: false,
								data: {
									postId: container.post_id,
									mediaId: publishResult.mediaId,
								},
							});
							const { deliverNotification } = await import(
								"../deliverNotification.js"
							);
							deliverNotification({
								userId: postOwner.user_id,
								type: "post_published",
								title: "Instagram post published",
								message: "Your scheduled Instagram post has been published.",
								data: {
									postId: container.post_id,
									mediaId: publishResult.mediaId,
								},
							}).catch((err) =>
								logger.warn(
									"[ig-container-publisher] Notification delivery failed",
									{ error: String(err) },
								),
							);
						}
					} catch (notifErr) {
						logger.warn("[ig-container-publisher] Notification insert failed", {
							error: String(notifErr),
						});
					}
				} else {
					// Publish failed
					await supabase
						.from("ig_pending_containers")
						.update({
							status: "error",
							error: publishResult.error || "Publish failed",
							last_checked_at: new Date().toISOString(),
							updated_at: new Date().toISOString(),
							check_count: (container.check_count || 0) + 1,
						})
						.eq("id", container.id);

					await supabase
						.from("posts")
						.update({
							status: "failed",
							error_message: publishResult.error || "Publish failed",
							updated_at: new Date().toISOString(),
						})
						.eq("id", container.post_id ?? container.id);

					// Notify user of IG publish failure
					try {
						const { data: postOwner } = await supabase
							.from("posts")
							.select("user_id")
							.eq("id", container.post_id ?? "")
							.maybeSingle();
						if (postOwner?.user_id) {
							await supabase.from("notifications").insert({
								user_id: postOwner.user_id,
								type: "post_failed",
								title: "Instagram post failed",
								message: `Your Instagram post failed to publish: ${publishResult.error || "Unknown error"}`,
								read: false,
								data: { postId: container.post_id },
							});
							const { deliverNotification } = await import(
								"../deliverNotification.js"
							);
							deliverNotification({
								userId: postOwner.user_id,
								type: "post_failed",
								title: "Instagram post failed",
								message: `Your Instagram post failed to publish: ${publishResult.error || "Unknown error"}`,
								data: { postId: container.post_id },
							}).catch((err) =>
								logger.warn(
									"[ig-container-publisher] Notification delivery failed",
									{ error: String(err) },
								),
							);
						}
					} catch (notifErr) {
						logger.warn("[ig-container-publisher] Notification insert failed", {
							error: String(notifErr),
						});
					}
				}
			} else if (statusResult.status === "error") {
				// Container errored
				await supabase
					.from("ig_pending_containers")
					.update({
						status: "error",
						error: statusResult.error ?? null,
						last_checked_at: new Date().toISOString(),
						updated_at: new Date().toISOString(),
						check_count: (container.check_count || 0) + 1,
					})
					.eq("id", container.id);

				await supabase
					.from("posts")
					.update({
						status: "failed",
						error_message: `Container error: ${statusResult.error}`,
						ig_container_status: "ERROR",
						updated_at: new Date().toISOString(),
					})
					.eq("id", container.post_id ?? "");
			} else {
				// Still pending - increment check count
				const newCheckCount = (container.check_count || 0) + 1;

				if (newCheckCount >= MAX_CHECK_ATTEMPTS) {
					// Max checks exceeded — move to dead letter queue
					await supabase
						.from("ig_pending_containers")
						.update({
							status: "error",
							error: `Container still processing after ${MAX_CHECK_ATTEMPTS} checks`,
							last_checked_at: new Date().toISOString(),
							updated_at: new Date().toISOString(),
							check_count: newCheckCount,
							dead_letter: true,
							dead_letter_at: new Date().toISOString(),
							dead_letter_reason: `Container timed out after ${MAX_CHECK_ATTEMPTS} checks`,
						})
						.eq("id", container.id);

					await supabase
						.from("posts")
						.update({
							status: "failed",
							error_message: `Container timed out after ${MAX_CHECK_ATTEMPTS} attempts`,
							ig_container_status: "EXPIRED",
							updated_at: new Date().toISOString(),
						})
						.eq("id", container.post_id ?? "");

					logger.warn("IG container timed out", {
						containerId: container.container_id,
						maxChecks: MAX_CHECK_ATTEMPTS,
					});

					// Notify user of container timeout
					try {
						const { data: postOwner } = await supabase
							.from("posts")
							.select("user_id")
							.eq("id", container.post_id ?? "")
							.maybeSingle();
						if (postOwner?.user_id) {
							await supabase.from("notifications").insert({
								user_id: postOwner.user_id,
								type: "post_failed",
								title: "Instagram post timed out",
								message:
									"Your Instagram post failed after multiple attempts. The media container expired.",
								read: false,
								data: { postId: container.post_id },
							});
							const { deliverNotification } = await import(
								"../deliverNotification.js"
							);
							deliverNotification({
								userId: postOwner.user_id,
								type: "post_failed",
								title: "Instagram post timed out",
								message:
									"Your Instagram post failed after multiple attempts. The media container expired.",
								data: { postId: container.post_id },
							}).catch((err) =>
								logger.warn(
									"[ig-container-publisher] Notification delivery failed",
									{ error: String(err) },
								),
							);
						}
					} catch (notifErr) {
						logger.warn("[ig-container-publisher] Notification insert failed", {
							error: String(notifErr),
						});
					}
				} else {
					// Update check count and reset to pending for next cron run
					await supabase
						.from("ig_pending_containers")
						.update({
							status: "pending",
							last_checked_at: new Date().toISOString(),
							updated_at: new Date().toISOString(),
							check_count: newCheckCount,
						})
						.eq("id", container.id);
				}
			}
		} catch (err: unknown) {
			const newCheckCount = (container.check_count || 0) + 1;
			logger.error("Error processing IG container", {
				containerId: container.id,
				checkCount: newCheckCount,
				error: serializeError(err),
			});
			try {
				const { captureServerException } = await import("../sentryServer.js");
				await captureServerException(err, {
					cronJob: "ig-container-publisher",
					containerId: container.id,
				});
			} catch (_sentryErr) {
				logger.warn("[ig-container-publisher] Sentry capture failed", {
					error: String(_sentryErr),
				});
			}

			// If we've hit max retries on errors (e.g. corrupted token), mark as dead letter
			if (newCheckCount >= MAX_CHECK_ATTEMPTS) {
				await supabase
					.from("ig_pending_containers")
					.update({
						status: "error",
						error: serializeError(err),
						last_checked_at: new Date().toISOString(),
						updated_at: new Date().toISOString(),
						check_count: newCheckCount,
						dead_letter: true,
						dead_letter_at: new Date().toISOString(),
						dead_letter_reason: `Processing error after ${MAX_CHECK_ATTEMPTS} attempts`,
					})
					.eq("id", container.id);
				await supabase
					.from("posts")
					.update({
						status: "failed",
						error_message: `Container processing failed after ${MAX_CHECK_ATTEMPTS} attempts`,
						ig_container_status: "EXPIRED",
						updated_at: new Date().toISOString(),
					})
					.eq("id", container.post_id ?? "");
			} else {
				await supabase
					.from("ig_pending_containers")
					.update({
						status: "pending",
						error: serializeError(err),
						last_checked_at: new Date().toISOString(),
						updated_at: new Date().toISOString(),
						check_count: newCheckCount,
					})
					.eq("id", container.id);
			}
		}

		// Brief delay between containers
		await new Promise((resolve) => setTimeout(resolve, 500));
	}

	return published;
}
