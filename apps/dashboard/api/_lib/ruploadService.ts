/**
 * Instagram Resumable Video Upload Service
 *
 * Handles chunked video uploads to Meta's rupload.facebook.com endpoint.
 * Used for large video files that may timeout with standard URL-based uploads.
 *
 * Flow:
 * 1. Initialize upload session (POST to rupload with file_size + first chunk or file_url)
 * 2. Upload remaining chunks (if using chunked mode)
 * 3. Return upload handle for container creation
 *
 * Docs: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing
 */

import { logger } from "./logger.js";
import { withRetry } from "./retryUtils.js";

const RUPLOAD_BASE = "https://rupload.facebook.com";
const DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024; // 4MB chunks
const UPLOAD_TIMEOUT = 60000; // 60s per chunk

export interface ResumableUploadResult {
	success: boolean;
	/** The upload handle (h) returned by rupload — pass to container creation */
	uploadHandle?: string | undefined;
	error?: string | undefined;
}

export interface ResumableUploadProgress {
	bytesUploaded: number;
	totalBytes: number;
	percentComplete: number;
}

/**
 * Upload a video to Instagram via resumable upload.
 *
 * Supports two modes:
 * 1. **URL mode**: Pass a public video URL — Meta fetches it server-side (simplest)
 * 2. **Buffer mode**: Pass raw video bytes — uploaded in chunks (for large files)
 *
 * Returns an upload handle to use with container creation.
 */
