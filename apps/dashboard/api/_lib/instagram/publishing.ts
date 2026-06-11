/**
 * Instagram Publishing — container creation, status polling, and media publishing.
 * Includes postToInstagram (the main publish flow), checkContainerStatus, checkContainerReady,
 * publishContainer, checkPublishingLimit, deleteFromInstagram, toggleCommentEnabled, and deleteInstagramMedia.
 */

import {
	type ContainerStatus,
	decrypt,
	fetchContainerWithRetry,
	getGraphBaseUrl,
	IGApiError,
	type IGPostData,
	type IGPostingResult,
	igFetch,
	logger,
	mapIGError,
} from "./shared.js";

export function applyInstagramReelsAudioParams(
	params: Record<string, unknown>,
	postData: Pick<IGPostData, "mediaType" | "audioName" | "igAudioId">,
) {
	if (postData.mediaType !== "REELS") return;
	if (postData.audioName) {
		params.audio_name = postData.audioName;
	}
	if (postData.igAudioId) {
		params.audio_id = postData.igAudioId;
	}
}

export function instagramTrialParams(
	postData: Pick<
		IGPostData,
		"mediaType" | "trialReels" | "trialGraduationStrategy"
	>,
): { graduation_strategy: "MANUAL" | "SS_PERFORMANCE" } | undefined {
	if (!postData.trialReels || postData.mediaType !== "REELS") return undefined;
	if (!postData.trialGraduationStrategy) return undefined;
	return {
		graduation_strategy: postData.trialGraduationStrategy,
	};
}

// ============================================================================
// Container Status Polling
// ============================================================================

/**
 * Poll container status until FINISHED, ERROR, or timeout (5 minutes)
 */
export async function checkContainerStatus(
	token: string,
	containerId: string,
	loginType?: string,
): Promise<{ status: ContainerStatus; error?: string | undefined }> {
	const graphBase = getGraphBaseUrl(loginType);
	const maxAttempts = 60;
	// Progressive polling: 2s for first 5 attempts (covers most images),
	// then 5s for remaining attempts (videos/carousels take longer)
	const getPollInterval = (attempt: number) => (attempt < 5 ? 2000 : 5000);
	const statusUrl = `${graphBase}/v25.0/${containerId}?fields=status_code,status`;

	interface ContainerStatusResponse {
		status_code?: ContainerStatus | undefined;
		status?: string | undefined;
		error?: { message?: string | undefined } | undefined;
	}

	for (let attempt = 0; attempt < maxAttempts; attempt++) {
		// #471: Wrap individual poll iteration in try/catch for transient network errors.
		// igFetch already retries via withRetry, but if all retries fail on a single poll,
		// we retry the poll itself once before giving up (network blips during long polling).
		let data: ContainerStatusResponse;
		try {
			const response = await igFetch(
				statusUrl,
				undefined,
				"igApi:containerStatus",
				token,
			);
			data = (await response.json()) as ContainerStatusResponse;
		} catch (pollErr) {
			// Transient network error on this poll iteration — retry once after a short delay
			logger.warn("Container status poll failed, retrying once", {
				containerId,
				attempt,
				error: pollErr instanceof Error ? pollErr.message : String(pollErr),
			});
			await new Promise((resolve) => setTimeout(resolve, 2000));
			try {
				const retryResponse = await igFetch(
					statusUrl,
					undefined,
					"igApi:containerStatus",
					token,
				);
				data = (await retryResponse.json()) as ContainerStatusResponse;
			} catch (retryErr) {
				// Both attempts failed — return error so caller can decide what to do
				return {
					status: "ERROR" as ContainerStatus,
					error: `Network error polling container status: ${retryErr instanceof Error ? retryErr.message : String(retryErr)}`,
				};
			}
		}

		if (data.error) {
			return {
				status: "ERROR",
				error: data.error.message || "Failed to check container status",
			};
		}

		const status = data.status_code as ContainerStatus;

		if (status === "FINISHED") {
			return { status: "FINISHED" };
		}

		if (status === "ERROR") {
			return {
				status: "ERROR",
				error: data.status || "Container processing failed",
			};
		}

		if (status === "EXPIRED") {
			return { status: "EXPIRED", error: "Container expired" };
		}

		// IN_PROGRESS - wait and try again
		await new Promise((resolve) =>
			setTimeout(resolve, getPollInterval(attempt)),
		);
	}

	// All poll attempts exhausted — return TIMED_OUT (distinct from IN_PROGRESS)
	// so callers can differentiate a genuine timeout from an in-flight container.
	return {
		status: "TIMED_OUT",
		error: "Container polling timed out after 5 minutes",
	};
}

