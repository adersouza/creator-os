/**
 * Threads API Posting Service for Vercel API Routes
 *
 * Handles all posting to Threads via the official Graph API
 * Ported from Firebase Cloud Functions
 */

import { decrypt } from "./encryption.js";
import { logger } from "./logger.js";
import { classifyMetaError } from "./metaErrors.js";
import { calculateEngagementRate } from "./metricCalculators.js";
import { withRetry } from "./retryUtils.js";

const THREADS_CAROUSEL_MAX_ITEMS = 20;
const THREADS_POST_INSIGHT_METRICS =
	"views,likes,replies,reposts,quotes,shares";
const THREADS_REPLY_FIELDS =
	"id,text,username,timestamp,media_product_type,media_type,media_url,permalink,profile_picture_url,is_reply,is_reply_owned_by_me,replied_to,root_post,has_replies,hide_status,reply_audience,shortcode,thumbnail_url,children,topic_tag";

interface PollAttachment {
	options?: string[] | undefined;
	option_a?: string | undefined;
	option_b?: string | undefined;
	option_c?: string | undefined;
	option_d?: string | undefined;
}

interface SpoilerEntity {
	entity_type: "SPOILER";
	offset: number;
	length: number;
}

interface TextStylingInfo {
	offset: number;
	length: number;
	styling_info: (
		| "bold"
		| "italic"
		| "highlight"
		| "underline"
		| "strikethrough"
	)[];
}

interface TextAttachment {
	plaintext: string;
	link_attachment_url?: string | undefined;
	text_with_styling_info?: TextStylingInfo[] | undefined;
}

export interface PostData {
	content: string;
	media?:
		| {
				type: "image" | "video";
				url: string;
				duration?: number | undefined;
				altText?: string | undefined;
		  }[]
		| undefined;
	topics?: string[] | undefined;
	topicTag?: string | undefined;
	linkUrl?: string | undefined;
	locationId?: string | undefined;
	quotePostId?: string | undefined;
	gifAttachment?: { gifId: string; provider: string } | undefined;
	pollAttachment?: PollAttachment | undefined;
	isSpoiler?: boolean | undefined;
	textSpoilers?: SpoilerEntity[] | undefined;
	allowlistedCountryCodes?: string[] | undefined;
	textAttachment?: TextAttachment | undefined;
	replyApprovalMode?: "manual_approval" | "none" | undefined;
	isGhostPost?: boolean | undefined;
	crossreshareToIg?: boolean | undefined;
	crossreshareToIgDarkMode?: boolean | undefined;
	replyToId?: string | undefined;
	settings: {
		allowReplies: boolean;
		whoCanReply:
			| "everyone"
			| "followers"
			| "mentioned"
			| "author_only"
			| "followers_only";
	};
}

interface RateLimitInfo {
	limit?: number | undefined;
	remaining?: number | undefined;
	reset?: number | undefined;
	usagePercent?: number | undefined;
}

export interface PostingResult {
	success: boolean;
	threadId?: string | undefined;
	error?: string | undefined;
	crossreshareToIgStatus?: "SUCCESS" | "FAILED" | undefined;
	timestamp: Date;
	rateLimit?: RateLimitInfo | undefined;
	/**
	 * Whether the failure is safe to retry. Set by container-creation and
	 * publish-step failure paths via classifyMetaError. Callers (publish
	 * worker, queue, manual publish) can use this to drive dead-letter vs
	 * requeue decisions instead of treating every Meta error as permanent.
	 * Undefined on success.
	 */
	retryable?: boolean | undefined;
}

/**
 * Parse rate limit headers from API response
 */
function parseRateLimitHeaders(response: Response): RateLimitInfo | undefined {
	const rateLimitInfo: RateLimitInfo = {};
	let hasAnyData = false;

	const limit = response.headers.get("X-RateLimit-Limit");
	const remaining = response.headers.get("X-RateLimit-Remaining");
	const reset = response.headers.get("X-RateLimit-Reset");

	if (limit) {
		rateLimitInfo.limit = parseInt(limit, 10);
		hasAnyData = true;
	}
	if (remaining) {
		rateLimitInfo.remaining = parseInt(remaining, 10);
		hasAnyData = true;
	}
	if (reset) {
		rateLimitInfo.reset = parseInt(reset, 10);
		hasAnyData = true;
	}

	const appUsage = response.headers.get("X-App-Usage");
	if (appUsage) {
		try {
			const usage = JSON.parse(appUsage);
			if (usage.call_count !== undefined) {
				rateLimitInfo.usagePercent = usage.call_count;
				hasAnyData = true;
			}
		} catch (err) {
			logger.debug(
				"Failed to parse X-App-Usage header from Threads API response",
				{ error: String(err) },
			);
			// Ignore parse errors
		}
	}

	return hasAnyData ? rateLimitInfo : undefined;
}

