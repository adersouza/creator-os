/**
 * Handler for fetching a conversation thread.
 * Action: "conversation"
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiSuccess,
	badRequest,
	notFound,
	serverError,
} from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { resolveAccount } from "../../resolveAccount.js";

export async function handleConversation(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { accountId, mediaId, reverse } = req.body;
	if (!accountId || !mediaId) {
		return badRequest(res, "accountId and mediaId are required");
	}

	const account = await resolveAccount(accountId, userId);
	if (!account) {
		return notFound(res, "Account not found");
	}

	// biome-ignore lint/suspicious/noExplicitAny: Supabase row type lacks encrypted token field
	const encryptedToken = (account as any).threads_access_token_encrypted;
	if (!encryptedToken) {
		return badRequest(res, "No access token for this account");
	}

	try {
		const { getConversation } = await import("../../threadsApi.js");
		const data = await getConversation(encryptedToken, mediaId, !!reverse);
		return apiSuccess(res, data);
	} catch (error: unknown) {
		logger.error("Conversation fetch error", {
			error: error instanceof Error ? error.message : String(error),
			mediaId,
		});
		return serverError(res, "Failed to fetch conversation");
	}
}