// ============================================================================
// Quick Container Status Check (non-blocking, for cron publisher)
// ============================================================================

/**
 * Check container status once without polling.
 * Used by ig-container-publisher cron to avoid blocking.
 */
export async function checkContainerReady(
	token: string,
	containerId: string,
	loginType?: string,
): Promise<{ status: "pending" | "ready" | "error"; error?: string | undefined }> {
	const graphBase = getGraphBaseUrl(loginType);
	const statusUrl = `${graphBase}/v25.0/${containerId}?fields=status_code,status`;
	const response = await igFetch(statusUrl, undefined, "igApi", token);
	const data = await response.json();

	if (data.error) {
		return {
			status: "error",
			error: data.error.message || "Status check failed",
		};
	}

	if (data.status_code === "FINISHED") return { status: "ready" };
	if (data.status_code === "ERROR")
		return {
			status: "error",
			error: data.status || "Container processing failed",
		};
	if (data.status_code === "EXPIRED")
		return { status: "error", error: "Container expired" };
	return { status: "pending" };
}

// ============================================================================
// Publish Container
// ============================================================================

/**
 * Publish a ready container to Instagram
 * Used for both immediate publishing and retry of timed-out containers
 */
export async function publishContainer(
	token: string,
	igUserId: string,
	containerId: string,
	loginType?: string,
): Promise<IGPostingResult> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const publishUrl = `${graphBase}/v25.0/${igUserId}/media_publish?creation_id=${containerId}`;

		// Retry publish up to 3 times on "still processing" (2207027/2207026).
		// Meta's status endpoint can report FINISHED before media is fully
		// propagated to the publish infrastructure — a short backoff resolves it.
		const MAX_PUBLISH_RETRIES = 3;
		const RETRY_DELAYS = [3000, 5000, 8000]; // 3s, 5s, 8s

		for (let attempt = 0; attempt <= MAX_PUBLISH_RETRIES; attempt++) {
			const publishResponse = await igFetch(
				publishUrl,
				{ method: "POST" },
				"igApi:publishContainer",
				token,
			);

			const publishData = await publishResponse.json();

			if (publishResponse.ok && !publishData.error) {
				logger.info("IG media published", { mediaId: publishData.id, attempt });

				// Fetch permalink for the published media
				let permalink: string | undefined;
				try {
					const mediaInfoRes = await igFetch(
						`${graphBase}/v25.0/${publishData.id}?fields=permalink`,
						{ method: "GET" },
						"igApi:getPermalink",
						token,
					);
					const mediaInfo = await mediaInfoRes.json();
					if (mediaInfo.permalink) {
						permalink = mediaInfo.permalink;
					}
				} catch (e) {
					logger.warn("Failed to fetch permalink after publish", {
						error: String(e),
					});
				}

				return {
					success: true,
					mediaId: publishData.id,
					permalink,
					timestamp: new Date(),
				};
			}

			// Check if "still processing" — retry with backoff
			const subcode = publishData?.error?.error_subcode;
			const isStillProcessing = subcode === 2207027 || subcode === 2207026;

			if (isStillProcessing && attempt < MAX_PUBLISH_RETRIES) {
				logger.info("IG publish: container still processing, retrying", {
					containerId,
					attempt: attempt + 1,
					delayMs: RETRY_DELAYS[attempt],
				});
				await new Promise((r) => setTimeout(r, RETRY_DELAYS[attempt]));
				continue;
			}

			// Non-retryable error or retries exhausted
			logger.error("IG publish error", {
				containerId,
				attempt,
				error: String(publishData?.error?.message || publishData),
				errorSubcode: subcode,
			});
			const mapped = publishData.error ? mapIGError(publishData.error) : null;
			return {
				success: false,
				containerId: isStillProcessing ? containerId : undefined,
				error:
					mapped?.userMessage ||
					publishData.error?.message ||
					"Failed to publish",
				retryable: mapped?.retryable,
				timestamp: new Date(),
			};
		}

		// Should not reach here, but safety fallback
		return {
			success: false,
			containerId,
			error: "Publish retries exhausted — container still processing",
			retryable: true,
			timestamp: new Date(),
		};
	} catch (error: unknown) {
		logger.error("IG publish container error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
			timestamp: new Date(),
		};
	}
}

