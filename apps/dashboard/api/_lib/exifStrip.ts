// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * EXIF Metadata Stripping Utility
 *
 * Strips GPS coordinates, device serial numbers, and other PII from JPEG images.
 * Uses pure JavaScript JPEG segment parsing — no native dependencies required.
 * Works in Vercel serverless environment.
 *
 * Removed segments:
 * - APP1 (0xFFE1): EXIF data — GPS coords, device serial, timestamps, camera info
 * - APP13 (0xFFED): IPTC data — photographer name, copyright, location metadata
 *
 * All other JPEG segments (quantization tables, Huffman tables, image data) are
 * preserved byte-for-byte, so image quality is completely unaffected.
 */

import { logger } from "./logger.js";
import {
	fetchAllowedMediaUrl,
	isAllowedSupabasePublicUrl,
} from "./outboundUrlSecurity.js";

/**
 * JPEG marker constants
 */
const JPEG_SOS = 0xffda; // Start of Scan (compressed image data follows)
const JPEG_APP1 = 0xffe1; // EXIF data
const JPEG_APP13 = 0xffed; // IPTC data

/**
 * Check if a buffer starts with the JPEG SOI marker.
 */
function isJpeg(buf: Buffer): boolean {
	return buf.length >= 2 && buf[0] === 0xff && buf[1] === 0xd8;
}

/**
 * Strip EXIF and IPTC metadata from a JPEG buffer.
 * Returns a new buffer with APP1 (EXIF) and APP13 (IPTC) segments removed.
 * Non-JPEG input is returned unchanged (safe to call on any media type).
 */
export function stripExifFromBuffer(input: Buffer): Buffer {
	if (!isJpeg(input)) {
		return input;
	}

	const segments: Buffer[] = [];
	// Keep SOI marker (bytes 0-1)
	segments.push(input.subarray(0, 2));

	let offset = 2;
	let strippedCount = 0;

	while (offset < input.length - 1) {
		// Every marker starts with 0xFF
		if (input[offset] !== 0xff) {
			// Not a marker — append remaining bytes (shouldn't happen in valid JPEG)
			logger.warn(
				"[EXIF Strip] Malformed JPEG: unexpected byte at offset, skipping EXIF strip",
				{
					offset,
					byte: input[offset],
					bufferLength: input.length,
				},
			);
			segments.push(input.subarray(offset));
			break;
		}

		const marker = (input[offset]! << 8) | input[offset + 1]!;

		// SOS (Start of Scan) — everything after this is compressed image data.
		// Copy the rest of the file verbatim.
		if (marker === JPEG_SOS) {
			segments.push(input.subarray(offset));
			break;
		}

		// Markers that carry a length field (all 0xFFCn, 0xFFDn except standalone,
		// and 0xFFEn application markers)
		const hasLength =
			(marker >= 0xffc0 && marker <= 0xffcf && marker !== 0xffc0 + 8) || // SOF, DHT, DAC, etc. (not JPG marker 0xFFC8)
			marker === 0xffc8 || // Actually JPG marker does have length in practice
			(marker >= 0xffda && marker <= 0xffdf) || // SOS already handled above; DRI, etc.
			(marker >= 0xffe0 && marker <= 0xffef) || // APP0-APP15
			marker === 0xffdb || // DQT
			marker === 0xffdd || // DRI
			marker === 0xfffe; // COM (comment)

		if (hasLength) {
			// Read the 2-byte length field (includes the length bytes themselves but not the marker)
			if (offset + 3 >= input.length) {
				// Truncated — append what's left
				segments.push(input.subarray(offset));
				break;
			}

			const segmentLength = (input[offset + 2]! << 8) | input[offset + 3]!;
			const totalSegmentSize = 2 + segmentLength; // marker (2) + length-indicated bytes

			// Strip APP1 (EXIF) and APP13 (IPTC) segments
			if (marker === JPEG_APP1 || marker === JPEG_APP13) {
				strippedCount++;
				offset += totalSegmentSize;
				continue;
			}

			// Keep all other segments
			segments.push(input.subarray(offset, offset + totalSegmentSize));
			offset += totalSegmentSize;
			continue;
		}

		// Standalone markers (no length field): RST0-RST7 (0xFFD0-0xFFD7), SOI, EOI, TEM
		segments.push(input.subarray(offset, offset + 2));
		offset += 2;
	}

	if (strippedCount === 0) {
		// No metadata found — return original buffer to avoid unnecessary allocation
		return input;
	}

	return Buffer.concat(segments);
}

/**
 * Fetch an image from a URL, strip EXIF data, and return the cleaned buffer.
 * Returns null if the fetch fails or encounters an error.
 */