async function recordThreadsUsage(
	response: Response,
	endpointFamily: string,
	accountId?: string | undefined,
) {
	const hasUsage =
		response.headers.has("X-App-Usage") ||
		response.headers.has("X-Business-Use-Case-Usage") ||
		response.headers.has("Retry-After");
	if (!hasUsage) return;
	const { getPrivilegedSupabaseAny, PRIVILEGED_DB_REASONS } = await import(
		"./privilegedDb.js"
	);
	const { recordMetaApiUsageSnapshot } = await import("./reliability.js");
	await recordMetaApiUsageSnapshot(
		getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.metaUsageTelemetry),
		{
		userId: null,
		accountId: accountId ?? null,
		platform: "threads",
		endpointFamily,
		response,
		requestId:
			response.headers.get("x-fb-trace-id") ??
			response.headers.get("x-request-id"),
		},
	);
}

/**
 * Post to Threads using official API
 */
export async function postToThreads(
	encryptedAccessToken: string,
	threadsUserId: string,
	postData: PostData,
): Promise<PostingResult> {
	let creationId: string | undefined;
	let token: string | undefined;
	try {
		token = decrypt(encryptedAccessToken);

		// Prepare content with hashtags from topics
		let finalContent = postData.content || "";

		if (postData.topics && postData.topics.length > 0) {
			const hashtags = postData.topics
				.map((topic) => {
					const originalTopic = topic.trim();
					if (!originalTopic) return null;

					const cleanTopic = originalTopic
						.replace(/\s+/g, "")
						.replace(/[^a-zA-Z0-9_]/g, "");
					if (!cleanTopic) return null;

					const hashtagWithHash = `#${cleanTopic}`;
					const contentLower = finalContent.toLowerCase();
					const hashtagLower = hashtagWithHash.toLowerCase();

					if (contentLower.includes(hashtagLower)) {
						return null;
					}

					return hashtagWithHash;
				})
				.filter(Boolean);

			if (hashtags.length > 0) {
				finalContent = `${finalContent}\n\n${hashtags.join(" ")}`.trim();
			}
		}

		// Validate max 5 links per post (Threads policy effective Dec 22, 2025)
		if (finalContent) {
			const urlRegex = /https?:\/\/[^\s)}\]>]+/gi;
			const linkCount = (finalContent.match(urlRegex) || []).length;
			if (linkCount > 5) {
				return {
					success: false,
					error: "Threads posts can contain a maximum of 5 links.",
					timestamp: new Date(),
				};
			}
		}

		// Threads only supports JPEG and PNG images — reject WebP before API call
		if (postData.media && postData.media.length > 0) {
			for (const mediaItem of postData.media) {
				if (
					mediaItem.type === "image" &&
					mediaItem.url &&
					/\.webp(\?|$)/i.test(mediaItem.url)
				) {
					return {
						success: false,
						error:
							"Threads only supports JPEG and PNG images. WebP is not supported.",
						timestamp: new Date(),
					};
				}
			}
		}

		// #429: Validate video codec/container format — Meta APIs only support H.264 in MP4/MOV
		// This is a URL-based heuristic (we can't inspect the actual codec without downloading).
		if (postData.media && postData.media.length > 0) {
			const INCOMPATIBLE_VIDEO_PATTERN =
				/\.(webm|avi|mkv|wmv|flv|3gp|ts|m4v|ogv)(\?|$)/i;
			for (const mediaItem of postData.media) {
				if (
					mediaItem.type === "video" &&
					mediaItem.url &&
					INCOMPATIBLE_VIDEO_PATTERN.test(mediaItem.url)
				) {
					const ext =
						mediaItem.url
							.match(INCOMPATIBLE_VIDEO_PATTERN)?.[1]
							?.toUpperCase() || "unknown";
					return {
						success: false,
						error: `Unsupported video format (.${ext}). Threads requires H.264 video codec in MP4 or MOV containers. Please convert your video to .mp4 or .mov before uploading.`,
						timestamp: new Date(),
					};
				}
			}
		}

		logger.info("Creating Threads post container", {
			userId: threadsUserId,
			contentPreview: finalContent.substring(0, 50),
			mediaCount: postData.media?.length || 0,
		});

		// Token validity is verified by the container creation call itself.
		// No need for a separate verification call — saves an API call and rate limit quota.

		// Strip EXIF metadata from media before publishing (privacy: removes GPS, device info)
		if (postData.media && postData.media.length > 0) {
			const { stripExifFromStorageUrl } = await import("./exifStrip.js");
			await Promise.all(
				postData.media
					.filter((mediaItem) => mediaItem.type === "image")
					.map((mediaItem) => stripExifFromStorageUrl(mediaItem.url)),
			);
		}

		// Build container params
		let containerParams: URLSearchParams;
		const hasMedia = postData.media && postData.media.length > 0;

		if (hasMedia && postData.media && postData.media.length > 1) {
			// Carousel post (Threads API: 2-20 image/video items)
			if (postData.media.length > THREADS_CAROUSEL_MAX_ITEMS) {
				throw new Error(
					`Carousel posts support a maximum of ${THREADS_CAROUSEL_MAX_ITEMS} items`,
				);
			}
			logger.info("Creating carousel post", {
				itemCount: postData.media.length,
			});

			const mediaContainerIds = await Promise.all(
				postData.media.map(async (mediaItem) => {
					const isImage = mediaItem.type === "image";
					const mediaType = isImage ? "IMAGE" : "VIDEO";
					const mediaKey = isImage ? "image_url" : "video_url";

					const mediaParams = new URLSearchParams({
						media_type: mediaType,
						[mediaKey]: mediaItem.url,
						is_carousel_item: "true",
						...(mediaItem.type === "image" && mediaItem.altText
							? { alt_text: mediaItem.altText }
							: {}),
					});

					const mediaContainerResponse = await withRetry(
						() =>
							fetch(`https://graph.threads.net/v1.0/${threadsUserId}/threads`, {
								method: "POST",
								body: mediaParams,
								headers: { Authorization: `Bearer ${token}` },
								signal: AbortSignal.timeout(10000),
							}),
						{ label: "postToThreads:mediaContainer" },
					);

					const mediaContainerData = await mediaContainerResponse.json();

					if (!mediaContainerResponse.ok || mediaContainerData.error) {
						logger.error("Media container creation error", {
							error: String(mediaContainerData?.error?.message),
						});
						throw new Error(
							mediaContainerData.error?.message ||
								"Failed to create media container",
						);
					}

					// Poll each carousel item container until FINISHED before proceeding
					const itemId = mediaContainerData.id;
					const itemIsVideo = !isImage;
					const itemMaxAttempts = itemIsVideo ? 20 : 15;
					const itemDelayMs = itemIsVideo ? 3000 : 1000;

					for (
						let pollAttempt = 0;
						pollAttempt < itemMaxAttempts;
						pollAttempt++
					) {
						await new Promise((resolve) =>
							setTimeout(resolve, pollAttempt === 0 ? 500 : itemDelayMs),
						);
						try {
							const itemStatusRes = await withRetry(
								() =>
									fetch(
										`https://graph.threads.net/v1.0/${itemId}?fields=status,error_message`,
										{
											headers: { Authorization: `Bearer ${token}` },
											signal: AbortSignal.timeout(8000),
										},
									),
								{ label: `threadsCarouselItemStatus:${itemId}` },
							);
							const itemStatusData = await itemStatusRes.json();
							const itemStatus = itemStatusData.status;

							if (itemStatus === "FINISHED" || itemStatus === "PUBLISHED")
								break;
							if (itemStatus === "ERROR") {
								throw new Error(
									`Carousel item processing failed: ${itemStatusData.error_message || "unknown error"}`,
								);
							}
							if (itemStatus === "EXPIRED") {
								throw new Error("Carousel item container expired");
							}
							logger.info("Carousel item still processing", {
								itemId,
								status: itemStatus,
								attempt: pollAttempt,
								isVideo: itemIsVideo,
							});
						} catch (pollErr) {
							// If it's our own thrown error, rethrow
							if (
								pollErr instanceof Error &&
								(pollErr.message.includes("Carousel item processing failed") ||
									pollErr.message.includes("Carousel item container expired"))
							) {
								throw pollErr;
							}
							// Status check network failure — proceed and hope for the best
							break;
						}
					}

					return itemId;
				}),
			);

			containerParams = new URLSearchParams({
				media_type: "CAROUSEL",
				children: mediaContainerIds.join(","),
				text: finalContent,
			});
		} else if (hasMedia) {
			// Single media post
			const firstMedia = postData.media?.[0];
			if (!firstMedia) throw new Error("Media array is empty");
			const isImage = firstMedia.type === "image";
			const mediaType = isImage ? "IMAGE" : "VIDEO";
			const mediaKey = isImage ? "image_url" : "video_url";

			// #480: Validate video duration for Threads (max 5 minutes / 300s)
			if (!isImage && firstMedia.duration && firstMedia.duration > 300) {
				return {
					success: false,
					error: `Video too long for Threads (${Math.round(firstMedia.duration)}s). Maximum is 5 minutes (300s).`,
					timestamp: new Date(),
				};
			}

			containerParams = new URLSearchParams({
				media_type: mediaType,
				[mediaKey]: firstMedia.url,
				text: finalContent,
				...(isImage && firstMedia.altText
					? { alt_text: firstMedia.altText }
					: {}),
			});
		} else {
			// Text-only post
			containerParams = new URLSearchParams({
				media_type: "TEXT",
				text: finalContent,
			});
		}

		// auto_publish DISABLED (2026-03-26) — all posts now use the standard
		// two-step container→publish flow. auto_publish was a likely trigger for
		// Threads ghost-deleting posts (single-call pattern looks automated).
		// All 2,575 ghosted posts since Mar 13 used auto_publish for text-only.

		// Add reply_to_id for thread chains
		if (postData.replyToId) {
			containerParams.append("reply_to_id", postData.replyToId);
		}

		// Add reply controls
		if (
			postData.settings.whoCanReply &&
			postData.settings.whoCanReply !== "everyone"
		) {
			const replyControlMap: Record<string, string> = {
				followers: "accounts_you_follow",
				mentioned: "mentioned_only",
				author_only: "parent_post_author_only",
				followers_only: "followers_only",
			};
			const replyControl = replyControlMap[postData.settings.whoCanReply];
			if (replyControl) {
				containerParams.append("reply_control", replyControl);
			}
		}

		// Add ghost post
		if (postData.isGhostPost) {
			containerParams.append("is_ghost_post", "true");
		}

		// Add reply approval mode (Meta API parameter: enable_reply_approvals)
		if (postData.replyApprovalMode === "manual_approval") {
			containerParams.append("enable_reply_approvals", "true");
		}

		// Add link attachment (only valid for TEXT posts per Threads API docs)
		if (postData.linkUrl?.trim() && !hasMedia) {
			containerParams.append("link_attachment", postData.linkUrl.trim());
		}

		// Add location
		if (postData.locationId?.trim()) {
			containerParams.append("location_id", postData.locationId.trim());
		}

		// Add quote post
		if (postData.quotePostId?.trim()) {
			containerParams.append("quote_post_id", postData.quotePostId.trim());
		}

		// Add poll attachment
		if (postData.pollAttachment && !hasMedia) {
			const poll =
				postData.pollAttachment.options &&
				postData.pollAttachment.options.length >= 2
					? {
							option_a: postData.pollAttachment.options[0],
							option_b: postData.pollAttachment.options[1],
							...(postData.pollAttachment.options[2]
								? { option_c: postData.pollAttachment.options[2] }
								: {}),
							...(postData.pollAttachment.options[3]
								? { option_d: postData.pollAttachment.options[3] }
								: {}),
						}
					: postData.pollAttachment;
			containerParams.append("poll_attachment", JSON.stringify(poll));
		}

		// Add text attachment for long-form
		if (postData.textAttachment && !hasMedia && !postData.pollAttachment) {
			containerParams.append(
				"text_attachment",
				JSON.stringify(postData.textAttachment),
			);
		}

		// Add spoiler flag
		if (postData.isSpoiler && hasMedia) {
			containerParams.append("is_spoiler_media", "true");
		}

		// Add text spoilers
		if (postData.textSpoilers && postData.textSpoilers.length > 0) {
			const validSpoilers = postData.textSpoilers.slice(0, 10);
			containerParams.append("text_entities", JSON.stringify(validSpoilers));
		}

		// Add topic tag (API parameter — only 1 supported per post)
		// Prefer dedicated topicTag field; fall back to first topic/hashtag
		const rawTag = postData.topicTag || (postData.topics?.[0] ?? null);
		if (rawTag) {
			const cleanTag = rawTag
				.trim()
				.replace(/^#/, "")
				.replace(/[.&]/g, "")
				.slice(0, 50);
			if (cleanTag) {
				containerParams.append("topic_tag", cleanTag);
			}
		}

		// Add GIF attachment (TEXT posts only, no media)
		if (postData.gifAttachment?.gifId && !hasMedia) {
			containerParams.append(
				"gif_attachment",
				JSON.stringify({
					gif_id: postData.gifAttachment.gifId,
					provider: postData.gifAttachment.provider || "GIPHY",
				}),
			);
		}

		// Add cross-share to Instagram Stories
		if (postData.crossreshareToIgDarkMode) {
			containerParams.append("crossreshare_to_ig_dark_mode", "true");
		} else if (postData.crossreshareToIg) {
			containerParams.append("crossreshare_to_ig", "true");
		}

		// Add geo-gating
		if (
			postData.allowlistedCountryCodes &&
			postData.allowlistedCountryCodes.length > 0
		) {
			containerParams.append(
				"allowlisted_country_codes",
				postData.allowlistedCountryCodes.join(","),
			);
		}

		const { pollContainerStatus } = await import("./retryUtils.js");

		const MAX_CONTAINER_RETRIES = 2;
		let containerError: string | undefined;

		for (
			let containerAttempt = 0;
			containerAttempt <= MAX_CONTAINER_RETRIES;
			containerAttempt++
		) {
			if (containerAttempt > 0) {
				const retryDelay = containerAttempt * 5000;
				logger.info("Retrying container creation after transient error", {
					attempt: containerAttempt,
					previousError: containerError,
					delayMs: retryDelay,
				});
				await new Promise((resolve) => setTimeout(resolve, retryDelay));
			}

			containerError = undefined;

			// Create container
			let containerResponse = await withRetry(
				() =>
					fetch(`https://graph.threads.net/v1.0/${threadsUserId}/threads`, {
						method: "POST",
						body: containerParams,
						headers: { Authorization: `Bearer ${token}` },
						signal: AbortSignal.timeout(10000),
					}),
				{ label: "postToThreads:createContainer" },
			);
			await recordThreadsUsage(
				containerResponse,
				"postToThreads:createContainer",
				threadsUserId,
			);

			let containerData = await containerResponse.json();

			// Handle unsupported features error
			if (
				containerData.error?.code === 33 &&
				containerData.error?.error_subcode === 4279044
			) {
				containerParams.delete("text_entities");
				containerParams.delete("allowlisted_country_codes");
				containerParams.delete("is_spoiler_media");
				containerParams.delete("crossreshare_to_ig");
				containerParams.delete("crossreshare_to_ig_dark_mode");

				containerResponse = await withRetry(
					() =>
						fetch(`https://graph.threads.net/v1.0/${threadsUserId}/threads`, {
							method: "POST",
							body: containerParams,
							headers: { Authorization: `Bearer ${token}` },
							signal: AbortSignal.timeout(10000),
						}),
					{ label: "postToThreads:createContainer:fallback" },
				);
				await recordThreadsUsage(
					containerResponse,
					"postToThreads:createContainer:fallback",
					threadsUserId,
				);

				containerData = await containerResponse.json();
			}

			if (!containerResponse.ok || containerData.error) {
				logger.error("Container creation error", {
					error: containerData?.error?.message,
					errorCode: containerData?.error?.code,
					errorType: containerData?.error?.type,
					errorSubcode: containerData?.error?.error_subcode,
					fbtrace_id: containerData?.error?.fbtrace_id,
					httpStatus: containerResponse.status,
				});
				const classified = classifyMetaError({
					code:
						typeof containerData?.error?.code === "number"
							? containerData.error.code
							: undefined,
					error_subcode:
						typeof containerData?.error?.error_subcode === "number"
							? containerData.error.error_subcode
							: undefined,
					type:
						typeof containerData?.error?.type === "string"
							? containerData.error.type
							: undefined,
					message:
						typeof containerData?.error?.message === "string"
							? containerData.error.message
							: undefined,
					httpStatus: containerResponse.status,
				});
				return {
					success: false,
					error: containerData.error?.message || "Failed to create container",
					timestamp: new Date(),
					retryable: classified.retryable,
				};
			}

			creationId = containerData.id;
			logger.info("Container created, polling for readiness", { creationId });
			if (!creationId) {
				return {
					success: false,
					error: "Container creation did not return an id",
					timestamp: new Date(),
				};
			}

			// Poll container status before publishing (catches ERROR/EXPIRED states early)
			let containerReady = true;
			if (hasMedia) {
				const hasVideoMedia =
					postData.media?.some((m) => m.type === "video") ?? false;
				const pollResult = await pollContainerStatus({
					creationId,
					token,
					maxAttempts: hasVideoMedia ? 20 : 15,
					delayMs: hasVideoMedia ? 3000 : 1000,
					firstDelayMs: 500,
					containerAttempt,
					maxContainerRetries: MAX_CONTAINER_RETRIES,
				});
				if (pollResult.transient) {
					containerError = pollResult.error;
					containerReady = false;
				} else if (!pollResult.ready) {
					return {
						success: false,
						error: pollResult.error || "Container did not become ready",
						timestamp: new Date(),
					};
				}
			}

			if (containerReady) break;
		}

		if (!creationId) {
			return {
				success: false,
				error: "Missing container id before publish",
				timestamp: new Date(),
			};
		}

		// Publish the container
		let publishData: {
			id?: string | undefined;
			crossreshare_to_ig_status?: "SUCCESS" | "FAILED" | undefined;
			error?:
				| {
						message?: string | undefined;
						code?: number | undefined;
						type?: string | undefined;
						error_subcode?: number | undefined;
				  }
				| undefined;
		} = {};
		let publishResponse: Response | null = null;
		let rateLimit: ReturnType<typeof parseRateLimitHeaders> | undefined;
		for (let attempt = 0; attempt < 5; attempt++) {
			if (attempt > 0) {
				await new Promise((resolve) => setTimeout(resolve, 1000));
			}

			const publishParams = new URLSearchParams({
				creation_id: creationId,
			});

			publishResponse = await withRetry(
				() =>
					fetch(
						`https://graph.threads.net/v1.0/${threadsUserId}/threads_publish`,
						{
							method: "POST",
							body: publishParams,
							headers: { Authorization: `Bearer ${token}` },
							signal: AbortSignal.timeout(10000),
						},
					),
				{ label: "postToThreads:publish" },
			);
			await recordThreadsUsage(
				publishResponse,
				"postToThreads:publish",
				threadsUserId,
			);

			publishData = await publishResponse.json();
			rateLimit = parseRateLimitHeaders(publishResponse);

			if (publishResponse.ok && !publishData.error) break;
			// Retry only on "media not ready" error subcodes
			const subcode = publishData?.error?.error_subcode;
			if (subcode !== 2207026 && subcode !== 2207051) break;
			logger.info("Container not ready, retrying publish", {
				attempt,
				subcode,
				creationId,
			});
		}

		if (!publishResponse?.ok || publishData.error) {
			logger.error("Publish error", {
				error: String(publishData?.error?.message),
			});
			const classified = classifyMetaError({
				code:
					typeof publishData?.error?.code === "number"
						? publishData.error.code
						: undefined,
				error_subcode:
					typeof publishData?.error?.error_subcode === "number"
						? publishData.error.error_subcode
						: undefined,
				type:
					typeof publishData?.error?.type === "string"
						? publishData.error.type
						: undefined,
				message:
					typeof publishData?.error?.message === "string"
						? publishData.error.message
						: undefined,
				httpStatus: publishResponse?.status,
			});
			return {
				success: false,
				error: publishData.error?.message || "Failed to publish",
				timestamp: new Date(),
				rateLimit,
				retryable: classified.retryable,
			};
		}

		const igStoryStatus = publishData.crossreshare_to_ig_status;
		if (igStoryStatus) {
			logger.info("Cross-share to IG Stories result", {
				status: igStoryStatus,
				threadId: publishData.id,
			});
		}

		return {
			success: true,
			threadId: publishData.id,
			crossreshareToIgStatus: igStoryStatus,
			timestamp: new Date(),
			rateLimit,
		};
	} catch (error: unknown) {
		const errMsg = error instanceof Error ? error.message : "Unknown error";
		const isTimeout = errMsg.includes("timeout") || errMsg.includes("aborted");

		// If we timed out AFTER creating a container, check if Meta published it anyway
		if (isTimeout && creationId && token) {
			try {
				logger.info(
					"Timeout after container creation — checking if Meta published anyway",
					{ creationId },
				);
				const checkRes = await withRetry(
					() =>
						fetch(
							`https://graph.threads.net/v1.0/${creationId}?fields=status`,
							{
								headers: { Authorization: `Bearer ${token}` },
								signal: AbortSignal.timeout(5000),
							},
						),
					{ label: `threadsPublishTimeoutCheck:${creationId}` },
				);
				const checkData = await checkRes.json();
				if (checkData.status === "PUBLISHED" || checkData.id) {
					logger.info("Container was actually published despite timeout", {
						creationId,
						status: checkData.status,
					});
					return {
						success: true,
						threadId: checkData.id || creationId,
						timestamp: new Date(),
					};
				}
				logger.info("Container not published after timeout", {
					creationId,
					status: checkData.status,
				});
			} catch (checkErr) {
				logger.warn("Failed to verify container status after timeout", {
					creationId,
					error: String(checkErr),
				});
			}
		}

		logger.error("Threads API error", { error: errMsg });
		return {
			success: false,
			error: errMsg,
			timestamp: new Date(),
		};
	}
}

