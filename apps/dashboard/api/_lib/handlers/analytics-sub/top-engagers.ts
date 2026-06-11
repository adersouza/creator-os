/**
 * Top Engagers
 *
 * GET /api/analytics?action=top-engagers&accountId=X&limit=10
 * Aggregates most frequent commenters/repliers from post_replies + ig_comments.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";

// biome-ignore lint/suspicious/noExplicitAny: flexible table queries
const db = (): any => getSupabase();

const QuerySchema = z.object({
	accountId: z.string().min(1),
	limit: z.coerce.number().int().min(1).max(50).optional().default(10),
});

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;

		const { data: threadsAccount } = await db()
			.from("accounts")
			.select("id")
			.eq("id", parsed.accountId)
			.eq("user_id", user.id)
			.maybeSingle();

		let accountPlatform: "threads" | "instagram" | null = threadsAccount
			? "threads"
			: null;

		if (!accountPlatform) {
			const { data: instagramAccount } = await db()
				.from("instagram_accounts")
				.select("id")
				.eq("id", parsed.accountId)
				.eq("user_id", user.id)
				.maybeSingle();
			if (instagramAccount) accountPlatform = "instagram";
		}

		if (!accountPlatform) return apiError(res, 404, "Account not found");

		const engagerMap = new Map<
			string,
			{ username: string; count: number; lastInteraction: string }
		>();

		if (accountPlatform === "threads") {
			const { data: replies } = await db()
				.from("post_replies")
				.select("reply_username, created_at")
				.eq("account_id", parsed.accountId)
				.not("reply_username", "is", null)
				.order("created_at", { ascending: false })
				.limit(500);

			for (const reply of replies || []) {
				const username = reply.reply_username?.toLowerCase();
				if (!username) continue;
				const existing = engagerMap.get(username);
				if (existing) {
					existing.count++;
				} else {
					engagerMap.set(username, {
						username: reply.reply_username,
						count: 1,
						lastInteraction: reply.created_at,
					});
				}
			}
		}

		if (accountPlatform === "instagram") {
			const { data: igComments } = await db()
				.from("ig_comments")
				.select("from_username, created_at")
				.eq("account_id", parsed.accountId)
				.not("from_username", "is", null)
				.order("created_at", { ascending: false })
				.limit(500);

			for (const comment of igComments || []) {
				const username = comment.from_username?.toLowerCase();
				if (!username) continue;
				const existing = engagerMap.get(username);
				if (existing) {
					existing.count++;
				} else {
					engagerMap.set(username, {
						username: comment.from_username,
						count: 1,
						lastInteraction: comment.created_at,
					});
				}
			}
		}

		// Sort by engagement count and take top N
		const topEngagers = [...engagerMap.values()]
			.sort((a, b) => b.count - a.count)
			.slice(0, parsed.limit)
			.map((e) => ({
				username: e.username,
				engagementCount: e.count,
				lastInteraction: e.lastInteraction,
			}));

		return apiSuccess(res, topEngagers as unknown as Record<string, unknown>);
	},
);
