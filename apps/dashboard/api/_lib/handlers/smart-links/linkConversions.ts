/**
 * List conversions for a specific smart link.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { db } from "./shared.js";

export async function handleLinkConversions(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const linkId = req.query.linkId as string;
	if (!linkId) return apiError(res, 400, "linkId is required");

	// Verify ownership
	const { data: link } = await db()
		.from("smart_links")
		.select("id")
		.eq("id", linkId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!link) return apiError(res, 404, "Smart link not found");

	const { data, error } = await db()
		.from("smart_link_conversions")
		.select("*")
		.eq("smart_link_id", linkId)
		.order("converted_at", { ascending: false })
		.limit(100);

	if (error) {
		logger.error("[smart-links] Conversions list error", {
			error: String(error),
		});
		return apiError(res, 500, "Failed to fetch conversions");
	}

	return apiSuccess(res, { conversions: data || [] });
}
