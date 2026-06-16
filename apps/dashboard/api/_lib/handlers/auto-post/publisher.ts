// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Auto-Post Publisher Module
 *
 * Handles the actual posting logic: creating containers, publishing to Threads/IG,
 * rate limit handling with retry, and media attachment.
 */

import * as crypto from "node:crypto";
import { decrypt } from "../../encryption.js";
import { logger } from "../../logger.js";
import { classifyMetaError } from "../../metaErrors.js";
import { getRedis } from "../../redis.js";
import { withRetry } from "../../retryUtils.js";
import { getSupabaseAny } from "../../supabase.js";
import type {
	AutoPostConfig,
	IGPostingResultInternal,
	PostingResult,
} from "./types.js";

const db = () => getSupabaseAny();
const THREADS_TEXT_MAX_BYTES = 500;
const THREADS_CAROUSEL_MAX_ITEMS = 20;

function formatMetaErrorMessage(
	message: string,
	code: string | number | undefined,
	type: string | undefined,
	subcode?: string | number | undefined,
): string {
	const parts = [
		code !== undefined && code !== null && code !== "" ? `code=${code}` : null,
		type ? `type=${type}` : null,
		subcode !== undefined && subcode !== null && subcode !== ""
			? `subcode=${subcode}`
			: null,
	].filter(Boolean);
	return parts.length > 0 ? `${message} (${parts.join(", ")})` : message;
}

export function validateThreadsPublishText(
	content: string,
	mediaCount: number,
): { ok: true } | { ok: false; error: string } {
	const normalized = content ?? "";
	if (mediaCount === 0 && normalized.trim().length === 0) {
		return { ok: false, error: "Text-only Threads posts require content" };
	}
	const byteLength = Buffer.byteLength(normalized, "utf8");
	if (byteLength > THREADS_TEXT_MAX_BYTES) {
		return {
			ok: false,
			error: `Threads post text exceeds ${THREADS_TEXT_MAX_BYTES} UTF-8 bytes`,
		};
	}
	return { ok: true };
}

// ============================================================================
// Threads API Publishing
// ============================================================================

