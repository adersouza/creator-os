// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Instagram platform publishing logic for scheduled posts.
 * Handles container retry for in-progress posts and publishing new
 * scheduled Instagram posts (IMAGE, CAROUSEL, REELS, STORIES).
 */

import { IG_CONTAINER_STATUS } from "../../constants.js";
import { deliverNotification } from "../../deliverNotification.js";
import { decrypt } from "../../encryption.js";
import { checkSubscriptionPostLimit } from "../../handlers/posts/shared.js";
import { checkIGRateLimit } from "../../igRateLimit.js";
import { resolveInstagramTrialReelIntent } from "../../instagramTrialReels.js";
import { logger } from "../../logger.js";
import { runPublishPreflight } from "../../publishPreflight.js";
import { maxBodyChars } from "../../socialPlatform.js";
import { getSupabaseAny } from "../../supabase.js";
import { eqOrNull } from "../../supabaseSafe.js";
import type { Json } from "../../../../types/supabase.js";
import { handleCrossPost } from "./crossPost.js";
import type { ProcessingStats } from "./shared.js";
import { db, isTransientError, safeInsertNotification } from "./shared.js";

function isPreviewScheduleOnly(metadata: Json | null | undefined): boolean {
	const campaignFactory =
		metadata && typeof metadata === "object" && !Array.isArray(metadata)
			? (metadata as Record<string, unknown>).campaign_factory
			: null;
	return (
		!!campaignFactory &&
		typeof campaignFactory === "object" &&
		!Array.isArray(campaignFactory) &&
		(campaignFactory as Record<string, unknown>).preview_schedule_only === true
	);
}

/**
 * STEP 1: Retry IG posts that are stuck in "publishing" with existing containers.
 * Checks container status and publishes if FINISHED, fails if EXPIRED/ERROR,
 * auto-fails if stuck IN_PROGRESS for >2 hours.
 */
