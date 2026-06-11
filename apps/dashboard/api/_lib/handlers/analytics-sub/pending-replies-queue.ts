/**
 * Pending replies queue — fleet rollup of auto_reply_queue by account.
 *
 * GET /api/analytics?action=pending-replies-queue
 *
 * Counts rows in auto_reply_queue with status IN (pending, needs_review),
 * grouped by account. "needs_review" is the human-in-the-loop bucket
 * (flagged by safety rules); "pending" is awaiting the auto-reply worker.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";

const QuerySchema = z.object({
	accountId: z.string().optional(),
});

const PENDING_STATUSES = ["pending", "needs_review"];

// biome-ignore lint/suspicious/noExplicitAny: auto_reply_queue RLS-scoped via account_id join
const db = (): any => getSupabase();

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId } = parsed;

		// Scope to the user's Threads accounts — auto_reply_queue is Threads-only.
		let targetAccountIds: string[] = [];
		if (accountId && accountId !== "ALL") {
			const { data: owned } = await db()
				.from("accounts")
				.select("id")
				.eq("user_id", user.id)
				.eq("id", accountId);
			targetAccountIds = (owned || []).map((a: { id: string }) => a.id);
		} else {
			const { data: accounts } = await db()
				.from("accounts")
				.select("id")
				.eq("user_id", user.id);
			targetAccountIds = (accounts || []).map((a: { id: string }) => a.id);
		}

		if (targetAccountIds.length === 0) {
			return apiSuccess(res, { accounts: [], total: 0, needsReview: 0, pending: 0 });
		}

		const { data: accountRows } = await db()
			.from("accounts")
			.select("id, username")
			.in("id", targetAccountIds);

		const usernameById = new Map<string, string | null>();
		for (const a of (accountRows || []) as Array<{ id: string; username: string | null }>) {
			usernameById.set(a.id, a.username);
		}

		const { data: rows } = await db()
			.from("auto_reply_queue")
			.select("account_id, status, flagged_reason")
			.in("account_id", targetAccountIds)
			.in("status", PENDING_STATUSES);

		const perAccount = new Map<
			string,
			{ pending: number; needsReview: number; reasons: Map<string, number> }
		>();
		let totalPending = 0;
		let totalNeedsReview = 0;

		for (const r of (rows || []) as Array<{
			account_id: string;
			status: string;
			flagged_reason: string | null;
		}>) {
			const bucket = perAccount.get(r.account_id) || {
				pending: 0,
				needsReview: 0,
				reasons: new Map<string, number>(),
			};
			if (r.status === "pending") {
				bucket.pending += 1;
				totalPending += 1;
			} else if (r.status === "needs_review") {
				bucket.needsReview += 1;
				totalNeedsReview += 1;
				const reason = r.flagged_reason || "unspecified";
				bucket.reasons.set(reason, (bucket.reasons.get(reason) || 0) + 1);
			}
			perAccount.set(r.account_id, bucket);
		}

		const accounts = Array.from(perAccount.entries())
			.map(([aid, b]) => ({
				accountId: aid,
				username: usernameById.get(aid) || null,
				pending: b.pending,
				needsReview: b.needsReview,
				total: b.pending + b.needsReview,
				topReason: (() => {
					let topKey: string | null = null;
					let topCount = 0;
					for (const [k, v] of b.reasons) {
						if (v > topCount) {
							topKey = k;
							topCount = v;
						}
					}
					return topKey;
				})(),
			}))
			.filter((a) => a.total > 0)
			.sort((a, b) => b.total - a.total);

		return apiSuccess(res, {
			accounts,
			total: totalPending + totalNeedsReview,
			needsReview: totalNeedsReview,
			pending: totalPending,
		});
	},
);