/**
 * Fetch post metrics from Threads API
 */
export interface PostMetrics {
	views: number;
	likes: number;
	replies: number;
	reposts: number;
	quotes: number;
	shares: number;
	/** Always 0 — clicks is a user-level metric, not available at post level */
	clicks: number;
	engagementRate: number;
}

export async function getPostMetrics(
	encryptedAccessToken: string,
	threadId: string,
): Promise<{
	success: boolean;
	metrics?: PostMetrics | undefined;
	error?: string | undefined;
}> {
	try {
		const token = decrypt(encryptedAccessToken);

		// Fetch post insights from Threads API
		const insightsUrl = `https://graph.threads.net/v1.0/${threadId}/insights?metric=${THREADS_POST_INSIGHT_METRICS}`;
		const insightsResponse = await withRetry(
			() =>
				fetch(insightsUrl, {
					headers: { Authorization: `Bearer ${token}` },
					signal: AbortSignal.timeout(10000),
				}),
			{ label: "getPostMetrics" },
		);
		await recordThreadsUsage(insightsResponse, "getPostMetrics");
		const insightsData = await insightsResponse.json();

		if (!insightsResponse.ok || insightsData.error) {
			logger.error("Insights fetch error", {
				error: String(insightsData?.error?.message),
			});
			return {
				success: false,
				error: insightsData.error?.message || "Failed to fetch insights",
			};
		}

		// Parse the insights data
		const metrics: PostMetrics = {
			views: 0,
			likes: 0,
			replies: 0,
			reposts: 0,
			quotes: 0,
			shares: 0,
			clicks: 0,
			engagementRate: 0,
		};

		if (insightsData.data) {
			for (const item of insightsData.data) {
				const name = item.name?.toLowerCase();
				const value = item.value ?? item.values?.[0]?.value ?? 0;

				switch (name) {
					case "views":
						metrics.views = value;
						break;
					case "likes":
						metrics.likes = value;
						break;
					case "replies":
						metrics.replies = value;
						break;
					case "reposts":
						metrics.reposts = value;
						break;
					case "quotes":
						metrics.quotes = value;
						break;
					case "shares":
						metrics.shares = value;
						break;
					case "clicks":
						metrics.clicks = value;
						break;
				}
			}
		}

		// Calculate engagement rate using canonical formula
		metrics.engagementRate = calculateEngagementRate(
			{
				views: metrics.views,
				likes: metrics.likes,
				replies: metrics.replies,
				reposts: metrics.reposts,
				quotes: metrics.quotes,
				shares: metrics.shares,
			},
			"threads",
		);

		return { success: true, metrics };
	} catch (error: unknown) {
		logger.error("Get metrics error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

/**
 * Delete a post from Threads
 */
export async function deleteFromThreads(
	encryptedAccessToken: string,
	threadId: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	try {
		const token = decrypt(encryptedAccessToken);

		const deleteUrl = `https://graph.threads.net/v1.0/${threadId}`;
		const deleteResponse = await withRetry(
			() =>
				fetch(deleteUrl, {
					method: "DELETE",
					headers: { Authorization: `Bearer ${token}` },
					signal: AbortSignal.timeout(10000),
				}),
			{ label: "deleteFromThreads" },
		);

		if (!deleteResponse.ok) {
			const errorData = await deleteResponse.json();
			const errMsg: string =
				errorData?.error?.message || "Failed to delete from Threads";

			// Treat "does not exist / no permission / unsupported" as idempotent success.
			// The post is already gone from Threads — no further action needed.
			const isAlreadyGone =
				deleteResponse.status === 404 ||
				/does not exist|cannot be loaded due to missing permissions|does not support this operation/i.test(
					errMsg,
				);

			if (isAlreadyGone) {
				logger.warn(
					"Threads delete skipped — post already gone or inaccessible",
					{
						threadId,
						status: deleteResponse.status,
						reason: errMsg,
					},
				);
				return { success: true };
			}

			logger.error("Threads delete error", {
				error: errMsg,
				status: deleteResponse.status,
			});
			return { success: false, error: errMsg };
		}

		return { success: true };
	} catch (error: unknown) {
		logger.error("Threads delete error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

/**
 * Repost a Threads post (§6.13)
 * POST /{threads-media-id}/repost
 */
export async function repostOnThreads(
	encryptedAccessToken: string,
	mediaId: string,
): Promise<{
	success: boolean;
	repostId?: string | undefined;
	error?: string | undefined;
}> {
	try {
		const token = decrypt(encryptedAccessToken);

		const repostUrl = `https://graph.threads.net/v1.0/${mediaId}/repost`;
		const response = await withRetry(
			() =>
				fetch(repostUrl, {
					method: "POST",
					headers: { Authorization: `Bearer ${token}` },
					signal: AbortSignal.timeout(10000),
				}),
			{ label: "repostOnThreads" },
		);

		if (!response.ok) {
			const errorData = await response.json();
			const errMsg = errorData?.error?.message || "Failed to repost on Threads";
			logger.error("Threads repost error", {
				error: errMsg,
				status: response.status,
				mediaId,
			});
			return { success: false, error: errMsg };
		}

		const result = await response.json();
		return { success: true, repostId: result.id };
	} catch (error: unknown) {
		logger.error("Threads repost error", { error: String(error), mediaId });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

/**
 * Get replies for a Threads media post (§6.3).
 *
 * The older /conversation edge is not available for this app in prod and
 * returns "nonexisting field (conversation)", so this helper keeps its public
 * name for callers but reads the supported /replies edge.
 */
export async function getConversation(
	encryptedAccessToken: string,
	mediaId: string,
	reverse = false,
) {
	const token = decrypt(encryptedAccessToken);
	const url = `https://graph.threads.net/v1.0/${mediaId}/replies?fields=${THREADS_REPLY_FIELDS}&reverse=${reverse ? "true" : "false"}`;
	const response = await withRetry(
		() =>
			fetch(url, {
				headers: { Authorization: `Bearer ${token}` },
				signal: AbortSignal.timeout(15000),
			}),
		{ label: "getConversation" },
	);
	const data = await response.json();
	if (data.error) throw new Error(data.error.message);
	return data;
}

/**
 * Get ghost posts for a user (§6.11)
 * GET /{user-id}/ghost_posts
 * Ghost posts are auto-published text posts that expire after 24h.
 */
export async function getGhostPosts(
	encryptedAccessToken: string,
	userId: string,
) {
	const token = decrypt(encryptedAccessToken);
	const fields =
		"id,media_product_type,media_type,text,timestamp,permalink,is_reply,shortcode";
	const url = `https://graph.threads.net/v1.0/${userId}/ghost_posts?fields=${fields}`;
	const response = await withRetry(
		() =>
			fetch(url, {
				headers: { Authorization: `Bearer ${token}` },
				signal: AbortSignal.timeout(10000),
			}),
		{ label: "getGhostPosts" },
	);
	const data = await response.json();
	if (data.error) throw new Error(data.error.message);
	return data;
}

/**
 * Look up a Threads profile by username (requires threads_profile_discovery scope)
 */
export async function lookupThreadsProfile(
	encryptedAccessToken: string,
	username: string,
) {
	const token = decrypt(encryptedAccessToken);
	const fields =
		"username,name,profile_picture_url,biography,is_verified,follower_count,likes_count,quotes_count,replies_count,reposts_count,views_count";
	const url = `https://graph.threads.net/v1.0/profile_lookup?username=${encodeURIComponent(username)}&fields=${fields}`;
	const response = await withRetry(
		() =>
			fetch(url, {
				headers: { Authorization: `Bearer ${token}` },
				signal: AbortSignal.timeout(10000),
			}),
		{ label: "profileLookup" },
	);
	const data = await response.json();
	if (data.error) throw new Error(data.error.message);
	return data;
}

/**
 * Get recent posts from a Threads profile (requires threads_profile_discovery scope)
 */
export async function getProfilePosts(
	encryptedAccessToken: string,
	username: string,
	limit = 25,
) {
	const token = decrypt(encryptedAccessToken);
	const fields =
		"id,media_product_type,media_type,media_url,permalink,text,timestamp,shortcode,is_quote_post,has_replies,root_post,replied_to,is_reply,hide_status,reply_audience,total_votes,gif_url,topic_tag";
	const url = `https://graph.threads.net/v1.0/profile_posts?username=${encodeURIComponent(username)}&fields=${fields}&limit=${limit}`;
	const response = await withRetry(
		() =>
			fetch(url, {
				headers: { Authorization: `Bearer ${token}` },
				signal: AbortSignal.timeout(10000),
			}),
		{ label: "profilePosts" },
	);
	const data = await response.json();
	if (data.error) throw new Error(data.error.message);
	return data;
}

export async function getPendingReplies(
	encryptedAccessToken: string,
	mediaId: string,
) {
	const token = decrypt(encryptedAccessToken);
	const url = `https://graph.threads.net/v1.0/${mediaId}/pending_replies?fields=id,text,username,timestamp,media_type,media_url,permalink,profile_picture_url,is_verified,reply_approval_status`;
	const response = await withRetry(
		() =>
			fetch(url, {
				headers: { Authorization: `Bearer ${token}` },
				signal: AbortSignal.timeout(10000),
			}),
		{ label: "getPendingReplies" },
	);
	const data = await response.json();
	if (data.error) throw new Error(data.error.message);
	return data;
}

export async function approveReply(
	encryptedAccessToken: string,
	replyId: string,
) {
	const token = decrypt(encryptedAccessToken);
	const url = `https://graph.threads.net/v1.0/${replyId}/manage_pending_reply`;
	const response = await withRetry(
		() =>
			fetch(url, {
				method: "POST",
				headers: {
					"Content-Type": "application/x-www-form-urlencoded",
					Authorization: `Bearer ${token}`,
				},
				body: new URLSearchParams({ approve: "true" }),
				signal: AbortSignal.timeout(10000),
			}),
		{ label: "approveReply" },
	);
	const data = await response.json();
	if (data.error) throw new Error(data.error.message);
	return data;
}

/**
 * Fetch follower demographics from Threads API
 * Returns breakdowns for country, city, age, gender
 */
export interface DemographicsBreakdown {
	breakdown_type: string;
	values: { value: string; count: number }[];
}

export async function getThreadsDemographics(
	encryptedAccessToken: string,
	threadsUserId: string,
): Promise<{
	success: boolean;
	breakdowns?: DemographicsBreakdown[] | undefined;
	error?: string | undefined;
}> {
	try {
		const token = decrypt(encryptedAccessToken);
		const breakdownTypes = ["country", "city", "age", "gender"] as const;

		const results = await Promise.allSettled(
			breakdownTypes.map(async (breakdown) => {
				const url = `https://graph.threads.net/v1.0/${threadsUserId}/threads_insights?metric=follower_demographics&breakdown=${breakdown}`;
				const response = await withRetry(
					() =>
						fetch(url, {
							headers: { Authorization: `Bearer ${token}` },
							signal: AbortSignal.timeout(10000),
						}),
					{ label: `threadsDemographics:${breakdown}` },
				);
				const data = await response.json();

				if (data.error) {
					logger.warn("Threads demographics error", {
						breakdown,
						error: data.error.message,
					});
					return null;
				}

				const values: { value: string; count: number }[] = [];
				if (data.data?.[0]?.total_value?.breakdowns?.[0]?.results) {
					for (const result of data.data[0].total_value.breakdowns[0].results) {
						const dimensionValue = result.dimension_values?.[0] || "unknown";
						values.push({ value: dimensionValue, count: result.value || 0 });
					}
				}

				if (values.length > 0) {
					return { breakdown_type: breakdown, values } as DemographicsBreakdown;
				}
				return null;
			}),
		);

		const breakdowns: DemographicsBreakdown[] = results
			.filter(
				(r): r is PromiseFulfilledResult<DemographicsBreakdown> =>
					r.status === "fulfilled" && r.value !== null,
			)
			.map((r) => r.value);

		return { success: true, breakdowns };
	} catch (error: unknown) {
		logger.error("Threads demographics error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

export async function declineReply(
	encryptedAccessToken: string,
	replyId: string,
) {
	const token = decrypt(encryptedAccessToken);
	const url = `https://graph.threads.net/v1.0/${replyId}/manage_pending_reply`;
	const response = await withRetry(
		() =>
			fetch(url, {
				method: "POST",
				headers: {
					"Content-Type": "application/x-www-form-urlencoded",
					Authorization: `Bearer ${token}`,
				},
				body: new URLSearchParams({ approve: "false" }),
				signal: AbortSignal.timeout(10000),
			}),
		{ label: "declineReply" },
	);
	const data = await response.json();
	if (data.error) throw new Error(data.error.message);
	return data;
}