export async function retryIGContainers(
	stats: ProcessingStats,
	startTime: number,
	MAX_RUNTIME_MS: number,
): Promise<void> {
	// Lazy import Instagram API once for all IG posts
	const { checkContainerStatus, publishContainer } = await import(
		"../../instagramApi.js"
	);

	const retryPostsQuery = eqOrNull(
		db()
			.from("posts")
			.select(
				`
        id,
        user_id,
        instagram_account_id,
        ig_container_id,
        ig_container_status,
        ig_publish_attempts,
        updated_at,
        instagram_accounts!inner (
          id,
          instagram_user_id,
          instagram_access_token_encrypted,
          facebook_page_access_token_encrypted,
          username,
          login_type
        )
      `,
			)
			.eq("status", "publishing")
			.eq("platform", "instagram")
			.not("ig_container_id", "is", null)
			.lt("ig_publish_attempts", 5), // Max 5 retry attempts
		"approval_status",
		"approved",
	);
	const { data: retryPosts, error: retryError } = await retryPostsQuery
		.order("updated_at", { ascending: true })
		.limit(3);

	if (retryError) {
		logger.error("IG retry query error", { error: retryError.message });
		return;
	}

	if (!retryPosts || retryPosts.length === 0) return;

	logger.info("Retrying IG posts with existing containers", {
		count: retryPosts.length,
	});

	for (const retryPost of retryPosts) {
		if (Date.now() - startTime > MAX_RUNTIME_MS) {
			logger.warn("Approaching timeout during IG container retry, breaking", {
				published: stats.published,
			});
			break;
		}
		const igAccount = (retryPost as Record<string, unknown>)
			.instagram_accounts as {
			id: string;
			instagram_user_id: string;
			instagram_access_token_encrypted: string;
			facebook_page_access_token_encrypted: string | null;
			login_type: string | null;
			username: string | null;
		} | null;
		const loginType = igAccount?.login_type || "facebook";

		try {
			const token = decrypt(igAccount?.instagram_access_token_encrypted ?? "");

			// Check container status
			const statusResult = await checkContainerStatus(
				token,
				retryPost.ig_container_id ?? "",
				loginType,
			);
			logger.info("Container status check", {
				containerId: retryPost.ig_container_id,
				status: statusResult.status,
			});

			// Update container status in DB
			await db()
				.from("posts")
				.update({
					ig_container_status: statusResult.status,
					ig_publish_attempts: (retryPost.ig_publish_attempts || 0) + 1,
					updated_at: new Date().toISOString(),
				})
				.eq("id", retryPost.id);

			if (statusResult.status === "FINISHED") {
				// Container is ready - publish it!
				const publishResult = await publishContainer(
					token,
					igAccount?.instagram_user_id ?? "",
					retryPost.ig_container_id ?? "",
					loginType,
				);

				if (publishResult.success && publishResult.mediaId) {
					// Atomic guard: only publish if not rejected
					const retryGuardQuery = eqOrNull(
						db()
							.from("posts")
							.update({
								status: "published",
								instagram_post_id: publishResult.mediaId,
								permalink: publishResult.permalink || null,
								published_at: new Date().toISOString(),
								ig_container_status: "PUBLISHED",
								updated_at: new Date().toISOString(),
							})
							.eq("id", retryPost.id)
							.eq("status", "publishing"),
						"approval_status",
						"approved",
					);
					const { data: retryGuardResult } =
						await retryGuardQuery.select("id");

					if (!retryGuardResult || retryGuardResult.length === 0) {
						logger.warn("IG retry post was rejected before publish", {
							postId: retryPost.id,
						});
						continue;
					}

					stats.published++;
					logger.info("Retry successful", {
						postId: retryPost.id,
						mediaId: publishResult.mediaId,
						permalink: publishResult.permalink,
					});

					// Cross-post: queue adapted version for Threads if enabled
					await handleCrossPost(retryPost, "instagram");
				} else {
					throw new Error(publishResult.error || "Publish failed");
				}
			} else if (
				statusResult.status === "EXPIRED" ||
				statusResult.status === "ERROR"
			) {
				// Container expired/failed - mark as failed, will need manual retry
				await db()
					.from("posts")
					.update({
						status: "failed",
						error_message: `Container ${statusResult.status}: ${statusResult.error}. Please retry.`,
						ig_container_id: null, // Clear expired container
						ig_container_status: statusResult.status,
						updated_at: new Date().toISOString(),
					})
					.eq("id", retryPost.id);

				stats.failed++;
				logger.warn("Container expired/failed", {
					postId: retryPost.id,
					status: statusResult.status,
				});
			}
			// If IN_PROGRESS or TIMED_OUT (poll window exhausted), check wall-clock age
			if (
				statusResult.status === IG_CONTAINER_STATUS.IN_PROGRESS ||
				statusResult.status === "TIMED_OUT"
			) {
				const containerAge =
					Date.now() - new Date(retryPost.updated_at || Date.now()).getTime();
				const TWO_HOURS_MS = 2 * 60 * 60 * 1000;

				if (containerAge > TWO_HOURS_MS) {
					// Container stuck for >2 hours — auto-fail to prevent infinite retry
					await db()
						.from("posts")
						.update({
							status: "failed",
							error_message: `Container stuck IN_PROGRESS for over 2 hours (${Math.round(containerAge / 60000)} min). This usually means a media processing issue on Meta's side. Please retry with a different media file.`,
							ig_container_id: null,
							ig_container_status: "TIMEOUT",
							updated_at: new Date().toISOString(),
						})
						.eq("id", retryPost.id);

					stats.failed++;
					logger.warn("Container timeout - auto-failed", {
						postId: retryPost.id,
						containerId: retryPost.ig_container_id,
						ageMinutes: Math.round(containerAge / 60000),
					});
				}
				// Otherwise, do nothing - will retry next cron run
			}
		} catch (err: unknown) {
			logger.error("Retry error for IG post", {
				postId: retryPost.id,
				error: err instanceof Error ? err.message : String(err),
			});
		}

		await new Promise((resolve) => setTimeout(resolve, 1000));
	}
}

