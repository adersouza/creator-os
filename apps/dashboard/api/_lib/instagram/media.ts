/**
 * Instagram Media Operations — user media retrieval, stories, saved media,
 * tagged media, mentioned media, and mentions reply.
 */

import {
	decrypt,
	getGraphBaseUrl,
	type IGMediaItem,
	type IGStory,
	igFetch,
	logger,
} from "./shared.js";

const IG_MEDIA_PUBLIC_FIELDS = [
	"id",
	"caption",
	"media_type",
	"media_url",
	"permalink",
	"timestamp",
	"thumbnail_url",
	"username",
	"like_count",
	"comments_count",
];

const IG_MEDIA_FACEBOOK_LOGIN_FIELDS = [
	"media_audio_type",
	"media_product_type",
	"reposts_count",
	"saved_count",
	"shares_count",
	"total_like_count",
	"total_comments_count",
	"total_views_count",
	"view_count",
];

function getMediaListFields(
	loginType?: string,
	includeFacebookLoginFields = true,
) {
	return [
		...IG_MEDIA_PUBLIC_FIELDS,
		...(loginType === "facebook" && includeFacebookLoginFields
			? IG_MEDIA_FACEBOOK_LOGIN_FIELDS
			: []),
	].join(",");
}

// ============================================================================
// Get User's Stories
// ============================================================================

/**
 * Get user's active stories (within last 24 hours)
 */