export async function postToThreads(
	encryptedAccessToken: string,
	threadsUserId: string,
	content: string,
	mediaUrl?: string | null,
	textSpoilers?: Array<{
		entity_type: "SPOILER";
		offset: number;
		length: number;
	}> | null,
	topicTag?: string | null,
	isSpoilerMedia?: boolean,
	mediaUrls?: string[] | null,
): Promise<PostingResult> {
	let token: string | undefined;
	let creationId: string | undefined;
	try {
		token = decrypt(encryptedAccessToken);

		// Use mediaUrls array if provided, fall back to single mediaUrl
		let allMedia =
			mediaUrls && mediaUrls.length > 0
				? mediaUrls
				: mediaUrl
					? [mediaUrl]
					: [];
		const textPreflight = validateThreadsPublishText(content, allMedia.length);
		if (!textPreflight.ok) {
			return {
				success: false,
				error: textPreflight.error,
				retryable: false,
			};
		}

		// Helper: detect media type from URL
		const getMediaInfo = (url: string) => {
			const urlPath = url.split("?")[0];
			const ext = urlPath!.includes(".")
				? urlPath!.split(".").pop()?.toLowerCase()
				: "";
			if (ext === "webp")
				return {
					valid: false,
					error: "WebP images not supported by Threads",
				} as const;
			const unsupported = ["webm", "avi", "mkv"];
			if (ext && unsupported.includes(ext))
				return { valid: false, error: `Unsupported format: .${ext}` } as const;
			const isImage = !ext || !["mp4", "mov"].includes(ext);
			return {
				valid: true,
				isImage,
				mediaType: isImage ? "IMAGE" : "VIDEO",
				mediaKey: isImage ? "image_url" : "video_url",
			} as const;
		};

		// RULE: Videos are ALWAYS posted as single media, never in carousels.
		// If any video is present in a multi-media set, use only the first video as a single post.
		if (allMedia.length > 1) {
			const hasVideo = allMedia.some((url) => {
				const info = getMediaInfo(url);
				return info.valid && !info.isImage;
			});
			if (hasVideo) {
				// Find the first video and post it solo
				const firstVideo = allMedia.find((url) => {
					const info = getMediaInfo(url);
					return info.valid && !info.isImage;
				});
				if (firstVideo) {
					allMedia = [firstVideo];
					logger.info(
						"Video found in multi-media set — forcing single video post",
						{
							originalCount: mediaUrls?.length || 1,
						},
					);
				}
			}
		}

		if (allMedia.length > THREADS_CAROUSEL_MAX_ITEMS) {
			return {
				success: false,
				error: `Carousel posts support a maximum of ${THREADS_CAROUSEL_MAX_ITEMS} items`,
				retryable: false,
			};
		}

		logger.info("Creating container", {
			contentPreview: content.substring(0, 50),
			mediaCount: allMedia.length,
		});

		for (const url of allMedia) {
			const info = getMediaInfo(url);
			if (!info.valid) {
				return {
					success: false,
					error: info.error,
					retryable: false,
				};
			}
		}

		// Strip EXIF metadata from all media (privacy: removes GPS, device info)
		if (allMedia.length > 0) {
			const { stripExifFromMediaUrls } = await import("../../exifStrip.js");
			allMedia = await stripExifFromMediaUrls(allMedia);
			const preflight = await validatePublishableMediaUrls(allMedia);
			if (!preflight.ok) {
				return {
					success: false,
					error: preflight.error,
					retryable: false,
				};
			}
		}

		// Build container params
		let containerParams: URLSearchParams;

		if (allMedia.length > 1) {
			// Carousel post (Threads API: up to 20 items, PHOTOS ONLY)
			const mediaContainerIds = await Promise.all(
				allMedia.map(async (url) => {
					const info = getMediaInfo(url);
					if (!info.valid) throw new Error(info.error);

					const mediaParams = new URLSearchParams({
						media_type: info.mediaType,
						[info.mediaKey]: url,
						is_carousel_item: "true",
					});

					const resp = await withRetry(
						() =>
							fetch(`https://graph.threads.net/v1.0/${threadsUserId}/threads`, {
								method: "POST",
								body: mediaParams,
								headers: { Authorization: `Bearer ${token}` },
								signal: AbortSignal.timeout(10000),
							}),
						{ label: "auto-post:carousel-item" },
					);

					const data = await resp.json();
					if (!resp.ok || data.error) {
						throw new Error(
							data.error?.message || "Failed to create carousel item container",
						);
					}

					// Poll each carousel item container until FINISHED before proceeding
					const itemId = data.id as string;
					const itemIsVideo = info.valid && !info.isImage;
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
								{ label: `autoPostCarouselItemStatus:${itemId}` },
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
							if (
								pollErr instanceof Error &&
								(pollErr.message.includes("Carousel item processing failed") ||
									pollErr.message.includes("Carousel item container expired"))
							) {
								throw pollErr;
							}
							// Status check network failure — proceed
							break;
						}
					}

					return itemId;
				}),
			);

			containerParams = new URLSearchParams({
				media_type: "CAROUSEL",
				children: mediaContainerIds.join(","),
				text: content,
			});
		} else if (allMedia.length === 1) {
			const info = getMediaInfo(allMedia[0]!);
			if (!info.valid)
				return { success: false, error: info.error, retryable: false };

			containerParams = new URLSearchParams({
				media_type: info.mediaType,
				[info.mediaKey]: allMedia[0]!,
				text: content,
			});
		} else {
			containerParams = new URLSearchParams({
				media_type: "TEXT",
				text: content,
			});
		}

		// Add text spoiler entities if present (Threads spoiler trick feature)
		if (textSpoilers && textSpoilers.length > 0) {
			const validSpoilers = textSpoilers.slice(0, 10); // Max 10 per Threads API
			containerParams.append("text_entities", JSON.stringify(validSpoilers));
		}

		// Mark media as spoiler (blurred until tap) — drives curiosity engagement.
		// Competitors using spoiler photos get 5-10x more likes than non-spoiler posts.
		if (isSpoilerMedia && allMedia.length > 0) {
			containerParams.append("is_spoiler_media", "true");
		}

		// Add topic tag (notification-style header above post content)
		if (topicTag) {
			// Threads API: 1-50 chars, no periods or ampersands. Strip invalid chars.
			const cleanTag = topicTag
				.replace(/^#/, "")
				.replace(/[.&]/g, "")
				.trim()
				.slice(0, 50);
			if (cleanTag) {
				containerParams.append("topic_tag", cleanTag);
			}
		}

		const { pollContainerStatus, isTransientContainerError } = await import(
			"../../retryUtils.js"
		);

		const MAX_CONTAINER_RETRIES = 2;
		let containerError: string | undefined;

		for (
			let containerAttempt = 0;
			containerAttempt <= MAX_CONTAINER_RETRIES;
			containerAttempt++
		) {
			if (containerAttempt > 0) {
				// Wait before re-creating — give Meta's infra time to recover
				const retryDelay = containerAttempt * 5000;
				logger.info("Retrying container creation after transient error", {
					attempt: containerAttempt,
					previousError: containerError,
					delayMs: retryDelay,
				});
				await new Promise((resolve) => setTimeout(resolve, retryDelay));
			}

			containerError = undefined;

			// Create container (with retry on 429)
			const containerResponse = await withRetry(
				() =>
					fetch(`https://graph.threads.net/v1.0/${threadsUserId}/threads`, {
						method: "POST",
						headers: { Authorization: `Bearer ${token}` },
						body: containerParams,
						signal: AbortSignal.timeout(15000),
					}),
				{ label: "auto-post:create-container" },
			);

			const containerData = await containerResponse.json();
			if (!containerResponse.ok || containerData.error) {
				const errorMsg =
					containerData.error?.message || "Failed to create container";
				const errorCode = containerData.error?.code || "unknown";
				const errorType = containerData.error?.type || "unknown";
				const errorFbTrace = containerData.error?.fbtrace_id || "none";
				// Classify with structured taxonomy for consistent handling
				const classified = classifyMetaError({
					code: typeof errorCode === "number" ? errorCode : undefined,
					type: typeof errorType === "string" ? errorType : undefined,
					message: errorMsg,
					httpStatus: containerResponse.status,
				});
				logger.error("Container creation failed", {
					status: containerResponse.status,
					code: errorCode,
					type: errorType,
					message: errorMsg,
					fbtrace: errorFbTrace,
					threadsUserId,
					classified: classified.category,
				});
				if (
					containerResponse.status === 429 ||
					classified.category === "rate_limit"
				) {
					return {
						success: false,
						error: `Rate limited after retries: ${errorMsg}`,
						retryable: true,
					};
				}
				// Transient errors — trust the classifier, don't override with string matching
				const isTransientCreationError = classified.retryable;
				if (
					isTransientCreationError &&
					containerAttempt < MAX_CONTAINER_RETRIES
				) {
					containerError = errorMsg;
					logger.warn("Transient container creation error, will re-create", {
						creationId: undefined,
						errorMsg,
						code: errorCode,
						attempt: containerAttempt,
					});
					continue;
				}
				return {
					success: false,
					error: formatMetaErrorMessage(
						errorMsg,
						errorCode,
						typeof errorType === "string" ? errorType : undefined,
						containerData.error?.error_subcode,
					),
					retryable: classified.retryable,
				};
			}

			creationId = containerData.id;
			logger.info("Container created", { creationId });

			// Poll container status before publishing (media needs processing time)
			let containerReady = true;
			if (allMedia.length > 0) {
				const hasVideo = allMedia.some((url) => {
					const info = getMediaInfo(url);
					return info.valid && !info.isImage;
				});
				if (!creationId) {
					return {
						success: false,
						error: "Missing creationId for media publish",
						retryable: true,
					};
				}
				const pollResult = await pollContainerStatus({
					creationId,
					token,
					maxAttempts: hasVideo ? 20 : 15,
					delayMs: hasVideo ? 3000 : 1000,
					firstDelayMs: 2000,
					containerAttempt,
					maxContainerRetries: MAX_CONTAINER_RETRIES,
				});
				if (pollResult.transient) {
					containerError = pollResult.error;
					containerReady = false;
				} else if (!pollResult.ready) {
					return {
						success: false,
						error: pollResult.error ?? "Unknown error",
						retryable: false,
					};
				}
			} else {
				// Text-only: quick status check — Meta may not be ready immediately
				await new Promise((resolve) => setTimeout(resolve, 1500));
				try {
					const statusRes = await withRetry(
						() =>
							fetch(
								`https://graph.threads.net/v1.0/${creationId}?fields=status,error_message`,
								{
									headers: { Authorization: `Bearer ${token}` },
									signal: AbortSignal.timeout(5000),
								},
							),
						{ label: `autoPostTextContainerStatus:${creationId}` },
					);
					const statusData = await statusRes.json();
					if (statusData.status === "ERROR") {
						const errorMsg =
							statusData.error_message || "Container processing failed";
						if (
							isTransientContainerError(errorMsg) &&
							containerAttempt < MAX_CONTAINER_RETRIES
						) {
							logger.warn("Transient text container error, will re-create", {
								creationId,
								errorMsg,
								attempt: containerAttempt,
							});
							containerError = errorMsg;
							containerReady = false;
						} else {
							logger.error("Text container entered ERROR state", {
								creationId,
								errorMsg,
							});
							return {
								success: false,
								error: `Container error: ${errorMsg}`,
								retryable: false,
							};
						}
					}
				} catch {
					// Status check failed — proceed to publish attempt anyway
				}
			}

			// Container processed successfully — proceed to publish
			if (containerReady) break;
		}

		if (!creationId) {
			return {
				success: false,
				error: `Container creation failed after ${MAX_CONTAINER_RETRIES + 1} attempts: ${containerError || "unknown"}`,
				retryable: true,
			};
		}

		// Publish container (with retry on 429 and code 24 "resource not found")
		const publishParams = new URLSearchParams({
			creation_id: creationId,
		});

		let publishData: {
			id?: string | undefined;
			error?:
				| {
						message?: string | undefined;
						code?: number | undefined;
						error_subcode?: number | undefined;
						type?: string | undefined;
				  }
				| undefined;
		} = {};
		let publishResponse: Response | null = null;
		for (let publishAttempt = 0; publishAttempt < 3; publishAttempt++) {
			if (publishAttempt > 0) {
				await new Promise((resolve) => setTimeout(resolve, 2000));
				logger.info("Retrying publish after code 24", {
					creationId,
					attempt: publishAttempt,
				});
			}

			publishResponse = await withRetry(
				() =>
					fetch(
						`https://graph.threads.net/v1.0/${threadsUserId}/threads_publish`,
						{
							method: "POST",
							headers: { Authorization: `Bearer ${token}` },
							body: publishParams,
							signal: AbortSignal.timeout(30000),
						},
					),
				{ label: "auto-post:publish" },
			);

			publishData = await publishResponse.json();
			// Code 24 = container not ready yet — retry after delay
			if (publishData.error?.code === 24 && publishAttempt < 2) continue;
			break;
		}

		if (!publishResponse?.ok || publishData.error) {
			const errorMsg = publishData.error?.message || "Failed to publish";
			const errorCode = publishData.error?.code || "unknown";
			const errorType = publishData.error?.type || "unknown";
			if (publishResponse?.status === 429) {
				return {
					success: false,
					error: `Rate limited after retries: ${errorMsg} (code=${errorCode}, type=${errorType})`,
					retryable: true,
				};
			}
			// Classify the Meta error so transient (code=1 OAuthException, "An
			// unknown error occurred") is retryable. The prior hardcoded
			// `retryable: false` dead-lettered every non-429 transient on first
			// attempt. classifyMetaError treats permanent (code=100/10/24/etc.)
			// as non-retryable and transient (code=1/2) as retryable.
			const classified = classifyMetaError({
				code:
					typeof publishData.error?.code === "number"
						? publishData.error.code
						: undefined,
				error_subcode:
					typeof publishData.error?.error_subcode === "number"
						? publishData.error.error_subcode
						: undefined,
				type:
					typeof publishData.error?.type === "string"
						? publishData.error.type
						: undefined,
				message:
					typeof publishData.error?.message === "string"
						? publishData.error.message
						: errorMsg,
				httpStatus: publishResponse?.status,
			});
			return {
				success: false,
				error: formatMetaErrorMessage(
					errorMsg,
					errorCode,
					typeof errorType === "string" ? errorType : undefined,
					publishData.error?.error_subcode,
				),
				retryable: classified.retryable,
			};
		}

		return {
			success: true,
			threadId: publishData.id,
		};
	} catch (error: unknown) {
		const errorMessage = error instanceof Error ? error.message : String(error);
		const isTimeout =
			errorMessage.toLowerCase().includes("timeout") ||
			errorMessage.toLowerCase().includes("aborted");

		if (isTimeout && creationId && token) {
			try {
				logger.info(
					"Timeout after container creation — checking container status",
					{
						creationId,
					},
				);
				const statusResponse = await withRetry(
					() =>
						fetch(
							`https://graph.threads.net/v1.0/${creationId}?fields=status,error_message`,
							{
								headers: { Authorization: `Bearer ${token}` },
								signal: AbortSignal.timeout(8000),
							},
						),
					{ label: `autoPostTimeoutStatus:${creationId}` },
				);
				const statusData = await statusResponse.json();
				const status = statusData.status as string | undefined;

				if (status === "PUBLISHED") {
					logger.info("Container published despite timeout", {
						creationId,
						status,
					});
					return {
						success: true,
						threadId: creationId,
					};
				}

				if (status === "ERROR" || status === "EXPIRED") {
					logger.warn("Container failed after timeout", {
						creationId,
						status,
						error: statusData.error_message,
					});
					return {
						success: false,
						error:
							statusData.error_message || `Container ${status.toLowerCase()}`,
						retryable: status !== "EXPIRED",
					};
				}

				logger.warn(
					"Publish timed out after container creation — treating as retryable",
					{
						creationId,
						status: status || "unknown",
					},
				);
			} catch (statusError) {
				logger.warn("Failed to verify container status after timeout", {
					creationId,
					error:
						statusError instanceof Error
							? statusError.message
							: String(statusError),
				});
			}
		}

		logger.error("Posting error", {
			error: errorMessage,
		});
		return {
			success: false,
			error: errorMessage || "Unknown error",
			retryable: isTimeout,
		};
	}
}

