/**
 * Threads Profile Discovery Endpoint
 *
 * POST /api/threads/profile?action=lookup|posts
 *
 * Called from threads.ts router.
 * Uses getAuthUserOrError directly to avoid double-wrapping.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, getAuthUserOrError } from "../../apiResponse.js";
import { createDbContext } from "../../dbContext.js";
import { logger } from "../../logger.js";
import { getProfilePosts, lookupThreadsProfile } from "../../threadsApi.js";
import { verifyAccountOwnership } from "../helpers/verifyOwnership.js";

export default async function handleProfile(
	req: VercelRequest,
	res: VercelResponse,
) {
	if (req.method !== "POST") return apiError(res, 405, "Method not allowed");

	const user = await getAuthUserOrError(req, res);
	if (!user) return;
	const { userDb } = createDbContext(req, user);

	// Sub-action comes from body (query param is "profile" from Vercel rewrite)
	const action = (req.body?.action || req.query.subAction) as string;
	const { accountId, username, limit } = req.body;

	if (!accountId || !username) {
		return apiError(res, 400, "accountId and username are required");
	}

	const account = (await verifyAccountOwnership(
		res,
		accountId,
		user.id,
		"id, threads_user_id, threads_access_token_encrypted",
		userDb,
	)) as {
		id: string;
		threads_user_id: string | null;
		threads_access_token_encrypted: string | null;
	} | null;
	if (!account) return;

	if (!account.threads_access_token_encrypted) {
		return apiError(res, 400, "Account not connected to Threads");
	}

	try {
		switch (action) {
			case "lookup": {
				const profile = await lookupThreadsProfile(
					account.threads_access_token_encrypted,
					username,
				);
				return apiSuccess(res, { profile });
			}

			case "posts": {
				const posts = await getProfilePosts(
					account.threads_access_token_encrypted,
					username,
					limit || 25,
				);
				return apiSuccess(res, { posts });
			}

			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		const message =
			error instanceof Error ? error.message : JSON.stringify(error);
		// "Invalid operation" means the token lacks threads_profile_discovery scope —
		// user needs to reconnect the account to grant the newer permission.
		if (message === "Invalid operation") {
			logger.warn("Profile discovery missing scope", {
				action,
				username,
				accountId,
			});
			return apiError(
				res,
				403,
				"This account needs to be reconnected to enable profile discovery. Go to Settings → Accounts and reconnect.",
			);
		}
		logger.error("Profile discovery error", {
			action,
			username,
			error: message,
		});
		return apiError(res, 500, "Profile discovery failed", {
			details: message,
		});
	}
}