// ============================================================================
// Post to Instagram
// ============================================================================

/**
 * Post to Instagram using the container-based publishing flow.
 *
 * Flow: create container -> poll status -> publish
 */
export async function postToInstagram(
	encryptedToken: string,
	igUserId: string,
	postData: IGPostData,
	encryptedFbPageToken?: string,
	loginType?: string,
): Promise<IGPostingResult> {
	try {
		// NOTE: IG rate limit check removed from this function (publishing pipeline audit).
		// Callers (scheduled-posts.ts, queue.ts, publishPost.ts) are responsible for checking
		// ig_check_and_increment_rate_limit BEFORE calling postToInstagram().
		// Adding a rate limit check here would double-count, halving the effective daily limit.

		const graphBase = getGraphBaseUrl(loginType);
		// Stories work with both login types:
		// - Instagram Login: uses IG user token directly (Business & Creator accounts)
		// - Facebook Login: uses Facebook Page token
		// Use Facebook Page token only for Facebook Login accounts with Stories
		const usePageToken =
			postData.mediaType === "STORIES" &&
			loginType === "facebook" &&
			encryptedFbPageToken;
		if (usePageToken && !encryptedFbPageToken) {
			throw new Error("Missing Facebook Page token for IG Stories publish");
		}
		const token = decrypt(usePageToken ? encryptedFbPageToken : encryptedToken);

		logger.info("Creating IG media container", {
			mediaType: postData.mediaType,
			igUserId,
			loginType,
		});

		// #story-validation: Stories must have exactly one media (image XOR video)
		if (postData.mediaType === "STORIES") {
			const hasImage = !!postData.imageUrl;
			const hasVideo = !!postData.videoUrl;
			if (!hasImage && !hasVideo) {
				return {
					success: false,
					error:
						"Instagram Stories require either an image or a video. Text-only stories are not supported.",
					timestamp: new Date(),
				};
			}
			if (hasImage && hasVideo) {
				return {
					success: false,
					error:
						"Instagram Stories support only one media item — provide either an image or a video, not both.",
					timestamp: new Date(),
				};
			}
		}

		if (postData.trialReels) {
			if (postData.mediaType !== "REELS") {
				return {
					success: false,
					error: "Instagram Trial Reels can only be published as Reels.",
					timestamp: new Date(),
				};
			}
			if (!postData.videoUrl || postData.imageUrl || postData.children?.length) {
				return {
					success: false,
					error: "Instagram Trial Reels require exactly one video.",
					timestamp: new Date(),
				};
			}
			if (!/\.(mp4|mov)(\?|$)/i.test(postData.videoUrl)) {
				return {
					success: false,
					error: "Instagram Trial Reels require an MP4 or MOV video URL.",
					timestamp: new Date(),
				};
			}
			if (postData.collaborators && postData.collaborators.length > 0) {
				return {
					success: false,
					error: "Instagram Trial Reels cannot include collaborators.",
					timestamp: new Date(),
				};
			}
		}

		// #429: Validate video codec/container format — Meta APIs only support H.264 in MP4/MOV
		// This is a URL-based heuristic (we can't inspect the actual codec without downloading).
		const INCOMPATIBLE_VIDEO_PATTERN =
			/\.(webm|avi|mkv|wmv|flv|3gp|ts|m4v|ogv)(\?|$)/i;
		const videoUrlToCheck = postData.videoUrl;
		if (videoUrlToCheck && INCOMPATIBLE_VIDEO_PATTERN.test(videoUrlToCheck)) {
			const ext =
				videoUrlToCheck.match(INCOMPATIBLE_VIDEO_PATTERN)?.[1]?.toUpperCase() ||
				"unknown";
			return {
				success: false,
				error: `Unsupported video format (.${ext}). Instagram requires H.264 video codec in MP4 or MOV containers. Please convert your video to .mp4 or .mov before uploading.`,
				timestamp: new Date(),
			};
		}

		// Also check carousel children for incompatible video formats
		if (postData.children) {
			for (const child of postData.children) {
				if (
					child.type === "video" &&
					INCOMPATIBLE_VIDEO_PATTERN.test(child.url)
				) {
					const ext =
						child.url.match(INCOMPATIBLE_VIDEO_PATTERN)?.[1]?.toUpperCase() ||
						"unknown";
					return {
						success: false,
						error: `Unsupported video format (.${ext}) in carousel item. Instagram requires H.264 video codec in MP4 or MOV containers. Please convert your video to .mp4 or .mov.`,
						timestamp: new Date(),
					};
				}
			}
		}

		// Validate image formats: Instagram supports JPEG, PNG, BMP — reject WebP early
		const UNSUPPORTED_IMAGE_PATTERN = /\.(webp)(\?|$)/i;

		if (postData.mediaType === "IMAGE") {
			const imageUrl = postData.imageUrl || "";
			if (UNSUPPORTED_IMAGE_PATTERN.test(imageUrl)) {
				return {
					success: false,
					error:
						"Instagram only supports JPEG images. Please convert your PNG/WebP to JPEG before uploading.",
					timestamp: new Date(),
				};
			}
		}

		if (postData.mediaType === "CAROUSEL" && postData.children) {
			for (const child of postData.children) {
				if (
					child.type === "image" &&
					UNSUPPORTED_IMAGE_PATTERN.test(child.url)
				) {
					return {
						success: false,
						error:
							"Instagram only supports JPEG images in carousels. Please convert PNG/WebP files to JPEG before uploading.",
						timestamp: new Date(),
					};
				}
			}
		}

		if (postData.mediaType === "STORIES" && postData.imageUrl) {
			if (UNSUPPORTED_IMAGE_PATTERN.test(postData.imageUrl)) {
				return {
					success: false,
					error:
						"Instagram Stories only support JPEG images. Please convert your PNG/WebP to JPEG before uploading.",
					timestamp: new Date(),
				};
			}
		}

		// Strip EXIF metadata from all image media before publishing (privacy: removes GPS, device info)
		{
			const { stripExifFromStorageUrl } = await import("../exifStrip.js");
			const exifTasks: Promise<string>[] = [];
			if (postData.imageUrl) {
				exifTasks.push(stripExifFromStorageUrl(postData.imageUrl));
			}
			if (postData.children) {
				for (const child of postData.children) {
					if (child.type === "image") {
						exifTasks.push(stripExifFromStorageUrl(child.url));
					}
				}
			}
			if (exifTasks.length > 0) {
				await Promise.all(exifTasks);
			}
		}

		let containerId: string | undefined;

		if (postData.mediaType === "CAROUSEL") {
			// Step 1a: Create child containers for carousel items
			if (
				!postData.children ||
				postData.children.length < 2 ||
				postData.children.length > 10
			) {
				return {
					success: false,
					error: "Carousel requires 2-10 media items",
					timestamp: new Date(),
				};
			}

			// Create all child containers in parallel (they are independent)
			const childContainerIds = await Promise.all(
				postData.children.map(async (child) => {
					const isImage = child.type === "image";
					// Per Meta API docs: is_carousel_item is boolean, not string
					const childParams: Record<string, unknown> = {
						is_carousel_item: true,
					};
					if (isImage) {
						childParams.image_url = child.url;
						if (child.altText) childParams.alt_text = child.altText;
					} else {
						childParams.video_url = child.url;
						childParams.media_type = "VIDEO";
					}

					const result = await fetchContainerWithRetry(
						`${graphBase}/v25.0/${igUserId}/media`,
						{
							method: "POST",
							headers: { "Content-Type": "application/json" },
							body: JSON.stringify(childParams),
						},
						"igApi:carouselChild",
						token,
					);
					if (!result.ok) {
						const childData = result.data;
						logger.error("IG carousel child container error", {
							childIndex: postData.children?.indexOf(child),
							mediaUrl: child.url?.substring(0, 120),
							mediaType: child.type,
							errorCode: (childData?.error as Record<string, unknown>)?.code,
							errorSubcode: (childData?.error as Record<string, unknown>)
								?.error_subcode,
							errorType: (childData?.error as Record<string, unknown>)?.type,
							errorCategory: result.classified?.category,
							error: String(
								(childData?.error as Record<string, unknown>)?.message ||
									childData,
							),
						});
						const mapped = childData.error
							? mapIGError(
									childData.error as {
										message?: string | undefined;
										type?: string | undefined;
										code?: number | undefined;
										error_subcode?: number | undefined;
									},
								)
							: null;
						throw new Error(
							mapped?.userMessage ||
								((childData?.error as Record<string, unknown>)
									?.message as string) ||
								"Failed to create carousel child container",
						);
					}
					return result.data.id as string;
				}),
			).catch((err) => {
				// Note: any already-created containers will expire after 24h
				logger.warn(
					"Carousel child creation failed — orphaned containers may exist",
					{
						error: err.message,
					},
				);
				throw err;
			});

			// Poll all children in parallel
			const pollResults = await Promise.all(
				childContainerIds.map((id) =>
					checkContainerStatus(token, id, loginType),
				),
			);
			const failedPoll = pollResults.find((r) => r.status !== "FINISHED");
			if (failedPoll) {
				logger.warn("Carousel child polling failed — orphaned containers", {
					orphanedContainerIds: childContainerIds,
					failedStatus: failedPoll.status,
					failedError: failedPoll.error,
				});
				return {
					success: false,
					error: `Carousel child failed: ${failedPoll.error}`,
					timestamp: new Date(),
				};
			}

			// Step 1b: Create carousel container
			// children must be an array when posting JSON (per Meta API docs)
			const carouselParamsObj: Record<string, unknown> = {
				media_type: "CAROUSEL",
				caption: postData.caption,
				children: childContainerIds,
			};
			if (postData.locationId) {
				carouselParamsObj.location_id = postData.locationId;
			}
			// Add collaborators (up to 3 per Meta API limit)
			if (postData.collaborators && postData.collaborators.length > 0) {
				carouselParamsObj.collaborators = postData.collaborators
					.slice(0, 3)
					.join(",");
			}
			// Product tags on carousel (max 5)
			if (postData.productTags && postData.productTags.length > 0) {
				carouselParamsObj.product_tags = JSON.stringify(
					postData.productTags.slice(0, 5),
				);
			}
			if (postData.isPaidPartnership) {
				carouselParamsObj.is_paid_partnership = true;
			}
			if (
				postData.brandedContentSponsorIds &&
				postData.brandedContentSponsorIds.length > 0
			) {
				carouselParamsObj.branded_content_sponsor_ids =
					postData.brandedContentSponsorIds.slice(0, 2).join(",");
			}
			const carouselResponse = await igFetch(
				`${graphBase}/v25.0/${igUserId}/media`,
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify(carouselParamsObj),
				},
				"igApi:carouselContainer",
				token,
			);

			const carouselData = await carouselResponse.json();

			if (!carouselResponse.ok || carouselData.error) {
				logger.error("IG carousel parent container error", {
					childCount: childContainerIds.length,
					errorCode: carouselData?.error?.code,
					errorSubcode: carouselData?.error?.error_subcode,
					errorType: carouselData?.error?.type,
					error: String(carouselData?.error?.message || carouselData),
				});
				const mapped = carouselData.error
					? mapIGError(carouselData.error)
					: null;
				return {
					success: false,
					error:
						mapped?.userMessage ||
						carouselData.error?.message ||
						"Failed to create carousel container",
					timestamp: new Date(),
				};
			}

			containerId = carouselData.id;
		} else {
			// Single media container (IMAGE, VIDEO, REELS, STORIES)
			const params: Record<string, unknown> = {
				caption: postData.caption,
			};

			if (postData.mediaType === "IMAGE") {
				params.image_url = postData.imageUrl || "";
				if (postData.altText) {
					params.alt_text = postData.altText;
				}
			} else if (
				postData.mediaType === "VIDEO" ||
				postData.mediaType === "REELS"
			) {
				params.media_type = postData.mediaType;

				// #480: Validate video duration — Reels: 3s–15min, Feed Video: max 600s
				if (postData.duration) {
					const dur = postData.duration;
					if (postData.mediaType === "REELS" && (dur < 3 || dur > 900)) {
						return {
							success: false,
							error: `Reel duration must be 3 seconds – 15 minutes (got ${Math.round(dur)}s).`,
							timestamp: new Date(),
						};
					}
					if (postData.mediaType === "VIDEO" && dur > 600) {
						return {
							success: false,
							error: `Video too long for Instagram Feed (${Math.round(dur)}s). Maximum is 10 minutes (600s).`,
							timestamp: new Date(),
						};
					}
				}

				// Auto-detect large videos (>50MB) for resumable upload, or use if forced
				let useResumable = postData.useResumableUpload || false;
				if (!useResumable && postData.videoUrl) {
					try {
						const { shouldUseResumableUpload } = await import(
							"../ruploadService.js"
						);
						useResumable = await shouldUseResumableUpload(postData.videoUrl);
					} catch {
						// Check failed — proceed with standard upload
					}
				}

				if (useResumable && postData.videoUrl) {
					logger.info("Using resumable upload for large video", {
						mediaType: postData.mediaType,
						igUserId,
					});
					const { uploadVideoResumable } = await import("../ruploadService.js");
					const uploadResult = await uploadVideoResumable(token, igUserId, {
						videoUrl: postData.videoUrl,
					});
					if (!uploadResult.success || !uploadResult.uploadHandle) {
						return {
							success: false,
							error: uploadResult.error || "Resumable video upload failed",
							timestamp: new Date(),
						};
					}
					// Upload handle is the container ID — skip standard creation
					containerId = uploadResult.uploadHandle;
					logger.info("Resumable upload container ready", { containerId });
				} else {
					// Standard URL-based upload
					params.video_url = postData.videoUrl || "";
				}

				if (postData.coverUrl && postData.mediaType === "REELS") {
					params.cover_url = postData.coverUrl;
				}
				const trialParams = instagramTrialParams(postData);
				if (trialParams) {
					params.trial_params = trialParams;
				}
				if (
					postData.shareToFeed !== undefined &&
					postData.mediaType === "REELS"
				) {
					params.share_to_feed = String(postData.shareToFeed);
				}
			} else if (postData.mediaType === "STORIES") {
				params.media_type = "STORIES";
				if (postData.imageUrl) {
					params.image_url = postData.imageUrl;
				} else if (postData.videoUrl) {
					params.video_url = postData.videoUrl;
				}
				// Stories don't support captions
				delete params.caption;
			}

			// Add location if provided (not supported for Stories)
			if (postData.locationId && postData.mediaType !== "STORIES") {
				params.location_id = postData.locationId;
			}

			// Add collaborators (up to 3 per Meta API limit, not for Stories)
			if (
				postData.collaborators &&
				postData.collaborators.length > 0 &&
				postData.mediaType !== "STORIES"
			) {
				params.collaborators = postData.collaborators.slice(0, 3).join(",");
			}

			// Add user tags (images and Stories only — not supported on carousel children or videos)
			if (postData.userTags && postData.userTags.length > 0) {
				if (
					postData.mediaType === "IMAGE" ||
					postData.mediaType === "STORIES"
				) {
					params.user_tags = JSON.stringify(postData.userTags);
				}
			}

			// Thumb offset — pick a specific video frame as cover thumbnail (Reels/Video)
			if (postData.thumbOffset !== undefined && postData.thumbOffset > 0) {
				if (postData.mediaType === "REELS" || postData.mediaType === "VIDEO") {
					params.thumb_offset = String(postData.thumbOffset);
				}
			}

			applyInstagramReelsAudioParams(params, postData);

			// Product tags — tag products from IG Shop (max 5, images/videos only)
			if (
				postData.productTags &&
				postData.productTags.length > 0 &&
				postData.mediaType !== "STORIES"
			) {
				params.product_tags = JSON.stringify(postData.productTags.slice(0, 5));
			}

			if (postData.isPaidPartnership && postData.mediaType !== "STORIES") {
				params.is_paid_partnership = "true";
			}
			if (
				postData.brandedContentSponsorIds &&
				postData.brandedContentSponsorIds.length > 0 &&
				postData.mediaType !== "STORIES"
			) {
				params.branded_content_sponsor_ids = postData.brandedContentSponsorIds
					.slice(0, 2)
					.join(",");
			}

			// Skip standard container creation if resumable upload already set containerId
			if (!containerId) {
				const result = await fetchContainerWithRetry(
					`${graphBase}/v25.0/${igUserId}/media`,
					{
						method: "POST",
						headers: { "Content-Type": "application/json" },
						body: JSON.stringify(params),
					},
					"igApi:mediaContainer",
					token,
				);

				if (!result.ok) {
					const containerData = result.data;
					logger.error("IG container creation error", {
						error: String(
							(containerData?.error as Record<string, unknown>)?.message ||
								containerData,
						),
						errorCategory: result.classified?.category,
						retryable: result.classified?.retryable,
					});
					const mapped = containerData.error
						? mapIGError(
								containerData.error as {
									message?: string | undefined;
									type?: string | undefined;
									code?: number | undefined;
									error_subcode?: number | undefined;
								},
							)
						: null;
					return {
						success: false,
						error:
							mapped?.userMessage ||
							((containerData?.error as Record<string, unknown>)
								?.message as string) ||
							"Failed to create media container",
						retryable: result.classified?.retryable ?? true,
						timestamp: new Date(),
					};
				}

				containerId = result.data.id as string;
			}
		}

		logger.info("IG container created", { containerId });

		if (!containerId) {
			return {
				success: false,
				error: "No container ID returned",
				timestamp: new Date(),
			};
		}

		// Step 2: Poll container status (with timeout awareness)
		const statusResult = await checkContainerStatus(
			token,
			containerId,
			loginType,
		);
		if (statusResult.status !== "FINISHED") {
			// IN_PROGRESS: container still processing within the poll window
			// TIMED_OUT: poll loop exhausted but container still exists — retry later
			if (
				statusResult.status === "IN_PROGRESS" ||
				statusResult.status === "TIMED_OUT"
			) {
				logger.info("IG container still processing, returning for retry", {
					containerId,
				});
				return {
					success: false,
					error: `Container still processing: ${statusResult.error}`,
					containerId, // Return container ID for retry
					timestamp: new Date(),
				};
			}
			return {
				success: false,
				error: `Container processing failed: ${statusResult.error}`,
				timestamp: new Date(),
			};
		}

		// Step 2.5: Copyright check for video/reel content (non-blocking)
		if (postData.mediaType === "VIDEO" || postData.mediaType === "REELS") {
			try {
				const copyrightUrl = `${graphBase}/v25.0/${containerId}?fields=copyright_check_status`;
				const copyrightRes = await igFetch(
					copyrightUrl,
					undefined,
					"igApi:copyrightCheck",
					token,
				);
				const copyrightData = await copyrightRes.json();
				const copyrightStatus = copyrightData.copyright_check_status;
				if (copyrightStatus?.matches_found === true) {
					return {
						success: false,
						error:
							"Copyright violation detected. This video contains copyrighted content and cannot be published. Please use original audio/video.",
						timestamp: new Date(),
					};
				}
			} catch (copyrightErr) {
				logger.warn("Copyright check failed (non-critical)", {
					error: String(copyrightErr),
				});
			}
		}

		// Step 3: Publish
		const publishResult = await publishContainer(
			token,
			igUserId,
			containerId,
			loginType,
		);

		// Step 4: Post-publish toggles (fire-and-forget)
		if (publishResult.success && publishResult.mediaId) {
			// Disable comments if requested
			if (postData.commentEnabled === false) {
				try {
					await toggleCommentEnabled(
						encryptedToken,
						publishResult.mediaId,
						false,
						loginType,
					);
				} catch (err) {
					logger.warn("Failed to disable comments post-publish", {
						error: String(err),
					});
				}
			}
			if (postData.firstComment?.trim()) {
				try {
					const graphBase = getGraphBaseUrl(loginType);
					const tokenForComment = decrypt(encryptedToken);
					const response = await igFetch(
						`${graphBase}/v25.0/${publishResult.mediaId}/comments`,
						{
							method: "POST",
							headers: { "Content-Type": "application/json" },
							body: JSON.stringify({ message: postData.firstComment.trim() }),
						},
						"igApi:firstComment",
						tokenForComment,
					);
					const data = await response.json();
					if (!response.ok || data.error) {
						logger.warn("Failed to add first comment post-publish", {
							error: data.error?.message || "Unknown error",
						});
					}
				} catch (err) {
					logger.warn("Failed to add first comment post-publish", {
						error: String(err),
					});
				}
			}
		}

		return publishResult;
	} catch (error: unknown) {
		logger.error("IG post error", { error: String(error) });
		if (error instanceof IGApiError) {
			return {
				success: false,
				error: error.userMessage,
				retryable: error.retryable,
				timestamp: new Date(),
			};
		}
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
			retryable: true, // Unknown errors should be retried
			timestamp: new Date(),
		};
	}
}

