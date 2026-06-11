/**
 * Consolidated Media API Route
 * GET /api/media?action=random
 * POST /api/media?action=upload
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import type { DbContext } from "../../dbContext.js";
import { logger } from "../../logger.js";
import { withAuthDb } from "../../middleware.js";
import { enforceRouteRateLimit } from "../../routeRateLimit.js";
import { getUserTier } from "../../tierGate.js";
import { z } from "../../zodCompat.js";

type MediaDb = DbContext["userDb"];

async function handleRandom(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	db: MediaDb,
) {
	const groupId = req.query.groupId as string | undefined;
	const imagesOnly = req.query.imagesOnly === "true";

	let query = db
		.from("media")
		.select("id, file_name, url, storage_url, mime_type, group_id")
		.eq("user_id", userId);
	if (groupId) query = query.eq("group_id", groupId);
	if (imagesOnly) query = query.like("mime_type", "image/%");

	const { data: mediaList, error: mediaError } = await query.limit(500);

	if (mediaError) {
		return apiError(res, 500, "Failed to fetch media");
	}

	if (!mediaList?.length) {
		return apiSuccess(res, { media: null });
	}

	const randomIndex = Math.floor(Math.random() * mediaList.length);
	const media = mediaList[randomIndex];

	if (!media) {
		return apiSuccess(res, { media: null });
	}

	return apiSuccess(res, {
		media: {
			id: media.id,
			fileName: media.file_name,
			url: media.url || media.storage_url,
			mimeType: media.mime_type,
			groupId: media.group_id,
		},
	});
}

// Allowed MIME types for media uploads
const ALLOWED_MIME_TYPES = [
	"image/jpeg",
	"image/jpg",
	"image/png",
	"image/gif",
	"image/webp",
	"video/mp4",
	"video/quicktime",
	"video/webm",
];

const MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024; // 50MB server-side limit
const MEDIA_ITEM_LIMITS: Record<string, number> = {
	free: 100,
	pro: 1000,
	agency: 10000,
	empire: Infinity,
};

async function checkMediaItemQuota(
	userId: string,
	additionalCount: number,
	db: MediaDb,
): Promise<{ allowed: boolean; tier: string; used: number; limit: number }> {
	const tier = await getUserTier(userId);
	const limit = MEDIA_ITEM_LIMITS[tier] ?? MEDIA_ITEM_LIMITS.free ?? 100;
	if (limit === Infinity) return { allowed: true, tier, used: 0, limit };

	const { count, error } = await db
		.from("media")
		.select("*", { count: "exact", head: true })
		.eq("user_id", userId);
	if (error) {
		logger.error("[media] Failed to count media for quota check", {
			userId,
			error: error.message,
		});
		throw new Error("Failed to check media quota");
	}

	const used = count || 0;
	return {
		allowed: used + Math.max(0, additionalCount) <= limit,
		tier,
		used,
		limit,
	};
}

function storagePathFromAppUrl(fileUrl: string): string | null {
	try {
		const parsed = new URL(fileUrl);
		if (parsed.protocol !== "https:") return null;
		const supabaseUrl = process.env.SUPABASE_URL || "";
		if (supabaseUrl && parsed.hostname !== new URL(supabaseUrl).hostname) {
			return null;
		}
		const marker = "/storage/v1/object/";
		const markerIndex = parsed.pathname.indexOf(marker);
		if (markerIndex < 0) return null;
		const objectPath = parsed.pathname.slice(markerIndex + marker.length);
		const withoutVisibility = objectPath.replace(/^(public|sign)\//, "");
		if (!withoutVisibility.startsWith("media/")) return null;
		return decodeURIComponent(withoutVisibility.slice("media/".length));
	} catch {
		return null;
	}
}

function storagePathBelongsToUser(path: string, userId: string): boolean {
	return path === userId || path.startsWith(`${userId}/`);
}

const UploadSchema = z.object({
	fileName: z
		.string()
		.min(1, "fileName is required")
		.max(255, "fileName too long"),
	fileUrl: z.string().url("fileUrl must be a valid URL"),
	storagePath: z.string().optional(),
	mimeType: z
		.string()
		.optional()
		.refine((val) => !val || ALLOWED_MIME_TYPES.includes(val), {
			message: "Unsupported file type",
		}),
	fileSize: z
		.number()
		.max(MAX_FILE_SIZE_BYTES, "File too large (max 50MB)")
		.optional(),
	folderId: z.string().uuid("Invalid folder ID").nullable().optional(),
	groupId: z.string().uuid("Invalid group ID").nullable().optional(),
	accountId: z.string().uuid("Invalid account ID").nullable().optional(),
	accountPlatform: z.enum(["threads", "instagram"]).nullable().optional(),
});

async function handleUpload(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	db: MediaDb,
) {
	const parsed = UploadSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const {
		fileName,
		fileUrl,
		storagePath,
		mimeType,
		folderId,
		groupId,
		accountId,
		accountPlatform,
	} = parsed.data;

	const quota = await checkMediaItemQuota(userId, 1, db);
	if (!quota.allowed) {
		return apiError(
			res,
			403,
			`Media library limit reached for your plan (${quota.used}/${quota.limit}).`,
			{ code: "MEDIA_QUOTA_EXCEEDED" },
		);
	}

	// Explicit SVG/XML block — SVG can contain embedded scripts (XSS)
	if (mimeType && (mimeType.includes("svg") || mimeType.includes("xml"))) {
		return apiError(res, 400, "SVG and XML files are not permitted");
	}

	// Validate that fileUrl points to our own Supabase storage (prevent SSRF)
	const supabaseUrl = process.env.SUPABASE_URL || "";
	if (supabaseUrl && !fileUrl.startsWith(supabaseUrl)) {
		return apiError(res, 400, "File URL must point to application storage");
	}
	const resolvedStoragePath = storagePath || storagePathFromAppUrl(fileUrl);
	if (!resolvedStoragePath || !storagePathBelongsToUser(resolvedStoragePath, userId)) {
		return apiError(res, 400, "Storage path does not belong to this user");
	}
	if (storagePath && storagePathFromAppUrl(fileUrl) !== storagePath) {
		return apiError(res, 400, "Storage path does not match file URL");
	}

	// Validate folder belongs to user if provided
	if (folderId) {
		const { data: folder, error: folderError } = await db
			.from("media_folders")
			.select("id")
			.eq("id", folderId)
			.eq("user_id", userId)
			.maybeSingle();
		if (folderError || !folder) {
			return apiError(res, 400, "Invalid folder");
		}
	}
	if (accountId) {
		const table =
			accountPlatform === "instagram" ? "instagram_accounts" : "accounts";
		const { data: account, error: accountError } = await db
			.from(table)
			.select("id")
			.eq("id", accountId)
			.eq("user_id", userId)
			.maybeSingle();
		if (accountError || !account) {
			return apiError(res, 400, "Invalid creator");
		}
	}
	if (groupId) {
		const { data: group, error: groupError } = await db
			.from("account_groups")
			.select("id")
			.eq("id", groupId)
			.eq("user_id", userId)
			.maybeSingle();
		if (groupError || !group) {
			return apiError(res, 400, "Invalid group");
		}
	}

	// Strip EXIF metadata from JPEG uploads at ingestion time (privacy: removes GPS, device info)
	if (mimeType && (mimeType.includes("jpeg") || mimeType.includes("jpg"))) {
		try {
			const { stripExifFromStorageUrl } = await import("../../exifStrip.js");
			await stripExifFromStorageUrl(fileUrl);
		} catch (stripErr) {
			// Non-blocking — file is still usable without stripping
			logger.warn(
				"[media] EXIF strip failed at ingestion, uploading with metadata",
				{
					error: String(stripErr),
					fileUrl: fileUrl.substring(0, 100),
				},
			);
		}
	}

	// Auto-flag videos as spotlight-eligible (staged for Snap Spotlight reposting)
	const isVideo = mimeType?.startsWith("video/");

	const { data: media, error: insertError } = await db
		.from("media")
		.insert({
			user_id: userId,
			file_name: fileName,
			url: fileUrl,
			storage_url: fileUrl,
			storage_path: resolvedStoragePath,
			mime_type: mimeType || null,
			folder_id: folderId || null,
			group_id: groupId || null,
			account_id: accountId || null,
			account_platform: accountId ? accountPlatform || null : null,
			spotlight_eligible: isVideo || false,
			created_at: new Date().toISOString(),
			// biome-ignore lint/suspicious/noExplicitAny: media table insert fields not fully in generated types
		} as any)
		.select()
		.maybeSingle();

	if (insertError) {
		logger.error("[media] Failed to save media record", {
			error: insertError.message,
			code: insertError.code,
			details: insertError.details,
			hint: insertError.hint,
			fileName,
			mimeType,
		});
		return apiError(res, 500, "Failed to save media record");
	}

	if (!media) {
		return apiError(res, 500, "Failed to retrieve saved media record");
	}

	return apiSuccess(res, {
		media: {
			id: media.id,
			fileName: media.file_name,
			url: media.url,
			mimeType: media.mime_type,
			folderId: media.folder_id,
			groupId: media.group_id,
			accountId: media.account_id,
			accountPlatform: media.account_platform,
			createdAt: media.created_at,
		},
	});
}

async function handleSpotlightQueue(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	db: MediaDb,
) {
	const groupId = req.query.groupId as string | undefined;
	const limit = Math.min(Math.max(Number(req.query.limit) || 50, 1), 200);

	let query = db
		.from("media")
		.select("id, file_name, url, storage_url, mime_type, group_id, created_at")
		.eq("user_id", userId)
		.eq("spotlight_eligible", true)
		.order("created_at", { ascending: false })
		.limit(limit);

	if (groupId) {
		query = query.eq("group_id", groupId);
	}

	const { data, error } = await query;

	if (error) {
		return apiError(res, 500, "Internal server error");
	}

	const items = data || [];

	// Resolve group names for organization
	const groupIds = [
		...new Set(
			items.map((i: Record<string, unknown>) => i.group_id).filter(Boolean),
		),
	] as string[];
	const groupNameMap = new Map<string, string>();
	if (groupIds.length > 0) {
		const { data: groups } = await db
			.from("account_groups")
			.select("id, name")
			.in("id", groupIds);
		for (const g of groups || []) {
			groupNameMap.set(g.id, g.name || g.id);
		}
	}

	// Organize by group (model name)
	const byGroup: Record<
		string,
		Array<{ id: string; fileName: string; url: string; createdAt: string }>
	> = {};
	for (const item of items) {
		const groupName = groupNameMap.get(item.group_id as string) || "ungrouped";
		if (!byGroup[groupName]) byGroup[groupName] = [];
		byGroup[groupName].push({
			id: item.id as string,
			fileName: item.file_name as string,
			url: (item.storage_url || item.url) as string,
			createdAt: item.created_at as string,
		});
	}

	return apiSuccess(res, {
		total: items.length,
		groups: byGroup,
	});
}

const BulkRegisterSchema = z.object({
	items: z
		.array(
			z.object({
				fileName: z.string().min(1).max(255),
				fileUrl: z.string().url(),
				mimeType: z.string().optional(),
				groupId: z.string().uuid().optional(),
			}),
		)
		.min(1)
		.max(500),
});

async function handleBulkRegister(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	db: MediaDb,
) {
	const parsed = BulkRegisterSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(res, 400, "Invalid input");
	}

	const { items } = parsed.data;
	const supabaseUrl = process.env.SUPABASE_URL || "";
	const quota = await checkMediaItemQuota(userId, items.length, db);
	if (!quota.allowed) {
		return apiError(
			res,
			403,
			`Media library limit reached for your plan (${quota.used}/${quota.limit} used, ${items.length} requested).`,
			{ code: "MEDIA_QUOTA_EXCEEDED" },
		);
	}

	const rows = items.map((item) => ({
		user_id: userId,
		file_name: item.fileName,
		url: item.fileUrl,
		storage_url: item.fileUrl,
		storage_path: storagePathFromAppUrl(item.fileUrl),
		mime_type:
			item.mimeType || (item.fileName.endsWith(".mp4") ? "video/mp4" : null),
		folder_id: null,
		group_id: item.groupId || null,
		spotlight_eligible:
			item.mimeType?.startsWith("video/") ||
			item.fileName.endsWith(".mp4") ||
			false,
		created_at: new Date().toISOString(),
	}));

	// Validate all URLs point to our Supabase storage
	if (supabaseUrl) {
		const badUrl = rows.find((r) => !r.url.startsWith(supabaseUrl));
		if (badUrl) {
			return apiError(
				res,
				400,
				"All file URLs must point to application storage",
			);
		}
	}
	for (const item of items) {
		const resolvedPath = storagePathFromAppUrl(item.fileUrl);
		if (!resolvedPath || !storagePathBelongsToUser(resolvedPath, userId)) {
			return apiError(res, 400, "All file URLs must belong to this user");
		}
	}
	const groupIds = [
		...new Set(items.map((item) => item.groupId).filter(Boolean)),
	] as string[];
	if (groupIds.length > 0) {
		const { data: groups, error: groupsError } = await db
			.from("account_groups")
			.select("id")
			.eq("user_id", userId)
			.in("id", groupIds);
		if (groupsError || (groups || []).length !== groupIds.length) {
			return apiError(res, 400, "Invalid group");
		}
	}

	const { data, error } = await db
		.from("media")
		// biome-ignore lint/suspicious/noExplicitAny: media table insert fields not fully in generated types
		.insert(rows as any[])
		.select("id, file_name, url, group_id");

	if (error) {
		logger.error("[media] Bulk register failed", {
			error: error.message,
			code: error.code,
			hint: error.hint,
			count: items.length,
		});
		return apiError(res, 500, "Bulk register failed");
	}

	return apiSuccess(res, {
		registered: data?.length ?? 0,
		items: (data || []).map((m: Record<string, unknown>) => ({
			id: m.id,
			fileName: m.file_name,
			url: m.url,
			groupId: m.group_id,
		})),
	});
}

const UPLOAD_ACTIONS = new Set(["upload", "bulk-register", "share", "refresh"]);
const READ_ACTIONS = new Set(["random", "spotlight-queue", "giphy"]);

export default withAuthDb(async (req, res, { user, userDb }) => {
	const isGiphy = req.query._handler === "giphy";
	const action = isGiphy ? "giphy" : (req.query.action as string);
	if (UPLOAD_ACTIONS.has(action) || READ_ACTIONS.has(action)) {
		const isUpload = UPLOAD_ACTIONS.has(action);
		const allowed = await enforceRouteRateLimit(res, {
			key: `media-${isUpload ? "upload" : "read"}:user:${user.id}:hour`,
			limit: isUpload ? 30 : 120,
			windowSeconds: 3600,
			failMode: isUpload ? "closed" : "open",
			message: isUpload
				? "Too many media upload requests. Try again later."
				: "Too many media read requests. Try again later.",
		});
		if (!allowed) return;
	}

	// Giphy uses its own `action` param (search/trending), so route via _handler to avoid collision
	if (isGiphy) {
		return (await import("../../handlers/media-sub/giphy.js")).default(
			req,
			res,
		);
	}

	try {
		switch (action) {
			case "random":
				if (req.method !== "GET")
					return apiError(res, 405, "Method not allowed");
				return handleRandom(req, res, user.id, userDb);
			case "upload":
				if (req.method !== "POST")
					return apiError(res, 405, "Method not allowed");
				return handleUpload(req, res, user.id, userDb);
			case "bulk-register":
				if (req.method !== "POST")
					return apiError(res, 405, "Method not allowed");
				return handleBulkRegister(req, res, user.id, userDb);
			case "spotlight-queue":
				if (req.method !== "GET")
					return apiError(res, 405, "Method not allowed");
				return handleSpotlightQueue(req, res, user.id, userDb);
			case "share":
				return (await import("../../handlers/media-sub/share.js")).default(
					req,
					res,
				);
			case "refresh":
				return (await import("../../handlers/media-sub/refresh.js")).default(
					req,
					res,
				);
			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("Media API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
