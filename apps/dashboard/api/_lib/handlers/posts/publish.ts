// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Publish handler — handles publishing posts to Threads and Instagram.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { decrypt } from "../../encryption.js";
import { logger } from "../../logger.js";
import { normalizeIGMediaType } from "../../instagram/shared.js";
import { resolveInstagramTrialReelIntent } from "../../instagramTrialReels.js";
import { runPublishPreflight } from "../../publishPreflight.js";
import { withRetry } from "../../retryUtils.js";
import { sanitizeHtml } from "../../sanitize.js";
import type { PostData } from "../../threadsApi.js";
import { postToThreads } from "../../threadsApi.js";
import { PublishPostSchema, parseBodyOrError } from "../../validation.js";
import { dispatchWebhook } from "../../webhookDispatcher.js";
import {
	type AccountIdRow,
	type AccountRow,
	checkSubscriptionPostLimit,
	db,
	extractHashtags,
	type IgAccountRow,
	normalizePostMediaType,
	type ProfileRow,
	resolveMediaUrls,
	setRateLimitHeaders,
	validateRawMediaItemsForUser,
} from "./shared.js";

export async function handlePublish(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = parseBodyOrError(res, PublishPostSchema, req.body);
	if (!parsed) return;
	const {
		accountId,
		content,
		media: rawMedia,
		topics,
		linkUrl,
		locationId,
		quotePostId,
		gifAttachment,
		pollAttachment,
		isSpoiler,
		isGhostPost,
		textSpoilers,
		allowlistedCountryCodes,
		textAttachment,
		settings,
		platform,
		instagramAccountId,
		igMediaType,
		mediaType: mediaTypeAlias,
		altText,
		collaborators,
		isTrialReel,
		trialReels,
		instagramTrialReels,
		instagram_trial_reels,
		coverUrl,
		shareToFeed,
		userTags,
		crossPostGroupId,
		crossreshareToIg,
		crossreshareToIgDarkMode,
		mediaIds,
		topicTag,
		thumbOffset,
		reelCover,
		audioName,
		igAudioId,
		productTags,
		brandedContentSponsorIds,
		isPaidPartnership,
		commentEnabled,
		graduation,
		firstComment,
		// biome-ignore lint/suspicious/noExplicitAny: Zod inferred union is too wide for destructuring
	} = parsed as any;

	// Resolve aliases (MCP sends mediaType/trialReels, frontend sends igMediaType/isTrialReel)
	const resolvedMediaTypeParam = igMediaType || mediaTypeAlias;
	const resolvedTrialReel =
		isTrialReel || trialReels || instagramTrialReels || instagram_trial_reels;
	const resolvedThumbOffset = thumbOffset ?? reelCover;
	const resolvedTrialGraduation =
		graduation === "SS_PERFORMANCE"
			? "SS_PERFORMANCE"
			: graduation === "MANUAL"
				? "MANUAL"
				: undefined;

	// Resolve mediaIds from media library to actual URLs (for MCP/agent callers)
	let media = rawMedia;
	if (!media?.length && mediaIds?.length) {
		const { items } = await resolveMediaUrls(mediaIds, userId);
		if (items.length > 0) media = items;
	}
	if (rawMedia?.length) {
		const mediaValidationError = await validateRawMediaItemsForUser(
			userId,
			rawMedia,
		);
		if (mediaValidationError) {
			return apiError(res, 400, mediaValidationError, {
				code: "INVALID_MEDIA_URL",
			});
		}
	}

	// Log advanced features being used
	logger.info("Publish request received", {
		platform,
		pollAttachment: pollAttachment ? JSON.stringify(pollAttachment) : "none",
		isSpoiler,
		textSpoilersCount: textSpoilers?.length || 0,
		allowlistedCountryCodesCount: allowlistedCountryCodes?.length || 0,
		mediaCount: media?.length || 0,
		mediaIdsResolved: !!mediaIds?.length,
	});

	const hasMedia = (media?.length ?? 0) > 0;
	if (!content?.trim() && !(platform === "instagram" && hasMedia)) {
		return apiError(
			res,
			400,
			platform === "instagram"
				? "Instagram posts need media or a caption"
				: "content is required",
		);
	}

	// Platform-specific length limit. Threads enforces UTF-8 byte length in
	// practice, so emoji and multibyte text must be measured before Meta calls.
	const contentLength =
		platform === "instagram"
			? content.length
			: Buffer.byteLength(content, "utf8");
	const charLimit = platform === "instagram" ? 2200 : 500;
	if (contentLength > charLimit) {
		return apiError(res, 400, `Content exceeds ${charLimit} character limit`);
	}

	// ============================================================================
	// Subscription + daily cap + account limit checks (parallelized)
	// ============================================================================
	const capAccountId =
		platform === "instagram" ? instagramAccountId : accountId;

	const [tierCheck, capResult, profileResult] = await Promise.all([
		// 1. Subscription tier daily post limit
		checkSubscriptionPostLimit(userId, {
			mode: "publish",
			additionalCount: 1,
		}),
		// 2. Daily publish cap per account (agent safety: 8 posts/day/account)
		capAccountId && capAccountId !== "ALL"
			? import("../../dailyCap.js").then(({ checkDailyCap }) =>
					checkDailyCap(
						capAccountId,
						platform === "instagram" ? "instagram" : "threads",
					),
				)
			: Promise.resolve({ allowed: true, used: 0, limit: 8 }),
		// 3. Profile for account limit check
		db()
			.from("profiles")
			.select("subscription_tier, extra_accounts")
			.eq("id", userId)
			.maybeSingle() as unknown as Promise<{
			data: ProfileRow | null;
			error: unknown;
		}>,
	]);

	if (!tierCheck.allowed) {
		logger.info("Daily post limit reached", {
			userId,
			tier: tierCheck.tier,
			used: tierCheck.used,
			limit: tierCheck.limit,
		});
		return apiError(
			res,
			403,
			"Daily post limit reached for your plan. Upgrade to post more.",
		);
	}

	if (!capResult.allowed) {
		return apiError(
			res,
			429,
			`Daily publish cap reached for this account (${capResult.used}/${capResult.limit} today). Try again tomorrow.`,
			{ code: "DAILY_CAP_EXCEEDED" },
		);
	}

	// Account limit enforcement (only if not unlimited tier)
	{
		const profile = profileResult.data;
		const userTier = (profile?.subscription_tier || "free").toLowerCase();
		const extraAccounts = profile?.extra_accounts || 0;

		const { getAccountLimit } = await import("../../billing.js");
		const maxAccounts = getAccountLimit(userTier, extraAccounts);

		if (maxAccounts !== Infinity) {
			const [{ data: activeThreads }, { data: activeIG }] = await Promise.all([
				db()
					.from("accounts")
					.select("id, created_at")
					.eq("user_id", userId)
					.eq("is_active", true),
				db()
					.from("instagram_accounts")
					.select("id, created_at")
					.eq("user_id", userId)
					.eq("is_active", true),
			]);
			const combinedAccounts = [
				...((activeThreads || []) as Array<{
					id: string;
					created_at?: string | null;
				}>),
				...((activeIG || []) as Array<{
					id: string;
					created_at?: string | null;
				}>),
			].sort((a, b) =>
				String(a.created_at || "").localeCompare(String(b.created_at || "")),
			);
			const totalActive = combinedAccounts.length;

			if (totalActive > maxAccounts) {
				const targetId =
					platform === "instagram" ? instagramAccountId : accountId;

				if (targetId) {
					const allowedIds = new Set(
						combinedAccounts
							.slice(0, maxAccounts)
							.map((a: AccountIdRow) => a.id),
					);

					if (!allowedIds.has(targetId)) {
						const tierName =
							userTier.charAt(0).toUpperCase() + userTier.slice(1);
						logger.info("Account limit exceeded for publish", {
							userId,
							tier: userTier,
							targetId,
							totalActive,
							maxAccounts,
						});
						return apiError(
							res,
							403,
							`Your ${tierName} plan allows ${maxAccounts} account(s). This account exceeds your limit. Please upgrade to publish to more accounts.`,
							{ code: "ACCOUNT_LIMIT_EXCEEDED" },
						);
					}
				}
			}
		}
	}

	// ============================================================================
	// Instagram publish path
	// ============================================================================
	if (platform === "instagram") {
		if (!instagramAccountId) {
			return apiError(
				res,
				400,
				"instagramAccountId is required for Instagram posts",
			);
		}

		const { data: igAccount, error: igError } = (await db()
			.from("instagram_accounts")
			.select(
				"id, user_id, instagram_user_id, username, instagram_access_token_encrypted, facebook_page_access_token_encrypted, login_type, is_active, needs_reauth, status, token_expires_at",
			)
			.eq("id", instagramAccountId)
			.eq("user_id", userId)
			.maybeSingle()) as { data: IgAccountRow | null; error: unknown };

		if (igError || !igAccount) {
			return apiError(res, 404, "Instagram account not found");
		}

		if (!igAccount.instagram_access_token_encrypted) {
			return apiError(res, 400, "Instagram account not properly connected");
		}

		const igAccountStatus = igAccount as IgAccountRow & {
			is_active?: boolean | null;
			needs_reauth?: boolean | null;
			status?: string | null;
			token_expires_at?: string | null;
		};
		const preflight = await runPublishPreflight(
			{
				...parsed,
				platform: "instagram",
				media,
				igMediaType: resolvedMediaTypeParam,
				isTrialReel: resolvedTrialReel,
				trialReels: resolvedTrialReel,
				instagramTrialReels,
				instagram_trial_reels,
				trialGraduationStrategy: resolvedTrialGraduation,
			},
			{
				account: {
					found: true,
					isActive: igAccountStatus.is_active,
					needsReauth: igAccountStatus.needs_reauth,
					status: igAccountStatus.status,
					tokenExpiresAt: igAccountStatus.token_expires_at,
					hasAccessToken: !!igAccount.instagram_access_token_encrypted,
					hasPlatformUserId: !!igAccount.instagram_user_id,
					loginType: igAccount.login_type,
					followerCount: igAccount.follower_count,
				},
				checkMediaUrls: true,
			},
		);
		if (!preflight.ok) {
			return apiError(res, 422, "Publish preflight failed", {
				code: "PUBLISH_PREFLIGHT_FAILED",
				extra: { preflight },
			});
		}

		let instagramPublishingQuota:
			| { usage: number; limit: number; remaining: number; windowHours: number }
			| undefined;
		if (igAccount.login_type === "facebook") {
			const { checkPublishingLimit } = await import("../../instagramApi.js");
			const quotaResult = await checkPublishingLimit(
				igAccount.instagram_access_token_encrypted,
				igAccount.instagram_user_id,
				igAccount.login_type,
			);
			if (quotaResult.success && quotaResult.quota) {
				instagramPublishingQuota = quotaResult.quota;
				if (instagramPublishingQuota.remaining <= 0) {
					return apiError(
						res,
						429,
						"Instagram publishing cap reached. Facebook Login accounts can publish 50 posts in a rolling 24-hour window.",
						{
							code: "INSTAGRAM_PUBLISHING_CAP_REACHED",
							extra: { publishingQuota: instagramPublishingQuota },
						},
					);
				}
			} else {
				logger.warn("IG publishing quota unavailable before publish", {
					accountId: instagramAccountId,
					error: quotaResult.error,
				});
			}
		}

		// Check rate limit before publishing (fail-closed: block on error)
		try {
			const { data: rateLimit, error: rlError } = await db().rpc(
				"check_publish_rate_limit",
				{
					p_account_id: instagramAccountId,
					p_platform: "instagram",
				},
			);
			if (rlError || !rateLimit || rateLimit.length === 0) {
				logger.error(
					"IG rate limit check failed (fail-closed, blocking publish)",
					{ error: String(rlError) },
				);
				return apiError(
					res,
					503,
					"Rate limit service unavailable. Please try again shortly.",
				);
			} else {
				if (!rateLimit[0]!.allowed) {
					setRateLimitHeaders(
						res,
						rateLimit[0]!.daily_limit,
						rateLimit[0]!.daily_used,
					);
					return apiError(res, 429, "Rate limit exceeded");
				}
				// Set rate limit headers on successful check (so frontend sees remaining quota)
				setRateLimitHeaders(
					res,
					rateLimit[0]!.daily_limit,
					rateLimit[0]!.daily_used,
				);
			}
		} catch (rlErr) {
			logger.error(
				"IG rate limit check exception (fail-closed, blocking publish)",
				{ error: String(rlErr) },
			);
			return apiError(
				res,
				503,
				"Rate limit service unavailable. Please try again shortly.",
			);
		}

		// Sanitize content before DB insert (XSS prevention)
		const cleanContent = sanitizeHtml(content);

		// Determine IG media type
		const resolvedIgMediaType =
			normalizeIGMediaType(resolvedMediaTypeParam) ||
			(media?.length > 1
				? "CAROUSEL"
				: media?.length === 1
					? media[0].type === "video"
						? "REELS"
						: "IMAGE"
					: "IMAGE");
		const normalizedPostMediaType = normalizePostMediaType(
			resolvedIgMediaType,
			"image",
		);

		// Extract hashtags from content for performance tracking
		const extractedHashtags = extractHashtags(content);

		// Build IG metadata for features without dedicated columns
		const igMetadata: Record<string, unknown> = {
			...(collaborators?.length > 0 ? { collaborators } : {}),
			...(coverUrl ? { coverUrl } : {}),
			...(shareToFeed !== undefined ? { shareToFeed } : {}),
			...(userTags?.length > 0 ? { userTags } : {}),
			...(resolvedTrialReel && (instagramTrialReels || instagram_trial_reels)
				? { trialReels: true, instagramTrialReels: true, instagram_trial_reels: true }
				: {}),
			...(resolvedTrialReel && resolvedTrialGraduation
				? { trialGraduationStrategy: resolvedTrialGraduation }
				: {}),
			...(resolvedThumbOffset !== undefined
				? { thumbOffset: resolvedThumbOffset }
				: {}),
			...(audioName ? { audioName } : {}),
			...(igAudioId ? { igAudioId } : {}),
			...(productTags?.length > 0 ? { productTags } : {}),
			...(brandedContentSponsorIds?.length > 0
				? { brandedContentSponsorIds }
				: {}),
			...(isPaidPartnership ? { isPaidPartnership: true } : {}),
			...(commentEnabled !== undefined ? { commentEnabled } : {}),
			...(firstComment ? { firstComment } : {}),
		};

		// Create post record
		const { data: post, error: postError } = (await db()
			.from("posts")
			.insert({
				user_id: userId,
				account_id: null,
				instagram_account_id: instagramAccountId,
				content: cleanContent,
				media_urls: media?.map((m: { url: string }) => m.url) || [],
				media_type: normalizedPostMediaType,
				platform: "instagram",
				ig_media_type: resolvedIgMediaType,
				alt_text: altText || null,
				location_id: locationId || null,
				hashtags: extractedHashtags,
				cross_post_group_id: crossPostGroupId || null,
				status: "publishing",
				...(Object.keys(igMetadata).length > 0 ? { metadata: igMetadata } : {}),
				// biome-ignore lint/suspicious/noExplicitAny: Supabase insert type workaround for extra columns
			} as any)
			.select()
			.maybeSingle()) as {
			data: { id: string } | null;
			error: {
				code?: string | undefined;
				hint?: string | undefined;
				message?: string | undefined;
			} | null;
		};

		if (postError || !post) {
			logger.error("Post insert error", {
				error: String(postError),
				code: postError?.code,
				hint: postError?.hint,
			});
			return apiError(res, 500, "Failed to create post record", {
				details: postError?.message || "Unknown error",
			});
		}

		const { orchestrateIGPublish } = await import(
			"../../instagram/orchestrate.js"
		);

		const trialIntent = resolveInstagramTrialReelIntent({
			metadata: Object.keys(igMetadata).length > 0 ? igMetadata : undefined,
			instagramTrialReels,
			instagram_trial_reels,
			trialGraduationStrategy: resolvedTrialGraduation,
		});
		const igPostData = {
			caption: cleanContent,
			mediaType:
				resolvedIgMediaType as import("../../instagramApi.js").IGMediaType,
			imageUrl: media?.[0]?.type === "image" ? media[0].url : undefined,
			videoUrl: media?.[0]?.type === "video" ? media[0].url : undefined,
			altText: altText || undefined,
			locationId: locationId || undefined,
			collaborators: collaborators || undefined,
			trialReels:
				trialIntent.enabled && resolvedIgMediaType === "REELS" ? true : undefined,
			trialGraduationStrategy:
				trialIntent.enabled && resolvedIgMediaType === "REELS"
					? trialIntent.strategy
					: undefined,
			coverUrl: coverUrl || undefined,
			shareToFeed: shareToFeed !== undefined ? shareToFeed : undefined,
			userTags: userTags || undefined,
			thumbOffset: resolvedThumbOffset || undefined,
			audioName: audioName || undefined,
			igAudioId: igAudioId || undefined,
			productTags: productTags || undefined,
			brandedContentSponsorIds: brandedContentSponsorIds || undefined,
			isPaidPartnership: isPaidPartnership || undefined,
			commentEnabled: commentEnabled !== undefined ? commentEnabled : undefined,
			firstComment: firstComment || undefined,
			children:
				resolvedIgMediaType === "CAROUSEL" && media
					? media.map(
							(m: {
								type: string;
								url: string;
								altText?: string | undefined;
							}) => ({
								type: m.type as "image" | "video",
								url: m.url,
								altText: m.altText,
							}),
						)
					: undefined,
		};

		const result = await orchestrateIGPublish({
			encryptedToken: igAccount.instagram_access_token_encrypted,
			igUserId: igAccount.instagram_user_id,
			postData: igPostData,
			encryptedFbPageToken:
				igAccount.facebook_page_access_token_encrypted || undefined,
			mediaCheck: true,
			postPublish: {
				engagementSync: {
					postId: post.id,
					accountId: igAccount.id,
					userId,
					source: "immediate",
				},
			},
		});

		if (result.success && result.mediaId) {
			// Update DB status immediately (metrics fetched async below)
			await db()
				.from("posts")
				.update({
					status: "published",
					scheduled_for: null,
					instagram_post_id: result.mediaId,
					permalink: result.permalink || null,
					published_at: new Date().toISOString(),
					updated_at: new Date().toISOString(),
					// biome-ignore lint/suspicious/noExplicitAny: Supabase update payload type mismatch
				} as any)
				.eq("id", post.id);

			// Dispatch outgoing webhook (fire-and-forget)
			dispatchWebhook(userId, "post.published", {
				postId: post.id,
				content: cleanContent,
				platform: "instagram",
			});

			// Fetch initial IG metadata async (fire-and-forget — avoids blocking response by ~1-2s)
			const capturedIgMediaId = result.mediaId;
			import("../../instagramApi.js")
				.then(
					async ({ getInstagramMediaAudioType, getInstagramPostMetrics }) => {
						const [metricsSettled, audioTypeSettled] = await Promise.allSettled(
							[
								getInstagramPostMetrics(
									igAccount.instagram_access_token_encrypted,
									capturedIgMediaId,
									igAccount.login_type || "instagram",
									resolvedIgMediaType,
								),
								getInstagramMediaAudioType(
									igAccount.instagram_access_token_encrypted,
									capturedIgMediaId,
									igAccount.login_type || "instagram",
								),
							],
						);
						const updatePayload: Record<string, unknown> = {};
						const metricsResult =
							metricsSettled.status === "fulfilled"
								? metricsSettled.value
								: null;
						const audioTypeResult =
							audioTypeSettled.status === "fulfilled"
								? audioTypeSettled.value
								: null;

						if (metricsSettled.status === "rejected") {
							logger.warn("Async IG metrics fetch failed", {
								error: String(metricsSettled.reason),
							});
						}
						if (audioTypeSettled.status === "rejected") {
							logger.warn("Async IG media audio type fetch failed", {
								error: String(audioTypeSettled.reason),
							});
						}

						if (audioTypeResult?.success && audioTypeResult.mediaAudioType) {
							updatePayload.media_audio_type = audioTypeResult.mediaAudioType;
						}

						if (metricsResult?.success && metricsResult.metrics) {
							const m = metricsResult.metrics;
							const totalLikes = m.total_likes || m.likes || 0;
							const totalComments = m.total_comments || m.comments || 0;
							const totalViews = m.total_views || m.views || m.impressions || 0;
							Object.assign(updatePayload, {
								ig_impressions: totalViews || m.impressions || 0,
								ig_reach: m.reach || 0,
								ig_saved: m.saved || 0,
								ig_shares: m.shares || 0,
								ig_reposts: m.reposts || 0,
								likes_count: totalLikes,
								replies_count: totalComments,
								views_count: totalViews,
								ig_views: totalViews,
								ig_plays: m.plays || 0,
								ig_video_views: m.video_views || 0,
								ig_replays: 0,
								ig_skip_rate: m.reels_skip_rate || 0,
								engagement_rate: m.engagementRate || 0,
							});
						}

						if (Object.keys(updatePayload).length === 0) return;
						await db()
							.from("posts")
							// biome-ignore lint/suspicious/noExplicitAny: Supabase update payload type mismatch
							.update(updatePayload as any)
							.eq("id", post.id);
					},
				)
				.catch((metadataErr: unknown) =>
					logger.warn("Async IG metadata refresh failed", {
						error: String(metadataErr),
					}),
				);

			return apiSuccess(res, {
				postId: post.id,
				mediaId: result.mediaId,
				permalink: result.permalink || null,
				platform: "instagram",
				...(instagramPublishingQuota
					? { publishingQuota: instagramPublishingQuota }
					: {}),
			});
		}

		if (result.containerId) {
			await db()
				.from("posts")
				.update({
					status: "publishing",
					ig_container_id: result.containerId,
					ig_container_created_at: new Date().toISOString(),
					ig_container_status: "IN_PROGRESS",
					ig_publish_attempts: 1,
					updated_at: new Date().toISOString(),
					// biome-ignore lint/suspicious/noExplicitAny: Supabase update payload type mismatch
				} as any)
				.eq("id", post.id);

			return apiSuccess(res, {
				postId: post.id,
				containerId: result.containerId,
				status: "processing",
				platform: "instagram",
				...(instagramPublishingQuota
					? { publishingQuota: instagramPublishingQuota }
					: {}),
			});
		}

		await db()
			.from("posts")
			.update({
				status: "failed",
				error_message: result.error ?? null,
				updated_at: new Date().toISOString(),
			})
			.eq("id", post.id);

		return apiError(res, 500, result.error || "Failed to publish to Instagram");
	}

	// ============================================================================
	// Threads publish path (existing behavior)
	// ============================================================================
	if (!accountId) return apiError(res, 400, "accountId is required");

	const { data: account, error: accountError } = (await db()
		.from("accounts")
		.select(
			"id, user_id, threads_user_id, username, threads_access_token_encrypted, is_active, needs_reauth, status, token_expires_at",
		)
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as { data: AccountRow | null; error: unknown };

	if (accountError || !account) {
		logger.error("Account lookup failed", {
			accountId,
			userId,
			accountError: JSON.stringify(accountError),
		});
		return apiError(res, 404, "Account not found");
	}

	if (!account.threads_access_token_encrypted || !account.threads_user_id) {
		return apiError(res, 400, "Account is not connected to Threads");
	}

	const threadsAccountStatus = account as AccountRow & {
		is_active?: boolean | null;
		needs_reauth?: boolean | null;
		status?: string | null;
		token_expires_at?: string | null;
	};
	const preflight = await runPublishPreflight(
		{
			...parsed,
			platform: "threads",
			media,
			isTrialReel: resolvedTrialReel,
		},
		{
			account: {
				found: true,
				isActive: threadsAccountStatus.is_active,
				needsReauth: threadsAccountStatus.needs_reauth,
				status: threadsAccountStatus.status,
				tokenExpiresAt: threadsAccountStatus.token_expires_at,
				hasAccessToken: !!account.threads_access_token_encrypted,
				hasPlatformUserId: !!account.threads_user_id,
			},
			checkMediaUrls: true,
		},
	);
	if (!preflight.ok) {
		return apiError(res, 422, "Publish preflight failed", {
			code: "PUBLISH_PREFLIGHT_FAILED",
			extra: { preflight },
		});
	}

	// Check rate limit before publishing (fail-closed: block on error)
	try {
		const { data: rateLimit, error: rlError } = await db().rpc(
			"check_publish_rate_limit",
			{
				p_account_id: accountId,
				p_platform: "threads",
			},
		);
		if (rlError || !rateLimit || rateLimit.length === 0) {
			logger.error(
				"Threads rate limit check failed (fail-closed, blocking publish)",
				{ error: String(rlError) },
			);
			return apiError(
				res,
				503,
				"Rate limit service unavailable. Please try again shortly.",
			);
		} else {
			if (!rateLimit[0]!.allowed) {
				setRateLimitHeaders(
					res,
					rateLimit[0]!.daily_limit,
					rateLimit[0]!.daily_used,
				);
				return apiError(res, 429, "Rate limit exceeded");
			}
			// Set rate limit headers on successful check (so frontend sees remaining quota)
			setRateLimitHeaders(
				res,
				rateLimit[0]!.daily_limit,
				rateLimit[0]!.daily_used,
			);
		}
	} catch (rlErr) {
		logger.error(
			"Threads rate limit check exception (fail-closed, blocking publish)",
			{ error: String(rlErr) },
		);
		return apiError(
			res,
			503,
			"Rate limit service unavailable. Please try again shortly.",
		);
	}

	// Sanitize content before DB insert (XSS prevention)
	const cleanThreadsContent = sanitizeHtml(content);

	// Determine media type for the post
	const mediaType = media?.length
		? media.length > 1
			? "CAROUSEL"
			: media[0].type === "image"
				? "IMAGE"
				: "VIDEO"
		: "TEXT";
	const normalizedPostMediaType = normalizePostMediaType(mediaType);

	// Extract hashtags from content and merge with topics
	const contentHashtags = extractHashtags(content);
	const topicHashtags = (topics || []).map((t: string) =>
		t.toLowerCase().replace(/^#/, ""),
	);
	const allHashtags = [...new Set([...contentHashtags, ...topicHashtags])];

	const { data: post, error: postError } = (await db()
		.from("posts")
		.insert({
			user_id: userId,
			account_id: accountId,
			content: cleanThreadsContent,
			media_urls: media?.map((m: { url: string }) => m.url) || [],
			media_type: normalizedPostMediaType,
			hashtags: allHashtags,
			location_id: locationId || null,
			quoted_post_id: quotePostId || null,
			is_quote: !!quotePostId,
			is_carousel: media && media.length > 1,
			platform: "threads",
			cross_post_group_id: crossPostGroupId || null,
			status: "publishing",
			// biome-ignore lint/suspicious/noExplicitAny: Supabase insert type workaround for extra columns
		} as any)
		.select()
		.maybeSingle()) as {
		data: { id: string } | null;
		error: {
			code?: string | undefined;
			hint?: string | undefined;
			message?: string | undefined;
		} | null;
	};

	if (postError || !post) {
		logger.error("Threads post insert error", {
			error: String(postError),
			code: postError?.code,
			hint: postError?.hint,
		});
		return apiError(res, 500, "Failed to create post record", {
			details: postError?.message || "Unknown error",
		});
	}

	// Text spoilers: only from request body (manually set). No auto-detect.
	const resolvedTextSpoilers = textSpoilers;

	const postData: PostData = {
		content: cleanThreadsContent,
		media: media || [],
		topics: topics || [],
		topicTag: topicTag || undefined,
		linkUrl,
		locationId,
		quotePostId,
		gifAttachment: gifAttachment || undefined,
		pollAttachment,
		isSpoiler,
		isGhostPost: isGhostPost || false,
		crossreshareToIg: crossreshareToIg || undefined,
		crossreshareToIgDarkMode: crossreshareToIgDarkMode || undefined,
		textSpoilers: resolvedTextSpoilers,
		allowlistedCountryCodes,
		textAttachment,
		// biome-ignore lint/suspicious/noExplicitAny: Zod inferred union is too wide for destructuring
		replyApprovalMode: (parsed as any).replyApprovalMode || undefined,
		settings: settings || { allowReplies: true, whoCanReply: "everyone" },
	};

	const result = await postToThreads(
		account.threads_access_token_encrypted,
		account.threads_user_id,
		postData,
	);

	logger.info("postToThreads result", {
		success: result.success,
		threadId: result.threadId,
		error: result.error,
	});

	if (result.success && result.threadId) {
		logger.info("Updating post to published status", { postId: post.id });
		const threadsUpdatePayload: Record<string, unknown> = {
			status: "published",
			scheduled_for: null,
			threads_post_id: result.threadId,
			permalink: null,
			published_at: new Date().toISOString(),
			updated_at: new Date().toISOString(),
		};
		const { error: updateError } = await db()
			.from("posts")
			// biome-ignore lint/suspicious/noExplicitAny: Supabase update payload type mismatch
			.update(threadsUpdatePayload as any)
			.eq("id", post.id);

		if (updateError) {
			logger.error("Failed to update post status", {
				error: String(updateError),
			});
		}

		// Dispatch outgoing webhook (fire-and-forget)
		dispatchWebhook(userId, "post.published", {
			postId: post.id,
			content: cleanThreadsContent,
			platform: "threads",
		});

		// Fetch permalink and update DB (fire-and-forget — avoids blocking response by ~1-2s)
		const capturedThreadId = result.threadId;
		Promise.resolve()
			.then(async () => {
				const token = decrypt(account.threads_access_token_encrypted);
				const postInfoUrl = `https://graph.threads.net/v1.0/${capturedThreadId}?fields=id,permalink`;
				const postInfoResponse = await withRetry(
					() =>
						fetch(postInfoUrl, {
							headers: { Authorization: `Bearer ${token}` },
							signal: AbortSignal.timeout(10000),
						}),
					{ label: `manualPostPermalink:${capturedThreadId}` },
				);
				const postInfoData = await postInfoResponse.json();
				if (postInfoData.permalink) {
					await db()
						.from("posts")
						.update({
							permalink: postInfoData.permalink,
							updated_at: new Date().toISOString(),
						})
						.eq("id", post.id);
				}
			})
			.catch((e: unknown) =>
				logger.warn("Async permalink fetch failed", { error: String(e) }),
			);

		// Schedule engagement syncs at 1h, 6h, 24h (fire-and-forget)
		import("../../qstashSchedule.js").then(({ schedulePostPublishSyncs }) =>
			schedulePostPublishSyncs(
				post.id,
				account.id,
				userId,
				"threads",
				"immediate",
			),
		);

		// Best-effort: give manual Threads publishes the same precise +15min reply-harvest
		// workflow as autoposted content when the account belongs to an enabled auto-reply group.
		Promise.resolve()
			.then(async () => {
				const { data: group } = await db()
					.from("account_groups")
					.select("id")
					.eq("user_id", userId)
					.contains("account_ids", [account.id])
					.maybeSingle();
				if (!group?.id) return;

				const { data: groupConfig } = await db()
					.from("auto_post_group_config")
					.select("workspace_id, enable_auto_reply")
					.eq("group_id", group.id)
					.maybeSingle();
				if (!groupConfig?.workspace_id || !groupConfig.enable_auto_reply)
					return;

				const { dispatchReplyHarvest } = await import(
					"../../qstashSchedule.js"
				);
				await dispatchReplyHarvest({
					queueItemId: post.id,
					workspaceId: groupConfig.workspace_id,
					groupId: group.id,
					ownerId: userId,
					accountId: account.id,
					postId: post.id,
					sourceTable: "posts",
				});
			})
			.catch((e: unknown) =>
				logger.warn("Manual Threads reply-harvest scheduling failed", {
					postId: post.id,
					error: String(e),
				}),
			);

		return apiSuccess(res, {
			postId: post.id,
			threadId: result.threadId,
			permalink: null,
			...(result.crossreshareToIgStatus
				? { crossreshareToIgStatus: result.crossreshareToIgStatus }
				: {}),
		});
	} else {
		logger.info("Post failed, updating to failed status");
		await db()
			.from("posts")
			.update({
				status: "failed",
				error_message: result.error ?? null,
				updated_at: new Date().toISOString(),
			})
			.eq("id", post.id);

		return apiError(res, 500, result.error || "Failed to publish post");
	}
}
