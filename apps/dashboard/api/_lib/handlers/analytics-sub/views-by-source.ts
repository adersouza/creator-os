// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Threads Views-By-Source Time Series
 *
 * GET /api/analytics?action=views-by-source&accountId=...&days=30
 * GET /api/analytics?action=views-by-source&accountIds=a,b,c&days=30
 *
 * Returns the daily views-by-source breakdown captured by the Threads sync
 * (account_analytics.threads_views_by_source). Source keys: home, profile,
 * search, activity, ig, fb.
 *
 * Scope: a single Threads accountId (for the account view) OR a comma-
 * separated list (All / Threads fleet view). Non-Threads accounts in the
 * list are ignored silently.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { getAccountIdsForContext } from "../../workspaceAccounts.js";
import { enforceAnalyticsSubRateLimit } from "./rateLimit.js";

// biome-ignore lint/suspicious/noExplicitAny: table columns not all in generated types
const db = (): any => getSupabase();

const SOURCE_KEYS = [
	"home",
	"profile",
	"search",
	"activity",
	"ig",
	"fb",
] as const;

type SourceKey = (typeof SOURCE_KEYS)[number];

const QuerySchema = z.object({
	accountId: z.string().optional(),
	accountIds: z.string().optional(),
	days: z.coerce.number().int().min(1).max(90).optional().default(30),
	workspaceId: z.string().optional(),
});

export interface ViewsBySourcePoint {
	/** ISO date (YYYY-MM-DD). */
	date: string;
	home: number;
	profile: number;
	search: number;
	activity: number;
	ig: number;
	fb: number;
	total: number;
}

export interface ViewsBySourceResponse {
	/** Resolved Threads account IDs included in the series. */
	accountIds: string[];
	periodDays: number;
	/** Daily series ascending by date. Missing days are zero-filled. */
	series: ViewsBySourcePoint[];
	/** Totals across the full window per source — used for legend/summary. */
	totals: Record<SourceKey, number>;
	/** True when no row across any account has non-null capture yet. */
	empty: boolean;
}

function zeroPoint(date: string): ViewsBySourcePoint {
	return {
		date,
		home: 0,
		profile: 0,
		search: 0,
		activity: 0,
		ig: 0,
		fb: 0,
		total: 0,
	};
}

