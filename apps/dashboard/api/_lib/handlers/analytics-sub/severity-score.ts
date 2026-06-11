// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Fleet severity score — 7-day rolling z-score vs 90-day own-history
 *
 * GET /api/analytics?action=severity-score&accountIds=a,b,c
 *
 * Replaces the EQS-percentile proxy that FleetAnomalyGrid used in Wave 1.
 * For each account we load the last 91 days from account_metrics_history,
 * derive the daily "new views" velocity (Threads) or daily "new reach"
 * velocity (IG) as the diff between consecutive daily snapshots, then score
 * the most recent 7-day window against the distribution of 7-day rolling
 * windows across the prior 83 days.
 *
 * Backstop: |daily_delta| < 10 on the most-recent day suppresses the flag to
 * "healthy" regardless of z — tiny accounts produce noisy z-scores that would
 * otherwise fire crit for every day-to-day wobble (production_playbook §5).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { getAccountIdsForContext } from "../../workspaceAccounts.js";
import { enforceAnalyticsSubRateLimit } from "./rateLimit.js";

// biome-ignore lint/suspicious/noExplicitAny: schema not in generated types
const db = (): any => getSupabase();

const QuerySchema = z.object({
	accountIds: z.string().optional(),
	groupId: z.string().optional(),
	workspaceId: z.string().optional(),
});

/** Absolute z-score thresholds per the Wave 2 plan / production_playbook §5. */
const Z_CRIT = 2.5;
const Z_WARN = 2.0;
/** Noise floor. Accounts whose last-day delta doesn't clear this don't count. */
const DELTA_FLOOR = 10;

export type Severity = "critical" | "warning" | "healthy" | "insufficient";

export interface AccountSeverity {
	accountId: string;
	/** Which metric was used — varies by platform. */
	metric: "threads_views" | "ig_reach";
	/** Most-recent 7-day velocity mean. */
	current7d: number;
	/** 83-day baseline mean of 7-day rolling windows. */
	baselineMean: number;
	/** 83-day baseline stddev. 0 when <7 rolling windows available. */
	baselineStd: number;
	/** (current7d − baselineMean) / baselineStd. null when baselineStd == 0. */
	z: number | null;
	/** Last-day delta — suppression input. */
	lastDayDelta: number;
	severity: Severity;
}

export interface SeverityScoreResponse {
	accounts: Record<string, AccountSeverity>;
	/** Accounts for which we had no rows / no platform match. */
	missing: string[];
}

interface MetricRow {
	account_id: string;
	date: string;
	platform: string | null;
	total_views: number | null;
	/** Legacy rows sometimes have follower/posts — not used here. */
}

interface AnalyticsRow {
	account_id: string;
	date: string;
	/** 28d rolling window — heavily smoothed, 1d-lagged. Used as fallback. */
	ig_reach: number | null;
	/** Absolute daily follower-reach (Apr 24 migration). Preferred signal. */
	ig_follower_reach: number | null;
	/** Absolute daily non-follower-reach (Apr 24 migration). Preferred signal. */
	ig_non_follower_reach: number | null;
	total_views: number | null;
}

function mean(xs: number[]): number {
	if (xs.length === 0) return 0;
	return xs.reduce((s, v) => s + v, 0) / xs.length;
}

function stdDev(xs: number[], m: number): number {
	if (xs.length < 2) return 0;
	const variance =
		xs.reduce((s, v) => s + (v - m) * (v - m), 0) / (xs.length - 1);
	return Math.sqrt(Math.max(variance, 0));
}

function rollingMean(xs: number[], window: number): number[] {
	if (xs.length < window) return [];
	const out: number[] = [];
	let runningSum = 0;
	for (let i = 0; i < xs.length; i++) {
		runningSum += xs[i]!;
		if (i >= window) runningSum -= xs[i - window]!;
		if (i >= window - 1) out.push(runningSum / window);
	}
	return out;
}