// ============================================================================
// Instagram API Publishing
// ============================================================================

export async function publishToInstagram(
	encryptedAccessToken: string,
	igUserId: string,
	content: string,
	mediaUrls: string[],
	encryptedFbPageToken?: string,
	postId?: string,
	accountId?: string,
): Promise<IGPostingResultInternal> {
	try {
		if (!mediaUrls || mediaUrls.length === 0) {
			return {
				success: false,
				error: "Instagram requires at least one media URL",
			};
		}

		const { orchestrateIGPublish } = await import(
			"../../instagram/orchestrate.js"
		);

		const isVideoUrl = (url: string) => /\.(mp4|mov)(\?|$)/i.test(url);

		// RULE: Videos are ALWAYS posted as single media, carousels are PHOTOS ONLY.
		// If any video is present in a multi-media set, post only the first video as REELS.
		let effectiveUrls = mediaUrls;
		if (mediaUrls.length > 1) {
			const hasVideo = mediaUrls.some(isVideoUrl);
			if (hasVideo) {
				const firstVideo = mediaUrls.find(isVideoUrl);
				effectiveUrls = firstVideo ? [firstVideo] : [mediaUrls[0]!];
				logger.info(
					"Video found in IG multi-media set — forcing single video post",
					{
						originalCount: mediaUrls.length,
					},
				);
			}
		}

		const primaryUrl = effectiveUrls[0];
		const isVideo = isVideoUrl(primaryUrl!);
		const hasMultipleMedia = effectiveUrls.length > 1;

		const igPostData = {
			caption: content,
			mediaType: hasMultipleMedia
				? ("CAROUSEL" as const)
				: isVideo
					? ("REELS" as const)
					: ("IMAGE" as const),
			imageUrl: !isVideo && !hasMultipleMedia ? primaryUrl : undefined,
			videoUrl: isVideo && !hasMultipleMedia ? primaryUrl : undefined,
			children: hasMultipleMedia
				? effectiveUrls.map((url: string) => ({
						type: (isVideoUrl(url) ? "video" : "image") as "image" | "video",
						url,
					}))
				: undefined,
		};

		const result = await orchestrateIGPublish({
			encryptedToken: encryptedAccessToken,
			igUserId,
			postData: igPostData,
			encryptedFbPageToken: encryptedFbPageToken || undefined,
			postPublish: postId
				? {
						engagementSync: {
							postId,
							accountId: accountId || igUserId,
							source: "auto-post",
						},
					}
				: undefined,
		});

		return {
			success: result.success,
			mediaId: result.mediaId,
			containerId: result.containerId,
			error: result.error,
			retryable: result.retryable,
			permalink: result.permalink,
		};
	} catch (error: unknown) {
		logger.error("IG posting error", {
			error: error instanceof Error ? error.message : String(error),
		});
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown IG error",
		};
	}
}

