/**
 * Internal accounts list endpoint (Bearer auth)
 * GET /api/accounts
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "./_lib/apiResponse.js";
import { withAuthDb } from "./_lib/middleware.js";
import { enforceRouteRateLimit } from "./_lib/routeRateLimit.js";

interface ThreadsAccountRow {
	id: string;
	username: string | null;
	display_name: string | null;
	avatar_url: string | null;
	followers_count: number | null;
	following_count: number | null;
	is_active: boolean | null;
	last_synced_at: string | null;
	created_at: string | null;
	group_id: string | null;
}

interface IgAccountRow {
	id: string;
	username: string | null;
	display_name: string | null;
	avatar_url: string | null;
	follower_count: number | null;
	following_count: number | null;
	is_active: boolean | null;
	last_synced_at: string | null;
	created_at: string | null;
	group_id: string | null;
}

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, context) => {
		const { user, userDb, adminDbAny } = context;
		const action = req.query.action as string;
		const isWrite = action === "bulk-sync";
		const allowed = await enforceRouteRateLimit(res, {
			key: `accounts-${isWrite ? "write" : "read"}:${user.id}`,
			limit: 60,
			windowSeconds: 60,
			failMode: isWrite ? "closed" : "open",
			message: "Rate limit exceeded",
		});
		if (!allowed) return;

		if (action === "bulk-cap-status") {
			return (
				await import("./_lib/handlers/accounts-sub/bulk-cap-status.js")
			).default(req, res);
		}
		if (action === "bio-audit") {
			return (
				await import("./_lib/handlers/accounts-sub/bio-audit.js")
			).default(req, res, user);
		}
		if (action === "bulk-sync") {
			return (
				await import("./_lib/handlers/accounts-sub/bulk-sync.js")
			).default(req, res, user);
		}
		if (action === "assign-group") {
			if (req.method !== "POST") return apiError(res, 405, "Method not allowed");
			const accountId =
				typeof req.body?.accountId === "string" ? req.body.accountId : null;
			const groupId =
				typeof req.body?.groupId === "string" && req.body.groupId.length > 0
					? req.body.groupId
					: null;
			if (!accountId) return apiError(res, 400, "accountId is required");

			const { error } = await adminDbAny.rpc("assign_account_to_group", {
				p_account_id: accountId,
				p_target_group_id: groupId,
				p_user_id: user.id,
			});
			if (error) {
				return apiError(res, 500, "Failed to assign account to group", {
					details: error.message,
				});
			}
			return apiSuccess(res);
		}
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const [{ data: threads }, { data: instagram }] = await Promise.all([
			userDb
				.from("accounts")
				.select(
					"id, username, display_name, avatar_url, followers_count, following_count, is_active, last_synced_at, created_at, group_id",
				)
				.eq("user_id", user.id),
			userDb
				.from("instagram_accounts")
				.select(
					"id, username, display_name, avatar_url, follower_count, following_count, is_active, last_synced_at, created_at, group_id",
				)
				.eq("user_id", user.id),
		]);

		const accounts = [
			...(threads || []).map((a: ThreadsAccountRow) => ({
				id: a.id,
				platform: "threads",
				username: a.username,
				display_name: a.display_name,
				avatar_url: a.avatar_url,
				follower_count: a.followers_count || 0,
				following_count: a.following_count || 0,
				is_active: a.is_active,
				last_synced_at: a.last_synced_at,
				connected_at: a.created_at,
				group_id: a.group_id,
			})),
			...(instagram || []).map((a: IgAccountRow) => ({
				id: a.id,
				platform: "instagram",
				username: a.username,
				display_name: a.display_name,
				avatar_url: a.avatar_url,
				follower_count: a.follower_count || 0,
				following_count: a.following_count || 0,
				is_active: a.is_active,
				last_synced_at: a.last_synced_at,
				connected_at: a.created_at,
				group_id: a.group_id,
			})),
		];

		return apiSuccess(res, { accounts });
	},
);
