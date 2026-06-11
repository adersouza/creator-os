// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { getSupabase } from "../_lib/supabase.js";
import { logger } from "./logger.js";
import {
	fetchAllowedMediaUrl,
	isAllowedPlatformMediaUrl,
	isAllowedSupabasePublicUrl,
} from "./outboundUrlSecurity.js";

/**
 * Media Storage Utility
 *
 * Downloads media from Threads CDN and stores it permanently in Supabase Storage.
 * This prevents 403 errors from expired CDN URLs.
 *
 * EXIF metadata (GPS coordinates, device serial numbers, timestamps) is automatically
 * stripped from JPEG images before upload to protect user privacy.
 */

// Lazy import to avoid loading EXIF stripping module unless media is being processed
async function stripExifLazy(buf: Buffer): Promise<Buffer> {
	const { stripExifFromBuffer } = await import("./exifStrip.js");
	return stripExifFromBuffer(buf);
}

const BUCKET_NAME = "post-media";
const MAX_MEDIA_SIZE_BYTES = 100 * 1024 * 1024; // Match the post-media bucket limit.

/** Magic byte signatures for file type validation */
const MAGIC_BYTES: Record<string, number[]> = {
	"image/jpeg": [0xff, 0xd8, 0xff],
	"image/jpg": [0xff, 0xd8, 0xff],
	"image/png": [0x89, 0x50, 0x4e, 0x47],
	"image/gif": [0x47, 0x49, 0x46],
	"image/webp": [0x52, 0x49, 0x46, 0x46], // RIFF header
	"video/mp4": [], // MP4 has variable header (ftyp box), skip magic check
	"video/quicktime": [],
	"video/webm": [0x1a, 0x45, 0xdf, 0xa3], // EBML header
};

/** Validate buffer magic bytes match the declared content type */
function validateMagicBytes(buffer: Buffer, contentType: string): boolean {
	const mimeKey = contentType.split(";")[0]?.trim();
	const expected = MAGIC_BYTES[mimeKey!];
	if (!expected || expected.length === 0) return true; // No magic bytes to check
	if (buffer.length < expected.length) return false;
	return expected.every((byte, i) => buffer[i] === byte);
}

/**
 * Download media from a URL and upload to Supabase Storage
 * Returns the permanent public URL
 */
export async function storeMediaFromUrl(
	sourceUrl: string,
	userId: string,
	postId: string,
	mediaIndex: number = 0,
): Promise<string | null> {
	try {
		// Skip if already a Supabase URL
		if (
			sourceUrl.startsWith(process.env.SUPABASE_URL || "") &&
			process.env.SUPABASE_URL
		) {
			return sourceUrl;
		}
		if (sourceUrl.includes(".supabase.co")) {
			return sourceUrl;
		}

		// SSRF protection: only fetch platform/Supabase media, and re-check each redirect hop.
		if (
			!isAllowedPlatformMediaUrl(sourceUrl) &&
			!isAllowedSupabasePublicUrl(sourceUrl)
		) {
			logger.warn("[mediaStorage] Blocked fetch from disallowed domain", {
				url: sourceUrl.substring(0, 200),
			});
			return null;
		}

		// Download the media
		const response = await fetchAllowedMediaUrl(sourceUrl, {
			signal: AbortSignal.timeout(15000),
		});
		if (!response?.ok) {
			logger.error("Failed to download media", { status: response?.status });
			return null;
		}

		// Get content type and determine extension
		const contentType = response.headers.get("content-type") || "image/jpeg";
		const contentLength = Number(response.headers.get("content-length") || 0);
		if (contentLength > MAX_MEDIA_SIZE_BYTES) {
			logger.warn("[mediaStorage] Refusing oversized media download", {
				contentLength,
				maxBytes: MAX_MEDIA_SIZE_BYTES,
			});
			return null;
		}
		const extension = getExtensionFromContentType(contentType);

		// Create unique filename: userId/postId/index.ext
		const filename = `${userId}/${postId}/${mediaIndex}.${extension}`;

		// Get the media as a buffer
		const arrayBuffer = await response.arrayBuffer();
		if (arrayBuffer.byteLength > MAX_MEDIA_SIZE_BYTES) {
			logger.warn("[mediaStorage] Refusing oversized media payload", {
				byteLength: arrayBuffer.byteLength,
				maxBytes: MAX_MEDIA_SIZE_BYTES,
			});
			return null;
		}
		let buffer: Buffer = Buffer.from(new Uint8Array(arrayBuffer));

		// Validate magic bytes match declared content type (prevents MIME spoofing)
		if (!validateMagicBytes(buffer, contentType)) {
			logger.warn(
				"[mediaStorage] Magic bytes mismatch — possible MIME spoofing",
				{
					contentType,
					firstBytes: buffer.slice(0, 8).toString("hex"),
				},
			);
			return null;
		}

		// Strip EXIF metadata from JPEG images (removes GPS, device info, timestamps)
		if (contentType.includes("jpeg") || contentType.includes("jpg")) {
			try {
				buffer = await stripExifLazy(buffer);
			} catch (err) {
				logger.warn("EXIF stripping failed, uploading with metadata intact", {
					error: String(err),
				});
			}
		}

		// Upload to Supabase Storage
		const { error } = await getSupabase()
			.storage.from(BUCKET_NAME)
			.upload(filename, buffer, {
				contentType,
				upsert: true, // Overwrite if exists
			});

		if (error) {
			logger.error("Failed to upload media to storage", {
				error: String(error),
			});
			return null;
		}

		// Get the public URL
		const { data: urlData } = getSupabase()
			.storage.from(BUCKET_NAME)
			.getPublicUrl(filename);

		return urlData?.publicUrl || null;
	} catch (err) {
		logger.error("Error storing media", { error: String(err) });
		return null;
	}
}

/**
 * Store multiple media URLs for a post
 */
export async function storePostMedia(
	mediaUrls: string[],
	userId: string,
	postId: string,
): Promise<string[]> {
	const storedUrls: string[] = [];

	for (let i = 0; i < mediaUrls.length; i++) {
		const storedUrl = await storeMediaFromUrl(mediaUrls[i]!, userId, postId, i);
		if (storedUrl) {
			storedUrls.push(storedUrl);
		} else {
			// Keep original URL as fallback
			storedUrls.push(mediaUrls[i]!);
		}
	}

	return storedUrls;
}

/**
 * Check if a URL is expired (returns 403)
 */
export async function isMediaExpired(url: string): Promise<boolean> {
	try {
		const response = await fetchAllowedMediaUrl(url, {
			method: "HEAD",
			signal: AbortSignal.timeout(10000),
		});
		if (!response) return true;
		return response.status === 403 || response.status === 404;
	} catch (err) {
		logger.debug("Failed to check media URL expiry via HEAD request", {
			url: url.substring(0, 200),
			error: String(err),
		});
		return true;
	}
}

/**
 * Get file extension from content type
 */
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
