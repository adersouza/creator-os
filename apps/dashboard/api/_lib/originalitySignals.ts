// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import crypto from "node:crypto";
import { logger } from "./logger.js";
import { validateUrlNotPrivate } from "./ssrfProtection.js";

export interface OriginalitySignalInput {
	postId: string;
	userId: string;
	content?: string | null | undefined;
	mediaUrls?: string[] | null | undefined;
	metadata?: Record<string, unknown> | null | undefined;
}

export interface OriginalitySignals {
	textHash: string | null;
	mediaUrlHashes: string[];
	perceptualHashes: string[];
	watermarkApplied: boolean;
	provenance: Record<string, unknown>;
}

const MAX_MEDIA_BYTES = 8 * 1024 * 1024;
const MEDIA_FETCH_TIMEOUT_MS = 8_000;

export function sha256Hex(value: string): string {
	return crypto.createHash("sha256").update(value).digest("hex");
}

export function normalizeTextForFingerprint(content: string): string {
	return content
		.toLowerCase()
		.replace(/https?:\/\/\S+/g, " ")
		.replace(/[@#]\w+/g, " ")
		.replace(/[^\p{L}\p{N}\s]/gu, " ")
		.replace(/\s+/g, " ")
		.trim();
}

export function textFingerprint(content: string | null | undefined): string | null {
	const normalized = normalizeTextForFingerprint(content || "");
	return normalized ? sha256Hex(normalized) : null;
}

export function mediaUrlFingerprint(url: string): string {
	try {
		const parsed = new URL(url);
		parsed.search = "";
		parsed.hash = "";
		return sha256Hex(parsed.toString());
	} catch {
		return sha256Hex(url.trim());
	}
}

export function hammingDistanceHex(a: string, b: string): number {
	const width = Math.min(a.length, b.length);
	let distance = Math.abs(a.length - b.length) * 4;
	for (let i = 0; i < width; i++) {
		const x = Number.parseInt(a[i]!, 16);
		const y = Number.parseInt(b[i]!, 16);
		if (Number.isNaN(x) || Number.isNaN(y)) {
			distance += 4;
			continue;
		}
		let v = x ^ y;
		while (v) {
			distance += v & 1;
			v >>= 1;
		}
	}
	return distance;
}

export function perceptualHashSimilarity(a: string, b: string): number {
	if (!a || !b) return 0;
	const bits = Math.max(a.length, b.length) * 4;
	if (bits <= 0) return 0;
	return Math.max(0, 1 - hammingDistanceHex(a, b) / bits);
}

export async function averageHashFromBuffer(buffer: Buffer): Promise<string | null> {
	try {
		const sharp = (await import("sharp")).default;
		const raw = await sharp(buffer, { failOn: "none" })
			.resize(8, 8, { fit: "fill" })
			.grayscale()
			.raw()
			.toBuffer();
		if (raw.length < 64) return null;
		const avg =
			raw.reduce((sum: number, value: number) => sum + value, 0) / raw.length;
		let bits = "";
		for (const value of raw) bits += value >= avg ? "1" : "0";
		let hex = "";
		for (let i = 0; i < bits.length; i += 4) {
			hex += Number.parseInt(bits.slice(i, i + 4), 2).toString(16);
		}
		return hex.padStart(16, "0");
	} catch (err) {
		logger.warn("[originality] perceptual hash failed", {
			error: err instanceof Error ? err.message : String(err),
		});
		return null;
	}
}

export async function fetchPerceptualHash(url: string): Promise<string | null> {
	const ssrfError = await validateUrlNotPrivate(url);
	if (ssrfError) {
		logger.warn("[originality] media URL blocked", { url, error: ssrfError });
		return null;
	}
	try {
		const response = await fetch(url, {
			signal: AbortSignal.timeout(MEDIA_FETCH_TIMEOUT_MS),
		});
		if (!response.ok) return null;
		const contentType = response.headers.get("content-type") || "";
		if (!contentType.toLowerCase().startsWith("image/")) return null;
		const len = Number(response.headers.get("content-length") || "0");
		if (len > MAX_MEDIA_BYTES) return null;
		const arrayBuffer = await response.arrayBuffer();
		if (arrayBuffer.byteLength > MAX_MEDIA_BYTES) return null;
		return averageHashFromBuffer(Buffer.from(arrayBuffer));
	} catch (err) {
		logger.warn("[originality] media fetch failed", {
			url,
			error: err instanceof Error ? err.message : String(err),
		});
		return null;
	}
}

export async function buildOriginalitySignals(
	input: OriginalitySignalInput,
	options: { fetchMedia?: boolean | undefined } = {},
): Promise<OriginalitySignals> {
	const mediaUrls = Array.from(
		new Set((input.mediaUrls || []).filter((url) => typeof url === "string" && url.trim())),
	);
	const mediaUrlHashes = mediaUrls.map(mediaUrlFingerprint);
	const perceptualHashes: string[] = [];
	if (options.fetchMedia) {
		for (const url of mediaUrls.slice(0, 2)) {
			const hash = await fetchPerceptualHash(url);
			if (hash) perceptualHashes.push(hash);
		}
	}

	const metadata = input.metadata || {};
	const watermarkApplied =
		metadata.watermark_applied === true ||
		metadata.watermarkApplied === true ||
		typeof metadata.watermark_config_id === "string" ||
		typeof metadata.watermarkConfigId === "string";

	return {
		textHash: textFingerprint(input.content),
		mediaUrlHashes,
		perceptualHashes,
		watermarkApplied,
		provenance: {
			sourceType: metadata.source_type ?? metadata.sourceType ?? null,
			sourcePostId: metadata.source_post_id ?? metadata.sourcePostId ?? null,
			captureVersion: 1,
			fetchedMedia: options.fetchMedia === true,
		},
	};
}
