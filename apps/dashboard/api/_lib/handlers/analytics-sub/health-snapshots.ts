/**
 * Health Snapshots Handler
 *
 * GET /api/analytics?action=health-snapshots
 *
 * Returns pre-computed account health data for the dashboard
 * (AccountHealthRadar + MoversAndShakers widgets).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuthDb } from "../../middleware.js";

interface HealthSnapshotRow {
	account_id: string;
	account_name: string;
	platform: string;
	has_anomaly: boolean;
	anomaly_severity: string | null;
	anomaly_detail: string | null;
	reach_drop_pct: number | null;
	growth_pct: number;
	followers_current: number;
	posts_this_period: number;
	days_since_last_post: number;
	engagement_rate: number | null;
	computed_at: string | null;
}

export default withAuthDb(async (req: VercelRequest, res: VercelResponse, { user, userDb }) => {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	try {
		const periodDays = Number(req.query.periodDays) || 7;

		const { data: snapshots, error } = await userDb
			.from("account_health_snapshots")
			.select("*")
			.eq("user_id", user.id)
			.eq("period_days", periodDays)
			.order("growth_pct", { ascending: false });

		if (error) {
			logger.error("[health-snapshots] Query failed", {
				error: error.message,
				userId: user.id,
			});
			return apiError(res, 500, "Failed to fetch health snapshots");
		}

		const rows = (snapshots || []) as HealthSnapshotRow[];

		// Split into alerts and movers
		// Filter out "stale" alerts for accounts that never posted (days_since_last_post >= 30)
		// — these are connected but unused accounts, not actionable alerts
		const alerts = rows
			.filter(
				(r) =>
					r.has_anomaly &&
					!(r.days_since_last_post >= 30 && inferAlertType(r) === "stale"),
			)
			.map((r) => ({
				accountId: r.account_id,
				accountName: r.account_name,
				platform: r.platform,
				severity: r.anomaly_severity,
				type: inferAlertType(r),
				detail: r.anomaly_detail,
				metric:
					r.anomaly_severity === "low"
						? undefined
						: Math.round(r.reach_drop_pct || r.growth_pct),
			}));

		// Top performers: prefer growth > 0, fall back to best engagement rate,
		// then most active (posts this period). Never return empty if there's data.
		let topPerformers = rows
			.filter((r) => r.growth_pct > 0)
			.slice(0, 5)
			.map(mapMover);

		if (topPerformers.length === 0 && rows.length > 0) {
			// Fallback: highest engagement rate accounts that posted recently
			topPerformers = [...rows]
				.filter((r) => r.posts_this_period > 0)
				.sort((a, b) => (b.engagement_rate || 0) - (a.engagement_rate || 0))
				.slice(0, 5)
				.map(mapMover);
		}

		if (topPerformers.length === 0 && rows.length > 0) {
			// Last fallback: most active accounts by post count
			topPerformers = [...rows]
				.sort((a, b) => (b.posts_this_period || 0) - (a.posts_this_period || 0))
				.slice(0, 5)
				.map(mapMover);
		}

		const needsAttention = rows
			.filter((r) => r.growth_pct <= 0 || r.days_since_last_post >= 3)
			.sort((a, b) => {
				// Stale accounts first, then worst growth
				if (a.days_since_last_post >= 3 && b.days_since_last_post < 3)
					return -1;
				if (b.days_since_last_post >= 3 && a.days_since_last_post < 3) return 1;
				return a.growth_pct - b.growth_pct;
			})
			.slice(0, 5)
			.map(mapMover);

		return apiSuccess(res, {
			alerts,
			topPerformers,
			needsAttention,
			totalAccounts: rows.length,
			computedAt: rows[0]?.computed_at || null,
		});
	} catch (error) {
		logger.error("[health-snapshots] Unexpected error", {
			error: error instanceof Error ? error.message : String(error),
		});
		return apiError(res, 500, "Internal server error");
	}
});

function inferAlertType(row: HealthSnapshotRow): string {
	if (row.anomaly_severity === "high" && (row.reach_drop_pct ?? 0) < -40) {
		return (row.reach_drop_pct ?? 0) < -70 ? "shadowban" : "reach_drop";
	}
	if (row.anomaly_severity === "medium") return "engagement_crash";
	if (row.days_since_last_post >= 3) return "stale";
	return "reach_drop";
}

function mapMover(r: HealthSnapshotRow) {
	return {
		accountId: r.account_id,
		accountName: r.account_name,
		platform: r.platform,
		growthPct: Number.parseFloat(Number(r.growth_pct).toFixed(1)),
		followersCount: r.followers_current || 0,
		postsThisPeriod: r.posts_this_period || 0,
		daysSinceLastPost:
			r.days_since_last_post >= 3 ? r.days_since_last_post : undefined,
	};
}