// ============================================================================
// Delete from Instagram
// ============================================================================

export async function deleteFromInstagram(
	_encryptedToken: string,
	_mediaId: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	// Instagram API does not support deleting media via API.
	// Deletes must be performed manually through the Instagram app.
	// We only remove the post from our database (handled by the caller).
	logger.warn(
		"Instagram does not support API deletes — post removed from dashboard only",
	);
	return { success: true };
}

// ============================================================================
// Check Publishing Limit
// ============================================================================

export async function checkPublishingLimit(
	encryptedToken: string,
	igUserId: string,
	loginType?: string,
): Promise<{
	success: boolean;
	quota?: { usage: number; limit: number; remaining: number; windowHours: number } | undefined;
	error?: string | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const limitUrl = `${graphBase}/v25.0/${igUserId}/content_publishing_limit?fields=config,quota_usage`;
		const limitResponse = await igFetch(
			limitUrl,
			undefined,
			"igApi:publishingLimit",
			token,
		);
		const limitData = await limitResponse.json();

		if (!limitResponse.ok || limitData.error) {
			logger.error("IG publishing limit error", {
				error: String(limitData?.error?.message || limitData),
			});
			return {
				success: false,
				error: limitData.error?.message || "Failed to check publishing limit",
			};
		}

		const rawUsage = Number(limitData.data?.[0]?.quota_usage || 0);
		const rawLimit = Number(limitData.data?.[0]?.config?.quota_total || 100);
		const limit = loginType === "facebook" ? Math.min(rawLimit, 50) : rawLimit;

		return {
			success: true,
			quota: {
				usage: rawUsage,
				limit,
				remaining: Math.max(0, limit - rawUsage),
				windowHours: 24,
			},
		};
	} catch (error: unknown) {
		logger.error("IG publishing limit error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Delete Media (Dec 2025)
// ============================================================================

export async function deleteInstagramMedia(
	encryptedToken: string,
	mediaId: string,
	loginType?: string,
): Promise<{ success: boolean; error?: string | undefined; code?: string | undefined }> {
	// Media deletion is only supported via Facebook Login (graph.facebook.com)
	if (loginType !== "facebook") {
		return {
			success: false,
			code: "media_deletion_unsupported_on_ig_login",
			error:
				"Media deletion is only available for accounts connected via Facebook Login.",
		};
	}

	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const response = await igFetch(
			`${graphBase}/v25.0/${mediaId}`,
			{ method: "DELETE" },
			"igApi:deleteMedia",
			token,
		);

		const data = await response.json();

		if (!response.ok || data.error) {
			const mapped = data.error ? mapIGError(data.error) : null;
			return {
				success: false,
				error:
					mapped?.userMessage ||
					data.error?.message ||
					"Failed to delete media",
			};
		}

		return { success: true };
	} catch (error: unknown) {
		logger.error("IG deleteMedia error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Toggle Comments on Media
// ============================================================================

export async function toggleCommentEnabled(
	encryptedToken: string,
	mediaId: string,
	enabled: boolean,
	loginType?: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const response = await igFetch(
			`${graphBase}/v25.0/${mediaId}`,
			{
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ comment_enabled: enabled }),
			},
			"igApi:toggleCommentEnabled",
			token,
		);

		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to toggle comments",
			};
		}

		return { success: true };
	} catch (error: unknown) {
		logger.error("IG toggleCommentEnabled error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}