// ============================================================================
// Media Attachment Helpers
// ============================================================================

export interface MediaWithContext {
	id: string;
	url: string;
	description: string | null;
	tags: string[] | null;
	isVideo?: boolean | undefined;
}

/**
 * Get a themed group of 2-5 media items for carousel posts.
 * Groups by shared tags — e.g., all "gym" tagged images or all "selfie" images.
 * Falls back to random selection if no tag groups are large enough.
 * Returns null if fewer than 2 items can be grouped.
 * IMPORTANT: Carousels are PHOTOS ONLY — videos are excluded.
 */
export async function getThemedMediaGroup(
	userId: string,
	groupId?: string,
	targetSize = 3,
): Promise<MediaWithContext[] | null> {
	try {
		let query = db()
			.from("media")
			.select("id, url, file_type, ai_description, tags")
			.eq("user_id", userId)
			.not("tags", "is", null);

		if (groupId) {
			query = query.eq("group_id", groupId);
		}

		const { data: mediaItems, error } = await query.limit(200);
		if (error || !mediaItems || mediaItems.length < 2) return null;

		// Carousels are PHOTOS ONLY — filter out all video file types
		const imageOnlyItems = mediaItems.filter(
			(item: { file_type?: string | undefined }) => {
				const ft = (item.file_type || "").toLowerCase();
				return !ft.startsWith("video");
			},
		);
		const videoCount = mediaItems.length - imageOnlyItems.length;
		if (videoCount > 0) {
			logger.info("Videos excluded from carousel (photos only)", {
				videoCount,
				remainingImages: imageOnlyItems.length,
			});
		}
		if (imageOnlyItems.length < 2) return null;

		// Group by tags — find the largest tag cluster
		const tagGroups = new Map<string, typeof imageOnlyItems>();
		for (const item of imageOnlyItems) {
			const tags = item.tags as string[] | null;
			if (!Array.isArray(tags)) continue;
			for (const tag of tags) {
				const lower = tag.toLowerCase().trim();
				if (!lower) continue;
				if (!tagGroups.has(lower)) tagGroups.set(lower, []);
				(tagGroups.get(lower) ?? []).push(item);
			}
		}

		// Find best tag group (closest to targetSize, at least 2)
		let bestGroup: typeof mediaItems = [];
		let bestTag = "";
		for (const [tag, items] of tagGroups) {
			if (items.length >= 2 && items.length >= bestGroup.length) {
				bestGroup = items;
				bestTag = tag;
			}
		}

		if (bestGroup.length < 2) return null;

		// Shuffle and take targetSize items, capped at 5 (Threads carousel max is 10, but 3-5 is optimal)
		const capped = Math.min(targetSize, 5, bestGroup.length);
		const shuffled = [...bestGroup]
			.sort(() => Math.random() - 0.5)
			.slice(0, capped);

		// Validate URLs via Redis cache (reuse same pattern as single media)
		const redis = getRedis();
		const validated: MediaWithContext[] = [];
		for (const item of shuffled) {
			if (!item.url) continue;
			const cacheKey = `media-ok:${crypto.createHash("sha256").update(item.url).digest("hex").slice(0, 32)}`;
			const cached = await redis.get(cacheKey).catch(() => null);
			if (cached === "0") continue;
			if (cached === "1" || (await isReachableMediaUrl(item.url))) {
				if (cached !== "1")
					await redis.set(cacheKey, "1", { ex: 3600 }).catch(() => {});
				const ft = (item.file_type || "") as string;
				validated.push({
					id: item.id,
					url: item.url,
					description: item.ai_description || null,
					tags: item.tags || null,
					isVideo: ft.startsWith("video/"),
				});
			} else {
				await redis.set(cacheKey, "0", { ex: 600 }).catch(() => {});
			}
			if (validated.length >= capped) break;
		}

		if (validated.length < 2) return null;

		logger.info("Themed media group selected", {
			tag: bestTag,
			count: validated.length,
			groupId,
		});

		return validated;
	} catch (err) {
		logger.warn("Themed media group selection failed", { error: String(err) });
		return null;
	}
}

