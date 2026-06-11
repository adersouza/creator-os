/**
 * Originality Capture Cron — /api/cron/originality-capture
 *
 * Backfills durable originality signals for recent posts. Cheap text/media-URL
 * fingerprints and expensive perceptual image hashes both live here so the
 * analytics read path stays read-only.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { verifyCronAuth } from "../_lib/apiResponse.js";
import { trackCronRun, withCronLock } from "../_lib/cronUtils.js";
import { buildOriginalitySignals } from "../_lib/originalitySignals.js";
import { getSupabaseAny } from "../_lib/supabase.js";

export const config = { maxDuration: 300 };

const JOB_NAME = "originality-capture";
const LOOKBACK_DAYS = 45;
const QUERY_LIMIT = 120;
const MAX_POSTS_PER_RUN = 80;
const MAX_MEDIA_FETCHES_PER_RUN = 14;

interface PostRow {
	id: string;
	user_id: string;
	account_id: string | null;
	instagram_account_id: string | null;
	content: string | null;
	media_urls: string[] | null;
	metadata: Record<string, unknown> | null;
}

interface ExistingSignalRow {
	post_id: string;
	text_hash: string | null;
	perceptual_hashes: string[] | null;
	media_url_hashes: string[] | null;
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "POST" && req.method !== "GET") {
		return res.status(405).json({ error: "Method not allowed" });
	}
	if (!verifyCronAuth(req, res)) return;

	const db = getSupabaseAny();
	const lockResult = await withCronLock(
		db,
		JOB_NAME,
		async () => {
			return trackCronRun(db, JOB_NAME, async () => {
				const result = await runOriginalityCapture(db);
				return {
					itemsProcessed: result.processed,
					metadata: result,
				};
			});
		},
		310,
	);

	if (!("result" in lockResult)) {
		return res.status(200).json({ success: false, skipped: true });
	}

	return res.status(200).json({
		success: true,
		...lockResult.result,
	});
}

// biome-ignore lint/suspicious/noExplicitAny: generated DB types lag analytics support tables
async function runOriginalityCapture(db: any) {
	const cutoff = new Date(
		Date.now() - LOOKBACK_DAYS * 86_400_000,
	).toISOString();
	const { data, error } = await db
		.from("posts")
		.select(
			"id, user_id, account_id, instagram_account_id, content, media_urls, metadata",
		)
		.eq("status", "published")
		.gte("published_at", cutoff)
		.order("published_at", { ascending: false })
		.limit(QUERY_LIMIT);

	if (error) throw new Error(`posts query failed: ${error.message}`);

	const posts = ((data || []) as PostRow[]).filter(
		(post) =>
			post.user_id &&
			((post.content || "").trim() ||
				(Array.isArray(post.media_urls) &&
					post.media_urls.some(
						(url) => typeof url === "string" && url.trim(),
					))),
	);

	if (posts.length === 0) {
		return {
			processed: 0,
			withPerceptualHashes: 0,
			skippedExisting: 0,
			candidates: 0,
		};
	}

	const postIds = posts.map((post) => post.id);
	const { data: existingRows } = await db
		.from("post_originality_signals")
		.select("post_id, text_hash, perceptual_hashes, media_url_hashes")
		.in("post_id", postIds);

	const existing = new Map(
		((existingRows || []) as ExistingSignalRow[]).map((row) => [
			row.post_id,
			row,
		]),
	);

	const candidates = posts
		.filter((post) => {
			const row = existing.get(post.id);
			const hasMedia = hasUsableMedia(post);
			return (
				!row ||
				(!row.text_hash && (post.content || "").trim()) ||
				(hasMedia && (row.media_url_hashes || []).length === 0) ||
				(hasMedia && (row.perceptual_hashes || []).length === 0)
			);
		})
		.slice(0, MAX_POSTS_PER_RUN);

	let processed = 0;
	let withPerceptualHashes = 0;
	let failed = 0;
	let mediaFetches = 0;

	for (const post of candidates) {
		try {
			const platform = post.instagram_account_id ? "instagram" : "threads";
			const existingRow = existing.get(post.id);
			const shouldFetchMedia =
				hasUsableMedia(post) &&
				(existingRow?.perceptual_hashes || []).length === 0 &&
				mediaFetches < MAX_MEDIA_FETCHES_PER_RUN;
			const signals = await buildOriginalitySignals(
				{
					postId: post.id,
					userId: post.user_id,
					content: post.content,
					mediaUrls: post.media_urls,
					metadata: post.metadata,
				},
				{ fetchMedia: shouldFetchMedia },
			);
			if (shouldFetchMedia) mediaFetches++;
			const now = new Date().toISOString();
			const perceptualHashes = shouldFetchMedia
				? signals.perceptualHashes
				: (existingRow?.perceptual_hashes ?? signals.perceptualHashes);
			const { error: upsertError } = await db
				.from("post_originality_signals")
				.upsert(
					{
						user_id: post.user_id,
						post_id: post.id,
						account_id: post.account_id,
						instagram_account_id: post.instagram_account_id,
						platform,
						text_hash: signals.textHash,
						media_url_hashes: signals.mediaUrlHashes,
						perceptual_hashes: perceptualHashes,
						watermark_applied: signals.watermarkApplied,
						provenance: signals.provenance,
						captured_at: now,
						updated_at: now,
					},
					{ onConflict: "post_id" },
				);
			if (upsertError) throw upsertError;
			processed++;
			if (perceptualHashes.length > 0) withPerceptualHashes++;
		} catch {
			failed++;
		}
	}

	return {
		processed,
		withPerceptualHashes,
		failed,
		mediaFetches,
		skippedExisting: posts.length - candidates.length,
		candidates: posts.length,
	};
}

function hasUsableMedia(post: PostRow): boolean {
	return (
		Array.isArray(post.media_urls) &&
		post.media_urls.some((url) => typeof url === "string" && url.trim())
	);
}
