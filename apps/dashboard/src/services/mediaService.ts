// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Media Service
 * Handles media library operations with group assignment support
 * Used by Auto-Poster for group-specific media selection
 */

import logger from "@/utils/logger";
import { supabase } from "./supabase";

// Helper to get current user ID for Supabase
const getSupabaseUserId = async (): Promise<string | null> => {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	return session?.user?.id || null;
};

const getWorkspaceId = async (): Promise<string | null> => {
	try {
		const userId = await getSupabaseUserId();
		if (!userId) return null;
		const { data, error } = await supabase
			.from("workspaces")
			.select("id")
			.eq("owner_id", userId)
			.limit(1)
			.maybeSingle();
		if (error || !data) return null;
		return data.id;
	} catch {
		return null;
	}
};

// Media asset with group assignment
export interface MediaAsset {
	id: string;
	url: string;
	name: string;
	size: string;
	date: string;
	storagePath: string;
	folderId: string | null;
	groupId: string | null; // Group assignment for Auto-Poster
	accountId: string | null;
	accountPlatform: "threads" | "instagram" | null;
	workspaceId?: string | null | undefined;
	fileType: "image" | "video";
	mimeType?: string | undefined;
	lastUsedAt?: string | null | undefined;
}

// Media stats for a group
export interface GroupMediaStats {
	groupId: string;
	groupName: string;
	totalMedia: number;
	imageCount: number;
	videoCount: number;
}

interface MediaRow {
	id: string;
	file_url?: string | null | undefined;
	storage_url?: string | null | undefined;
	url?: string | null | undefined;
	file_name?: string | null | undefined;
	name?: string | null | undefined;
	file_size?: number | null | undefined;
	created_at?: string | null | undefined;
	storage_path?: string | null | undefined;
	folder_id?: string | null | undefined;
	group_id?: string | null | undefined;
	account_id?: string | null | undefined;
	account_platform?: "threads" | "instagram" | null | undefined;
	workspace_id?: string | null | undefined;
	file_type?: "image" | "video" | null | undefined;
	mime_type?: string | null | undefined;
	last_used_at?: string | null | undefined;
}

const MEDIA_CACHE_TTL_MS = 30_000;
const allMediaCache = new Map<
	string,
	{ expiresAt: number; rows: MediaAsset[] }
>();
const allMediaInFlight = new Map<string, Promise<MediaAsset[]>>();

function applyWorkspaceFilter<T>(query: T, workspaceId: string | null): T {
	const maybeQuery = query as {
		or?: (clause: string) => T;
		is?: (column: string, value: null) => T;
	};
	if (workspaceId && typeof maybeQuery.or === "function") {
		return maybeQuery.or(
			`workspace_id.eq.${workspaceId},workspace_id.is.null`,
		);
	}
	if (typeof maybeQuery.is === "function") {
		return maybeQuery.is("workspace_id", null);
	}
	return query;
}

export function invalidateMediaCache(userId?: string | null) {
	if (userId) {
		for (const key of allMediaCache.keys()) {
			if (key.startsWith(`${userId}:`)) allMediaCache.delete(key);
		}
		for (const key of allMediaInFlight.keys()) {
			if (key.startsWith(`${userId}:`)) allMediaInFlight.delete(key);
		}
		return;
	}
	allMediaCache.clear();
	allMediaInFlight.clear();
}

function mapMediaRow(row: MediaRow): MediaAsset {
	return {
		id: row.id,
		url: row.file_url || row.storage_url || row.url || "",
		name: row.file_name || row.name || "",
		size: row.file_size
			? `${(row.file_size / (1024 * 1024)).toFixed(1)} MB`
			: "Unknown",
		date: row.created_at
			? new Date(row.created_at).toLocaleDateString()
			: "Recently",
		storagePath: row.file_url || row.storage_path || "",
		folderId: row.folder_id || null,
		groupId: row.group_id || null,
		accountId: row.account_id || null,
		accountPlatform: row.account_platform || null,
		workspaceId: row.workspace_id || null,
		fileType: row.file_type || "image",
		mimeType: row.mime_type || undefined,
		lastUsedAt: row.last_used_at || null,
	};
}

/**
 * Get all media assets for the current user
 */
