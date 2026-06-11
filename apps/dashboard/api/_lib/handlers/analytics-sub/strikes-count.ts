/**
 * Strikes count — moderation/health events per account in last N days.
 *
 * GET /api/analytics?action=strikes-count&accountId=X&periodDays=90
 *
 * Powers the 4th donut on `ScorecardTile` (mockup widgets-redesign-v2 #9).
 * Mockup label: "Strikes · 0 /90d".
 *
 * Composed from existing signals — no new schema needed.
 *
 * What counts as a strike:
 *   - accounts.is_shadowbanned = TRUE → 1 strike (ongoing reach suppression).
 *   - accounts.consecutive_refresh_failures > 3 → 1 strike (chronic token break,
 *     not transient single retries).
 *   - anomaly_alerts of type shadowban_suspected or reach_anomaly in the window
 *     and not dismissed → 1 strike each.
 *
 * What does NOT count (intentionally — would otherwise dwarf real strikes):
 *   - posts.status='failed' — routine rate-limit / transient API errors fire
 *     dozens of these per account during normal autoposter operation. They're
 *     publish noise, not moderation events.
 *   - needs_reauth — a token expiry alone isn't a "strike," it's a maintenance
 *     event. The Token donut already covers this.
 *   - dismissed anomaly alerts — operator already triaged them.
 *
 * Tones for the donut:
 *   0 strikes → "good" (fleet clean)
 *   1-2     → "warn"
 *   3+      → "crit"
 *
 * Both single-account and fleet scopes supported. Fleet scope returns the
 * sum of per-account strikes plus an `accountsWithStrikes` count so the tile
 * can render "12 of 88 accounts have ≥1 strike" if it wants.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z, zEnum } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { getAccountIdsForContext } from "../../workspaceAccounts.js";

const QuerySchema = z.object({
	accountId: z.string().optional(),
	periodDays: z.coerce.number().int().min(7).max(180).optional().default(90),
	platform: zEnum(["all", "instagram", "threads"]).optional().default("all"),
	workspaceId: z.string().optional(),
});

// Anomaly alert types that count as strikes. Engagement drops + follower
// drops are growth signals, not moderation events — leave them out.
const STRIKE_ALERT_TYPES = ["shadowban_suspected", "reach_anomaly"] as const;
const CONSECUTIVE_REFRESH_FAILURE_THRESHOLD = 3;

// biome-ignore lint/suspicious/noExplicitAny: not all columns are in generated types
const db = (): any => getSupabase();

interface AccountStrikes {
	accountId: string;
	platform: "threads" | "instagram";
	username: string | null;
	strikes: number;
	breakdown: {
		shadowban: number;
		chronicTokenFailures: number;
		anomalies: number;
	};
}

function severityForStrikes(n: number): "good" | "warn" | "crit" {
	if (n === 0) return "good";
	if (n <= 2) return "warn";
	return "crit";
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, periodDays, platform, workspaceId } = parsed;

		const cutoff = new Date(Date.now() - periodDays * 86_400_000).toISOString();

		// Resolve scope. Single account scope skips the workspace lookup.
		let scopedThreadsIds: string[] = [];
		let scopedIgIds: string[] = [];

		if (accountId && accountId !== "ALL") {
			// Disambiguate Threads vs IG by which table owns the id.
			const { data: t } = await db()
				.from("accounts")
				.select("id")
				.eq("user_id", user.id)
				.eq("id", accountId)
				.maybeSingle();
			if (t?.id) {
				scopedThreadsIds = [t.id];
			} else {
				const { data: i } = await db()
					.from("instagram_accounts")
					.select("id")
					.eq("user_id", user.id)
					.eq("id", accountId)
					.maybeSingle();
				if (i?.id) scopedIgIds = [i.id];
			}
		} else {
			if (platform !== "instagram") {
				scopedThreadsIds = await getAccountIdsForContext(
					user.id,
					workspaceId ?? null,
					"threads",
				);
			}
			if (platform !== "threads") {
				scopedIgIds = await getAccountIdsForContext(
					user.id,
					workspaceId ?? null,
					"instagram",
				);
			}
		}

		if (scopedThreadsIds.length === 0 && scopedIgIds.length === 0) {
			return apiSuccess(res, {
				totalStrikes: 0,
				severity: "good",
				accountsWithStrikes: 0,
				totalAccounts: 0,
				perAccount: [],
				periodDays,
			});
		}

		const allIds = [...scopedThreadsIds, ...scopedIgIds];

		// Threads accounts: shadowban + chronic token failures.
		const threadsRows: Array<{
			id: string;
			username: string | null;
			is_shadowbanned: boolean | null;
			consecutive_refresh_failures: number | null;
		}> =
			scopedThreadsIds.length === 0
				? []
				: ((
						await db()
							.from("accounts")
							.select(
								"id, username, is_shadowbanned, consecutive_refresh_failures",
							)
							.in("id", scopedThreadsIds)
					).data ?? []);

		// instagram_accounts has no is_shadowbanned, but does track refresh failures.
		const igRows: Array<{
			id: string;
			username: string | null;
			consecutive_refresh_failures: number | null;
		}> =
			scopedIgIds.length === 0
				? []
				: ((
						await db()
							.from("instagram_accounts")
							.select("id, username, consecutive_refresh_failures")
							.in("id", scopedIgIds)
					).data ?? []);

		// Anomaly alerts in window — only the moderation-flavored types
		// (shadowban_suspected, reach_anomaly). Engagement drops and follower
		// drops are growth signals, not strikes.
		const { data: alerts } =
			allIds.length === 0
				? { data: [] }
				: await db()
						.from("anomaly_alerts")
						.select("account_id, instagram_account_id, alert_type")
						.eq("user_id", user.id)
						.is("dismissed_at", null)
						.in("alert_type", STRIKE_ALERT_TYPES as unknown as string[])
						.gte("created_at", cutoff);

		const anomaliesByAccount = new Map<string, number>();
		for (const a of (alerts || []) as Array<{
			account_id: string | null;
			instagram_account_id: string | null;
		}>) {
			const key = a.account_id ?? a.instagram_account_id;
			if (!key) continue;
			anomaliesByAccount.set(key, (anomaliesByAccount.get(key) ?? 0) + 1);
		}

		const perAccount: AccountStrikes[] = [];

		for (const a of threadsRows) {
			const shadowban = a.is_shadowbanned ? 1 : 0;
			const chronicTokenFailures =
				(a.consecutive_refresh_failures ?? 0) >
					CONSECUTIVE_REFRESH_FAILURE_THRESHOLD
					? 1
					: 0;
			const anomalies = anomaliesByAccount.get(a.id) ?? 0;
			const strikes = shadowban + chronicTokenFailures + anomalies;
			perAccount.push({
				accountId: a.id,
				platform: "threads",
				username: a.username,
				strikes,
				breakdown: { shadowban, chronicTokenFailures, anomalies },
			});
		}

		for (const a of igRows) {
			// IG has no shadowban column.
			const shadowban = 0;
			const chronicTokenFailures =
				(a.consecutive_refresh_failures ?? 0) >
					CONSECUTIVE_REFRESH_FAILURE_THRESHOLD
					? 1
					: 0;
			const anomalies = anomaliesByAccount.get(a.id) ?? 0;
			const strikes = shadowban + chronicTokenFailures + anomalies;
			perAccount.push({
				accountId: a.id,
				platform: "instagram",
				username: a.username,
				strikes,
				breakdown: { shadowban, chronicTokenFailures, anomalies },
			});
		}

		const totalStrikes = perAccount.reduce((s, a) => s + a.strikes, 0);
		const accountsWithStrikes = perAccount.filter((a) => a.strikes > 0).length;
		const severity = severityForStrikes(
			accountId ? totalStrikes : Math.max(...perAccount.map((a) => a.strikes), 0),
		);

		// For the donut: when scope is fleet, render against accountsWithStrikes
		// (more stable than total strikes, which can be dominated by one bad
		// account). When scope is single-account, render against the per-account
		// strike count directly.
		const ringValue = accountId
			? totalStrikes
			: accountsWithStrikes;

		return apiSuccess(res, {
			totalStrikes,
			ringValue,
			severity,
			accountsWithStrikes,
			totalAccounts: perAccount.length,
			perAccount: perAccount
				.filter((a) => a.strikes > 0)
				.sort((a, b) => b.strikes - a.strikes),
			periodDays,
			notes: {
				sources: {
					shadowban:
						"accounts.is_shadowbanned (Threads only — instagram_accounts has no equivalent column)",
					chronicTokenFailures: `consecutive_refresh_failures > ${CONSECUTIVE_REFRESH_FAILURE_THRESHOLD} (chronic token break, not transient retries)`,
					anomalies: `anomaly_alerts in window, alert_type IN (${STRIKE_ALERT_TYPES.join(", ")}), dismissed_at IS NULL`,
				},
				excluded: {
					failedPosts:
						"posts.status='failed' is publish noise (rate limits / transient API errors), not a moderation event",
					needsReauth:
						"covered by the Token donut, not a strike on its own",
				},
				thresholds: {
					good: "0 strikes",
					warn: "1-2 strikes",
					crit: "3+ strikes",
				},
			},
		});
	},
);
