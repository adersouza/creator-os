/**
 * Handler for managing (hiding/unhiding) a reply.
 * Action: "manage"
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiSuccess,
	badRequest,
	notFound,
	serverError,
} from "../../apiResponse.js";
import { decrypt } from "../../encryption.js";
import { hideComment as igHideComment } from "../../instagramApi.js";
import { logger } from "../../logger.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { resolveAccount } from "../../resolveAccount.js";
import { withRetry } from "../../retryUtils.js";
import { ManageReplySchema } from "./shared.js";

export async function handleManageReply(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = ManageReplySchema.safeParse(req.body);
	if (!parsed.success) {
		return badRequest(res, `Invalid input: ${parsed.error.issues[0]?.message}`);
	}
	const { accountId, replyId, hide } = parsed.data;

	const resolved = await resolveAccount(accountId, userId);
	if (!resolved) {
		return notFound(res, "Account not found");
	}

	if (!resolved.encryptedToken) {
		return badRequest(res, "Account not properly configured");
	}

	const rateLimit = await checkRateLimit({
		key: `replies-manage:${userId}:${accountId}:hour`,
		limit: 120,
		windowSeconds: 3600,
		failMode: "closed",
	});
	if (!rateLimit.allowed) {
		return badRequest(res, "Rate limit exceeded for reply management.");
	}

	// ---- Instagram path: hide/unhide comment ----
	if (resolved.platform === "instagram") {
		logger.info("[replies:ig] Managing IG comment", { replyId, hide });
		const result = await igHideComment(
			resolved.encryptedToken,
			replyId,
			hide,
			resolved.loginType,
		);
		if (!result.success) {
			return serverError(
				res,
				result.error || "Failed to manage Instagram comment",
			);
		}
		return apiSuccess(res);
	}

	// ---- Threads path (original) ----
	const token = decrypt(resolved.encryptedToken);

	const manageUrl = `https://graph.threads.net/v1.0/${replyId}/manage_reply`;
	const response = await withRetry(() =>
		fetch(manageUrl, {
			method: "POST",
			headers: {
				Authorization: `Bearer ${token}`,
				"Content-Type": "application/x-www-form-urlencoded",
			},
			body: new URLSearchParams({
				hide: hide.toString(),
			}),
			signal: AbortSignal.timeout(15000),
		}),
	);

	const result = await response.json();

	if (!response.ok || result.error) {
		return serverError(res, result.error?.message || "Failed to manage reply");
	}

	return apiSuccess(res);
}