export const getAllMedia = async (
	workspaceId?: string | null,
): Promise<MediaAsset[]> => {
	const userId = await getSupabaseUserId();
	if (!userId) return [];
	const resolvedWorkspaceId = workspaceId ?? (await getWorkspaceId());
	const cacheKey = `${userId}:${resolvedWorkspaceId || "legacy"}`;
	const cached = allMediaCache.get(cacheKey);
	if (cached && cached.expiresAt > Date.now()) return cached.rows;
	const existing = allMediaInFlight.get(cacheKey);
	if (existing) return existing;

	const request = (async () => {
		let query = supabase
			.from("media")
			.select("*")
			.eq("user_id", userId)
			.order("last_used_at", { ascending: false, nullsFirst: false })
			.order("created_at", { ascending: false });
		query = applyWorkspaceFilter(query, resolvedWorkspaceId);
		const { data, error } = await query;

		if (error) throw error;

		return ((data || []) as MediaRow[]).map(mapMediaRow);
	})();
	allMediaInFlight.set(cacheKey, request);

	try {
		const rows = await request;
		allMediaCache.set(cacheKey, {
			expiresAt: Date.now() + MEDIA_CACHE_TTL_MS,
			rows,
		});
		return rows;
	} catch (error) {
		logger.error("[mediaService] Failed to get media:", error);
		return [];
	} finally {
		if (allMediaInFlight.get(cacheKey) === request)
			allMediaInFlight.delete(cacheKey);
	}
};

/**
 * Get media assets for a specific group
 */
export const getMediaByGroup = async (
	groupId: string,
	workspaceId?: string | null,
): Promise<MediaAsset[]> => {
	const userId = await getSupabaseUserId();
	if (!userId) return [];
	const resolvedWorkspaceId = workspaceId ?? (await getWorkspaceId());

	try {
		let query = supabase
			.from("media")
			.select("*")
			.eq("user_id", userId)
			.eq("group_id", groupId)
			.order("created_at", { ascending: false });
		query = applyWorkspaceFilter(query, resolvedWorkspaceId);
		const { data, error } = await query;

		if (error) throw error;

		return ((data || []) as MediaRow[]).map(mapMediaRow);
	} catch (error) {
		logger.error("[mediaService] Failed to get media by group:", error);
		return [];
	}
};

/**
 * Get count of media in a specific group
 */
export const getGroupMediaCount = async (groupId: string): Promise<number> => {
	const userId = await getSupabaseUserId();
	if (!userId) return 0;
	const workspaceId = await getWorkspaceId();

	try {
		let query = supabase
			.from("media")
			.select("*", { count: "exact", head: true })
			.eq("user_id", userId)
			.eq("group_id", groupId);
		query = applyWorkspaceFilter(query, workspaceId);
		const { count, error } = await query;

		if (error) throw error;
		return count || 0;
	} catch (error) {
		logger.error("[mediaService] Failed to get group media count:", error);
		return 0;
	}
};

/**
 * Get media stats for all groups
 */
export const getGroupMediaStats = async (
	groups: Array<{ id: string; name: string }>,
): Promise<GroupMediaStats[]> => {
	const userId = await getSupabaseUserId();
	if (!userId) return [];

	try {
		const allMedia = await getAllMedia();

		return groups.map((group) => {
			const groupMedia = allMedia.filter((m) => m.groupId === group.id);
			return {
				groupId: group.id,
				groupName: group.name,
				totalMedia: groupMedia.length,
				imageCount: groupMedia.filter((m) => m.fileType === "image").length,
				videoCount: groupMedia.filter((m) => m.fileType === "video").length,
			};
		});
	} catch (error) {
		logger.error("[mediaService] Failed to get group media stats:", error);
		return [];
	}
};

/**
 * Assign a single media item to a group
 */
export const assignMediaToGroup = async (
	mediaId: string,
	groupId: string | null,
): Promise<boolean> => {
	const userId = await getSupabaseUserId();
	if (!userId) return false;

	try {
		const workspaceId = await getWorkspaceId();
		const query = supabase
			.from("media")
			.update({ group_id: groupId })
			.eq("id", mediaId)
			.eq("user_id", userId);
		const scopedQuery = applyWorkspaceFilter(query, workspaceId);
		const { error } = await scopedQuery;

		if (error) throw error;
		logger.debug(
			`[mediaService] Assigned media ${mediaId} to group ${groupId || "none"}`,
		);
		return true;
	} catch (error) {
		logger.error("[mediaService] Failed to assign media to group:", error);
		return false;
	}
};

/**
 * Bulk assign multiple media items to a group
 */
