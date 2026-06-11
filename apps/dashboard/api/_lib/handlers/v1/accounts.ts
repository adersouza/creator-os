/**
 * Public API v1 — GET /api/v1/accounts
 * List connected accounts for the authenticated API key user.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { getFollowerCount } from "../../followerCount.js";
import { getSupabaseAny } from "../../supabase.js";
import { withApiKey } from "../../withApiKey.js";

interface ThreadsAccountRow {
	id: string;
	username: string | null;
	followers_count: number | null;
	created_at: string | null;
}

interface IgAccountRow {
	id: string;
	username: string | null;
	follower_count: number | null;
	created_at: string | null;
}

export default withApiKey(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const db = getSupabaseAny();

		// Threads accounts (uses followers_count — plural)
		const { data: threads } = await db
			.from("accounts")
			.select("id, username, followers_count, created_at")
			.eq("user_id", user.id);

		// Instagram accounts (uses follower_count — singular)
		const { data: instagram } = await db
			.from("instagram_accounts")
			.select("id, username, follower_count, created_at")
			.eq("user_id", user.id);

		const accounts = [
			...(threads || []).map((a: ThreadsAccountRow) => ({
				id: a.id,
				platform: "threads",
				username: a.username,
				follower_count: getFollowerCount(a),
				connected_at: a.created_at,
			})),
			...(instagram || []).map((a: IgAccountRow) => ({
				id: a.id,
				platform: "instagram",
				username: a.username,
				follower_count: getFollowerCount(a),
				connected_at: a.created_at,
			})),
		].filter((account) => !user.allowedAccountIds || user.allowedAccountIds.includes(account.id));

		return apiSuccess(res, { accounts });
	},
	"read",
);
