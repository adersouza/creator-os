// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Draft Folders CRUD API Route
 * POST /api/draft-folders?action=list|create|update|delete|move-posts
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logAudit } from "../../auditLog.js";
import type { DbContext } from "../../dbContext.js";
import { logger } from "../../logger.js";
import { withAuthDb } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { getUserTier } from "../../tierGate.js";
import { z } from "../../zodCompat.js";

type UserDb = DbContext["userDb"];

interface DraftFolder {
	id: string;
	user_id: string;
	name: string;
	color: string;
	icon: string;
	sort_order: number;
	created_at: string;
}

// ---------------------------------------------------------------------------
// Tier Limits
// ---------------------------------------------------------------------------

const FOLDER_LIMITS: Record<string, number> = {
	free: 3,
	pro: 20,
	agency: Infinity,
	empire: Infinity,
};

// ---------------------------------------------------------------------------
// Zod Schemas
// ---------------------------------------------------------------------------

const CreateSchema = z.object({
	name: z.string().min(1, "name is required").max(100),
	color: z.string().optional(),
	icon: z.string().optional(),
	sort_order: z.number().int().optional(),
});

const UpdateSchema = z.object({
	folderId: z.string().min(1, "folderId is required"),
	name: z.string().min(1).max(100).optional(),
	color: z.string().optional(),
	icon: z.string().optional(),
	sort_order: z.number().int().optional(),
});

const DeleteSchema = z.object({
	folderId: z.string().min(1, "folderId is required"),
});

const MovePostsSchema = z.object({
	postIds: z.array(z.string().min(1)).min(1, "postIds must not be empty"),
	folderId: z.string().nullable(),
});

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

async function handleList(
	_req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: UserDb,
) {
	// Fetch folders ordered by sort_order asc, then created_at desc
	const { data: folders, error } = await userDb
		.from("draft_folders")
		.select("*")
		.eq("user_id", userId)
		.order("sort_order", { ascending: true })
		.order("created_at", { ascending: false });

	if (error) {
		logger.error("[Draft Folders] Error fetching folders", {
			error: String(error),
		});
		return apiError(res, 500, "Failed to fetch folders");
	}

	if (!folders || folders.length === 0) {
		return apiSuccess(res, { folders: [] });
	}

	// Get draft post counts per folder
	const folderIds = (folders as unknown as DraftFolder[]).map((f) => f.id);
	const { data: postCounts, error: countError } = await userDb
		.from("posts")
		.select("draft_folder_id")
		.eq("user_id", userId)
		.eq("status", "draft")
		.in("draft_folder_id", folderIds);

	if (countError) {
		logger.error("[Draft Folders] Error counting posts", {
			error: String(countError),
		});
		// Return folders without counts rather than failing entirely
		const foldersWithCount = (folders as unknown as DraftFolder[]).map((f) => ({
			...f,
			post_count: 0,
		}));
		return apiSuccess(res, { folders: foldersWithCount });
	}

	// Tally counts per folder
	const countMap: Record<string, number> = {};
	for (const row of postCounts || []) {
		const fid = row.draft_folder_id;
		if (fid) {
			countMap[fid] = (countMap[fid] || 0) + 1;
		}
	}

	const foldersWithCount = (folders as unknown as DraftFolder[]).map((f) => ({
		...f,
		post_count: countMap[f.id] || 0,
	}));

	return apiSuccess(res, { folders: foldersWithCount });
}

async function handleCreate(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: UserDb,
) {
	const parsed = CreateSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { name, color, icon, sort_order } = parsed.data;

	// Enforce tier-based folder limits
	const userTier = await getUserTier(userId);
	const limit = FOLDER_LIMITS[userTier] ?? FOLDER_LIMITS.free;

	if (limit !== Infinity) {
		const { count, error: countError } = await userDb
			.from("draft_folders")
			.select("id", { count: "exact", head: true })
			.eq("user_id", userId);

		if (countError) {
			logger.error("[Draft Folders] Error counting folders", {
				error: String(countError),
			});
			return apiError(res, 500, "Failed to check folder count");
		}

		if ((count ?? 0) >= limit!) {
			return apiError(
				res,
				403,
				`Folder limit reached (${limit} for ${userTier} tier). Upgrade to create more.`,
				{ code: "FOLDER_LIMIT_REACHED" },
			);
		}
	}

	const { data: folder, error } = await userDb
		.from("draft_folders")
		.insert({
			user_id: userId,
			name,
			color: color || "#6366f1",
			icon: icon || "folder",
			sort_order: sort_order ?? 0,
		})
		.select()
		.maybeSingle();

	if (error) {
		logger.error("[Draft Folders] Error creating folder", {
			error: String(error),
		});
		return apiError(res, 500, "Failed to create folder");
	}

	return apiSuccess(res, { folder }, 201);
}