export async function getRandomMediaWithContext(
	userId: string,
	mediaSource: string,
	groupId?: string,
	accountId?: string,
): Promise<MediaWithContext | null> {
	const result = await getRandomMediaUrlInternal(
		userId,
		mediaSource,
		groupId,
		accountId,
	);
	return result;
}

export async function getRandomMediaUrl(
	userId: string,
	mediaSource: string,
	groupId?: string,
	accountId?: string,
): Promise<string | null> {
	const result = await getRandomMediaUrlInternal(
		userId,
		mediaSource,
		groupId,
		accountId,
	);
	return result?.url ?? null;
}

async function getRandomMediaUrlInternal(
	userId: string,
	mediaSource: string,
	groupId?: string,
	accountId?: string,
): Promise<MediaWithContext | null> {
	try {
		let query = db()
			.from("media")
			.select("id, url, file_type, ai_description, tags")
			.eq("user_id", userId)
			.not("url", "is", null);

		// Filter by group_id first (persona-scoped media), fall back to folder_id
		if (groupId) {
			query = query.eq("group_id", groupId);
		} else if (mediaSource && mediaSource !== "all" && mediaSource !== "any") {
			query = query.eq("folder_id", mediaSource);
		}

		const { data: mediaItems, error } = await query
			.order("created_at", { ascending: false })
			.limit(100);

		if (error || !mediaItems || mediaItems.length === 0) {
			logger.info("No media available for attachment");
			return null;
		}

		// Exclude media recently used by this specific account (prevents same image reposting)
		const recentlyUsedUrls = new Set<string>();
		if (accountId) {
			try {
				const { data: recentPosts } = await db()
					.from("auto_post_queue")
					.select("media_urls")
					.eq("account_id", accountId)
					.in("status", ["published", "posted", "pending"])
					.not("media_urls", "is", null)
					.gte(
						"created_at",
						new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
					)
					.order("created_at", { ascending: false })
					.limit(50);
				if (recentPosts) {
					for (const p of recentPosts) {
						const urls = (p as { media_urls: string[] | null }).media_urls;
						if (urls) for (const u of urls) recentlyUsedUrls.add(u);
					}
				}
			} catch {
				// Non-blocking — dedup is best-effort
			}
		}

		// Filter out recently used media (soft: if all are used, allow reuse)
		const freshItems = mediaItems.filter(
			(m: { url: string }) => !recentlyUsedUrls.has(m.url),
		);
		const candidateItems = freshItems.length > 0 ? freshItems : mediaItems;
		if (freshItems.length === 0 && recentlyUsedUrls.size > 0) {
			logger.info("All media recently used, allowing reuse", {
				totalMedia: mediaItems.length,
				recentlyUsed: recentlyUsedUrls.size,
			});
		}

		const redis = getRedis();

		// Performance-biased selection: prefer media attached to high-view posts.
		// Lazily build a performance cache from recent published posts with media.
		// Top 30% of media get 3x selection probability, rest random.
		const sorted = [...candidateItems];
		try {
			const perfCacheKey = `media-perf:${userId}:${groupId || "all"}`;
			let perfMap: Record<string, number> | null = null;
			const cached = await redis.get(perfCacheKey).catch(() => null);
			if (cached) {
				perfMap = JSON.parse(cached as string);
			} else {
				// Build from recent posts — which media got the best early velocity?
				// Score = views + replies*5 (replies drive algorithm distribution)
				const { data: recentPosts } = await db()
					.from("auto_post_queue")
					.select("media_urls, views_at_24h, engagement_rate")
					.eq("workspace_id", userId)
					.eq("status", "published")
					.not("media_urls", "is", null)
					.not("views_at_24h", "is", null)
					.gte(
						"posted_at",
						new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
					)
					.order("views_at_24h", { ascending: false })
					.limit(100);

				if (recentPosts && recentPosts.length >= 5) {
					perfMap = {};
					for (const p of recentPosts) {
						const urls = p.media_urls as string[] | null;
						const views = (p.views_at_24h as number) || 0;
						// engagement_rate is a composite signal — use it as reply proxy
						const engRate = (p.engagement_rate as number) || 0;
						const velocityScore = views + engRate * 500; // scale engagement_rate
						if (urls) {
							for (const url of urls) {
								const match = mediaItems.find(
									(m: { url: string }) => m.url === url,
								);
								if (match) {
									perfMap[match.id] = Math.max(
										perfMap[match.id] || 0,
										velocityScore,
									);
								}
							}
						}
					}
					await redis
						.set(perfCacheKey, JSON.stringify(perfMap), { ex: 3600 })
						.catch(() => {});
				}
			}

			if (perfMap && Object.keys(perfMap).length > 0) {
				sorted.sort((a, b) => {
					const scoreA = perfMap?.[a.id] ?? 0;
					const scoreB = perfMap?.[b.id] ?? 0;
					if (scoreA !== scoreB) return scoreB - scoreA;
					return Math.random() - 0.5;
				});
			} else {
				sorted.sort(() => Math.random() - 0.5);
			}
		} catch {
			sorted.sort(() => Math.random() - 0.5);
		}
		const shuffled = sorted;
		const MAX_UNCACHED_CHECKS = 3;
		let uncachedChecks = 0;
		const deadline = Date.now() + 15_000; // 15s overall timeout
		for (const selectedMedia of shuffled.slice(0, 10)) {
			if (Date.now() > deadline) {
				logger.warn("getRandomMediaUrl hit 15s timeout, returning null");
				break;
			}
			if (!selectedMedia.url) continue;

			// Check Redis cache first — avoids slow HEAD requests for recently validated URLs
			const cacheKey = `media-ok:${crypto.createHash("sha256").update(selectedMedia.url).digest("hex").slice(0, 32)}`;
			const cached = await redis.get(cacheKey).catch(() => null);
			if (cached === "1") {
				logger.info("Selected media (cached)", {
					url: selectedMedia.url,
					fileType: selectedMedia.file_type,
				});
				const ft = (selectedMedia.file_type || "") as string;
				return {
					id: selectedMedia.id,
					url: selectedMedia.url,
					description: selectedMedia.ai_description || null,
					tags: selectedMedia.tags || null,
					isVideo: ft.startsWith("video/"),
				};
			}
			if (cached === "0") continue; // known-bad, skip

			// Limit uncached (slow) HEAD checks to prevent timeout
			if (uncachedChecks >= MAX_UNCACHED_CHECKS) continue;
			uncachedChecks++;

			if (await isReachableMediaUrl(selectedMedia.url)) {
				await redis.set(cacheKey, "1", { ex: 3600 }).catch(() => {}); // 1h TTL
				logger.info("Selected media", {
					url: selectedMedia.url,
					fileType: selectedMedia.file_type,
				});
				const ft2 = (selectedMedia.file_type || "") as string;
				return {
					id: selectedMedia.id,
					url: selectedMedia.url,
					description: selectedMedia.ai_description || null,
					tags: selectedMedia.tags || null,
					isVideo: ft2.startsWith("video/"),
				};
			}
			await redis.set(cacheKey, "0", { ex: 600 }).catch(() => {}); // 10min TTL for failures
			logger.warn("Media URL failed validation", { url: selectedMedia.url });
		}

		// Fallback: if all validation failed but we have media, return first one unvalidated.
		// Supabase public URLs are almost always reachable — HEAD check timeouts shouldn't block media.
		if (mediaItems.length > 0) {
			const fallback =
				mediaItems[Math.floor(Math.random() * mediaItems.length)];
			if (fallback!.url) {
				const ftFb = (fallback!.file_type || "") as string;
				logger.warn(
					"Media URL validation all failed, using unvalidated fallback",
					{ url: fallback!.url },
				);
				return {
					id: fallback!.id,
					url: fallback!.url,
					description: fallback!.ai_description || null,
					tags: fallback!.tags || null,
					isVideo: ftFb.startsWith("video/"),
				};
			}
		}

		logger.warn("No media available after all attempts", { userId, groupId });
		return null;
	} catch (error) {
		logger.error("Error fetching media", {
			error: error instanceof Error ? error.message : String(error),
		});
		return null;
	}
}