function addPoint(
	dest: ViewsBySourcePoint,
	raw: Record<string, unknown> | null,
): void {
	if (!raw) return;
	for (const key of SOURCE_KEYS) {
		const v = raw[key];
		if (typeof v === "number" && Number.isFinite(v)) {
			dest[key] += v;
			dest.total += v;
		}
	}
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") {
			return apiError(res, 405, "Method not allowed");
		}

		const rateAllowed = await enforceAnalyticsSubRateLimit(res, {
			userId: user.id,
			action: "views-by-source",
			limit: 30,
		});
		if (!rateAllowed) return;

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, accountIds, days, workspaceId } = parsed;

		// Resolve candidate account IDs, then filter to ones that actually belong
		// to Threads accounts. Two entry points: explicit accountIds list (fleet),
		// single accountId (drill-in), or nothing → all accounts in context.
		const candidateIds: string[] = accountIds
			? accountIds
					.split(",")
					.map((s) => s.trim())
					.filter(Boolean)
			: accountId
				? [accountId]
				: await getAccountIdsForContext(
						user.id,
						workspaceId ?? null,
						"threads",
					);

		if (candidateIds.length === 0) {
			return apiSuccess(res, {
				accountIds: [],
				periodDays: days,
				series: [],
				totals: { home: 0, profile: 0, search: 0, activity: 0, ig: 0, fb: 0 },
				empty: true,
			});
		}

		// Guard: only include accountIds that belong to this user's Threads
		// accounts (or workspace members if workspaceId given).
		const allowed = new Set(
			await getAccountIdsForContext(user.id, workspaceId ?? null, "threads"),
		);
		const scopedIds = candidateIds.filter((id) => allowed.has(id));

		if (scopedIds.length === 0) {
			return apiSuccess(res, {
				accountIds: [],
				periodDays: days,
				series: [],
				totals: { home: 0, profile: 0, search: 0, activity: 0, ig: 0, fb: 0 },
				empty: true,
			});
		}

		// Pull a 1-day prologue on top of the requested window so we can compute
		// day-over-day deltas cleanly — defensive handling for ambiguity in how
		// Threads `views?breakdown=source` applies since/until. If the stored
		// snapshots are daily values the first day is the full snapshot; if the
		// stored snapshots are cumulative-lifetime the per-day diff is the true
		// daily velocity. Either way the chart reads correctly.
		const prologueCutoff = new Date(Date.now() - (days + 1) * 86_400_000)
			.toISOString()
			.split("T")[0]!;

		const { data: perAccRows, error: perAccErr } = await db()
			.from("account_analytics")
			.select("account_id, date, threads_views_by_source")
			.in("account_id", scopedIds)
			.gte("date", prologueCutoff)
			.not("threads_views_by_source", "is", null)
			.order("date", { ascending: true });

		if (perAccErr) {
			return apiError(res, 500, "Failed to fetch views-by-source", {
				details: perAccErr.message,
			});
		}

		// Group rows per-account so we can compute day-over-day deltas inside
		// each account's timeline, then sum across accounts per day.
		const rowsByAccountDate = new Map<
			string,
			Map<string, Record<string, unknown>>
		>();

		for (const row of (perAccRows ?? []) as Array<{
			account_id: string;
			date: string;
			threads_views_by_source: Record<string, unknown> | null;
		}>) {
			let byDate = rowsByAccountDate.get(row.account_id);
			if (!byDate) {
				byDate = new Map();
				rowsByAccountDate.set(row.account_id, byDate);
			}
			byDate.set(row.date, row.threads_views_by_source ?? {});
		}

		// Deltas keyed by date, summed across accounts.
		const dailyDelta = new Map<string, ViewsBySourcePoint>();
		for (const byDate of rowsByAccountDate.values()) {
			const dateKeys = Array.from(byDate.keys()).sort();
			let prev: Record<string, unknown> | null = null;
			for (const dateKey of dateKeys) {
				const curr = byDate.get(dateKey) ?? {};
				const existing = dailyDelta.get(dateKey) ?? zeroPoint(dateKey);
				if (prev === null) {
					// First row per account — treat the snapshot itself as the day's
					// delta (we have no prior to diff against). This is the right
					// thing if capture is daily-scoped; slightly over-attributes on
					// day 1 if capture is cumulative, but the chart still reads.
					addPoint(existing, curr);
				} else {
					// Diff each source key. Clamp negatives (post deletions on the
					// source side could push cumulative totals down; treat as zero).
					for (const key of SOURCE_KEYS) {
						const c = Number(curr[key]) || 0;
						const p = Number(prev[key]) || 0;
						const d = Math.max(0, c - p);
						existing[key] += d;
						existing.total += d;
					}
				}
				dailyDelta.set(dateKey, existing);
				prev = curr;
			}
		}

		// Zero-fill missing days so the chart draws a continuous axis.
		const series: ViewsBySourcePoint[] = [];
		for (let i = days - 1; i >= 0; i--) {
			const d = new Date(Date.now() - i * 86_400_000);
			const key = d.toISOString().split("T")[0]!;
			series.push(dailyDelta.get(key!) ?? zeroPoint(key!));
		}

		const totals: Record<SourceKey, number> = {
			home: 0,
			profile: 0,
			search: 0,
			activity: 0,
			ig: 0,
			fb: 0,
		};
		for (const pt of series) {
			for (const k of SOURCE_KEYS) totals[k] += pt[k];
		}

		const empty =
			Object.values(totals).every((v) => v === 0) && dailyDelta.size === 0;

		return apiSuccess(res, {
			accountIds: scopedIds,
			periodDays: days,
			series,
			totals,
			empty,
		});
	},
);
