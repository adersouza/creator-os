// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Analytics Handler: fix-baselines
 *
 * Reconcile account baseline_followers_count from earliest analytics snapshot.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getSupabase } from "../../supabase.js";

const db = () => getSupabase();

// ============================================================================
// Handler
// ============================================================================

/**
 * POST /api/analytics?action=fix-baselines
 * Update baseline_followers_count to match the earliest analytics snapshot.
 */
export async function handleFixBaselines(
	req: VercelRequest,
	res: VercelResponse,
) {
	logger.info("handleFixBaselines called");

	const authHeader = req.headers.authorization;
	if (!authHeader?.startsWith("Bearer ")) {
		return apiError(res, 401, "Missing or invalid authorization header");
	}

	const authToken = authHeader.replace("Bearer ", "");
	const {
		data: { user },
		error: authError,
	} = await db().auth.getUser(authToken);

	if (authError || !user) {
		return apiError(res, 401, "Invalid or expired token");
	}

	const userId = user.id;

	try {
		// Get all accounts for the user
		const { data: accounts, error: accountsError } = await db()
			.from("accounts")
			.select("id, username, followers_count, baseline_followers_count")
			.eq("user_id", userId);

		if (accountsError) {
			logger.error("Failed to fetch accounts", {
				error: accountsError.message,
			});
			return apiError(res, 500, "Failed to fetch accounts");
		}

		if (!accounts || accounts.length === 0) {
			return apiSuccess(res, {
				message: "No accounts found",
				accountsFixed: 0,
			});
		}

		const accountIds = accounts.map((a) => a.id);

		const { data: analyticsRows, error: analyticsError } = await db()
			.from("account_analytics")
			.select("account_id, followers_count, date")
			.in("account_id", accountIds)
			.order("date", { ascending: true });

		if (analyticsError) {
			logger.error("Failed to fetch analytics rows", {
				error: analyticsError.message,
			});
			return apiError(res, 500, "Failed to fetch analytics");
		}

		const earliestByAccount = new Map<
			string,
			{ followers_count: number | null; date: string }
		>();
		for (const row of analyticsRows ?? []) {
			if (!row.account_id) continue;
			if (!earliestByAccount.has(row.account_id)) {
				earliestByAccount.set(row.account_id, {
					followers_count: row.followers_count,
					date: row.date,
				});
			}
		}

		const nowIso = new Date().toISOString();
		const pending: Array<{
			id: string;
			username: string;
			oldBaseline: number;
			newBaseline: number;
			firstDate: string;
		}> = [];

		for (const account of accounts) {
			const earliest = earliestByAccount.get(account.id);
			if (!earliest) {
				logger.info("No analytics data for account", {
					account: account.username || account.id,
				});
				continue;
			}

			const firstRecordedFollowers = earliest.followers_count || 0;
			const currentBaseline = account.baseline_followers_count || 0;
			if (firstRecordedFollowers === currentBaseline) continue;

			pending.push({
				id: account.id,
				username: account.username || "unknown",
				oldBaseline: currentBaseline,
				newBaseline: firstRecordedFollowers,
				firstDate: earliest.date,
			});
		}

		const updateResults = await Promise.allSettled(
			pending.map((p) =>
				db()
					.from("accounts")
					.update({
						baseline_followers_count: p.newBaseline,
						updated_at: nowIso,
					})
					.eq("id", p.id),
			),
		);

		const results: Array<{
			accountId: string;
			username: string;
			oldBaseline: number;
			newBaseline: number;
		}> = [];
		let accountsFixed = 0;
		updateResults.forEach((r, i) => {
			const p = pending[i];
			if (r.status === "fulfilled" && !r.value.error) {
				results.push({
					accountId: p!.id,
					username: p!.username,
					oldBaseline: p!.oldBaseline,
					newBaseline: p!.newBaseline,
				});
				accountsFixed++;
				logger.info("Fixed baseline", {
					username: p!.username,
					oldBaseline: p!.oldBaseline,
					newBaseline: p!.newBaseline,
					firstDate: p!.firstDate,
				});
			} else {
				const errMsg =
					r.status === "rejected"
						? String(r.reason)
						: r.value.error?.message;
				logger.error("Failed to update baseline", {
					accountId: p!.id,
					error: errMsg,
				});
			}
		});

		return apiSuccess(res, {
			message: `Fixed baselines for ${accountsFixed} accounts`,
			accountsFixed,
			results,
		});
	} catch (error: unknown) {
		const message = error instanceof Error ? error.message : String(error);
		logger.error("Error in handleFixBaselines", { error: message });
		return apiError(res, 500, "Internal server error", {
			details: message,
		});
	}
}
