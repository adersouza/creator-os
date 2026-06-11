/**
 * Reply-depth leaders — Threads posts with the longest conversation chains.
 *
 * GET /api/analytics?action=reply-depth-leaders&accountId=X&periodDays=14
 *
 * Ranks by reply_depth × replies_count — "deep AND wide" conversations.
 * posts.reply_depth is populated by the replyChainPhase in sync-orchestrator
 * (runs every 15 min, budget 2 Threads API calls/account/run).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";

const QuerySchema = z.object({
	accountId: z.string().optional(),
	accountIds: z.string().optional(),
	periodDays: z.coerce.number().int().min(1).max(90).optional().default(14),
	limit: z.coerce.number().int().min(1).max(20).optional().default(5),
});

// biome-ignore lint/suspicious/noExplicitAny: posts columns aren't fully in generated types
const db = (): any => getSupabase();

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, accountIds: accountIdsStr, periodDays, limit } = parsed;

		let targetAccountIds: string[] = [];
		if (accountIdsStr) {
			targetAccountIds = accountIdsStr.split(",").filter(Boolean);
		} else if (accountId && accountId !== "ALL") {
			targetAccountIds = [accountId];
		}

		if (targetAccountIds.length === 0) {
			const { data: accounts } = await db()
				.from("accounts")
				.select("id")
				.eq("user_id", user.id);
			targetAccountIds = (accounts || []).map((a: { id: string }) => a.id);
		} else {
			const { data: owned } = await db()
				.from("accounts")
				.select("id")
				.eq("user_id", user.id)
				.in("id", targetAccountIds);
			targetAccountIds = (owned || []).map((a: { id: string }) => a.id);
		}

		if (targetAccountIds.length === 0) {
			return apiSuccess(res, { leaders: [], periodDays });
		}

		const cutoff = new Date();
		cutoff.setDate(cutoff.getDate() - periodDays);

		const { data: posts } = await db()
			.from("posts")
			.select(
				"id, content, published_at, permalink, reply_depth, replies_count, quotes_count, reposts_count, account_id, reply_chain",
			)
			.in("account_id", targetAccountIds)
			.eq("user_id", user.id)
			.eq("status", "published")
			.not("reply_depth", "is", null)
			.gt("reply_depth", 1)
			.gte("published_at", cutoff.toISOString());

		const accountIds = Array.from(
			new Set(
				((posts || []) as Array<{ account_id: string | null }>)
					.map((p) => p.account_id)
					.filter((id): id is string => !!id),
			),
		);
		let accountRows: Array<{
			id: string;
			username: string | null;
			avatar_url: string | null;
		}> = [];
		if (accountIds.length > 0) {
			const { data } = await db()
				.from("accounts")
				.select("id, username, avatar_url")
				.in("id", accountIds)
				.eq("user_id", user.id);
			accountRows = (data || []) as Array<{
				id: string;
				username: string | null;
				avatar_url: string | null;
			}>;
		}
		const accountMetaById = new Map<
			string,
			{ username: string | null; avatarUrl: string | null }
		>();
		for (const row of accountRows) {
			accountMetaById.set(row.id, {
				username: row.username,
				avatarUrl: row.avatar_url,
			});
		}

		const ranked = ((posts || []) as Array<{
			id: string;
			content: string | null;
			published_at: string;
			permalink: string | null;
			reply_depth: number | null;
			replies_count: number | null;
			quotes_count: number | null;
			reposts_count: number | null;
			account_id: string | null;
			reply_chain: ReplyChainItem[] | null;
		}>)
			.map((p) => {
				const depth = p.reply_depth || 0;
				const replies = p.replies_count || 0;
				return {
					id: p.id,
					content: p.content,
					publishedAt: p.published_at,
					permalink: p.permalink,
					replyDepth: depth,
					replies,
					quotes: p.quotes_count || 0,
					reposts: p.reposts_count || 0,
					score: depth * Math.max(1, replies),
					accountId: p.account_id,
					accountUsername: p.account_id
						? accountMetaById.get(p.account_id)?.username ?? null
						: null,
					accountAvatarUrl: p.account_id
						? accountMetaById.get(p.account_id)?.avatarUrl ?? null
						: null,
					replyChain: p.reply_chain ?? null,
				};
			})
			.sort((a, b) => b.score - a.score)
			.slice(0, limit);

		// Top leader gets the velocity histogram + full reply chain
		// attached. Other leaders strip replyChain to keep the response
		// payload tight (chain JSONB can be ~10kb per post).
		const leaders = ranked.map((leader, idx) => {
			if (idx === 0) {
				const velocity = computeVelocityHistogram(
					leader.replyChain,
					leader.publishedAt,
				);
				const creatorRepliesCount = countCreatorReplies(
					leader.replyChain,
					leader.accountUsername,
				);
				return {
					...leader,
					velocityHistogram: velocity?.histogram ?? null,
					velocityWindowHours: velocity?.windowHours ?? null,
					creatorRepliesCount,
				};
			}
			// Strip replyChain from non-winners — only the top tile renders it.
			const { replyChain: _drop, ...rest } = leader;
			return { ...rest, replyChain: null };
		});

		return apiSuccess(res, { leaders, periodDays });
	},
);

interface ReplyChainItem {
	id: string;
	replied_to: string | null;
	timestamp: number;
	username: string | null;
	text: string | null;
}

function countCreatorReplies(
	chain: ReplyChainItem[] | null,
	accountUsername: string | null,
): number | null {
	if (!chain || chain.length === 0 || !accountUsername) return null;
	const normalized = accountUsername.replace(/^@/, "").toLowerCase();
	return chain.filter((item) => {
		const username = item.username?.replace(/^@/, "").toLowerCase();
		return username === normalized;
	}).length;
}

function computeVelocityHistogram(
	chain: ReplyChainItem[] | null,
	publishedAtIso: string,
): { histogram: number[]; windowHours: number } | null {
	if (!chain || chain.length === 0) return null;

	const publishedSec = Math.floor(Date.parse(publishedAtIso) / 1000);
	if (!Number.isFinite(publishedSec)) return null;

	const nowSec = Math.floor(Date.now() / 1000);
	const ageHours = Math.max(1, (nowSec - publishedSec) / 3600);

	// 10 windows. If post is < 10h old, each window = 1h (some empty).
	// Older posts scale proportionally so we always render 10 bars.
	const windowHours = ageHours <= 10 ? 1 : ageHours / 10;
	const windowSec = windowHours * 3600;

	const histogram = new Array(10).fill(0);
	for (const item of chain) {
		if (item.timestamp == null) continue;
		const offsetSec = item.timestamp - publishedSec;
		if (offsetSec < 0) continue;
		const bucket = Math.min(9, Math.floor(offsetSec / windowSec));
		histogram[bucket]++;
	}
	return { histogram, windowHours };
}
