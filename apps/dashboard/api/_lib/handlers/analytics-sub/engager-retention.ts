/**
 * Engager Retention
 *
 * GET /api/analytics?action=engager-retention&accountId=X&periodDays=30
 * Classifies engagers as "new" (first interaction in the period) vs "returning"
 * (interacted before the period started).
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
	periodDays: z.coerce.number().int().min(1).max(90).optional().default(30),
});

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;

		// Verify account ownership. Threads accounts live in `accounts`; Instagram
		// accounts live in `instagram_accounts`, and both comment tables key by
		// their respective account_id.
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

		const periodStart = new Date();
		periodStart.setDate(periodStart.getDate() - parsed.periodDays);
		const periodStartISO = periodStart.toISOString();

		// ---------------------------------------------------------------
		// 1. Gather usernames + counts within the period
		// ---------------------------------------------------------------
		const inPeriodMap = new Map<string, { original: string; count: number }>();

		if (accountPlatform === "threads") {
			const { data: replies } = await db()
				.from("post_replies")
				.select("reply_username, created_at")
				.eq("account_id", parsed.accountId)
				.not("reply_username", "is", null)
				.gte("created_at", periodStartISO)
				.order("created_at", { ascending: false })
				.limit(2000);

			for (const r of replies || []) {
				const key = r.reply_username?.toLowerCase();
				if (!key) continue;
				const existing = inPeriodMap.get(key);
				if (existing) {
					existing.count++;
				} else {
					inPeriodMap.set(key, { original: r.reply_username, count: 1 });
				}
			}
		}

		if (accountPlatform === "instagram") {
			const { data: igComments } = await db()
				.from("ig_comments")
				.select("from_username, created_at")
				.eq("account_id", parsed.accountId)
				.not("from_username", "is", null)
				.gte("created_at", periodStartISO)
				.order("created_at", { ascending: false })
				.limit(2000);

			for (const c of igComments || []) {
				const key = c.from_username?.toLowerCase();
				if (!key) continue;
				const existing = inPeriodMap.get(key);
				if (existing) {
					existing.count++;
				} else {
					inPeriodMap.set(key, { original: c.from_username, count: 1 });
				}
			}
		}

		if (inPeriodMap.size === 0) {
			return apiSuccess(res, {
				newCount: 0,
				returningCount: 0,
				totalUnique: 0,
				newPercentage: 0,
				returningPercentage: 0,
				periodDays: parsed.periodDays,
				newEngagers: [],
				returningEngagers: [],
			} as unknown as Record<string, unknown>);
		}

		// ---------------------------------------------------------------
		// 2. Check which usernames existed BEFORE the period
		// ---------------------------------------------------------------
		const allUsernames = [...inPeriodMap.keys()];
		const prePeriodSet = new Set<string>();

		// Query in batches of 200 to stay within Supabase filter limits
		const BATCH = 200;
		for (let i = 0; i < allUsernames.length; i += BATCH) {
			const batch = allUsernames.slice(i, i + BATCH);
			// Get original-case usernames for this batch
			const originalBatch = batch.map((k) => inPeriodMap.get(k)?.original ?? k);

			if (accountPlatform === "threads") {
				const { data: preReplies } = await db()
					.from("post_replies")
					.select("reply_username")
					.eq("account_id", parsed.accountId)
					.lt("created_at", periodStartISO)
					.in("reply_username", originalBatch)
					.limit(1000);

				for (const r of preReplies || []) {
					const key = r.reply_username?.toLowerCase();
					if (key) prePeriodSet.add(key);
				}
			}

			if (accountPlatform === "instagram") {
				const { data: preIg } = await db()
					.from("ig_comments")
					.select("from_username")
					.eq("account_id", parsed.accountId)
					.lt("created_at", periodStartISO)
					.in("from_username", originalBatch)
					.limit(1000);

				for (const c of preIg || []) {
					const key = c.from_username?.toLowerCase();
					if (key) prePeriodSet.add(key);
				}
			}
		}

		// ---------------------------------------------------------------
		// 3. Classify and build response
		// ---------------------------------------------------------------
		const newEngagers: { username: string; engagementCount: number }[] = [];
		const returningEngagers: { username: string; engagementCount: number }[] =
			[];

		for (const [key, info] of inPeriodMap) {
			const entry = { username: info.original, engagementCount: info.count };
			if (prePeriodSet.has(key)) {
				returningEngagers.push(entry);
			} else {
				newEngagers.push(entry);
			}
		}

		// Sort descending by engagement count
		newEngagers.sort((a, b) => b.engagementCount - a.engagementCount);
		returningEngagers.sort((a, b) => b.engagementCount - a.engagementCount);

		const totalUnique = inPeriodMap.size;
		const newCount = newEngagers.length;
		const returningCount = returningEngagers.length;

		return apiSuccess(res, {
			newCount,
			returningCount,
			totalUnique,
			newPercentage:
				totalUnique > 0 ? Math.round((newCount / totalUnique) * 100) : 0,
			returningPercentage:
				totalUnique > 0 ? Math.round((returningCount / totalUnique) * 100) : 0,
			periodDays: parsed.periodDays,
			newEngagers: newEngagers.slice(0, 10),
			returningEngagers: returningEngagers.slice(0, 10),
		} as unknown as Record<string, unknown>);
	},
);