/**
 * STEP 2: Process new scheduled Instagram posts.
 * Handles validation, rate limiting, media transformation, and publishing.
 */
export async function processNewIGPosts(
	stats: ProcessingStats,
	startTime: number,
	MAX_RUNTIME_MS: number,
): Promise<void> {
	const now = new Date().toISOString();

	const igPostsQuery = eqOrNull(
		db()
			.from("posts")
			.select(
				`
        id,
        user_id,
        instagram_account_id,
        content,
        media_urls,
        ig_media_type,
        alt_text,
        location_id,
        metadata,
        publish_mode,
        handoff_status,
        notification_sent_at,
        reminder_count,
        scheduled_for,
        retry_count,
        instagram_accounts!inner (
          id,
          instagram_user_id,
          instagram_access_token_encrypted,
          facebook_page_access_token_encrypted,
          username,
          login_type,
          is_active,
          needs_reauth,
          status,
          token_expires_at
        )
      `,
			)
			.eq("status", "scheduled")
			.eq("platform", "instagram")
			.lte("scheduled_for", now),
		"approval_status",
		"approved",
	);
	const { data: igPosts, error: igPostsError } = await igPostsQuery
		.eq("instagram_accounts.is_active", true) // skip accounts deactivated by tier downgrade
		.order("scheduled_for", { ascending: true })
		.limit(10); // Process up to 10 IG posts per run (140s budget, ~20s each)

	if (igPostsError) {
		logger.error("IG query error", { error: igPostsError.message });
		return;
	}

	const publishablePosts = (igPosts ?? []).filter(
		(post: { metadata?: Json | null | undefined }) =>
			!isPreviewScheduleOnly(post.metadata),
	);
	const previewOnlyCount = (igPosts ?? []).length - publishablePosts.length;
	if (previewOnlyCount > 0) {
		logger.info("Skipping preview-only Instagram scheduled posts", {
			count: previewOnlyCount,
		});
	}

	if (publishablePosts.length === 0) {
		logger.info("No Instagram scheduled posts due");
		return;
	}

	logger.info("Found Instagram posts to process", {
		count: publishablePosts.length,
	});
	stats.found += publishablePosts.length;

	for (const igPost of publishablePosts) {
		if (Date.now() - startTime > MAX_RUNTIME_MS) {
			logger.warn("Approaching timeout during IG scheduled posts, breaking", {
				published: stats.published,
			});
			break;
		}
		const igAccount = (igPost as Record<string, unknown>)
			.instagram_accounts as {
			id: string;
			instagram_user_id: string;
			instagram_access_token_encrypted: string;
			facebook_page_access_token_encrypted: string | null;
			login_type: string | null;
			username: string | null;
			is_active: boolean;
			needs_reauth: boolean | null;
			status: string | null;
			token_expires_at: string | null;
			follower_count?: number | null;
		} | null;
		const loginType = igAccount?.login_type || "facebook";

		if ((igPost as { publish_mode?: string | null }).publish_mode === "notify") {
			const { notifyInstagramHandoff } = await import("../../notifyHandoff.js");
			const notifyResult = await notifyInstagramHandoff(igPost.id, "cron");
			if (notifyResult.result === "notified") {
				stats.retried++;
			} else {
				logger.info("Skipped IG Notify Me reminder", {
					postId: igPost.id,
					reason: notifyResult.error,
				});
			}
			continue;
		}

		// #OWASP-A04: Enforce subscription tier limits for IG scheduled posts
		try {
			const tierCheck = await checkSubscriptionPostLimit(igPost.user_id);
			if (!tierCheck.allowed) {
				logger.info("Skipping IG post — user exceeded tier daily post limit", {
					postId: igPost.id,
					userId: igPost.user_id,
					tier: tierCheck.tier,
					used: tierCheck.used,
					limit: tierCheck.limit,
				});
				await db()
					.from("posts")
					.update({
						status: "failed",
						error_message: `Daily post limit exceeded (${tierCheck.used}/${tierCheck.limit} for ${tierCheck.tier} tier). Upgrade your plan to publish more.`,
						updated_at: new Date().toISOString(),
					})
					.eq("id", igPost.id)
					.eq("status", "scheduled");
				stats.failed++;
				continue;
			}
		} catch (tierErr) {
			const tierErrorMessage = String(tierErr);
			logger.warn("[scheduled-posts] IG tier check failed, skipping publish", {
				postId: igPost.id,
				userId: igPost.user_id,
				error: tierErrorMessage,
			});
			stats.rateLimited++;
			stats.errors.push(
				`Post ${igPost.id}: tier check failed (${tierErrorMessage})`,
			);
			continue;
		}

		// Defense-in-depth: skip posts for accounts deactivated by tier downgrade.
		if (igAccount?.is_active === false) {
			logger.info(
				"Skipping IG post — account deactivated after tier downgrade",
				{
					postId: igPost.id,
					accountId: igAccount.id,
				},
			);
			continue;
		}

		if (!igAccount?.instagram_access_token_encrypted) {
			logger.warn("Skipping IG post - no valid account", {
				postId: igPost.id,
			});
			stats.failed++;
			stats.errors.push(
				`IG Post ${igPost.id}: Account not properly configured`,
			);

			await db()
				.from("posts")
				.update({
					status: "failed",
					error_message: "Instagram account not properly configured",
					updated_at: new Date().toISOString(),
				})
				.eq("id", igPost.id);
			await db()
				.from("notifications")
				.insert({
					user_id: igPost.user_id,
					type: "post_failed",
					title: "Instagram post failed",
					message:
						"Instagram account not properly configured. Please reconnect your account.",
					read: false,
					data: { postId: igPost.id, platform: "instagram" },
				});
			deliverNotification({
				userId: igPost.user_id,
				type: "post_failed",
				title: "Instagram post failed",
				message: "Instagram account not properly configured.",
				data: { postId: igPost.id },
			}).catch((err) =>
				logger.warn("[scheduled-posts] Notification delivery failed", {
					error: String(err),
				}),
			);

			continue;
		}

		// Validate IG content
		const igContent = igPost.content || "";
		const igMaxChars = maxBodyChars("instagram");
		if (igContent.length > igMaxChars) {
			const igTooLongMsg = `Caption exceeds ${igMaxChars} character limit (${igContent.length} chars). Please edit and reschedule.`;
			logger.warn(`Skipping IG post - caption exceeds ${igMaxChars} chars`, {
				postId: igPost.id,
			});
			stats.failed++;
			await db()
				.from("posts")
				.update({
					status: "failed",
					error_message: igTooLongMsg,
					updated_at: new Date().toISOString(),
				})
				.eq("id", igPost.id);
			await db()
				.from("notifications")
				.insert({
					user_id: igPost.user_id,
					type: "post_failed",
					title: "Instagram post failed",
					message: igTooLongMsg,
					read: false,
					data: { postId: igPost.id, platform: "instagram" },
				});
			deliverNotification({
				userId: igPost.user_id,
				type: "post_failed",
				title: "Instagram post failed",
				message: igTooLongMsg,
				data: { postId: igPost.id },
			}).catch((err) =>
				logger.warn("[scheduled-posts] Notification delivery failed", {
					error: String(err),
				}),
			);
			continue;
		}

		// Atomically claim this IG post FIRST, then check rate limits AFTER claim succeeds.
		// This prevents rate limit quota leaking when the claim fails (another instance got it).
		const igClaimQuery = eqOrNull(
			db()
				.from("posts")
				.update({
					status: "publishing",
					ig_publish_attempts: 1,
					updated_at: new Date().toISOString(),
				})
				.eq("id", igPost.id)
				.eq("status", "scheduled"),
			"approval_status",
			"approved",
		);
		const { data: claimedIgPost, error: igClaimError } = await igClaimQuery
			.select("id")
			.maybeSingle();

		if (igClaimError || !claimedIgPost) {
			logger.info("IG post already claimed by another instance, skipping", {
				postId: igPost.id,
			});
			continue;
		}

		// Check IG rate limits AFTER claim (Instagram allows 100 posts/24h)
		const igRate = await checkIGRateLimit(igAccount.id);

		if (!igRate) {
			logger.error(
				"IG rate limit check failed, releasing claim (fail closed)",
				{
					accountId: igAccount.id,
				},
			);
			await db()
				.from("posts")
				.update({ status: "scheduled", updated_at: new Date().toISOString() })
				.eq("id", igPost.id);
			stats.rateLimited++;
			continue;
		}

		if (!igRate.allowed) {
			logger.info("IG post rate limited", {
				postId: igPost.id,
				reason: igRate.reason,
			});
			try {
				await db()
					.from("notifications")
					.insert({
						user_id: igPost.user_id,
						type: "post_rate_limited",
						title: "Instagram post delayed — rate limit",
						message:
							"Your scheduled Instagram post was temporarily delayed due to platform rate limits. It will be retried automatically.",
						read: false,
						data: { postId: igPost.id, reason: igRate.reason },
					});
			} catch {
				/* notification non-critical */
			}
			await db()
				.from("posts")
				.update({ status: "scheduled", updated_at: new Date().toISOString() })
				.eq("id", igPost.id);
			stats.rateLimited++;
			continue;
		}

		const mediaUrls = igPost.media_urls || [];
		const igMeta =
			((igPost as Record<string, unknown>).metadata as Record<
				string,
				unknown
			>) || {};
		const trialIntent = resolveInstagramTrialReelIntent({
			metadata: igMeta,
			trialGraduationStrategy: igMeta.trialGraduationStrategy as string | undefined,
		});

		// #story-validation: Stories MUST have media — fail early with clear error
		if (igPost.ig_media_type === "STORIES" && mediaUrls.length === 0) {
			const storyMsg =
				"Instagram Stories require an image or video. This story had no media attached.";
			logger.warn("Skipping IG Story - no media attached", {
				postId: igPost.id,
			});
			stats.failed++;
			stats.errors.push(`IG Post ${igPost.id}: Story has no media`);
			await db()
				.from("posts")
				.update({
					status: "failed",
					error_message: storyMsg,
					updated_at: new Date().toISOString(),
				})
				.eq("id", igPost.id);
			await db()
				.from("notifications")
				.insert({
					user_id: igPost.user_id,
					type: "post_failed",
					title: "Instagram Story failed",
					message: storyMsg,
					read: false,
					data: { postId: igPost.id, platform: "instagram" },
				});
			deliverNotification({
				userId: igPost.user_id,
				type: "post_failed",
				title: "Instagram Story failed",
				message: storyMsg,
				data: { postId: igPost.id },
			}).catch((err) =>
				logger.warn("[scheduled-posts] Notification delivery failed", {
					error: String(err),
				}),
			);
			continue;
		}

		// Normalize ig_media_type: CAROUSEL_ALBUM (IG response format) -> CAROUSEL (IG API param)
		const rawMediaType =
			igPost.ig_media_type ||
			(mediaUrls.length > 1
				? "CAROUSEL"
				: mediaUrls.length === 1
					? /\.(mp4|mov)(\?|$)/i.test(mediaUrls[0]!)
						? "REELS"
						: "IMAGE"
					: "IMAGE");
		const resolvedMediaType =
			rawMediaType === "CAROUSEL_ALBUM" ? "CAROUSEL" : rawMediaType;

		// Determine if the first media URL is a video (used for Stories + Reels + Video types)
		const firstMediaIsVideo = mediaUrls[0]
			? /\.(mp4|mov)(\?|$)/i.test(mediaUrls[0])
			: false;

		const mediaAltTexts = (igMeta.mediaAltTexts as string[] | undefined) || [];
		const preflight = await runPublishPreflight(
			{
				platform: "instagram",
				instagramAccountId: igPost.instagram_account_id,
				content: igPost.content || "",
				igMediaType: resolvedMediaType,
				media: mediaUrls.map((url: string, index: number) => ({
					type: /\.(mp4|mov)(\?|$)/i.test(url) ? "video" : "image",
					url,
					altText: mediaAltTexts[index] || igPost.alt_text || undefined,
				})),
				collaborators: (igMeta.collaborators as string[] | undefined) || undefined,
				isTrialReel: igMeta.trialReels ? true : undefined,
				brandedContentSponsorIds:
					(igMeta.brandedContentSponsorIds as string[] | undefined) || undefined,
				isPaidPartnership: igMeta.isPaidPartnership ? true : undefined,
				coverUrl: (igMeta.coverUrl as string) || undefined,
				shareToFeed:
					igMeta.shareToFeed !== undefined
						? (igMeta.shareToFeed as boolean)
						: undefined,
					userTags: (igMeta.userTags as unknown[] | undefined) || undefined,
					productTags: (igMeta.productTags as unknown[] | undefined) || undefined,
					firstComment: (igMeta.firstComment as string) || undefined,
					metadata: (igPost.metadata as Record<string, unknown> | null | undefined) || undefined,
					trialReels: igMeta.trialReels ? true : undefined,
					instagramTrialReels: trialIntent.enabled ? true : undefined,
					trialGraduationStrategy: trialIntent.strategy,
			},
			{
				account: {
					found: !!igAccount,
					isActive: igAccount?.is_active,
					needsReauth: igAccount?.needs_reauth,
					status: igAccount?.status,
					tokenExpiresAt: igAccount?.token_expires_at,
					hasAccessToken: !!igAccount?.instagram_access_token_encrypted,
					hasPlatformUserId: !!igAccount?.instagram_user_id,
					loginType: igAccount?.login_type,
					followerCount: igAccount?.follower_count,
				},
				checkMediaUrls: true,
			},
		);
		if (!preflight.ok) {
			const message =
				preflight.issues.find((issue) => issue.severity === "error")?.message ||
				"Scheduled Instagram post failed preflight.";
			stats.failed++;
			stats.errors.push(`IG Post ${igPost.id}: ${message}`);
			await db()
				.from("posts")
				.update({
					status: "failed",
					error_message: message,
					updated_at: new Date().toISOString(),
				})
				.eq("id", igPost.id)
				.eq("status", "publishing");
			await safeInsertNotification(
				{
					user_id: igPost.user_id,
					type: "post_failed",
					title: "Instagram post failed preflight",
					message,
					read: false,
					data: {
						postId: igPost.id,
						platform: "instagram",
						preflight,
					} as unknown as Json,
				},
				{ postId: igPost.id, platform: "instagram", accountId: igAccount?.id },
			);
			continue;
		}

		const igPostData = {
			caption: igPost.content || "",
			mediaType:
				resolvedMediaType as import("../../instagramApi.js").IGMediaType,
			imageUrl:
				resolvedMediaType !== "CAROUSEL" &&
				mediaUrls[0] &&
				!(
					resolvedMediaType === "REELS" ||
					resolvedMediaType === "VIDEO" ||
					(resolvedMediaType === "STORIES" && firstMediaIsVideo)
				)
					? mediaUrls[0]
					: undefined,
			videoUrl:
				resolvedMediaType === "REELS" ||
				resolvedMediaType === "VIDEO" ||
				(resolvedMediaType === "STORIES" && firstMediaIsVideo)
					? mediaUrls[0]
					: undefined,
			altText: igPost.alt_text || undefined,
			locationId:
				((igPost as Record<string, unknown>).location_id as string) ||
				undefined,
			collaborators: (igMeta.collaborators as string[]) || undefined,
			coverUrl: (igMeta.coverUrl as string) || undefined,
			shareToFeed:
				igMeta.shareToFeed !== undefined
					? (igMeta.shareToFeed as boolean)
					: undefined,
			userTags:
				(igMeta.userTags as Array<{
					username: string;
					x: number;
					y: number;
				}>) || undefined,
			trialReels:
				trialIntent.enabled && resolvedMediaType === "REELS" ? true : undefined,
			trialGraduationStrategy:
				trialIntent.enabled && resolvedMediaType === "REELS"
					? trialIntent.strategy
					: undefined,
			thumbOffset: (igMeta.thumbOffset as number) || undefined,
			audioName: (igMeta.audioName as string) || undefined,
			igAudioId: (igMeta.igAudioId as string) || undefined,
			productTags:
				(igMeta.productTags as Array<{
					product_id: string;
					x?: number | undefined;
					y?: number | undefined;
				}>) || undefined,
			brandedContentSponsorIds:
				(igMeta.brandedContentSponsorIds as string[] | undefined) || undefined,
			isPaidPartnership: igMeta.isPaidPartnership ? true : undefined,
			commentEnabled:
				igMeta.commentEnabled !== undefined
					? (igMeta.commentEnabled as boolean)
					: undefined,
			firstComment: (igMeta.firstComment as string) || undefined,
			children:
				resolvedMediaType === "CAROUSEL"
					? mediaUrls.map((url: string, index: number) => ({
							type: (url.match(/\.(mp4|mov|avi)$/i) ? "video" : "image") as
								| "video"
								| "image",
							url,
							altText: mediaAltTexts[index] || undefined,
						}))
					: undefined,
		};

		const { orchestrateIGPublish } = await import(
			"../../instagram/orchestrate.js"
		);
		const igResult = await orchestrateIGPublish({
			encryptedToken: igAccount.instagram_access_token_encrypted,
			igUserId: igAccount.instagram_user_id,
			postData: igPostData,
			encryptedFbPageToken:
				igAccount.facebook_page_access_token_encrypted || undefined,
			loginType,
			mediaCheck: true,
			postPublish: {
				engagementSync: {
					postId: igPost.id,
					accountId: igAccount.id,
					userId: igPost.user_id,
					source: "cron",
				},
				storyAutoShare: {
					enabled: resolvedMediaType === "IMAGE" && !!mediaUrls[0],
					mediaUrl: mediaUrls[0] || "",
				},
			},
		});

		if (igResult.success && igResult.mediaId) {
			// Atomic guard: only publish if not rejected
			const igUpdatePayload: Record<string, unknown> = {
				status: "published",
				instagram_post_id: igResult.mediaId,
				permalink: igResult.permalink || null,
				published_at: new Date().toISOString(),
				ig_container_status: "PUBLISHED",
				updated_at: new Date().toISOString(),
			};
			const igGuardQuery = eqOrNull(
				getSupabaseAny()
					.from("posts")
					.update(igUpdatePayload)
					.eq("id", igPost.id)
					.eq("status", "publishing"),
				"approval_status",
				"approved",
			);
			const { data: igGuardResult } = await igGuardQuery.select("id");

			if (!igGuardResult || igGuardResult.length === 0) {
				logger.warn("IG post was rejected before publish", {
					postId: igPost.id,
				});
				continue;
			}

			await safeInsertNotification(
				{
					user_id: igPost.user_id,
					type: "post_published",
					title: "Instagram post published",
					message: `Your scheduled post to @${igAccount.username} on Instagram has been published.`,
					read: false,
					data: {
						postId: igPost.id,
						mediaId: igResult.mediaId,
						permalink: igResult.permalink,
						platform: "instagram",
					},
				},
				{ postId: igPost.id, platform: "instagram", accountId: igAccount.id },
			);

			stats.published++;
			logger.info("Published IG post", {
				postId: igPost.id,
				mediaId: igResult.mediaId,
				permalink: igResult.permalink,
			});

			// Cross-post: queue adapted version for Threads if enabled
			await handleCrossPost(igPost, "instagram");
		} else if (igResult.containerId) {
			// Container created but not finished yet - save for retry
			await db()
				.from("posts")
				.update({
					ig_container_id: igResult.containerId,
					ig_container_created_at: new Date().toISOString(),
					ig_container_status: "IN_PROGRESS",
					updated_at: new Date().toISOString(),
				})
				.eq("id", igPost.id);

			logger.info("IG post container created, will retry next run", {
				postId: igPost.id,
				containerId: igResult.containerId,
			});
		} else {
			const igErrorMsg = igResult.error || "Unknown IG publishing error";
			const igRetryCount =
				((igPost as Record<string, unknown>).retry_count as number) || 0;

			// Auto-reschedule errors up to 3 times UNLESS explicitly non-retryable.
			// Default to retry — only permanently fail on known permanent errors
			// (invalid content, session expiry subcode 463/467, tier limits, etc.)
			const isExplicitlyNonRetryable = igResult.retryable === false;
			const isPermanent =
				isExplicitlyNonRetryable && !isTransientError(igErrorMsg);
			// Exponential backoff: 15min → 1h → 4h to avoid hammering Meta API
			if (!isPermanent && igRetryCount < 3) {
				const backoffDelays = [15 * 60_000, 60 * 60_000, 4 * 60 * 60_000]; // 15m, 1h, 4h
				const delayMs = backoffDelays[igRetryCount] || backoffDelays[2];
				await db()
					.from("posts")
					.update({
						status: "scheduled",
						scheduled_for: new Date(Date.now() + delayMs!).toISOString(),
						retry_count: igRetryCount + 1,
						error_message: null,
						updated_at: new Date().toISOString(),
					})
					.eq("id", igPost.id);

				stats.retried++;
				logger.info("Auto-rescheduled IG post on transient error", {
					postId: igPost.id,
					retryCount: igRetryCount + 1,
					error: igErrorMsg,
				});
			} else {
				// Permanent failure or retries exhausted
				await db()
					.from("posts")
					.update({
						status: "failed",
						error_message: igErrorMsg,
						updated_at: new Date().toISOString(),
					})
					.eq("id", igPost.id);

				await db()
					.from("notifications")
					.insert({
						user_id: igPost.user_id,
						type: "post_failed",
						title: "Instagram post failed",
						message: `Failed to publish scheduled Instagram post: ${igErrorMsg}`,
						read: false,
						data: {
							postId: igPost.id,
							error: igErrorMsg,
							platform: "instagram",
						},
					});
				deliverNotification({
					userId: igPost.user_id,
					type: "post_failed",
					title: "Instagram post failed",
					message: `Failed to publish scheduled Instagram post: ${igErrorMsg}`,
					data: {
						postId: igPost.id,
						error: igErrorMsg,
						platform: "instagram",
					},
				}).catch((err) =>
					logger.warn("[scheduled-posts] Notification delivery failed", {
						error: String(err),
					}),
				);

				stats.failed++;
				stats.errors.push(`IG Post ${igPost.id}: ${igErrorMsg}`);
				logger.error("Failed IG post", {
					postId: igPost.id,
					error: igErrorMsg,
				});
			}
		}

		// Wait between posts
		await new Promise((resolve) => setTimeout(resolve, 2000));
	}
}