function classify(z: number | null, lastDelta: number): Severity {
	if (z === null) return "insufficient";
	if (Math.abs(lastDelta) < DELTA_FLOOR) return "healthy";
	const abs = Math.abs(z);
	if (abs > Z_CRIT) return "critical";
	if (abs > Z_WARN) return "warning";
	return "healthy";
}

function scoreOne(
	accountId: string,
	metric: AccountSeverity["metric"],
	dailyValues: number[],
): AccountSeverity {
	// Diff consecutive snapshots → daily deltas. Clamp negatives to 0 (posts
	// can disappear and push lifetime totals down — those are not "drops" for
	// the anomaly signal, they're deletions).
	const deltas: number[] = [];
	for (let i = 1; i < dailyValues.length; i++) {
		deltas.push(Math.max(0, dailyValues[i]! - dailyValues[i - 1]!));
	}

	if (deltas.length < 14) {
		return {
			accountId,
			metric,
			current7d: 0,
			baselineMean: 0,
			baselineStd: 0,
			z: null,
			lastDayDelta: deltas[deltas.length - 1] ?? 0,
			severity: "insufficient",
		};
	}

	const rolling = rollingMean(deltas, 7);
	const current7d = rolling[rolling.length - 1];
	const baseline = rolling.slice(0, -1);
	const baselineMean = mean(baseline);
	const baselineStd = stdDev(baseline, baselineMean);
	const z = baselineStd > 0 ? (current7d! - baselineMean) / baselineStd : null;
	const lastDayDelta = deltas[deltas.length - 1] ?? 0;

	return {
		accountId,
		metric,
		current7d: current7d!,
		baselineMean,
		baselineStd,
		z,
		lastDayDelta,
		severity: classify(z, lastDayDelta),
	};
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") {
			return apiError(res, 405, "Method not allowed");
		}

		const rateAllowed = await enforceAnalyticsSubRateLimit(res, {
			userId: user.id,
			action: "severity-score",
			limit: 30,
		});
		if (!rateAllowed) return;

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountIds: accountIdsCsv, groupId, workspaceId } = parsed;

		let requested = accountIdsCsv
			? accountIdsCsv
					.split(",")
					.map((s) => s.trim())
					.filter(Boolean)
			: [];
		if (requested.length === 0 && groupId) {
			const { data: group, error: groupError } = await db()
				.from("account_groups")
				.select("account_ids")
				.eq("id", groupId)
				.eq("user_id", user.id)
				.maybeSingle();
			if (groupError) {
				return apiError(res, 500, "Failed to resolve account group", {
					details: groupError.message,
				});
			}
			requested = ((group?.account_ids ?? []) as string[]).filter(Boolean);
		}

		// Owner guard — only score accounts the caller owns (or workspace peers own).
		const allowed = new Set(
			await getAccountIdsForContext(user.id, workspaceId ?? null),
		);
		const scoped =
			requested.length > 0 || groupId
				? requested.filter((id) => allowed.has(id))
				: Array.from(allowed);

		if (scoped.length === 0) {
			return apiSuccess(res, { accounts: {}, missing: requested });
		}

		const cutoff = new Date(Date.now() - 91 * 86_400_000)
			.toISOString()
			.split("T")[0]!;

		// Pull both platforms in parallel. Threads lives in account_metrics_history
		// (platform='threads') for views; IG's ig_reach lives on account_analytics
		// (no dedicated row in metrics_history for per-day reach). Query each
		// table with the same scope and bucket by account_id downstream.
		const [metricsRes, analyticsRes] = await Promise.all([
			db()
				.from("account_metrics_history")
				.select("account_id, date, platform, total_views")
				.in("account_id", scoped)
				.gte("date", cutoff)
				.order("date", { ascending: true }),
			db()
				.from("account_analytics")
				.select(
					"account_id, date, ig_reach, ig_follower_reach, ig_non_follower_reach, total_views",
				)
				.in("account_id", scoped)
				.gte("date", cutoff)
				.order("date", { ascending: true }),
		]);

		if (metricsRes.error) {
			return apiError(res, 500, "Failed to load metrics history", {
				details: metricsRes.error.message,
			});
		}
		if (analyticsRes.error) {
			return apiError(res, 500, "Failed to load analytics", {
				details: analyticsRes.error.message,
			});
		}

		// Index by account. Prefer metrics_history for Threads; fall back to
		// account_analytics.total_views if no history rows exist. For IG use
		// account_analytics.ig_reach.
		const metricsByAccount = new Map<string, MetricRow[]>();
		for (const row of (metricsRes.data ?? []) as MetricRow[]) {
			const list = metricsByAccount.get(row.account_id) ?? [];
			list.push(row);
			metricsByAccount.set(row.account_id, list);
		}
		const analyticsByAccount = new Map<string, AnalyticsRow[]>();
		for (const row of (analyticsRes.data ?? []) as AnalyticsRow[]) {
			const list = analyticsByAccount.get(row.account_id) ?? [];
			list.push(row);
			analyticsByAccount.set(row.account_id, list);
		}

		const accounts: Record<string, AccountSeverity> = {};
		const missing: string[] = [];

		for (const accountId of scoped) {
			const metricsRows = metricsByAccount.get(accountId) ?? [];
			const analyticsRows = analyticsByAccount.get(accountId) ?? [];

			if (metricsRows.length === 0 && analyticsRows.length === 0) {
				missing.push(accountId);
				continue;
			}

			// Infer platform from whichever source has rows. IG accounts write
			// ig_reach into analytics; Threads writes platform='threads' into
			// metrics_history. Ambiguous cases (both populated) prefer Threads
			// because the hero-level reach anomaly chart the research cites is
			// Threads views (§2 / §3 of the deep-dive).
			const threadsRows = metricsRows.filter(
				(r) => (r.platform ?? "threads") === "threads",
			);

			// IG signal preference:
			//   1. ig_follower_reach + ig_non_follower_reach — absolute daily
			//      reach counts captured since the Apr 24 migration. True daily
			//      signal; z-scores react within ~1 day of a reach collapse.
			//   2. ig_reach (28-day rolling) — smoothed fallback for accounts
			//      that haven't rolled forward past the Apr 24 gap yet. Daily
			//      deltas here are 1-day-lagged and noisy.
			const absoluteIgValues: number[] = analyticsRows
				.filter(
					(r) =>
						r.ig_follower_reach !== null &&
						r.ig_non_follower_reach !== null &&
						r.ig_follower_reach !== undefined &&
						r.ig_non_follower_reach !== undefined,
				)
				.map(
					(r) =>
						(r.ig_follower_reach as number) +
						(r.ig_non_follower_reach as number),
				);
			const fallbackIgValues: number[] = analyticsRows
				.filter((r) => r.ig_reach !== null && r.ig_reach !== undefined)
				.map((r) => r.ig_reach as number);

			if (threadsRows.length >= 14) {
				const values = threadsRows.map((r) => r.total_views ?? 0);
				accounts[accountId] = scoreOne(accountId, "threads_views", values);
			} else if (absoluteIgValues.length >= 14) {
				accounts[accountId] = scoreOne(accountId, "ig_reach", absoluteIgValues);
			} else if (fallbackIgValues.length >= 14) {
				accounts[accountId] = scoreOne(accountId, "ig_reach", fallbackIgValues);
			} else {
				// Not enough history yet — return a sentinel so the grid can render
				// a neutral row. Never infer severity from thin data.
				accounts[accountId] = {
					accountId,
					metric: threadsRows.length > 0 ? "threads_views" : "ig_reach",
					current7d: 0,
					baselineMean: 0,
					baselineStd: 0,
					z: null,
					lastDayDelta: 0,
					severity: "insufficient",
				};
			}
		}

		return apiSuccess(res, { accounts, missing });
	},
);
