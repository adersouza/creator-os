/**
 * List all smart links for the authenticated user.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { db } from "./shared.js";

export async function handleList(
	_req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { data, error } = await db()
		.from("smart_links")
		.select("*")
		.eq("user_id", userId)
		.order("created_at", { ascending: false });

	if (error) {
		logger.error("[smart-links] List error", { error: String(error) });
		return apiError(res, 500, "Failed to fetch smart links");
	}

	return apiSuccess(res, { links: data || [] });
}
