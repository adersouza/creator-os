/**
 * Bulk Publish Cap Check
 *
 * POST /api/accounts/bulk-cap-status
 *
 * Returns per-account daily publish cap status for multiple accounts in one call.
 * Accepts either explicit accountIds or a groupId to resolve.
 *
 * Body option A: { accountIds: string[], platform: "threads"|"instagram" }
 * Body option B: { groupId: string, platform?: "threads"|"instagram" }
 *
 * Response: {
 *   accounts: [{ accountId, username, platform, used, remaining, limit, resetsAt }],
 *   groupSummary: { totalRemaining, accountsAtLimit, accountsWithCapacity },
 * }
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { checkDailyCap, DAILY_CAP } from "../../dailyCap.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { neqOrNull } from "../../supabaseSafe.js";
import { parseBodyOrError } from "../../validation.js";
import { z, zEnum } from "../../zodCompat.js";

const MAX_ACCOUNTS = 200;

// biome-ignore lint/suspicious/noExplicitAny: new columns not in generated types
const db = (): any => getSupabase();

const BulkCapSchema = z.object({
	accountIds: z.array(z.string()).optional(),
	groupId: z.string().optional(),
	platform: zEnum(["threads", "instagram"]).optional(),
});

function getResetsAtUTC(): string {
	const now = new Date();
	const tomorrow = new Date(now);
	tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);
	tomorrow.setUTCHours(0, 0, 0, 0);
	return tomorrow.toISOString();
}

interface AccountInfo {
	id: string;
	username: string | null;
	platform: "threads" | "instagram";
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}

		const parsed = parseBodyOrError(res, BulkCapSchema, req.body);
		if (!parsed) return;

		const { groupId, platform } = parsed;
		const { accountIds } = parsed;

		const userId = user.id;
		const accountsToCheck: AccountInfo[] = [];

		// ── Resolve accounts ───────────────────────────────────────────────
		if (groupId) {
			// Verify group ownership
			const { data: group } = await db()
				.from("account_groups")
				.select("id")
				.eq("id", groupId)
				.eq("user_id", userId)
				.maybeSingle();

			if (!group) return apiError(res, 404, "Group not found");

			// Get Threads accounts in group (unless platform is "instagram")
			if (!platform || platform === "threads") {
				const base = db()
					.from("accounts")
					.select("id, username")
					.eq("user_id", userId)
					.eq("group_id", groupId)
					.eq("is_active", true);
				const { data: threads } = await neqOrNull(base, "status", "suspended");
				for (const a of (threads ?? []) as {
					id: string;
					username: string | null;
				}[]) {
					accountsToCheck.push({
						id: a.id,
						username: a.username,
						platform: "threads",
					});
				}
			}

			// Get Instagram accounts in group (unless platform is "threads")
			if (!platform || platform === "instagram") {
				const base = db()
					.from("instagram_accounts")
					.select("id, username")
					.eq("user_id", userId)
					.eq("group_id", groupId)
					.eq("is_active", true);
				const { data: ig } = await neqOrNull(base, "status", "suspended");
				for (const a of (ig ?? []) as {
					id: string;
					username: string | null;
				}[]) {
					accountsToCheck.push({
						id: a.id,
						username: a.username,
						platform: "instagram",
					});
				}
			}
		} else if (accountIds && accountIds.length > 0) {
			// Need to know the platform for each account
			const resolvedPlatform = platform ?? "threads";

			if (resolvedPlatform === "threads") {
				const { data: owned } = await db()
					.from("accounts")
					.select("id, username")
					.eq("user_id", userId)
					.in("id", accountIds);
				for (const a of (owned ?? []) as {
					id: string;
					username: string | null;
				}[]) {
					accountsToCheck.push({
						id: a.id,
						username: a.username,
						platform: "threads",
					});
				}
			} else {
				const { data: ownedIg } = await db()
					.from("instagram_accounts")
					.select("id, username")
					.eq("user_id", userId)
					.in("id", accountIds);
				for (const a of (ownedIg ?? []) as {
					id: string;
					username: string | null;
				}[]) {
					accountsToCheck.push({
						id: a.id,
						username: a.username,
						platform: "instagram",
					});
				}
			}
		} else {
			return apiError(res, 400, "Provide either groupId or accountIds");
		}

		if (accountsToCheck.length === 0) {
			return apiSuccess(res, {
				accounts: [],
				groupSummary: {
					totalRemaining: 0,
					accountsAtLimit: 0,
					accountsWithCapacity: 0,
				},
			});
		}

		if (accountsToCheck.length > MAX_ACCOUNTS) {
			return apiError(
				res,
				400,
				`Max ${MAX_ACCOUNTS} accounts per request (got ${accountsToCheck.length})`,
			);
		}

		// ── Check caps in parallel ────────────────────────────────────────
		const resetsAt = getResetsAtUTC();
		const capResults = await Promise.all(
			accountsToCheck.map(async (acc) => {
				try {
					const cap = await checkDailyCap(acc.id, acc.platform);
					return {
						accountId: acc.id,
						username: acc.username,
						platform: acc.platform,
						used: cap.used,
						remaining: cap.limit - cap.used,
						limit: cap.limit,
						resetsAt,
					};
				} catch (err) {
					logger.warn("Cap check failed for account", {
						accountId: acc.id,
						error: String(err),
					});
					// Fail-open: report full capacity
					return {
						accountId: acc.id,
						username: acc.username,
						platform: acc.platform,
						used: 0,
						remaining: DAILY_CAP,
						limit: DAILY_CAP,
						resetsAt,
						error: "Cap check failed — showing default",
					};
				}
			}),
		);

		// ── Compute group summary ─────────────────────────────────────────
		let totalRemaining = 0;
		let accountsAtLimit = 0;
		let accountsWithCapacity = 0;
		for (const r of capResults) {
			totalRemaining += r.remaining;
			if (r.remaining <= 0) {
				accountsAtLimit++;
			} else {
				accountsWithCapacity++;
			}
		}

		return apiSuccess(res, {
			accounts: capResults,
			groupSummary: { totalRemaining, accountsAtLimit, accountsWithCapacity },
		});
	},
);
