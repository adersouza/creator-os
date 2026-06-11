/**
 * Media URL validation for scheduled post publishing.
 * Checks accessibility of media URLs before attempting to publish.
 */

import { logger } from "../../logger.js";
import { fetchAllowedMediaUrl } from "../../outboundUrlSecurity.js";

/**
 * #482: Check if media URLs are still accessible before publishing.
 * Sends a HEAD request with a 5-second timeout to the first media URL.
 * Returns null if OK, or an error message if the media has expired.
 */
export async function checkMediaUrlAccessible(
	mediaUrls: string[] | null | undefined,
): Promise<string | null> {
	if (!mediaUrls || mediaUrls.length === 0) return null;

	// Check ALL URLs, not just the first — carousel posts need every item valid
	for (const url of mediaUrls) {
		if (!url) continue;
		// Skip non-HTTP URLs (shouldn't happen after UUID resolution, but defensive)
		if (!url.startsWith("http")) {
			return `Media URL inaccessible: Failed to parse URL from ${url}. Please re-upload your media and reschedule.`;
		}
		try {
			const response = await fetchAllowedMediaUrl(url, {
				method: "HEAD",
				signal: AbortSignal.timeout(10000),
			});
			if (!response) {
				return "Media URL is not on an approved media CDN. Please re-upload your media and reschedule.";
			}

			if (response.status >= 400) {
				logger.warn("Media URL check failed", {
					url: url.substring(0, 100),
					status: response.status,
				});
				return `Media URL expired or inaccessible (HTTP ${response.status}). Please re-upload your media and reschedule.`;
			}

			// Meta IG API rejects images > 8MB — catch oversized files before publish
			const contentLength = response.headers.get("content-length");
			if (contentLength) {
				const sizeBytes = parseInt(contentLength, 10);
				const isImage = /\.(png|jpe?g|webp|gif|heic)(\?|$)/i.test(url);
				if (isImage && sizeBytes > 8_000_000) {
					logger.warn("Media URL too large for Instagram", {
						url: url.substring(0, 100),
						sizeBytes,
						sizeMB: (sizeBytes / 1_000_000).toFixed(1),
					});
					return `Image too large (${(sizeBytes / 1_000_000).toFixed(1)}MB). Instagram requires images under 8MB. Please compress and reschedule.`;
				}
			}
		} catch (err: unknown) {
			const errMsg = err instanceof Error ? err.message : String(err);
			if (errMsg.includes("abort") || errMsg.includes("timeout")) {
				logger.warn("Media URL check timed out", {
					url: url.substring(0, 100),
				});
				return "Media URL timed out (5s). Please re-upload your media and reschedule.";
			}
			logger.warn("Media URL check error", {
				url: url.substring(0, 100),
				error: errMsg,
			});
			return `Media URL inaccessible: ${errMsg}. Please re-upload your media and reschedule.`;
		}
	}

	return null; // All URLs accessible
}
