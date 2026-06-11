// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Phase 8: Orphaned Storage Cleanup
 * Removes files in the post-media bucket that are no longer referenced
 * by any post. Only files older than 7 days are considered orphaned.
 */

import type { Logger, PhaseMetadata, TypedSupabaseClient } from "./shared.js";
import { BUCKET_NAME } from "./shared.js";

type StorageListItem = {
	name: string;
	created_at?: string | null | undefined;
	updated_at?: string | null | undefined;
	id?: string | null | undefined;
	metadata?: Record<string, unknown> | null | undefined;
};

type StorageObject = {
	path: string;
	createdAt: string | null;
};

const BATCH_SIZE = 20;
const MAX_DELETE_PER_RUN = 200;
const MAX_LIST_DEPTH = 6;
const ORPHANED_AFTER_MS = 7 * 24 * 60 * 60 * 1000;

export async function phaseStorageCleanup(
	supabase: TypedSupabaseClient,
	logger: Logger,
): Promise<PhaseMetadata["storageCleanup"]> {
	let deleted = 0;

	// Get all media_urls from posts
	const { data: posts, error: postsErr } = await supabase
		.from("posts")
		.select("media_urls")
		.not("media_urls", "is", null);

	if (postsErr) {
		logger.error("[daily-maintenance] Failed to query post media_urls", {
			error: postsErr.message,
		});
		return { deleted: 0, error: postsErr.message };
	}

	// Build set of referenced storage paths
	const referencedPaths = new Set<string>();
	for (const post of posts || []) {
		for (const url of post.media_urls || []) {
			const path = extractPostMediaPath(url);
			if (path) referencedPaths.add(path);
		}
	}

	const listed = await listStorageObjectsRecursive(supabase, logger);
	if (listed.error) {
		return { deleted: 0, referenced: referencedPaths.size, error: listed.error };
	}
	if (listed.objects.length === 0) {
		return { deleted: 0, scanned: 0, referenced: referencedPaths.size };
	}

	const orphanedBefore = new Date(Date.now() - ORPHANED_AFTER_MS).toISOString();

	// Find orphaned files (not referenced + older than 7 days)
	const orphaned = listed.objects
		.filter((file) => {
			if (referencedPaths.has(file.path)) return false;
			// Only delete old files to avoid race conditions with in-progress uploads
			return Boolean(file.createdAt && file.createdAt < orphanedBefore);
		})
		.slice(0, MAX_DELETE_PER_RUN);

	if (orphaned.length === 0) {
		logger.info("[daily-maintenance] No orphaned storage files found", {
			scanned: listed.objects.length,
			referenced: referencedPaths.size,
		});
		return {
			deleted: 0,
			scanned: listed.objects.length,
			referenced: referencedPaths.size,
			orphaned: 0,
		};
	}

	for (let i = 0; i < orphaned.length; i += BATCH_SIZE) {
		const batch = orphaned.slice(i, i + BATCH_SIZE).map((file) => file.path);
		const { error: delErr } = await supabase.storage
			.from(BUCKET_NAME)
			.remove(batch);
		if (delErr) {
			logger.error("[daily-maintenance] Failed to delete storage batch", {
				error: delErr.message,
				batch,
			});
		} else {
			deleted += batch.length;
		}
	}

	logger.info("[daily-maintenance] Orphaned storage cleanup complete", {
		deleted,
		total: orphaned.length,
		scanned: listed.objects.length,
		referenced: referencedPaths.size,
	});
	return {
		deleted,
		scanned: listed.objects.length,
		referenced: referencedPaths.size,
		orphaned: orphaned.length,
	};
}

function extractPostMediaPath(value: unknown): string | null {
	if (typeof value !== "string" || !value.trim()) return null;
	const raw = value.trim();

	if (!raw.includes("://")) {
		return normalizeStoragePath(raw);
	}

	try {
		const url = new URL(raw);
		const marker = `/storage/v1/object/public/${BUCKET_NAME}/`;
		const markerIndex = url.pathname.indexOf(marker);
		if (markerIndex >= 0) {
			return normalizeStoragePath(
				decodeURIComponent(url.pathname.slice(markerIndex + marker.length)),
			);
		}

		const bucketMarker = `/${BUCKET_NAME}/`;
		const bucketIndex = url.pathname.indexOf(bucketMarker);
		if (bucketIndex >= 0) {
			return normalizeStoragePath(
				decodeURIComponent(url.pathname.slice(bucketIndex + bucketMarker.length)),
			);
		}
	} catch {
		const match = raw.match(new RegExp(`/${BUCKET_NAME}/([^?#]+)`));
		if (match?.[1]) return normalizeStoragePath(decodeURIComponent(match[1]));
	}

	return null;
}

function normalizeStoragePath(path: string): string | null {
	const normalized = path.replace(/^\/+/, "").split(/[?#]/)[0]?.trim();
	if (!normalized || normalized === ".emptyFolderPlaceholder") return null;
	return normalized;
}

function isStorageObject(item: StorageListItem): boolean {
	return Boolean(item.id || item.created_at || item.updated_at);
}

async function listStorageObjectsRecursive(
	supabase: TypedSupabaseClient,
	logger: Logger,
	prefix = "",
	depth = 0,
): Promise<{ objects: StorageObject[]; error?: string | undefined }> {
	if (depth > MAX_LIST_DEPTH) {
		logger.warn("[daily-maintenance] Storage cleanup max depth reached", {
			prefix,
		});
		return { objects: [] };
	}

	const { data, error } = await supabase.storage.from(BUCKET_NAME).list(prefix, {
		limit: 1000,
		sortBy: { column: "name", order: "asc" },
	});

	if (error) {
		logger.error("[daily-maintenance] Failed to list storage files", {
			error: error.message,
			prefix,
		});
		return { objects: [], error: error.message };
	}

	const objects: StorageObject[] = [];
	for (const item of (data || []) as StorageListItem[]) {
		if (!item.name || item.name === ".emptyFolderPlaceholder") continue;
		const path = prefix ? `${prefix}/${item.name}` : item.name;

		if (isStorageObject(item)) {
			objects.push({ path, createdAt: item.created_at || item.updated_at || null });
			continue;
		}

		const nested = await listStorageObjectsRecursive(
			supabase,
			logger,
			path,
			depth + 1,
		);
		if (nested.error) return nested;
		objects.push(...nested.objects);
	}

	return { objects };
}
