import crypto from "node:crypto";
import { logger } from "../../logger.js";
import {
	buildOriginalitySignals,
	perceptualHashSimilarity,
} from "../../originalitySignals.js";
import { getSupabaseAny } from "../../supabase.js";

const db = () => getSupabaseAny();
export const DEFAULT_DUPLICATE_WINDOW_HOURS = 72;
export const HARD_BLOCK_DUPLICATE_WINDOW_HOURS = 24;
const NO_MEDIA_FINGERPRINT = "no_media";

export interface PublishFingerprint {
	normalizedTextHash: string;
	mediaFingerprint: string;
	publishFingerprint: string;
	duplicateWindowHours: number;
}

export interface DuplicateFingerprintMatch {
	id: string;
	status: string;
	account_id: string | null;
	threads_post_id: string | null;
	posted_at: string | null;
	created_at: string | null;
	publish_fingerprint: string | null;
	match_type?: string | null;
	post_id?: string | null;
}

export interface MediaReuseSignals {
	mediaUrlHashes: string[];
	perceptualHashes: string[];
}

function sha256(value: string): string {
	return crypto.createHash("sha256").update(value).digest("hex");
}

export function normalizePublishText(content: string): string {
	return content
		.normalize("NFKC")
		.toLowerCase()
		.replace(/https?:\/\/\S+/g, " ")
		.replace(/[“”]/g, '"')
		.replace(/[‘’]/g, "'")
		.replace(/[^\p{L}\p{N}#@'\s]+/gu, " ")
		.replace(/\s+/g, " ")
		.trim();
}

export function fingerprintMedia(mediaUrls: string[] | null | undefined): string {
	const normalized = (mediaUrls ?? [])
		.map((url) => String(url || "").trim().toLowerCase())
		.filter(Boolean)
		.sort();
	if (normalized.length === 0) return NO_MEDIA_FINGERPRINT;
	return sha256(normalized.join("\n"));
}

export function buildPublishFingerprint(values: {
	workspaceId: string;
	accountId?: string | null | undefined;
	platform?: string | null | undefined;
	content: string;
	mediaUrls?: string[] | null | undefined;
	duplicateWindowHours?: number | null | undefined;
}): PublishFingerprint {
	const duplicateWindowHours = Math.max(
		HARD_BLOCK_DUPLICATE_WINDOW_HOURS,
		Math.min(
			168,
			Math.round(
				Number(values.duplicateWindowHours ?? DEFAULT_DUPLICATE_WINDOW_HOURS),
			),
		),
	);
	const normalizedTextHash = sha256(normalizePublishText(values.content));
	const mediaFingerprint = fingerprintMedia(values.mediaUrls);
	const accountScope = values.accountId || "unassigned";
	const platform = values.platform || "threads";
	return {
		normalizedTextHash,
		mediaFingerprint,
		duplicateWindowHours,
		publishFingerprint: sha256(
			[
				values.workspaceId,
				accountScope,
				platform,
				normalizedTextHash,
				mediaFingerprint,
			].join(":"),
		),
	};
}

export async function buildMediaReuseSignals(values: {
	content?: string | null | undefined;
	mediaUrls?: string[] | null | undefined;
	fetchPerceptual?: boolean | undefined;
	userId?: string | null | undefined;
}): Promise<MediaReuseSignals> {
	const signals = await buildOriginalitySignals(
		{
			postId: "autoposter-candidate",
			userId: values.userId || "autoposter",
			content: values.content ?? "",
			mediaUrls: values.mediaUrls ?? [],
			metadata: null,
		},
		{ fetchMedia: values.fetchPerceptual === true },
	);
	return {
		mediaUrlHashes: signals.mediaUrlHashes,
		perceptualHashes: signals.perceptualHashes,
	};
}

export async function findRecentDuplicateFingerprint(values: {
	workspaceId: string;
	accountId: string;
	platform?: string | null | undefined;
	normalizedTextHash: string;
	mediaFingerprint: string;
	duplicateWindowHours?: number | null | undefined;
	excludeQueueItemId?: string | null | undefined;
	statuses?: string[] | undefined;
}): Promise<DuplicateFingerprintMatch | null> {
	const duplicateWindowHours = values.duplicateWindowHours ?? DEFAULT_DUPLICATE_WINDOW_HOURS;
	const cutoff = new Date(
		Date.now() - duplicateWindowHours * 60 * 60 * 1000,
	).toISOString();

	try {
		let query = db()
			.from("auto_post_queue")
			.select(
				"id, status, account_id, threads_post_id, posted_at, created_at, publish_fingerprint",
			)
			.eq("workspace_id", values.workspaceId)
			.eq("account_id", values.accountId)
			.eq("platform", values.platform || "threads")
			.eq("normalized_text_hash", values.normalizedTextHash)
			.eq("media_fingerprint", values.mediaFingerprint)
			.in(
				"status",
				values.statuses ?? ["pending", "queued", "publishing", "published", "needs_review"],
			)
			.gte("created_at", cutoff)
			.order("created_at", { ascending: false })
			.limit(1);

		if (values.excludeQueueItemId) {
			query = query.neq("id", values.excludeQueueItemId);
		}

		const { data, error } = await query;
		if (error) throw error;
		return ((data ?? []) as DuplicateFingerprintMatch[])[0] ?? null;
	} catch (error) {
		logger.warn("findRecentDuplicateFingerprint failed", {
			workspaceId: values.workspaceId,
			accountId: values.accountId,
			error: String(error),
		});
		return null;
	}
}

export async function findRecentMediaFingerprintAcrossAccounts(values: {
	workspaceId: string;
	userId?: string | null | undefined;
	accountId: string;
	platform?: string | null | undefined;
	mediaFingerprint: string;
	mediaUrlHashes?: string[] | null | undefined;
	perceptualHashes?: string[] | null | undefined;
	duplicateWindowHours?: number | null | undefined;
	excludeQueueItemId?: string | null | undefined;
	statuses?: string[] | undefined;
}): Promise<DuplicateFingerprintMatch | null> {
	const duplicateWindowHours =
		values.duplicateWindowHours ?? DEFAULT_DUPLICATE_WINDOW_HOURS;
	const cutoff = new Date(
		Date.now() - duplicateWindowHours * 60 * 60 * 1000,
	).toISOString();

	try {
		if (
			values.mediaFingerprint &&
			values.mediaFingerprint !== NO_MEDIA_FINGERPRINT
		) {
			let query = db()
				.from("auto_post_queue")
				.select(
					"id, status, account_id, threads_post_id, posted_at, created_at, publish_fingerprint",
				)
				.eq("workspace_id", values.workspaceId)
				.eq("platform", values.platform || "threads")
				.eq("media_fingerprint", values.mediaFingerprint)
				.not("account_id", "is", null)
				.neq("account_id", values.accountId)
				.in(
					"status",
					values.statuses ?? ["pending", "queued", "publishing", "published"],
				)
				.gte("created_at", cutoff)
				.order("created_at", { ascending: false })
				.limit(1);

			if (values.excludeQueueItemId) {
				query = query.neq("id", values.excludeQueueItemId);
			}

			const { data, error } = await query;
			if (error) throw error;
			const exactMatch = ((data ?? []) as DuplicateFingerprintMatch[])[0];
			if (exactMatch) {
				return { ...exactMatch, match_type: "media_fingerprint" };
			}
		}

		const signalMatch = await findRecentOriginalitySignalAcrossAccounts({
			userId: values.userId,
			accountId: values.accountId,
			platform: values.platform || "threads",
			mediaUrlHashes: values.mediaUrlHashes,
			perceptualHashes: values.perceptualHashes,
			cutoff,
		});
		if (signalMatch) return signalMatch;
		return null;
	} catch (error) {
		logger.warn("findRecentMediaFingerprintAcrossAccounts failed", {
			workspaceId: values.workspaceId,
			accountId: values.accountId,
			error: String(error),
		});
		return null;
	}
}

async function findRecentOriginalitySignalAcrossAccounts(values: {
	userId?: string | null | undefined;
	accountId: string;
	platform: string;
	mediaUrlHashes?: string[] | null | undefined;
	perceptualHashes?: string[] | null | undefined;
	cutoff: string;
}): Promise<DuplicateFingerprintMatch | null> {
	const userId = (values.userId || "").trim();
	const mediaUrlHashes = Array.from(new Set(values.mediaUrlHashes ?? [])).filter(Boolean);
	const perceptualHashes = Array.from(new Set(values.perceptualHashes ?? [])).filter(Boolean);
	if (!userId || (mediaUrlHashes.length === 0 && perceptualHashes.length === 0)) {
		return null;
	}

	const { data, error } = await db()
		.from("post_originality_signals")
		.select(
			"post_id, account_id, platform, captured_at, media_url_hashes, perceptual_hashes",
		)
		.eq("user_id", userId)
		.eq("platform", values.platform)
		.not("account_id", "is", null)
		.neq("account_id", values.accountId)
		.gte("captured_at", values.cutoff)
		.order("captured_at", { ascending: false })
		.limit(100);
	if (error) throw error;

	for (const row of (data ?? []) as Array<{
		post_id: string;
		account_id: string | null;
		captured_at: string | null;
		media_url_hashes: string[] | null;
		perceptual_hashes: string[] | null;
	}>) {
		const rowMediaHashes = new Set(row.media_url_hashes ?? []);
		if (mediaUrlHashes.some((hash) => rowMediaHashes.has(hash))) {
			return {
				id: row.post_id,
				post_id: row.post_id,
				status: "published",
				account_id: row.account_id,
				threads_post_id: null,
				posted_at: row.captured_at,
				created_at: row.captured_at,
				publish_fingerprint: null,
				match_type: "media_url_hash",
			};
		}

		for (const candidateHash of perceptualHashes) {
			for (const previousHash of row.perceptual_hashes ?? []) {
				if (perceptualHashSimilarity(candidateHash, previousHash) >= 0.94) {
					return {
						id: row.post_id,
						post_id: row.post_id,
						status: "published",
						account_id: row.account_id,
						threads_post_id: null,
						posted_at: row.captured_at,
						created_at: row.captured_at,
						publish_fingerprint: null,
						match_type: "perceptual_hash",
					};
				}
			}
		}
	}

	return null;
}

export async function stampQueueItemFingerprint(
	queueItemId: string,
	fingerprint: PublishFingerprint,
): Promise<void> {
	try {
		await db()
			.from("auto_post_queue")
			.update({
				normalized_text_hash: fingerprint.normalizedTextHash,
				media_fingerprint: fingerprint.mediaFingerprint,
				publish_fingerprint: fingerprint.publishFingerprint,
				duplicate_window_hours: fingerprint.duplicateWindowHours,
			} as Record<string, unknown>)
			.eq("id", queueItemId);
	} catch (error) {
		logger.warn("stampQueueItemFingerprint failed", {
			queueItemId,
			error: String(error),
		});
	}
}
