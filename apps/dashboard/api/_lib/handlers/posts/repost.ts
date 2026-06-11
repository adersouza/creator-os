/**
 * Repost handler — repost a Threads post to the user's profile.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { repostOnThreads } from "../../threadsApi.js";
import { db, type ThreadsAccountTokenRow } from "./shared.js";

/**
 * Repost a Threads post to the user's profile (§6.13).
 * Accepts { accountId, mediaId } — mediaId is the Threads media ID to repost.
 */
export async function handleRepost(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { accountId, mediaId } = req.body ?? {};

	if (!accountId || typeof accountId !== "string") {
		return apiError(res, 400, "accountId is required");
	}
	if (!mediaId || typeof mediaId !== "string") {
		return apiError(res, 400, "mediaId is required");
	}

	const { data: account } = (await db()
		.from("accounts")
		.select("threads_access_token_encrypted")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as {
		data: ThreadsAccountTokenRow | null;
		error: unknown;
	};

	if (!account?.threads_access_token_encrypted) {
		return apiError(res, 404, "Account not found");
	}

	const result = await repostOnThreads(
		account.threads_access_token_encrypted,
		mediaId,
	);

	if (!result.success) {
		return apiError(res, 400, result.error || "Repost failed");
	}

	return apiSuccess(res, { repostId: result.repostId });
}