export function shouldAttachMedia(
	config: AutoPostConfig,
	competitorMediaType?: string,
	groupMediaChance?: number,
): boolean {
	const mediaMode = config.posting_times?.media_mode ?? "random_chance";

	if (mediaMode === "never") return false;

	if (mediaMode === "match_competitor" && competitorMediaType) {
		return ["IMAGE", "VIDEO", "CAROUSEL_ALBUM"].includes(competitorMediaType);
	}

	// Group-level media_attachment_chance overrides workspace-level media_chance
	const mediaChance =
		groupMediaChance ?? config.posting_times?.media_chance ?? 0;
	if (mediaChance <= 0) return false;
	if (mediaChance >= 100) return true;
	return Math.random() * 100 < mediaChance;
}

async function isReachableMediaUrl(url: string): Promise<boolean> {
	try {
		const headResponse = await fetch(url, {
			method: "HEAD",
			signal: AbortSignal.timeout(5000),
		});
		if (headResponse.ok) return true;
		if (headResponse.status === 405 || headResponse.status === 400) {
			const peekResponse = await fetch(url, {
				method: "GET",
				headers: { Range: "bytes=0-0" },
				signal: AbortSignal.timeout(7000),
			});
			return peekResponse.ok;
		}
		return false;
	} catch (err) {
		logger.debug("Media URL reachability check failed", {
			url: url.substring(0, 200),
			error: String(err),
		});
		return false;
	}
}

