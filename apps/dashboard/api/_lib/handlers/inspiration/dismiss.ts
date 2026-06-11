/**
 * Dismiss an inspiration idea.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiSuccess, badRequest, serverError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { db, IdSchema } from "./shared.js";

export async function handleDismiss(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = IdSchema.safeParse(req.body);
	if (!parsed.success) {
		return badRequest(res, `Invalid input: ${parsed.error.issues[0]?.message}`);
	}
	const { id } = parsed.data;

	try {
		const { error } = await db()
			.from("inspiration_ideas")
			.update({ status: "dismissed" })
			.eq("id", id)
			.eq("user_id", userId);

		if (error) throw error;

		return apiSuccess(res);
	} catch (error: unknown) {
		logger.error("Dismiss idea error", { error: String(error) });
		return serverError(res, "Internal server error");
	}
}
