/**
 * Threads Reply Approvals Endpoint
 *
 * POST /api/threads/reply-approvals?action=pending|approve|decline
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import {
	approveReply,
	declineReply,
	getPendingReplies,
} from "../../threadsApi.js";

const db = () => getSupabase();

export default withAuth(async (req, res, user) => {
	if (req.method !== "POST") return apiError(res, 405, "Method not allowed");

	const action = req.query.action as string;
	const { accountId, mediaId, replyId } = req.body;

	if (!accountId) {
		return apiError(res, 400, "accountId is required");
	}

	const { data: account, error: accountError } = await db()
		.from("accounts")
		.select("id, threads_user_id, threads_access_token_encrypted")
		.eq("id", accountId)
		.eq("user_id", user.id)
		.maybeSingle();

	if (accountError || !account) {
		return apiError(res, 404, "Account not found");
	}

	if (!account.threads_access_token_encrypted) {
		return apiError(res, 400, "Account not connected to Threads");
	}

	try {
		switch (action) {
			case "pending": {
				if (!mediaId) {
					return apiError(res, 400, "mediaId is required");
				}
				const replies = await getPendingReplies(
					account.threads_access_token_encrypted,
					mediaId,
				);
				return apiSuccess(res, { replies });
			}

			case "approve": {
				if (!replyId) {
					return apiError(res, 400, "replyId is required");
				}
				const result = await approveReply(
					account.threads_access_token_encrypted,
					replyId,
				);
				return apiSuccess(res, { result });
			}

			case "decline": {
				if (!replyId) {
					return apiError(res, 400, "replyId is required");
				}
				const result = await declineReply(
					account.threads_access_token_encrypted,
					replyId,
				);
				return apiSuccess(res, { result });
			}

			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("Reply approvals error", { action, error: String(error) });
		return apiError(res, 500, "Reply approval action failed");
	}
});