async function validatePublishableMediaUrls(urls: string[]): Promise<{
	ok: boolean;
	error?: string | undefined;
}> {
	if (urls.length === 0) return { ok: true };

	const redis = getRedis();
	const unreachable: string[] = [];

	await Promise.all(
		urls.map(async (url) => {
			const cacheKey = `media-ok:${crypto.createHash("sha256").update(url).digest("hex").slice(0, 32)}`;
			const cached = await redis.get(cacheKey).catch(() => null);
			if (cached === "1") return;
			if (cached === "0") {
				unreachable.push(url);
				return;
			}

			const reachable = await isReachableMediaUrl(url);
			await redis
				.set(cacheKey, reachable ? "1" : "0", { ex: reachable ? 3600 : 600 })
				.catch(() => {});
			if (!reachable) unreachable.push(url);
		}),
	);

	if (unreachable.length === 0) return { ok: true };

	logger.warn("Media preflight failed before Threads container creation", {
		totalUrls: urls.length,
		unreachableCount: unreachable.length,
		sampleHost: safeMediaHost(unreachable[0]),
	});

	return {
		ok: false,
		error:
			unreachable.length === 1
				? "Media URL unreachable at publish time"
				: `${unreachable.length} media URLs unreachable at publish time`,
	};
}

function safeMediaHost(url: string | undefined): string | null {
	if (!url) return null;
	try {
		return new URL(url).host;
	} catch {
		return null;
	}
}

