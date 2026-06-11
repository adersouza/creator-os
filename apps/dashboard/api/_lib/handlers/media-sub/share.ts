/**
 * Media Folder Share API Route
 * POST /api/media/share
 *
 * Toggles the shared/unshared state of a media folder,
 * making it visible to all workspace members when shared.
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import { logAudit } from "../../auditLog.js";
import { logger } from "../../logger.js";
import { withAuthDb } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { z } from "../../zodCompat.js";

// ---------------------------------------------------------------------------
// Zod Schema
// ---------------------------------------------------------------------------

const ShareSchema = z.object({
	folderId: z.string().min(1, "folderId is required"),
	isShared: z.boolean(),
});

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
		key: `media-share:${userId}`,
		limit: 30,
		windowSeconds: 60,
		failMode: "open",
	});
	if (!rl.allowed) {
		return apiError(res, 429, "Rate limit exceeded. Please wait a moment.");
	}

	const parsed = ShareSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const { folderId, isShared } = parsed.data;

	try {
		// Verify user owns the folder
		const { data: folder, error: folderError } = await userDb
			.from("media_folders")
			.select("id, user_id, name")
			.eq("id", folderId)
			.eq("user_id", userId)
			.maybeSingle();

		if (folderError) {
			logger.error("[Media Share] Error fetching folder", {
				error: String(folderError),
			});
			return apiError(res, 500, "Failed to fetch folder");
		}

		if (!folder) {
			return apiError(res, 404, "Folder not found");
		}

		if (isShared) {
			// Look up user's workspace
			const { data: membership, error: memberError } = await userDb
				.from("workspace_members")
				.select("workspace_id")
				.eq("user_id", userId)
				.limit(1)
				.maybeSingle();

			if (memberError) {
				logger.error("[Media Share] Error fetching workspace membership", {
					error: String(memberError),
				});
				return apiError(res, 500, "Failed to fetch workspace membership");
			}

			if (!membership?.workspace_id) {
				return apiError(
					res,
					400,
					"You are not a member of any workspace. Create or join a workspace first.",
				);
			}

			// Set is_shared = true and workspace_id
			const { error: updateError } = await userDb
				.from("media_folders")
				.update({
					is_shared: true,
					workspace_id: membership.workspace_id,
				})
				.eq("id", folderId)
				.eq("user_id", userId);

			if (updateError) {
				logger.error("[Media Share] Error sharing folder", {
					error: String(updateError),
				});
				return apiError(res, 500, "Failed to share folder");
			}

			logAudit(userId, "media-folder.share", {
				resourceType: "media_folder",
				resourceId: folderId,
				metadata: {
					workspaceId: membership.workspace_id,
					folderName: folder.name,
				},
				req,
			});

			return apiSuccess(res, {
				folderId,
				isShared: true,
				workspaceId: membership.workspace_id,
			});
		} else {
			// Unshare: set is_shared = false and workspace_id = NULL
			const { error: updateError } = await userDb
				.from("media_folders")
				.update({
					is_shared: false,
					workspace_id: null,
				})
				.eq("id", folderId)
				.eq("user_id", userId);

			if (updateError) {
				logger.error("[Media Share] Error unsharing folder", {
					error: String(updateError),
				});
				return apiError(res, 500, "Failed to unshare folder");
			}

			logAudit(userId, "media-folder.unshare", {
				resourceType: "media_folder",
				resourceId: folderId,
				metadata: { folderName: folder.name },
				req,
			});

			return apiSuccess(res, {
				folderId,
				isShared: false,
				workspaceId: null,
			});
		}
	} catch (error: unknown) {
		logger.error("[Media Share] API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
