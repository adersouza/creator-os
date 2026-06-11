/**
 * Save/unsave an inspiration idea.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiSuccess, badRequest, serverError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { db, SaveSchema } from "./shared.js";

export async function handleSave(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = SaveSchema.safeParse(req.body);
	if (!parsed.success) {
		return badRequest(res, `Invalid input: ${parsed.error.issues[0]?.message}`);
	}
	const { id, unsave } = parsed.data;

	try {
		const updates = unsave
			? { saved: false, status: "pending" }
			: { saved: true, status: "saved" };

		const { error } = await db()
			.from("inspiration_ideas")
			.update(updates)
			.eq("id", id)
			.eq("user_id", userId);

		if (error) throw error;

		return apiSuccess(res);
	} catch (error: unknown) {
		logger.error("Save idea error", { error: String(error) });
		return serverError(res, "Internal server error");
	}
}