export async function uploadVideoResumable(
	token: string,
	igUserId: string,
	options: {
		/** Public URL to the video file */
		videoUrl?: string | undefined;
		/** Raw video bytes (alternative to videoUrl) */
		videoBuffer?: Buffer | undefined;
		/** MIME type (default: video/mp4) */
		mimeType?: string | undefined;
		/** File name for the upload */
		fileName?: string | undefined;
		/** Chunk size in bytes (default: 4MB) */
		chunkSize?: number | undefined;
		/** API version (default: v25.0) */
		apiVersion?: string | undefined;
	},
): Promise<ResumableUploadResult> {
	const {
		videoUrl,
		videoBuffer,
		mimeType = "video/mp4",
		chunkSize = DEFAULT_CHUNK_SIZE,
		apiVersion = "v25.0",
	} = options;

	if (!videoUrl && !videoBuffer) {
		return {
			success: false,
			error: "Either videoUrl or videoBuffer is required",
		};
	}

	try {
		// Step 1: Initialize the upload session by creating a container with upload_type=resumable
		const containerParams: Record<string, string> = {
			upload_type: "resumable",
		};

		const initResponse = await withRetry(
			() =>
				fetch(`https://graph.instagram.com/${apiVersion}/${igUserId}/media`, {
					method: "POST",
					headers: {
						Authorization: `Bearer ${token}`,
						"Content-Type": "application/json",
					},
					body: JSON.stringify(containerParams),
					signal: AbortSignal.timeout(15000),
				}),
			{ label: "rupload:init" },
		);

		const initData = await initResponse.json();

		if (!initResponse.ok || initData.error) {
			logger.error("[Rupload] Init failed", {
				error: String(initData?.error?.message || initData),
			});
			return {
				success: false,
				error:
					initData?.error?.message || "Failed to initialize resumable upload",
			};
		}

		const containerId = initData.id;
		if (!containerId) {
			return { success: false, error: "No container ID returned from init" };
		}

		logger.info("[Rupload] Session initialized", { containerId });

		// Step 2: Upload the video data to rupload endpoint
		const ruploadUrl = `${RUPLOAD_BASE}/ig-api-upload/${apiVersion}/${containerId}`;

		if (videoUrl) {
			// URL mode: tell rupload to fetch from URL
			const uploadResponse = await withRetry(
				() =>
					fetch(ruploadUrl, {
						method: "POST",
						headers: {
							Authorization: `OAuth ${token}`,
							file_url: videoUrl,
						},
						signal: AbortSignal.timeout(UPLOAD_TIMEOUT),
					}),
				{ label: "rupload:url-upload" },
			);

			const uploadData = await uploadResponse.json();

			if (!uploadResponse.ok || uploadData.error) {
				logger.error("[Rupload] URL upload failed", {
					error: String(uploadData?.error?.message || uploadData),
				});
				return {
					success: false,
					error: uploadData?.error?.message || "Resumable URL upload failed",
				};
			}

			const handle = uploadData.h;
			if (!handle) {
				// Some API versions return the container ID as the handle
				logger.info("[Rupload] URL upload complete (no explicit handle)", {
					containerId,
				});
				return { success: true, uploadHandle: containerId };
			}

			logger.info("[Rupload] URL upload complete", { handle });
			return { success: true, uploadHandle: handle };
		}

		// Buffer mode: upload in chunks
		if (!videoBuffer) {
			return {
				success: false,
				error: "videoBuffer is required for chunked upload mode",
			};
		}
		const buffer = videoBuffer;
		const totalSize = buffer.length;
		let offset = 0;

		logger.info("[Rupload] Starting chunked upload", {
			totalSize,
			chunkSize,
			chunks: Math.ceil(totalSize / chunkSize),
		});

		while (offset < totalSize) {
			const end = Math.min(offset + chunkSize, totalSize);
			const chunk = buffer.subarray(offset, end);
			const isLastChunk = end >= totalSize;

			const chunkResponse = await withRetry(
				() =>
					fetch(ruploadUrl, {
						method: "POST",
						headers: {
							Authorization: `OAuth ${token}`,
							offset: String(offset),
							file_size: String(totalSize),
							"Content-Type": mimeType,
						},
						body: chunk as unknown as BodyInit,
						signal: AbortSignal.timeout(UPLOAD_TIMEOUT),
					}),
				{
					label: `rupload:chunk-${offset}`,
					maxRetries: 3,
				},
			);

			const chunkData = await chunkResponse.json();

			if (!chunkResponse.ok || chunkData.error) {
				const errCode = chunkData?.error?.code;
				const errSubcode = chunkData?.error?.error_subcode;
				const isSessionExpired = errCode === 2207026 || errSubcode === 1363037;
				logger.error("[Rupload] Chunk upload failed", {
					offset,
					error: String(chunkData?.error?.message || chunkData),
					sessionExpired: isSessionExpired,
				});
				return {
					success: false,
					error: isSessionExpired
						? "Upload session expired. Please retry."
						: `Chunk upload failed at offset ${offset}: ${chunkData?.error?.message || "Unknown error"}`,
				};
			}

			logger.info("[Rupload] Chunk uploaded", {
				offset,
				end,
				progress: `${Math.round((end / totalSize) * 100)}%`,
			});

			offset = end;

			if (isLastChunk) {
				const handle = chunkData.h || containerId;
				logger.info("[Rupload] Chunked upload complete", { handle });
				return { success: true, uploadHandle: handle };
			}
		}

		return { success: true, uploadHandle: containerId };
	} catch (error) {
		logger.error("[Rupload] Upload error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Resumable upload failed",
		};
	}
}

/**
 * Check if a video should use resumable upload based on file size.
 * Videos larger than the threshold (default 50MB) will use resumable upload.
 *
 * @param videoUrl - URL to check (performs HEAD request for Content-Length)
 * @param thresholdBytes - Size threshold in bytes (default: 50MB)
 */
export async function shouldUseResumableUpload(
	videoUrl: string,
	thresholdBytes: number = 50 * 1024 * 1024,
): Promise<boolean> {
	try {
		const headResponse = await fetch(videoUrl, {
			method: "HEAD",
			signal: AbortSignal.timeout(5000),
		});

		const contentLength = headResponse.headers.get("content-length");
		if (contentLength) {
			const size = parseInt(contentLength, 10);
			if (!Number.isNaN(size) && size > thresholdBytes) {
				logger.info("[Rupload] Large video detected, using resumable upload", {
					size,
					threshold: thresholdBytes,
				});
				return true;
			}
		}

		return false;
	} catch {
		// If HEAD fails, fall back to standard upload
		return false;
	}
}