export const bulkAssignMediaToGroup = async (
	mediaIds: string[],
	groupId: string | null,
): Promise<number> => {
	const userId = await getSupabaseUserId();
	if (!userId) return 0;

	try {
		const workspaceId = await getWorkspaceId();
		const query = supabase
			.from("media")
			.update({ group_id: groupId })
			.eq("user_id", userId)
			.in("id", mediaIds);
		const scopedQuery = applyWorkspaceFilter(query, workspaceId);
		const { error } = await scopedQuery;

		if (error) throw error;
		logger.debug(
			`[mediaService] Bulk assigned ${mediaIds.length} media to group ${groupId || "none"}`,
		);
		return mediaIds.length;
	} catch (error) {
		logger.error("[mediaService] Failed to bulk assign media:", error);
		return 0;
	}
};

export const assignMediaToAccount = async (
	mediaId: string,
	accountId: string | null,
	accountPlatform: "threads" | "instagram" | null,
): Promise<boolean> => {
	const userId = await getSupabaseUserId();
	if (!userId) return false;

	try {
		const workspaceId = await getWorkspaceId();
		const query = supabase
			.from("media")
			.update({
				account_id: accountId,
				account_platform: accountId ? accountPlatform : null,
			})
			.eq("id", mediaId)
			.eq("user_id", userId);
		const scopedQuery = applyWorkspaceFilter(query, workspaceId);
		const { error } = await scopedQuery;

		if (error) throw error;
		invalidateMediaCache(userId);
		return true;
	} catch (error) {
		logger.error("[mediaService] Failed to assign media to account:", error);
		return false;
	}
};

export const bulkAssignMediaToAccount = async (
	mediaIds: string[],
	accountId: string | null,
	accountPlatform: "threads" | "instagram" | null,
): Promise<number> => {
	const userId = await getSupabaseUserId();
	if (!userId) return 0;

	try {
		const workspaceId = await getWorkspaceId();
		const query = supabase
			.from("media")
			.update({
				account_id: accountId,
				account_platform: accountId ? accountPlatform : null,
			})
			.eq("user_id", userId)
			.in("id", mediaIds);
		const scopedQuery = applyWorkspaceFilter(query, workspaceId);
		const { error } = await scopedQuery;

		if (error) throw error;
		invalidateMediaCache(userId);
		return mediaIds.length;
	} catch (error) {
		logger.error("[mediaService] Failed to bulk assign media to account:", error);
		return 0;
	}
};

/**
 * Get a random media item from a specific group (for Auto-Poster)
 * Returns null if no media available for the group
 */
export const getRandomMediaForGroup = async (
	groupId: string,
	preferImages: boolean = true,
	workspaceId?: string | null,
): Promise<MediaAsset | null> => {
	const userId = await getSupabaseUserId();
	if (!userId) return null;

	try {
		const groupMedia = await getMediaByGroup(groupId, workspaceId);

		if (groupMedia.length === 0) {
			logger.debug(`[mediaService] No media found for group ${groupId}`);
			return null;
		}

		// Prefer images if specified, but fall back to any media
		const images = groupMedia.filter((m) => m.fileType === "image");
		const pool = preferImages && images.length > 0 ? images : groupMedia;

		// Random selection
		const randomIndex = Math.floor(Math.random() * pool.length);
		return pool[randomIndex]!;
	} catch (error) {
		logger.error("[mediaService] Failed to get random media:", error);
		return null;
	}
};

/**
 * Insert a media record after upload
 */
export const insertMedia = async (params: {
	userId: string;
	fileName: string;
	fileUrl: string;
	storagePath: string;
	fileType: "image" | "video";
	fileSize: number;
	mimeType: string;
	folderId?: string | null | undefined;
	groupId?: string | null | undefined;
	tags?: string[] | null | undefined;
	workspaceId?: string | null | undefined;
}): Promise<void> => {
	const workspaceId = params.workspaceId ?? (await getWorkspaceId());
	const { error } = await supabase.from("media").insert({
		user_id: params.userId,
		workspace_id: workspaceId,
		file_name: params.fileName,
		file_url: params.fileUrl,
		storage_path: params.storagePath,
		file_type: params.fileType,
		file_size: params.fileSize,
		mime_type: params.mimeType,
		folder_id: params.folderId ?? null,
		group_id: params.groupId ?? null,
		tags: params.tags ?? null,
	});
	if (error) throw error;
	invalidateMediaCache(params.userId);
};

