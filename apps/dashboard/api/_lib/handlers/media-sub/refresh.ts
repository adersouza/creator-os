// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Media Refresh API Route
 * POST /api/media-refresh
 *
 * Refreshes expired CDN media URLs by fetching fresh URLs from Threads API
 * and storing them permanently in Supabase Storage.
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import { decrypt } from "../../encryption.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import {
	fetchAllowedMediaUrl,
	isAllowedPlatformMediaUrl,
	isAllowedSupabasePublicUrl,
} from "../../outboundUrlSecurity.js";
import {
	getPrivilegedSupabase,
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "../../privilegedDb.js";
import { withRetry } from "../../retryUtils.js";
import { z } from "../../zodCompat.js";

const MediaRefreshSchema = z.object({
	postId: z.string().min(1, "postId is required"),
});

// ============================================================================
// Supabase client
// ============================================================================

// ============================================================================
// Type Definitions
// ============================================================================

interface PostData {
	id: string;
	user_id: string;
	account_id: string;
	instagram_account_id: string | null;
	threads_post_id: string | null;
	instagram_post_id: string | null;
	platform: string | null;
	media_urls: string[] | null;
}

// ============================================================================
// Media Storage Functions
// ============================================================================

const BUCKET_NAME = "post-media";
const db = () => getPrivilegedSupabase(PRIVILEGED_DB_REASONS.mediaRefresh);
const dbAny = () =>
	getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.mediaRefresh);

function getExtensionFromContentType(contentType: string): string {
	const map: Record<string, string> = {
		"image/jpeg": "jpg",
		"image/jpg": "jpg",
		"image/png": "png",
		"image/gif": "gif",
		"image/webp": "webp",
		"video/mp4": "mp4",
		"video/quicktime": "mov",
		"video/webm": "webm",
	};
	return map[contentType.split(";")[0]!] || "jpg";
}

async function storeMediaFromUrl(
	sourceUrl: string,
	userId: string,
	postId: string,
	mediaIndex: number = 0,
): Promise<string | null> {
	try {
		if (sourceUrl.includes("supabase")) {
			return sourceUrl;
		}

		if (
			!isAllowedPlatformMediaUrl(sourceUrl) &&
			!isAllowedSupabasePublicUrl(sourceUrl)
		) {
			logger.error("Blocked media fetch from untrusted domain", {
				url: sourceUrl.substring(0, 200),
			});
			return null;
		}

		const response = await fetchAllowedMediaUrl(sourceUrl, {
			method: "GET",
			signal: AbortSignal.timeout(15000),
		});
		if (!response?.ok) {
			logger.error("Failed to download media", { status: response?.status });
			return null;
		}

		const contentType = response.headers.get("content-type") || "image/jpeg";
		const contentLength = parseInt(
			response.headers.get("content-length") || "0",
			10,
		);
		const MAX_MEDIA_SIZE = 100 * 1024 * 1024; // 100MB max for refreshed media
		if (contentLength > MAX_MEDIA_SIZE) {
			logger.error("Media too large to store", { contentLength });
			return null;
		}

		const extension = getExtensionFromContentType(contentType);
		const filename = `${userId}/${postId}/${mediaIndex}.${extension}`;

		const arrayBuffer = await response.arrayBuffer();
		if (arrayBuffer.byteLength > MAX_MEDIA_SIZE) {
			logger.error("Downloaded media exceeds size limit", {
				size: arrayBuffer.byteLength,
			});
			return null;
		}
		let buffer: Buffer = Buffer.from(new Uint8Array(arrayBuffer));

		// Strip EXIF metadata from JPEG images (removes GPS, device info, timestamps)
		if (contentType.includes("jpeg") || contentType.includes("jpg")) {
			try {
				const { stripExifFromBuffer } = await import("../../exifStrip.js");
				buffer = stripExifFromBuffer(buffer);
			} catch (stripErr) {
				logger.warn(
					"[media-refresh] EXIF strip failed, uploading with metadata",
					{
						error: String(stripErr),
					},
				);
			}
		}

		const { error } = await db()
			.storage.from(BUCKET_NAME)
			.upload(filename, buffer, {
				contentType,
				upsert: true,
			});

		if (error) {
			logger.error("Failed to upload media to storage", {
				error: String(error),
			});
			return null;
		}

		const { data: urlData } = db()
			.storage.from(BUCKET_NAME)
			.getPublicUrl(filename);

		return urlData?.publicUrl || null;
	} catch (err) {
		logger.error("Failed to store media from URL", { error: String(err) });
		return null;
	}
}

// ============================================================================
// Handler
// ============================================================================