export async function getInstagramStories(
	encryptedToken: string,
	igUserId: string,
	loginType?: string,
): Promise<{
	success: boolean;
	stories?: IGStory[] | undefined;
	error?: string | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		// Fetch stories from the stories edge
		const storiesUrl = `${graphBase}/v25.0/${igUserId}/stories?fields=id,media_type,media_url,timestamp,permalink`;

		logger.info("IG getStories", { igUserId, loginType });

		const response = await igFetch(
			storiesUrl,
			undefined,
			"igApi:getStories",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			logger.error("IG stories fetch error", {
				error: JSON.stringify(data.error || data),
			});
			return {
				success: false,
				error: data.error?.message || "Failed to fetch stories",
			};
		}

		const stories: IGStory[] = data.data || [];
		logger.info("IG stories found", { count: stories.length });

		return { success: true, stories };
	} catch (error: unknown) {
		logger.error("IG get stories error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Get User's Own Media (for analytics sync)
// ============================================================================

export async function getUserMedia(
	encryptedToken: string,
	igUserId: string,
	maxPosts: number = 50,
	loginType?: string,
): Promise<{
	success: boolean;
	media?: IGMediaItem[] | undefined;
	error?: string | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		// media_product_type is required to distinguish Reels from feed videos —
		// without it, every IG video syncs as ig_media_type=VIDEO and the
		// per-post insight call falls back to POST_INSIGHT_METRICS, dropping
		// reels_skip_rate / ig_reels_avg_watch_time which the dashboard
		// HookStrength + WatchPerView tiles depend on. Those richer fields are
		// Facebook Login-only, so Instagram Login accounts use the public set.
		let activeFields = getMediaListFields(loginType);
		const fallbackFields = getMediaListFields(loginType, false);

		const allMedia: IGMediaItem[] = [];
		let cursor: string | null = null;
		const maxPages = Math.ceil(maxPosts / 25);
		let pageCount = 0;

		while (pageCount < maxPages) {
			let url = `${graphBase}/v25.0/${igUserId}/media?fields=${activeFields},children{id,media_type,media_url,timestamp}&limit=25`;
			if (cursor) url += `&after=${cursor}`;

			const response = await igFetch(
				url,
				undefined,
				"igApi:getUserMedia",
				token,
			);
			const data = await response.json();

			if (!response.ok || data.error) {
				logger.error("IG getUserMedia error", {
					page: pageCount,
					status: response.status,
					error: JSON.stringify(data.error || data),
				});
				if (allMedia.length === 0 && activeFields !== fallbackFields) {
					logger.warn("IG getUserMedia retrying with public fields only", {
						igUserId,
						loginType,
					});
					activeFields = fallbackFields;
					cursor = null;
					pageCount = 0;
					continue;
				}
				if (allMedia.length > 0) break; // Return what we have
				return {
					success: false,
					error: data.error?.message || `API returned ${response.status}`,
				};
			}

			if (data.data && data.data.length > 0) {
				const mediaTypes = (data.data as IGMediaItem[]).map(
					(m) => m.media_type,
				);
				logger.info("IG getUserMedia page received", {
					page: pageCount,
					mediaTypes,
				});

				if (pageCount === 0 && data.data.length > 0) {
					const first = data.data[0];
					const last = data.data[data.data.length - 1];
					logger.info("IG getUserMedia range", {
						firstId: first.id,
						firstTimestamp: first.timestamp,
						firstType: first.media_type,
						lastId: last.id,
						lastTimestamp: last.timestamp,
						lastType: last.media_type,
					});
				}

				allMedia.push(...data.data);
			} else {
				logger.info("IG getUserMedia empty data array", {
					rawResponse: JSON.stringify(data).slice(0, 1000),
				});
			}

			cursor = data.paging?.cursors?.after || null;
			logger.info("IG getUserMedia pagination", {
				hasCursor: !!cursor,
				totalSoFar: allMedia.length,
			});

			if (!cursor || allMedia.length >= maxPosts) break;
			pageCount++;
		}

		logger.info("IG getUserMedia complete", {
			totalMedia: allMedia.length,
			pages: pageCount + 1,
		});
		return { success: true, media: allMedia.slice(0, maxPosts) };
	} catch (error: unknown) {
		const message = error instanceof Error ? error.message : String(error);
		logger.error("IG getUserMedia exception", {
			error: message,
			stack: error instanceof Error ? error.stack : undefined,
		});
		return { success: false, error: message || "Failed to fetch user media" };
	}
}

// ============================================================================
// Collaborative Media
// ============================================================================

/**
 * Fetch media where the app user is an accepted collaborator.
 */
export async function getCollaborativeMedia(
	encryptedToken: string,
	igUserId: string,
	loginType?: string,
	limit = 25,
): Promise<{
	success: boolean;
	media?: IGMediaItem[] | undefined;
	error?: string | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const safeLimit = Math.min(Math.max(limit, 1), 100);
		const url = `${graphBase}/v25.0/${igUserId}/collaborative_media?fields=${getMediaListFields(loginType)}&limit=${safeLimit}`;

		const response = await igFetch(
			url,
			undefined,
			"igApi:collaborativeMedia",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to fetch collaborative media",
			};
		}

		return { success: true, media: data.data || [] };
	} catch (error: unknown) {
		logger.error("IG getCollaborativeMedia error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

/**
 * Search for a specific collaborative media item.
 */
export async function searchCollaborativeMedia(
	encryptedToken: string,
	igUserId: string,
	mediaId: string,
	loginType?: string,
): Promise<{
	success: boolean;
	media?: IGMediaItem | null | undefined;
	error?: string | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const fields = `collaborative_media_search.media_id(${mediaId}){${getMediaListFields(loginType)}}`;
		const url = `${graphBase}/v25.0/${igUserId}?fields=${encodeURIComponent(fields)}`;

		const response = await igFetch(
			url,
			undefined,
			"igApi:collaborativeMediaSearch",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to search collaborative media",
			};
		}

		return {
			success: true,
			media: data.collaborative_media_search || null,
		};
	} catch (error: unknown) {
		logger.error("IG searchCollaborativeMedia error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Likes
// ============================================================================

export async function setInstagramLike(
	encryptedToken: string,
	igUserId: string,
	target: { mediaId?: string | undefined; commentId?: string | undefined },
	liked: boolean,
	loginType?: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const body = new URLSearchParams();
		if (target.mediaId) body.set("media_id", target.mediaId);
		if (target.commentId) body.set("comment_id", target.commentId);

		if (!body.has("media_id") && !body.has("comment_id")) {
			return { success: false, error: "mediaId or commentId is required" };
		}

		const response = await igFetch(
			`${graphBase}/v25.0/${igUserId}/likes`,
			{
				method: liked ? "POST" : "DELETE",
				headers: { "Content-Type": "application/x-www-form-urlencoded" },
				body,
			},
			liked ? "igApi:like" : "igApi:unlike",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to update like",
			};
		}

		return { success: true };
	} catch (error: unknown) {
		logger.error("IG setInstagramLike error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Saved Media
// ============================================================================

/**
 * Get saved media for an IG professional account.
 * Requires `instagram_manage_saved_media` permission.
 * GET /{ig-user-id}/saved_media?fields=id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,username
 */
export async function getSavedMedia(
	encryptedToken: string,
	igUserId: string,
	loginType?: string,
	limit = 30,
): Promise<{
	success: boolean;
	media?: IGMediaItem[] | undefined;
	error?: string | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const fields =
			"id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,username,like_count,comments_count";
		const url = `${graphBase}/v25.0/${igUserId}/saved_media?fields=${fields}&limit=${limit}`;

		const response = await igFetch(url, undefined, "igApi:savedMedia", token);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to fetch saved media",
			};
		}

		return { success: true, media: data.data || [] };
	} catch (error: unknown) {
		logger.error("IG getSavedMedia error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Tagged Media
// ============================================================================

/**
 * Get media in which the user has been tagged by another user.
 * Facebook Login only (requires instagram_basic + instagram_manage_comments + pages_read_engagement).
 */
export async function getTaggedMedia(
	encryptedToken: string,
	igUserId: string,
	loginType?: string,
): Promise<{
	success: boolean;
	media?: IGMediaItem[] | undefined;
	error?: string | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const url = `${graphBase}/v25.0/${igUserId}/tags?fields=id,caption,media_type,media_url,permalink,timestamp,username`;

		const response = await igFetch(url, undefined, "igApi:taggedMedia", token);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to fetch tagged media",
			};
		}

		return { success: true, media: data.data || [] };
	} catch (error: unknown) {
		logger.error("IG getTaggedMedia error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Mentioned Media
// ============================================================================

/**
 * Get data on an IG Media in which the user was @mentioned in a caption.
 * Per Meta docs, this requires a specific media_id (from webhook payload).
 * There is no "list all mentions" edge — each lookup is per media_id.
 * Facebook Login only (requires instagram_basic + instagram_manage_comments + pages_read_engagement).
 */
export async function getMentionedMedia(
	encryptedToken: string,
	igUserId: string,
	mediaId: string,
	loginType?: string,
): Promise<{
	success: boolean;
	media?: IGMediaItem | undefined;
	error?: string | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const url = `${graphBase}/v25.0/${igUserId}?fields=mentioned_media.media_id(${mediaId}){id,caption,media_type,media_url,permalink,timestamp,username}`;

		const response = await igFetch(
			url,
			undefined,
			"igApi:mentionedMedia",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to fetch mentioned media",
			};
		}

		return { success: true, media: data.mentioned_media };
	} catch (error: unknown) {
		logger.error("IG getMentionedMedia error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Reply to @Mention (caption or comment)
// ============================================================================

/**
 * Reply to a comment or media caption in which the user was @mentioned.
 * POST /{ig-user-id}/mentions — uses query params per Meta docs.
 * Permissions: instagram_business_basic, instagram_business_manage_comments
 */
export async function replyToMention(
	encryptedToken: string,
	igUserId: string,
	mediaId: string,
	message: string,
	commentId?: string,
	loginType?: string,
): Promise<{
	success: boolean;
	commentId?: string | undefined;
	error?: string | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const url = `${graphBase}/v25.0/${igUserId}/mentions`;
		const body = new URLSearchParams({ media_id: mediaId, message });
		if (commentId) {
			body.append("comment_id", commentId);
		}

		const response = await igFetch(
			url,
			{ method: "POST", body },
			"igApi:replyToMention",
			token,
		);

		const data = await response.json();
		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to reply to mention",
			};
		}
		return { success: true, commentId: data.id };
	} catch (error: unknown) {
		logger.error("IG replyToMention error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}