/**
 * Get a random media item from all media (fallback for global)
 */
export const getRandomMedia = async (
	preferImages: boolean = true,
	workspaceId?: string | null,
): Promise<MediaAsset | null> => {
	const userId = await getSupabaseUserId();
	if (!userId) return null;

	try {
		const allMedia = await getAllMedia(workspaceId);

		if (allMedia.length === 0) {
			return null;
		}

		// Prefer images if specified
		const images = allMedia.filter((m) => m.fileType === "image");
		const pool = preferImages && images.length > 0 ? images : allMedia;

		const randomIndex = Math.floor(Math.random() * pool.length);
		return pool[randomIndex]!;
	} catch (error) {
		logger.error("[mediaService] Failed to get random media:", error);
		return null;
	}
};

/* =========================================================================
   Upload — direct to supabase.storage bucket 'media', then row into `media`.
   Callers should run client-side validation (see utils/mediaValidation.ts)
   before calling — this function only handles the transport.
   ========================================================================= */

export interface UploadInput {
	file: File;
	folderId?: string | null | undefined;
	groupId?: string | null | undefined;
	workspaceId?: string | null | undefined;
	onProgress?: (pct: number) => void;
}

export interface UploadResult {
	asset: MediaAsset;
	publicUrl: string;
}

export async function uploadMedia(input: UploadInput): Promise<UploadResult> {
	const userId = await getSupabaseUserId();
	if (!userId) throw new Error("Not authenticated");

	const { file, folderId = null, groupId = null } = input;
	const workspaceId = input.workspaceId ?? (await getWorkspaceId());

	const fileType: "image" | "video" = file.type.startsWith("video/")
		? "video"
		: "image";

	const ext =
		file.name.split(".").pop() || (fileType === "video" ? "mp4" : "jpg");
	const safeBase = file.name
		.replace(/\.[^.]+$/, "")
		.replace(/[^a-zA-Z0-9_-]+/g, "-")
		.slice(0, 40);
	const path = `${userId}/${Date.now()}-${safeBase}.${ext}`;

	const { error: uploadError } = await supabase.storage
		.from("media")
		.upload(path, file, {
			cacheControl: "3600",
			upsert: false,
			...(file.type ? { contentType: file.type } : {}),
		});

	if (uploadError) {
		logger.error("[mediaService] storage upload failed:", uploadError);
		throw uploadError;
	}

	const { data: pub } = supabase.storage.from("media").getPublicUrl(path);
	const publicUrl = pub?.publicUrl ?? "";

	const { data: row, error: insertError } = await supabase
		.from("media")
		.insert({
			user_id: userId,
			workspace_id: workspaceId,
			file_name: file.name,
			file_size: file.size,
			file_type: fileType,
			mime_type: file.type,
			file_url: publicUrl,
			storage_path: path,
			folder_id: folderId,
			group_id: groupId,
		})
		.select("*")
		.single();

	if (insertError || !row) {
		await supabase.storage.from("media").remove([path]);
		throw insertError || new Error("Media row insert failed");
	}
	invalidateMediaCache(userId);

	return {
		asset: mapMediaRow(row as MediaRow),
		publicUrl,
	};
}

/**
 * Upload to any bucket (avatars, whitelabel-logos) and return the public URL.
 * No `media` row inserted — caller persists URL to its own domain column.
 */
export async function uploadToBucket(
	bucket: string,
	file: File,
	pathPrefix?: string,
): Promise<string> {
	const userId = await getSupabaseUserId();
	if (!userId) throw new Error("Not authenticated");

	const ext = file.name.split(".").pop() || "jpg";
	const safeBase = file.name
		.replace(/\.[^.]+$/, "")
		.replace(/[^a-zA-Z0-9_-]+/g, "-")
		.slice(0, 40);
	const path = `${userId}/${pathPrefix ? `${pathPrefix}/` : ""}${Date.now()}-${safeBase}.${ext}`;

	const { error } = await supabase.storage.from(bucket).upload(path, file, {
		cacheControl: "3600",
		upsert: true,
		...(file.type ? { contentType: file.type } : {}),
	});

	if (error) {
		logger.error(`[mediaService] upload to ${bucket} failed:`, error);
		throw error;
	}

	const { data } = supabase.storage.from(bucket).getPublicUrl(path);
	return data?.publicUrl ?? "";
}
