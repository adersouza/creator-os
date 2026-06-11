/**
 * Thread chain handler — publishes a multi-post thread chain on Threads.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { decrypt } from "../../encryption.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { withRetry } from "../../retryUtils.js";
import { sanitizeHtml } from "../../sanitize.js";
import { type AccountRow, db } from "./shared.js";

export async function handleThreadChain(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { accountId, posts: postContents } = req.body;

	if (!accountId) return apiError(res, 400, "accountId is required");
	if (!postContents || !Array.isArray(postContents) || postContents.length < 2)
		return apiError(res, 400, "At least 2 posts required for chain");

	const { data: account, error: accountError } = (await db()
		.from("accounts")
		.select("id, threads_user_id, threads_access_token_encrypted")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as { data: AccountRow | null; error: unknown };

	if (accountError || !account) {
		return apiError(res, 404, "Account not found");
	}

	if (!account.threads_access_token_encrypted) {
		return apiError(res, 400, "Account not properly configured");
	}

	const rateLimit = await checkRateLimit({
		key: `threads-chain:${userId}:${accountId}:hour`,
		limit: 20,
		windowSeconds: 3600,
		failMode: "closed",
	});
	if (!rateLimit.allowed) {
		return apiError(res, 429, "Thread chain rate limit exceeded.");
	}

	const token = decrypt(account.threads_access_token_encrypted);
	const postIds: string[] = [];
	let replyToId: string | null = null;

	// Create thread chain
	for (let i = 0; i < postContents.length; i++) {
		const content = sanitizeHtml(postContents[i]);

		// Step 1: Create container
		const createParams: Record<string, string> = {
			media_type: "TEXT",
			text: content,
		};

		if (replyToId) {
			createParams.reply_to_id = replyToId;
		}

		const createUrl = `https://graph.threads.net/v1.0/${account.threads_user_id}/threads`;
		const createResponse = await withRetry(() =>
			fetch(createUrl, {
				method: "POST",
				headers: {
					"Content-Type": "application/x-www-form-urlencoded",
					Authorization: `Bearer ${token}`,
				},
				body: new URLSearchParams(createParams),
				signal: AbortSignal.timeout(10000),
			}),
		);

		const createData = await createResponse.json();
		if (!createResponse.ok || !createData.id) {
			return apiError(
				res,
				500,
				`Failed to create thread ${i + 1}: ${createData.error?.message || "Unknown error"}`,
			);
		}

		const containerId = createData.id;

		// Step 2: Publish
		const publishUrl = `https://graph.threads.net/v1.0/${account.threads_user_id}/threads_publish`;
		const publishResponse = await withRetry(() =>
			fetch(publishUrl, {
				method: "POST",
				headers: {
					"Content-Type": "application/x-www-form-urlencoded",
					Authorization: `Bearer ${token}`,
				},
				body: new URLSearchParams({
					creation_id: containerId,
				}),
				signal: AbortSignal.timeout(10000),
			}),
		);

		const publishData = await publishResponse.json();
		if (!publishResponse.ok || !publishData.id) {
			return apiError(
				res,
				500,
				`Failed to publish thread ${i + 1}: ${publishData.error?.message || "Unknown error"}`,
			);
		}

		postIds.push(publishData.id);
		replyToId = publishData.id;

		// Rate limiting
		await new Promise((resolve) => setTimeout(resolve, 500));
	}

	return apiSuccess(res, {
		postIds,
	});
}
