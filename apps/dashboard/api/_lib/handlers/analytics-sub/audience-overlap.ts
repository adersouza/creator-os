/**
 * Audience Overlap
 *
 * GET /api/analytics?action=audience-overlap&accountIds=id1,id2
 * Finds shared engagers across multiple accounts owned by the same user.
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
	accountIds: z.string().min(1),
});

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;

		const accountIds = parsed.accountIds
			.split(",")
			.map((id: string) => id.trim())
			.filter(Boolean);

		if (accountIds.length < 2) {
			return apiError(res, 400, "At least 2 account IDs required");
		}
		if (accountIds.length > 20) {
			return apiError(res, 400, "Maximum 20 accounts supported");
		}

		const { data: ownedThreadsAccounts } = await db()
			.from("accounts")
			.select("id, username")
			.in("id", accountIds)
			.eq("user_id", user.id);
		const { data: ownedInstagramAccounts } = await db()
			.from("instagram_accounts")
			.select("id, username")
			.in("id", accountIds)
			.eq("user_id", user.id);

		const platformById = new Map<string, "threads" | "instagram">();
		for (const account of ownedThreadsAccounts || []) {
			platformById.set(account.id, "threads");
		}
		for (const account of ownedInstagramAccounts || []) {
			platformById.set(account.id, "instagram");
		}

		const ownedIds = new Set(
			[
				...(ownedThreadsAccounts || []),
				...(ownedInstagramAccounts || []),
			].map((a: { id: string }) => a.id),
		);
		const missingIds = accountIds.filter((id: string) => !ownedIds.has(id));
		if (missingIds.length > 0) {
			return apiError(
				res,
				404,
				`Accounts not found or not owned: ${missingIds.join(", ")}`,
			);
		}

		// Build a label map for readable output
		const labelMap = new Map<string, string>();
		for (const a of [
			...(ownedThreadsAccounts || []),
			...(ownedInstagramAccounts || []),
		]) {
			labelMap.set(a.id, a.username || a.id);
		}

		// ---------------------------------------------------------------
		// For each account, collect unique engager usernames
		// ---------------------------------------------------------------
		// Map<normalizedUsername, { original: string, accountIds: Set<string>, totalInteractions: number }>
		const engagerIndex = new Map<
			string,
			{ original: string; accountIds: Set<string>; totalInteractions: number }
		>();
		const perAccountCounts = new Map<string, number>();

		for (const accountId of accountIds) {
			const accountEngagers = new Set<string>();
			const platform = platformById.get(accountId);

			if (platform === "threads") {
				const { data: replies } = await db()
					.from("post_replies")
					.select("reply_username")
					.eq("account_id", accountId)
					.not("reply_username", "is", null)
					.order("created_at", { ascending: false })
					.limit(1000);

				for (const r of replies || []) {
					const key = r.reply_username?.toLowerCase();
					if (!key) continue;
					accountEngagers.add(key);
					const existing = engagerIndex.get(key);
					if (existing) {
						existing.accountIds.add(accountId);
						existing.totalInteractions++;
					} else {
						engagerIndex.set(key, {
							original: r.reply_username,
							accountIds: new Set([accountId]),
							totalInteractions: 1,
						});
					}
				}
			}

			if (platform === "instagram") {
				const { data: igComments } = await db()
					.from("ig_comments")
					.select("from_username")
					.eq("account_id", accountId)
					.not("from_username", "is", null)
					.order("created_at", { ascending: false })
					.limit(1000);

				for (const c of igComments || []) {
					const key = c.from_username?.toLowerCase();
					if (!key) continue;
					accountEngagers.add(key);
					const existing = engagerIndex.get(key);
					if (existing) {
						existing.accountIds.add(accountId);
						existing.totalInteractions++;
					} else {
						engagerIndex.set(key, {
							original: c.from_username,
							accountIds: new Set([accountId]),
							totalInteractions: 1,
						});
					}
				}
			}

			perAccountCounts.set(accountId, accountEngagers.size);
		}

		// ---------------------------------------------------------------
		// Find overlapping engagers (present in 2+ accounts)
		// ---------------------------------------------------------------
		const overlaps: {
			username: string;
			accountIds: string[];
			totalInteractions: number;
		}[] = [];

		for (const [_key, info] of engagerIndex) {
			if (info.accountIds.size >= 2) {
				overlaps.push({
					username: info.original,
					accountIds: [...info.accountIds],
					totalInteractions: info.totalInteractions,
				});
			}
		}

		// Sort by number of shared accounts desc, then by total interactions desc
		overlaps.sort(
			(a, b) =>
				b.accountIds.length - a.accountIds.length ||
				b.totalInteractions - a.totalInteractions,
		);

		// Limit to top 100 overlapping engagers
		const topOverlaps = overlaps.slice(0, 100);

		const totalUniqueAcrossAll = engagerIndex.size;
		const overlapCount = overlaps.length;

		return apiSuccess(res, {
			accounts: accountIds.map((id: string) => ({
				id,
				label: labelMap.get(id) ?? id,
				uniqueEngagers: perAccountCounts.get(id) ?? 0,
			})),
			overlaps: topOverlaps,
			overlapCount,
			overlapPercentage:
				totalUniqueAcrossAll > 0
					? Math.round((overlapCount / totalUniqueAcrossAll) * 100)
					: 0,
		} as unknown as Record<string, unknown>);
	},
);
