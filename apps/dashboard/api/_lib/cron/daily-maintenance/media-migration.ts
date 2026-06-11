// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Phase 5: Media Migration
 * Migrates expired CDN URLs to Supabase Storage for post media.
 */

import type { Logger, PhaseMetadata, TypedSupabaseClient } from "./shared.js";
import {
	BUCKET_NAME,
	getExtensionFromContentType,
	hasTimeBudget,
	MEDIA_BATCH_SIZE,
} from "./shared.js";
import { fetchAllowedMediaUrl } from "../../outboundUrlSecurity.js";

async function storeMediaFromUrl(
	supabase: TypedSupabaseClient,
	sourceUrl: string,
	userId: string,
	postId: string,
	mediaIndex: number,
	logger: Logger,
): Promise<string | null> {
	try {
		if (sourceUrl.includes("supabase")) {
			return sourceUrl;
		}

		const response = await fetchAllowedMediaUrl(sourceUrl, {
			signal: AbortSignal.timeout(15000),
		});
		if (!response?.ok) {
			logger.error("[daily-maintenance] Failed to download media", {
				status: response?.status,
			});
			return null;
		}

		const contentType = response.headers.get("content-type") || "image/jpeg";
		const extension = getExtensionFromContentType(contentType);
		const filename = `${userId}/${postId}/${mediaIndex}.${extension}`;

		const arrayBuffer = await response.arrayBuffer();
		let buffer: Buffer = Buffer.from(new Uint8Array(arrayBuffer));

		// Strip EXIF metadata from JPEG images (removes GPS, device info, timestamps)
		if (contentType.includes("jpeg") || contentType.includes("jpg")) {
			try {
				const { stripExifFromBuffer } = await import("../../exifStrip.js");
				buffer = stripExifFromBuffer(buffer);
			} catch (stripErr) {
				logger.warn(
					"[daily-maintenance] EXIF strip failed, uploading with metadata",
					{
						error: String(stripErr),
					},
				);
			}
		}

		const { error } = await supabase.storage
			.from(BUCKET_NAME)
			.upload(filename, buffer, { contentType, upsert: true });

		if (error) {
			logger.error("[daily-maintenance] Failed to upload media to storage", {
				error: String(error),
			});
			return null;
		}

		const { data: urlData } = supabase.storage
			.from(BUCKET_NAME)
			.getPublicUrl(filename);

		return urlData?.publicUrl || null;
	} catch (err) {
		logger.error("[daily-maintenance] Error storing media", {
			error: err instanceof Error ? err.message : String(err),
		});
		return null;
	}
}

async function storePostMedia(
	supabase: TypedSupabaseClient,
	mediaUrls: string[],
	userId: string,
	postId: string,
	logger: Logger,
): Promise<string[]> {
	const storedUrls: string[] = [];
	for (let i = 0; i < mediaUrls.length; i++) {
		const storedUrl = await storeMediaFromUrl(
			supabase,
			mediaUrls[i]!,
			userId,
			postId,
			i,
			logger,
		);
		storedUrls.push(storedUrl || mediaUrls[i]!);
	}
	return storedUrls;
}

export async function phaseMediaMigration(
	supabase: TypedSupabaseClient,
	logger: Logger,
	startTime: number,
): Promise<PhaseMetadata["mediaMigration"]> {
	const { decrypt } = await import("../../encryption.js");

	// Find posts with non-Supabase media URLs
	const { data: posts, error: fetchError } = await supabase
		.from("posts")
		.select("id, user_id, account_id, threads_post_id, media_urls")
		.not("media_urls", "is", null)
		.not("threads_post_id", "is", null)
		.limit(MEDIA_BATCH_SIZE);

	if (fetchError) {
		logger.error("[daily-maintenance] Media migration fetch error", {
			error: String(fetchError),
		});
		throw new Error(fetchError.message);
	}

	// Filter to only posts with CDN URLs (not already Supabase)
	const postsToMigrate = (posts || []).filter((post) => {
		const urls = post.media_urls as string[];
		return (
			urls &&
			urls.length > 0 &&
			urls.some((url: string) => url && !url.includes("supabase"))
		);
	});

	logger.info("[daily-maintenance] Found posts to migrate", {
		count: postsToMigrate.length,
	});

	if (postsToMigrate.length === 0) {
		return { migrated: 0, failed: 0 };
	}

	// Get unique account IDs to fetch tokens
	const accountIds = [
		...new Set(
			postsToMigrate
				.map((p) => p.account_id)
				.filter((id): id is string => id !== null),
		),
	];

	const { data: accounts } = await supabase
		.from("accounts")
		.select("id, threads_access_token_encrypted")
		.in("id", accountIds);

	const tokenMap = new Map<string, string>();
	for (const account of (accounts || []) as {
		id: string;
		threads_access_token_encrypted: string | null;
	}[]) {
		if (account.threads_access_token_encrypted) {
			try {
				tokenMap.set(
					account.id,
					decrypt(account.threads_access_token_encrypted),
				);
			} catch (_e) {
				logger.warn("[daily-maintenance] Failed to decrypt token for account", {
					accountId: account.id,
				});
			}
		}
	}

	let migrated = 0;
	let failed = 0;

	for (const post of postsToMigrate) {
		if (!hasTimeBudget(startTime)) {
			logger.warn(
				"[daily-maintenance] Time budget exhausted during media migration",
			);
			break;
		}

		try {
			const accessToken = post.account_id
				? tokenMap.get(post.account_id)
				: undefined;
			if (!accessToken) {
				logger.warn(
					"[daily-maintenance] No token for account during media migration",
					{ accountId: post.account_id },
				);
				failed++;
				continue;
			}

			// Fetch fresh post data from Threads API
			const response = await fetch(
				`https://graph.threads.net/v1.0/${post.threads_post_id}?fields=id,media_url,media_type`,
				{
					headers: { Authorization: `Bearer ${accessToken}` },
					signal: AbortSignal.timeout(10000),
				},
			);

			if (!response.ok) {
				logger.warn(
					"[daily-maintenance] Failed to fetch post for media migration",
					{
						threadsPostId: post.threads_post_id,
						status: response.status,
					},
				);
				failed++;
				continue;
			}

			const threadPost = await response.json();

			if (!threadPost.media_url) {
				await supabase
					.from("posts")
					.update({ media_urls: [] })
					.eq("id", post.id);
				continue;
			}

			const storedUrls = await storePostMedia(
				supabase,
				[threadPost.media_url],
				post.user_id,
				post.threads_post_id ?? "",
				logger,
			);

			if (storedUrls.length > 0 && storedUrls[0]!.includes("supabase")) {
				await supabase
					.from("posts")
					.update({ media_urls: storedUrls })
					.eq("id", post.id);
				migrated++;
				logger.info("[daily-maintenance] Migrated post media", {
					postId: post.id,
				});
			} else {
				failed++;
			}
		} catch (err) {
			logger.error(
				"[daily-maintenance] Error processing post for media migration",
				{
					postId: post.id,
					error: err instanceof Error ? err.message : String(err),
				},
			);
			failed++;
		}
	}

	logger.info("[daily-maintenance] Media migration complete", {
		migrated,
		failed,
	});
	return { migrated, failed };
}