export async function stripExifFromUrl(
	imageUrl: string,
): Promise<{ buffer: Buffer; contentType: string } | null> {
	try {
		const response = await fetchAllowedMediaUrl(imageUrl, {
			signal: AbortSignal.timeout(30_000),
		});

		if (!response?.ok) {
			logger.warn("[EXIF Strip] Failed to fetch image", {
				url: imageUrl.substring(0, 100),
				status: response?.status,
			});
			return null;
		}

		const contentType = response.headers.get("content-type") || "";
		const buffer = Buffer.from(await response.arrayBuffer());

		// Only strip EXIF from JPEG images (the only format that carries EXIF in APP1)
		if (
			contentType.includes("jpeg") ||
			contentType.includes("jpg") ||
			isJpeg(buffer)
		) {
			const stripped = stripExifFromBuffer(buffer);
			const bytesRemoved = buffer.length - stripped.length;

			if (bytesRemoved > 0) {
				logger.info("[EXIF Strip] Stripped EXIF metadata", {
					originalSize: buffer.length,
					strippedSize: stripped.length,
					bytesRemoved,
				});
			}

			return { buffer: stripped, contentType: contentType || "image/jpeg" };
		}

		// Non-JPEG: return as-is (PNG, WebP, GIF don't carry EXIF in APP1 segments)
		return { buffer, contentType };
	} catch (error) {
		logger.error("[EXIF Strip] Error processing image", {
			error: String(error),
		});
		return null;
	}
}

/**
 * Strip EXIF from a media file stored in Supabase Storage (in-place).
 * Downloads the file, strips metadata, re-uploads to the same path.
 * Only processes JPEG images from Supabase storage URLs.
 * Returns the original URL (content is now clean) or the original URL unchanged on skip/error.
 */
export async function stripExifFromStorageUrl(url: string): Promise<string> {
	// Only process Supabase storage URLs
	const supabaseUrl = process.env.SUPABASE_URL || "";
	if (!supabaseUrl || !url.includes(supabaseUrl)) return url;
	if (!isAllowedSupabasePublicUrl(url)) return url;

	// Skip non-image files (video, gif, webp, png don't carry EXIF in APP1)
	if (/\.(mp4|mov|webm|gif|webp|png)(\?|$)/i.test(url)) return url;

	try {
		const response = await fetchAllowedMediaUrl(url, {
			signal: AbortSignal.timeout(15_000),
		});
		if (!response?.ok) return url;

		const contentType = response.headers.get("content-type") || "";
		const buffer = Buffer.from(await response.arrayBuffer());

		// Only strip JPEG
		if (
			!contentType.includes("jpeg") &&
			!contentType.includes("jpg") &&
			!isJpeg(buffer)
		) {
			return url;
		}

		const stripped = stripExifFromBuffer(buffer);
		if (stripped === buffer) {
			// No EXIF found — no re-upload needed
			return url;
		}

		// Extract storage path from URL: .../storage/v1/object/public/<bucket>/<path>
		const storageMarker = "/storage/v1/object/public/";
		const markerIdx = url.indexOf(storageMarker);
		if (markerIdx === -1) return url;

		const afterMarker = url.substring(markerIdx + storageMarker.length);
		const slashIdx = afterMarker.indexOf("/");
		if (slashIdx === -1) return url;

		const bucket = afterMarker.substring(0, slashIdx);
		// Remove query params from path
		let filePath = afterMarker.substring(slashIdx + 1);
		const qIdx = filePath.indexOf("?");
		if (qIdx !== -1) filePath = filePath.substring(0, qIdx);

		// Lazy import supabase to avoid circular deps
		const { getSupabase } = await import("./supabase.js");
		const { error } = await getSupabase()
			.storage.from(bucket)
			.upload(filePath, stripped, {
				contentType: "image/jpeg",
				upsert: true,
			});

		if (error) {
			logger.warn("[EXIF Strip] Re-upload failed, original intact", {
				error: String(error),
			});
			return url;
		}

		const bytesRemoved = buffer.length - stripped.length;
		logger.info("[EXIF Strip] Stripped storage file in-place", {
			bucket,
			path: filePath,
			bytesRemoved,
		});

		return url;
	} catch (err) {
		logger.warn("[EXIF Strip] Storage strip failed (non-blocking)", {
			error: String(err),
		});
		return url;
	}
}

/**
 * Strip EXIF from multiple media URLs (convenience batch wrapper).
 * Processes in parallel with concurrency limit of 3.
 */
export async function stripExifFromMediaUrls(
	urls: string[],
): Promise<string[]> {
	if (!urls || urls.length === 0) return urls;

	const results: string[] = [];
	for (let i = 0; i < urls.length; i += 3) {
		const chunk = urls.slice(i, i + 3);
		const cleaned = await Promise.all(chunk.map(stripExifFromStorageUrl));
		results.push(...cleaned);
	}
	return results;
}

/**
 * Check if a JPEG buffer contains EXIF (APP1) data.
 * Useful for auditing or conditional processing.
 */
export function hasExifData(input: Buffer): boolean {
	if (!isJpeg(input)) {
		return false;
	}

	let offset = 2;
	while (offset < input.length - 3) {
		if (input[offset] !== 0xff) return false;

		const marker = (input[offset]! << 8) | input[offset + 1]!;

		// Reached image data without finding APP1
		if (marker === JPEG_SOS) return false;

		// Found EXIF marker
		if (marker === JPEG_APP1) return true;

		// Read length and skip to next marker
		const segmentLength = (input[offset + 2]! << 8) | input[offset + 3]!;
		offset += 2 + segmentLength;
	}

	return false;
}
