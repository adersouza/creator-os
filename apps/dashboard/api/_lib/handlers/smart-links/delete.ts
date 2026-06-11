/**
 * Delete a smart link.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { db } from "./shared.js";

export async function handleDelete(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const id = (req.query.id || req.body?.id) as string;
	if (!id) return apiError(res, 400, "id is required");

	// Get code for cache invalidation
	const { data: link } = await db()
		.from("smart_links")
		.select("id, code")
		.eq("id", id)
		.eq("user_id", userId)
		.maybeSingle();

	if (!link) return apiError(res, 404, "Smart link not found");

	const { error } = await db()
		.from("smart_links")
		.delete()
		.eq("id", id)
		.eq("user_id", userId);

	if (error) {
		logger.error("[smart-links] Delete error", { error: String(error) });
		return apiError(res, 500, "Failed to delete smart link");
	}

	// Invalidate Redis cache
	try {
		const { invalidateCache } = await import("../../redisCache.js");
		await invalidateCache(`smartlink:${link.code}`);
	} catch {
		/* Redis optional */
	}

	return apiSuccess(res, { deleted: true });
}