// ============================================================================
// Activity Logging
// ============================================================================

export async function logActivity(
	workspaceId: string,
	activityType: string,
	accountHandle: string,
	message: string,
	postIndex?: number,
	nextPostIn?: number,
	groupId?: string,
	groupName?: string,
) {
	const { error: activityErr } = await db()
		.from("auto_post_activity")
		.insert({
			workspace_id: workspaceId,
			activity_type: activityType,
			account_handle: accountHandle,
			post_index: postIndex,
			next_post_in: nextPostIn,
			message,
			group_id: groupId || null,
			group_name: groupName || null,
			created_at: new Date().toISOString(),
		});
	if (activityErr) {
		logger.warn("Failed to log auto-post activity", {
			error: activityErr.message,
			activityType,
			accountHandle,
		});
	}

	// Create user notification for posted/error activities
	if (activityType === "posted" || activityType === "error") {
		try {
			const { data: workspace } = await db()
				.from("workspaces")
				.select("owner_id")
				.eq("id", workspaceId)
				.maybeSingle();

			if (workspace?.owner_id) {
				const { createNotification } = await import(
					"../../createNotification.js"
				);
				await createNotification({
					userId: workspace.owner_id,
					type: activityType === "posted" ? "post_published" : "post_failed",
					title:
						activityType === "posted"
							? `Auto-posted to ${accountHandle}`
							: `Auto-post failed for ${accountHandle}`,
					message: message.substring(0, 200),
					data: { workspaceId, groupId, groupName, source: "auto-poster" },
				});
			}
		} catch (err) {
			logger.warn("Failed to create notification for auto-post activity", {
				workspaceId,
				activityType,
				error: String(err),
			});
			// Non-critical — don't fail the post over a notification error
		}
	}
}