export default withAuth(async (req, res, user) => {
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	try {
		const parsed = MediaRefreshSchema.safeParse(req.body);
		if (!parsed.success) {
			return apiError(
				res,
				400,
				`Invalid input: ${parsed.error.issues[0]?.message}`,
			);
		}

		const { postId } = parsed.data;

		// All posts (Threads + Instagram) are in the posts table
		const { data: postData, error: postError } = await db()
			.from("posts")
			.select(
				"id, user_id, account_id, instagram_account_id, threads_post_id, instagram_post_id, platform, media_urls",
			)
			.eq("id", postId)
			.eq("user_id", user.id)
			.maybeSingle();

		const post = postData as PostData | null;

		if (postError || !post) {
			return apiError(res, 404, "Post not found");
		}

		const isInstagramPost =
			post.platform === "instagram" || !!post.instagram_post_id;
		const platformPostId = isInstagramPost
			? post.instagram_post_id
			: post.threads_post_id;

		if (!platformPostId) {
			return apiError(res, 400, "Post has no platform ID for refresh");
		}

		// Check if already using Supabase URLs
		const currentUrls = (post.media_urls as string[]) || [];
		const allSupabase = currentUrls.every((url) => url?.includes("supabase"));

		if (allSupabase && currentUrls.length > 0) {
			// Already permanent URLs, return them
			return apiSuccess(res, {
				mediaUrls: currentUrls,
				refreshed: false,
			});
		}

		// Get account access token
		let accessToken: string;
		let apiHost: string;

		if (isInstagramPost) {
			const igAccountId = post.instagram_account_id || post.account_id;
			const { data: igAccount, error: igError } = await db()
				.from("instagram_accounts")
				.select("id, instagram_access_token_encrypted, login_type")
				.eq("id", igAccountId)
				.eq("user_id", user.id)
				.maybeSingle();

			if (igError || !igAccount?.instagram_access_token_encrypted) {
				return apiError(res, 400, "Instagram account token not available");
			}

			try {
				accessToken = decrypt(igAccount.instagram_access_token_encrypted);
			} catch (decryptError) {
				logger.error("Token decryption failed", {
					error: String(decryptError),
				});
				return apiError(res, 500, "Failed to decrypt access token");
			}

			const loginType = igAccount.login_type || "instagram";
			apiHost =
				loginType === "facebook"
					? "graph.facebook.com/v25.0"
					: "graph.instagram.com/v25.0";
		} else {
			const { data: account, error: accError } = await db()
				.from("accounts")
				.select("id, threads_access_token_encrypted")
				.eq("id", post.account_id)
				.eq("user_id", user.id)
				.maybeSingle();

			if (
				accError ||
				!(account as { threads_access_token_encrypted?: string | undefined })
					?.threads_access_token_encrypted
			) {
				return apiError(res, 400, "Threads account token not available");
			}

			try {
				accessToken = decrypt(
					(account as { threads_access_token_encrypted: string })
						.threads_access_token_encrypted,
				);
			} catch (decryptError) {
				logger.error("Token decryption failed", {
					error: String(decryptError),
				});
				return apiError(res, 500, "Failed to decrypt access token");
			}

			apiHost = "graph.threads.net/v1.0";
		}

		const fields = "id,media_url,media_type,thumbnail_url";
		const apiUrl = `https://${apiHost}/${platformPostId}?fields=${fields}`;

		const platformResponse = await withRetry(() =>
			fetch(apiUrl, {
				headers: { Authorization: `Bearer ${accessToken}` },
				signal: AbortSignal.timeout(10000),
			}),
		);

		if (!platformResponse.ok) {
			const errorData = await platformResponse.json();
			logger.error("Platform API error during media refresh", {
				error: String(errorData),
				isInstagramPost,
			});
			return apiError(res, 400, "Failed to fetch from platform API", {
				details: errorData.error?.message,
			});
		}

		const platformData = await platformResponse.json();

		if (!platformData.media_url) {
			// No media on this post
			await dbAny()
				.from("posts")
				.update({ media_urls: [] })
				.eq("id", postId)
				.eq("user_id", user.id);

			return apiSuccess(res, {
				mediaUrls: [],
				refreshed: true,
			});
		}

		// Store the fresh media URL in Supabase Storage
		const storedUrl = await storeMediaFromUrl(
			platformData.media_url,
			post.user_id,
			platformPostId,
			0,
		);

		if (!storedUrl) {
			return apiError(res, 500, "Failed to store media", {
				details: platformData.media_url,
			});
		}

		// Update the post with the permanent URL
		const newMediaUrls = [storedUrl];
		await dbAny()
			.from("posts")
			.update({ media_urls: newMediaUrls })
			.eq("id", postId)
			.eq("user_id", user.id);

		logger.info("Successfully refreshed media for post", { postId });

		return apiSuccess(res, {
			mediaUrls: newMediaUrls,
			refreshed: true,
		});
	} catch (error: unknown) {
		logger.error("MediaRefresh error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
