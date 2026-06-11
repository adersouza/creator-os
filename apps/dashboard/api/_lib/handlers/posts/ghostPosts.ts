/**
 * Ghost posts handler — fetch ghost posts for a Threads account.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { db } from "./shared.js";

/**
 * Fetch ghost posts for a Threads account (§6.11).
 * Ghost posts are auto-published text posts that expire after 24h.
 * Accepts { accountId }.
 */
export async function handleGhostPosts(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { accountId } = req.body ?? {};
	if (!accountId || typeof accountId !== "string") {
		return apiError(res, 400, "accountId is required");
	}

	const { data: account } = (await db()
		.from("accounts")
		.select("threads_access_token_encrypted, threads_user_id")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as {
		// biome-ignore lint/suspicious/noExplicitAny: Supabase untyped
		data: any | null;
		error: unknown;
	};

	if (!account?.threads_access_token_encrypted || !account?.threads_user_id) {
		return apiError(res, 404, "Account not found");
	}

	try {
		const { getGhostPosts } = await import("../../threadsApi.js");
		const data = await getGhostPosts(
			account.threads_access_token_encrypted,
			account.threads_user_id,
		);
		return apiSuccess(res, { posts: data.data || [] });
	} catch (error: unknown) {
		logger.error("Ghost posts fetch error", {
			error: error instanceof Error ? error.message : String(error),
			accountId,
		});
		return apiError(res, 500, "Failed to fetch ghost posts");
	}
}
