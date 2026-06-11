/**
 * Threads Publishing Quota
 *
 * GET /api/threads/quota?accountId=xxx
 *
 * Returns current publishing quota usage for a Threads account.
 * Docs: https://developers.facebook.com/docs/threads/quota
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { decrypt } from "../../encryption.js";
import { logger } from "../../logger.js";
import { withRetry } from "../../retryUtils.js";
import { getSupabase } from "../../supabase.js";

const APP_ORIGIN =
	process.env.APP_URL ||
	(process.env.VERCEL_URL
		? `https://${process.env.VERCEL_URL}`
		: "https://juno33.com");

export default async function handler(req: VercelRequest, res: VercelResponse) {
	res.setHeader("Access-Control-Allow-Origin", APP_ORIGIN);
	res.setHeader("Access-Control-Allow-Methods", "GET,OPTIONS");
	res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");

	if (req.method === "OPTIONS") return res.status(200).end();
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	const authHeader = req.headers.authorization;
	if (!authHeader?.startsWith("Bearer "))
		return apiError(res, 401, "Missing authorization");

	const token = authHeader.replace("Bearer ", "");
	const {
		data: { user },
		error: authError,
	} = await getSupabase().auth.getUser(token);
	if (authError || !user) return apiError(res, 401, "Invalid token");

	const accountId = req.query.accountId as string;
	if (!accountId) return apiError(res, 400, "accountId is required");

	try {
		const { data: account, error } = await getSupabase()
			.from("accounts")
			.select("id, threads_user_id, threads_access_token_encrypted")
			.eq("id", accountId)
			.eq("user_id", user.id)
			.maybeSingle();

		if (error || !account) return apiError(res, 404, "Account not found");

		const acc = account as {
			threads_access_token_encrypted: string;
			threads_user_id: string;
		};
		const accessToken = decrypt(acc.threads_access_token_encrypted);
		const threadsUserId = acc.threads_user_id;

		const quotaUrl = `https://graph.threads.net/v1.0/${threadsUserId}/threads_publishing_limit?fields=quota_usage,config,reply_quota_usage,reply_config,delete_quota_usage,delete_config,location_search_quota_usage,location_search_config`;

		const response = await withRetry(
			() =>
				fetch(quotaUrl, {
					headers: { Authorization: `Bearer ${accessToken}` },
					signal: AbortSignal.timeout(8000),
				}),
			{ label: `threadsQuota:${threadsUserId}` },
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			logger.error("[threads/quota] API error", { error: data.error });
			return apiError(res, 400, data.error?.message || "Failed to fetch quota");
		}

		// Parse the response
		const quotaData = data.data?.[0] || data;

		return apiSuccess(res, {
			posts: {
				used: quotaData.quota_usage ?? 0,
				limit: quotaData.config?.quota_total ?? 250,
				duration: quotaData.config?.quota_duration ?? 86400,
			},
			replies: {
				used: quotaData.reply_quota_usage ?? 0,
				limit: quotaData.reply_config?.quota_total ?? 1000,
				duration: quotaData.reply_config?.quota_duration ?? 86400,
			},
			deletes: {
				used: quotaData.delete_quota_usage ?? 0,
				limit: quotaData.delete_config?.quota_total ?? 100,
				duration: quotaData.delete_config?.quota_duration ?? 86400,
			},
			locationSearches: {
				used: quotaData.location_search_quota_usage ?? 0,
				limit: quotaData.location_search_config?.quota_total ?? 500,
				duration: quotaData.location_search_config?.quota_duration ?? 86400,
			},
		});
	} catch (err: unknown) {
		logger.error("[threads/quota] Error", { error: String(err) });
		return apiError(res, 500, "Failed to fetch publishing quota");
	}
}