async function handleUpdate(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: UserDb,
) {
	const parsed = UpdateSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { folderId, name, color, icon, sort_order } = parsed.data;

	// Verify ownership
	const { data: existing } = await userDb
		.from("draft_folders")
		.select("id")
		.eq("id", folderId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!existing) {
		return apiError(res, 404, "Folder not found");
	}

	const updateData: Partial<DraftFolder> = {};
	if (name !== undefined) updateData.name = name;
	if (color !== undefined) updateData.color = color;
	if (icon !== undefined) updateData.icon = icon;
	if (sort_order !== undefined) updateData.sort_order = sort_order;

	// #IDOR-fix: include user_id filter to prevent cross-user folder update
	const { data: folder, error } = await userDb
		.from("draft_folders")
		.update(updateData)
		.eq("id", folderId)
		.eq("user_id", userId)
		.select()
		.maybeSingle();

	if (error) {
		logger.error("[Draft Folders] Error updating folder", {
			error: String(error),
		});
		return apiError(res, 500, "Failed to update folder");
	}

	return apiSuccess(res, { folder });
}

async function handleDelete(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: UserDb,
) {
	const parsed = DeleteSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { folderId } = parsed.data;

	// Verify ownership
	const { data: existing } = await userDb
		.from("draft_folders")
		.select("id")
		.eq("id", folderId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!existing) {
		return apiError(res, 404, "Folder not found");
	}

	// Unfile posts first (set draft_folder_id = NULL) so they are not deleted
	await userDb
		.from("posts")
		.update({ draft_folder_id: null })
		.eq("draft_folder_id", folderId)
		.eq("user_id", userId);

	// Delete the folder
	const { error } = await userDb
		.from("draft_folders")
		.delete()
		.eq("id", folderId)
		.eq("user_id", userId);

	if (error) {
		logger.error("[Draft Folders] Error deleting folder", {
			error: String(error),
		});
		return apiError(res, 500, "Failed to delete folder");
	}

	return apiSuccess(res);
}

async function handleMovePosts(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: UserDb,
) {
	const parsed = MovePostsSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { postIds, folderId } = parsed.data;

	// If folderId is not null, verify folder ownership
	if (folderId !== null) {
		const { data: folder } = await userDb
			.from("draft_folders")
			.select("id")
			.eq("id", folderId)
			.eq("user_id", userId)
			.maybeSingle();

		if (!folder) {
			return apiError(res, 404, "Target folder not found");
		}
	}

	// Verify user owns all posts
	const { data: ownedPosts, error: ownerError } = await userDb
		.from("posts")
		.select("id")
		.eq("user_id", userId)
		.in("id", postIds);

	if (ownerError) {
		logger.error("[Draft Folders] Error verifying post ownership", {
			error: String(ownerError),
		});
		return apiError(res, 500, "Failed to verify post ownership");
	}

	const ownedIds = new Set((ownedPosts || []).map((p: { id: string }) => p.id));
	const unauthorized = postIds.filter((id) => !ownedIds.has(id));
	if (unauthorized.length > 0) {
		return apiError(res, 403, "You do not own all specified posts");
	}

	// Move posts to folder (or unfiled if null)
	const { error } = await userDb
		.from("posts")
		.update({ draft_folder_id: folderId })
		.in("id", postIds)
		.eq("user_id", userId);

	if (error) {
		logger.error("[Draft Folders] Error moving posts", {
			error: String(error),
		});
		return apiError(res, 500, "Failed to move posts");
	}

	return apiSuccess(res, { moved: postIds.length, folderId });
}

// ---------------------------------------------------------------------------
// Main Handler
// ---------------------------------------------------------------------------

export default withAuthDb(async (req, res, context) => {
	const { user, userDb } = context;
	const userId = user.id;

	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	// Rate limit: 30 requests/60s per user
	const rl = await checkRateLimit({
		key: `draft-folders:${userId}`,
		limit: 30,
		windowSeconds: 60,
		failMode: "open",
	});
	if (!rl.allowed) {
		return apiError(res, 429, "Rate limit exceeded. Please wait a moment.");
	}

	const action = req.query.action as string;

	try {
		switch (action) {
			case "list":
				return handleList(req, res, userId, userDb);
			case "create":
				logAudit(userId, "draft-folder.create", { req });
				return handleCreate(req, res, userId, userDb);
			case "update":
				logAudit(userId, "draft-folder.update", { req });
				return handleUpdate(req, res, userId, userDb);
			case "delete":
				logAudit(userId, "draft-folder.delete", { req });
				return handleDelete(req, res, userId, userDb);
			case "move-posts":
				logAudit(userId, "draft-folder.move-posts", { req });
				return handleMovePosts(req, res, userId, userDb);
			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("[Draft Folders] API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
